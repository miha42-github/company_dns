"""Tests for load.py and run_cluster.py. Run: python3 -m unittest perf_tests/test_cluster.py

The generator runs against a real local HTTP server; the orchestrator runs against a fake cluster, so nothing touches Kubernetes. They pin what
matters for a test that runs on a cluster shared with production: it only ever changes the staging Deployment, never deletes, always puts it back
(even after a failure), stops if a production pod restarts, and refuses an unsafe concurrency.
"""
import base64
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402
import run_cluster as rc  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    seen_hosts: list = []
    seen_auth: list = []
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        Handler.seen_hosts.append(self.headers.get("Host"))
        Handler.seen_auth.append(self.headers.get("Authorization"))
        status = 404 if "/code/" in self.path else 200
        body = b'{"code": %d}' % status
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class LoadGenerator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_percentiles(self):
        v = [float(i) for i in range(1, 101)]
        self.assertAlmostEqual(load.percentile(v, 50), 50.5)
        self.assertAlmostEqual(load.percentile(v, 99), 99.01, places=1)
        self.assertTrue(load.percentile([], 50) != load.percentile([], 50))  # nan

    def test_404_is_a_valid_answer_429_is_counted_apart_and_the_rest_are_errors(self):
        samples = [(0.0, 10.0, 200, "a"), (0.0, 20.0, 404, "a"), (0.0, 30.0, 429, "b"), (0.0, 40.0, 500, "b"), (0.0, 50.0, 0, "b")]
        s = load.summarise(samples, 10.0, 4)
        self.assertEqual((s["requests"], s["ok"], s["errors"], s["rate_limited"]), (5, 2, 2, 1))
        self.assertEqual(s["rps"], 0.2)
        self.assertEqual(s["error_rate"], 0.6)
        self.assertEqual(s["by_status"], {"200": 1, "404": 1, "429": 1, "500": 1, "0": 1})

    def test_every_mix_builds_distinct_requests_so_caches_cannot_answer_them(self):
        import random
        rng = random.Random(1)
        for name, mix in load.MIXES.items():
            paths = {load.build_path(rng, t) for _, t, _ in mix for _ in range(40)}
            self.assertGreater(len(paths), 30, name)
            for p in paths:
                self.assertTrue(p.startswith("/V4.0/"), p)
                self.assertNotIn("{", p)

    def test_a_real_run_against_a_local_server_with_the_host_name_kept(self):
        Handler.seen_hosts.clear()
        Handler.seen_auth.clear()
        # the URL's host name is what the server must see; the connection goes to the address
        target = load.Target(f"http://service.test:{self.port}", connect_to="127.0.0.1")
        r = load.run_level(target, "mixed", 4, 1.5, 0.5, auth="staging-test:tok", processes=2)
        self.assertGreater(r["requests"], 20)
        self.assertEqual((r["errors"], r["rate_limited"]), (0, 0))
        self.assertGreater(r["rps"], 10)
        self.assertEqual(set(Handler.seen_hosts), {f"service.test:{self.port}"})
        self.assertEqual(set(Handler.seen_auth), {"Basic " + base64.b64encode(b"staging-test:tok").decode()})
        self.assertEqual(r["concurrency"], 4)
        self.assertTrue(r["routes"])

    def test_an_unreachable_server_is_all_errors_not_a_crash(self):
        target = load.Target("http://127.0.0.1:9", timeout=1.0)
        r = load.run_level(target, "lookups", 2, 1.0, 0.0)
        self.assertEqual(r["ok"], 0)
        self.assertGreater(r["errors"], 0)
        self.assertEqual(r["error_rate"], 1.0)


class FakeCluster(rc.Cluster):
    """Just enough of a cluster: a staging Deployment, production's restart count, and a record of every call."""

    def __init__(self):
        self.kubectl = ["kubectl"]
        self.calls = []
        self.staging = {"replicas": 2, "resources": {"limits": {"cpu": "500m", "memory": "1Gi"}, "requests": {"cpu": "100m", "memory": "256Mi"}}, "env": "2"}
        self.prod_restarts = 0
        self.restart_prod_after_runs = None
        self.runs_done = 0

    def deployment(self, namespace=rc.NAMESPACE):
        self.calls.append((namespace, "get deployment"))
        s = self.staging
        return {"spec": {"replicas": s["replicas"], "template": {"spec": {"containers": [
            {"name": "company-dns", "resources": s["resources"], "env": [{"name": "COMPANY_DNS_REPLICAS", "value": s["env"]}]}]}}},
            "status": {"readyReplicas": s["replicas"]}}

    def restarts(self, namespace):
        self.calls.append((namespace, "restarts"))
        return self.prod_restarts if namespace == rc.PROD_NAMESPACE else 0

    def apply_patch(self, patch):
        self.calls.append((rc.NAMESPACE, "patch", json.dumps(patch)))
        c = patch["spec"]["template"]["spec"]["containers"][0]
        self.staging = {"replicas": patch["spec"]["replicas"], "resources": c["resources"], "env": c["env"][0]["value"]}

    def wait_ready(self, timeout=300.0):
        self.calls.append((rc.NAMESPACE, "wait ready"))

    def cgroup(self):
        self.calls.append((rc.NAMESPACE, "cgroup"))
        n = self.runs_done
        return {"p1": {"usage_us": n * 4_000_000, "periods": n * 100, "throttled_periods": n * 10, "throttled_us": 0, "mem_mib": 200.0, "mem_peak_mib": 250.0}}


def fake_run_level(cluster, fail_on=None):
    def run_level(target, mix, n, duration, warmup, auth):
        cluster.runs_done += 1
        if fail_on and cluster.runs_done == fail_on:
            raise RuntimeError("the load generator failed")
        if cluster.restart_prod_after_runs and cluster.runs_done >= cluster.restart_prod_after_runs:
            cluster.prod_restarts += 1
        return {"concurrency": n, "seconds": duration, "requests": 1000, "ok": 1000, "errors": 0, "rate_limited": 0, "by_status": {"200": 1000}, "rps": 100.0 * n,
                "p50_ms": 10.0, "p95_ms": 20.0 * n / 8, "p99_ms": 30.0, "max_ms": 50.0, "error_rate": 0.0, "routes": {}}
    return run_level


class Orchestrator(unittest.TestCase):
    def setUp(self):
        self.cluster = FakeCluster()
        self.real = load.run_level
        self.addCleanup(setattr, load, "run_level", self.real)
        load.run_level = fake_run_level(self.cluster)
        self.configs = [rc.parse_config("2x1000m/2Gi"), rc.parse_config("4x500m/1Gi")]

    def go(self, **kw):
        return rc.run_configs(self.cluster, self.configs, ["embedding", "lookups"], [8, 16], 1.0, 0.0, 0.0, None, "staging-test:tok", log=lambda *_: None, settle=0, **kw)

    def patches(self):
        return [json.loads(c[2]) for c in self.cluster.calls if len(c) == 3 and c[1] == "patch"]

    def test_configurations_parse_and_unsafe_ones_are_refused(self):
        c = rc.parse_config("2x1000m/2Gi")
        self.assertEqual((c["replicas"], c["cpu_m"], c["mem_mi"], c["name"]), (2, 1000, 2048, "2x1000m/2Gi"))
        for bad in ("2x1000/2Gi", "0x500m/1Gi", "9x500m/1Gi", "2x50m/1Gi", "2x9000m/1Gi", "2x500m/64Mi", "two"):
            with self.assertRaises(ValueError, msg=bad):
                rc.parse_config(bad)

    def test_requests_follow_the_manifests_ratios(self):
        r = rc.resources_for(rc.parse_config("2x500m/1Gi"))
        self.assertEqual(r, {"requests": {"cpu": "100m", "memory": "256Mi"}, "limits": {"cpu": "500m", "memory": "1024Mi"}})

    def test_the_patch_sets_replicas_resources_and_the_rate_limit_replica_count_in_one_rollout(self):
        p = rc.patch_for(4, rc.resources_for(self.configs[1]), "4")
        self.assertEqual(p["spec"]["replicas"], 4)
        c = p["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(c["name"], "company-dns")
        self.assertEqual(c["env"], [{"name": "COMPANY_DNS_REPLICAS", "value": "4"}])
        self.assertEqual(c["resources"]["limits"]["cpu"], "500m")

    def test_every_configuration_runs_every_mix_and_level_then_staging_is_restored(self):
        res = self.go()
        self.assertEqual(len(res["runs"]), 2 * 2 * 2)
        self.assertEqual([(r["config"], r["mix"], r["concurrency"]) for r in res["runs"]][:3], [("2x1000m/2Gi", "embedding", 8), ("2x1000m/2Gi", "embedding", 16), ("2x1000m/2Gi", "lookups", 8)])
        patches = self.patches()
        self.assertEqual([p["spec"]["replicas"] for p in patches], [2, 4, 2], "each configuration, then the original")
        self.assertEqual(self.cluster.staging, {"replicas": 2, "resources": {"limits": {"cpu": "500m", "memory": "1Gi"}, "requests": {"cpu": "100m", "memory": "256Mi"}}, "env": "2"})
        self.assertTrue(res["restored"])

    def test_staging_is_restored_even_when_the_load_fails_midway(self):
        load.run_level = fake_run_level(self.cluster, fail_on=3)
        with self.assertRaises(RuntimeError):
            self.go()
        self.assertEqual(self.cluster.staging["replicas"], 2)
        self.assertEqual(self.cluster.staging["resources"]["limits"]["cpu"], "500m")
        self.assertEqual(self.cluster.staging["env"], "2")

    def test_a_production_restart_stops_the_test_and_restores_staging(self):
        self.cluster.restart_prod_after_runs = 2
        res = self.go()
        self.assertIn("production pod restarted", res["aborted"])
        self.assertEqual(len(res["runs"]), 2, "it stopped right after the run during which production restarted")
        self.assertEqual(self.cluster.staging["replicas"], 2)
        self.assertEqual(res["production_restarts_before_after"], [0, 1])

    def test_only_the_staging_namespace_is_changed_and_nothing_is_deleted(self):
        self.go()
        for call in self.cluster.calls:
            if call[1] in ("patch",):
                self.assertEqual(call[0], rc.NAMESPACE)
            self.assertNotIn("delete", " ".join(map(str, call)))
        prod = {c[1] for c in self.cluster.calls if c[0] == rc.PROD_NAMESPACE}
        self.assertEqual(prod, {"restarts"}, "production is only read, and only for its restart count")

    def test_cgroup_numbers_become_cores_throttling_and_memory(self):
        before = {"p1": {"usage_us": 0, "periods": 0, "throttled_periods": 0, "mem_peak_mib": 100.0, "mem_mib": 90.0}, "gone": {"usage_us": 5}}
        after = {"p1": {"usage_us": 12_000_000, "periods": 600, "throttled_periods": 150, "mem_peak_mib": 260.0, "mem_mib": 240.0}}
        d = rc.cgroup_delta(before, after, 10.0)
        self.assertEqual((d["cpu_cores_used"], d["throttled_share"], d["mem_peak_mib_max"]), (1.2, 0.25, 260.0))
        parsed = rc.parse_cgroup({"cpu": "usage_usec 1000000\nnr_periods 50\nnr_throttled 5\nthrottled_usec 20\n", "mem": "104857600\n", "mem_peak": None})
        self.assertEqual((parsed["usage_us"], parsed["throttled_periods"], parsed["mem_mib"], parsed["mem_peak_mib"]), (1_000_000, 5, 100.0, None))

    def test_a_missing_counter_leaves_a_gap_not_a_crash(self):
        d = rc.cgroup_delta({"p": {"usage_us": None}}, {"p": {"usage_us": None}}, 5.0)
        self.assertEqual(d, {"cpu_cores_used": 0.0, "throttled_share": None, "mem_peak_mib_max": None})

    def test_the_summary_names_the_best_sustained_throughput_per_configuration(self):
        runs = [
            {"config": "A", "mix": "embedding", "concurrency": 8, "rps": 50.0, "p50_ms": 1, "p95_ms": 200.0, "p99_ms": 1, "errors": 0, "rate_limited": 0, "error_rate": 0.0, "total_cpu_cores": 2.0, "pods": {"cpu_cores_used": 1.5, "throttled_share": 0.1, "mem_peak_mib_max": 300}},
            {"config": "A", "mix": "embedding", "concurrency": 32, "rps": 90.0, "p50_ms": 1, "p95_ms": 5000.0, "p99_ms": 1, "errors": 0, "rate_limited": 0, "error_rate": 0.0, "total_cpu_cores": 2.0, "pods": {"cpu_cores_used": 2.0, "throttled_share": 0.6, "mem_peak_mib_max": 300}},
            {"config": "B", "mix": "embedding", "concurrency": 8, "rps": 70.0, "p50_ms": 1, "p95_ms": 100.0, "p99_ms": 1, "errors": 0, "rate_limited": 0, "error_rate": 0.0, "total_cpu_cores": 2.0, "pods": {"cpu_cores_used": 2.0, "throttled_share": 0.0, "mem_peak_mib_max": 300}},
        ]
        self.assertEqual(rc.best_sustained([r for r in runs if r["config"] == "A"])["rps"], 50.0, "the faster run broke the p95 bar")
        text = rc.summary({"started": "t", "original": {"replicas": 2}, "restored": True, "runs": runs, "production_restarts_before_after": [0, 0]})
        self.assertIn("| A | 2.0 | 50.0 | 8 | 200.0 | 25.0 |", text)
        self.assertIn("| B | 2.0 | 70.0 | 8 | 100.0 | 35.0 |", text)
        self.assertIn("Production restarts before and after: 0 -> 0", text)

    def test_main_refuses_unknown_mixes_and_unsafe_concurrency(self):
        self.assertEqual(rc.main(["--mixes", "nonsense"]), 2)
        self.assertEqual(rc.main(["--concurrency", "500"]), 2)


if __name__ == "__main__":
    unittest.main()
