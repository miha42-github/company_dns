"""Tests for limit_probe.py and ceiling.py. Run: python3 perf_tests/test_limits_ceiling.py

A local stand-in server with a real token bucket (and optional failures) lets the probe and the ramp run for real; the judging functions are tested directly.
"""
import csv
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ceiling as ce  # noqa: E402
import limit_probe as lp  # noqa: E402
import load  # noqa: E402
import pod_watch as pw  # noqa: E402


class Bucket:
    def __init__(self, rate, burst):
        self.rate, self.burst, self.tokens, self.t, self.lock = rate, burst, burst, time.monotonic(), threading.Lock()

    def take(self):
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.burst, self.tokens + (now - self.t) * self.rate)
            self.t = now
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            return False


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    bucket = None      # a Bucket, or None for no limit
    fail = False       # answer 500
    require_auth = False  # answer 401 to a request with no Authorization header
    fail_after = None  # answer 500 once this many requests have been answered (the preflight is the first)
    count = 0
    seen_auth: list = []
    delay = 0.0

    def do_GET(self):
        origin = self.headers.get("Origin")
        status, headers = 200, {}
        Handler.seen_auth.append(self.headers.get("Authorization"))
        Handler.count += 1
        if Handler.fail_after is not None and Handler.count > Handler.fail_after:
            Handler.fail = True
        if Handler.require_auth and not self.headers.get("Authorization"):
            body = b"{}"
            self.send_response(401)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(body)
            return
        if Handler.delay:
            time.sleep(Handler.delay)
        if Handler.fail:
            status = 500
        elif Handler.bucket and not origin and not Handler.bucket.take():
            status, headers = 429, {"Retry-After": "1"}
        body = b"{}"
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        Handler.bucket, Handler.fail, Handler.delay = None, False, 0.0
        Handler.require_auth = False
        Handler.fail_after, Handler.count = None, 0
        Handler.seen_auth.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)


class Probe(Server):
    def test_the_probe_measures_the_burst_and_the_sustained_rate(self):
        Handler.bucket = Bucket(rate=20.0, burst=15)
        r = lp.run_probe(load.Target(self.url), 8, 8, {"User-Agent": "x (+https://example.org)"})
        self.assertTrue(8 <= r["burst"] <= 20, r["burst"])  # approximate: requests in flight when the first 429 came back are not counted
        self.assertTrue(17 <= r["sustained_per_second"] <= 23, r["sustained_per_second"])
        self.assertEqual(r["retry_after"]["max"], 1)
        verdict, text = lp.render(r, 1200, 15, None, "t")
        self.assertEqual(verdict, "LIMITED")
        self.assertIn("**The most one address can get through**", text)

    def test_a_trusted_origin_skips_the_limit_and_the_probe_says_so(self):
        Handler.bucket = Bucket(rate=5.0, burst=5)
        r = lp.run_probe(load.Target(self.url), 5, 8, {"User-Agent": "x (+https://example.org)", "Origin": "https://mediumroast.io"})
        self.assertEqual(r["limited"], 0)
        verdict, text = lp.render(r, None, None, "https://mediumroast.io", "t")
        self.assertEqual(verdict, "UNLIMITED")
        self.assertIn("did not act at all", text)

    def test_no_limit_seen_is_not_reported_as_limited(self):
        r = lp.run_probe(load.Target(self.url), 5, 4, {"User-Agent": "x"})
        self.assertEqual(lp.render(r, 600, 50, None, "t")[0], "NO LIMIT SEEN")

    def test_summarise_counts_what_it_is_given(self):
        samples = [(0.1, 200, None)] * 30 + [(0.2, 429, "1")] * 5 + [(2.5, 404, None)] * 3 + [(3.0, 500, None)]
        r = lp.summarise(samples, 5)
        self.assertEqual((r["ok"], r["limited"], r["errors"], r["burst"]), (33, 5, 1, 30))

    def test_another_url_needs_the_flag(self):
        self.assertEqual(lp.main(["--url", "https://example.org", "--out", str(self.root)]), 2)
        self.assertEqual(lp.main(["--seconds", "1", "--out", str(self.root)]), 2)


def level(total, rps, p95=100.0, errors=0, limited=0, requests=1000):
    return {"level": total, "machine_concurrency": total, "start_utc": "2027-01-15T08:00:00Z", "end_utc": "2027-01-15T08:00:30Z", "requests": requests, "ok": requests - errors, "errors": errors,
            "rate_limited": limited, "rps": rps, "p50_ms": 10.0, "p95_ms": p95, "p99_ms": p95 * 1.2, "max_ms": p95 * 2, "error_rate": errors / requests, "generator_cores": 1.0, "note": ""}


class Judging(unittest.TestCase):
    def test_best_sustained_needs_the_latency_and_error_bars(self):
        levels = [level(256, 1500), level(512, 1900, p95=900), level(1024, 2100, p95=2500)]
        self.assertEqual(ce.best_sustained(levels)["level"], 512)
        self.assertIsNone(ce.best_sustained([level(256, 100, p95=3000)]))
        self.assertEqual(ce.best_sustained([level(256, 100, limited=5), level(512, 90)])["level"], 512, "a limited step is not a measurement")

    def test_the_ramp_stops_on_errors_latency_limiting_or_a_collapse(self):
        ok = [level(256, 1500), level(512, 1900)]
        self.assertIsNone(ce.buckled(ok, 0.02, 5000, 0.15))
        self.assertIn("error rate", ce.buckled(ok + [level(1024, 1800, errors=100)], 0.02, 5000, 0.15))
        self.assertIn("p95", ce.buckled(ok + [level(1024, 1800, p95=6000)], 0.02, 5000, 0.15))
        self.assertIn("rate limited", ce.buckled(ok + [level(1024, 1800, limited=50)], 0.02, 5000, 0.15))
        collapse = ok + [level(1024, 1500), level(1536, 1400)]
        self.assertIn("fell", ce.buckled(collapse, 0.02, 5000, 0.15))

    def test_merging_adds_the_machines_and_keeps_the_worst_latency(self):
        a, b = [level(256, 600, p95=100)], [level(256, 700, p95=150)]
        m = ce.merge_levels([a, b])[0]
        self.assertEqual((m["rps"], m["p95_ms"], m["requests"]), (1300.0, 150.0, 2000))

    def test_the_pods_side_is_joined_by_the_load_itself(self):
        base = 1_800_000_000
        levels = [dict(level(256, 1000), start_utc=ce.utc(base + 100), end_utc=ce.utc(base + 130)), dict(level(512, 1500), start_utc=ce.utc(base + 145), end_utc=ce.utc(base + 175))]
        watch = []
        for i in range(60):  # 5 s samples from base to base + 300, the pods busy between 100 and 175 on the watcher's clock (a 400 s skew)
            t = base + 400 + 5 * i
            busy = base + 400 + 100 <= t <= base + 400 + 180
            watch.append({"t": float(t), "time_utc": ce.utc(t), "cpu_cores_used": "14.0" if busy else "0.2", "throttled_share": "0.02", "mem_mib_max": "180", "new_restarts": "0", "ready": "20", "oom_killed": "0"})
        rows, note = ce.join_watch(levels, watch)
        self.assertIn("shifted by +", note)
        self.assertEqual([r["cpu_max"] for r in rows], [14.0, 14.0])
        self.assertEqual(rows[0]["restarts"], 0)


class Ramp(Server):
    def run_ramp(self, **kw):
        out = self.root / "run"
        argv = ["run", "--url", self.url, "--allow-other-url", "--anonymous", "--levels", "4", "8", "12", "--duration", "1", "--warmup", "0", "--pause", "0", "--processes", "2", "--out", str(out), "--label", "t"]
        for k, v in kw.items():
            argv += [f"--{k.replace('_', '-')}", str(v)]
        return ce.main(argv), out

    def test_a_ramp_writes_a_line_per_step_and_a_summary(self):
        code, out = self.run_ramp()
        self.assertEqual(code, 0)
        rows = list(csv.DictReader(open(out / "levels.csv")))
        self.assertEqual([r["level"] for r in rows], ["4", "8", "12"])
        self.assertIn("Best sustained", (out / "summary.md").read_text())
        self.assertEqual(json.loads((out / "meta.json").read_text())["label"], "t")

    def test_the_ramp_stops_when_the_service_fails(self):
        Handler.fail_after = 1  # the preflight is answered; everything after fails
        code, out = self.run_ramp()
        self.assertEqual(code, 0)
        rows = list(csv.DictReader(open(out / "levels.csv")))
        self.assertEqual(len(rows), 1, "it stopped after the first step")
        self.assertIn("error rate", (out / "summary.md").read_text())

    def test_without_credentials_or_with_an_unsafe_target_it_refuses(self):
        os.environ.pop("LOAD_AUTH", None)
        self.assertEqual(ce.main(["run", "--url", self.url, "--allow-other-url", "--dry-run"]), 2)
        self.assertEqual(ce.main(["run", "--anonymous", "--dry-run", "--url", "https://example.org"]), 2)
        self.assertEqual(ce.main(["run", "--anonymous", "--dry-run", "--url", self.url, "--allow-other-url", "--levels", "9000"]), 2)
        self.assertEqual(ce.main(["run", "--anonymous", "--dry-run", "--url", self.url, "--allow-other-url", "--machines", "9", "--levels", "4"]), 2)

    def test_the_token_from_the_environment_is_sent_and_never_printed_or_written(self):
        import base64
        import contextlib
        import io
        Handler.require_auth = True
        os.environ["LOAD_AUTH"] = "staging-test:s3cret-token"
        self.addCleanup(os.environ.pop, "LOAD_AUTH", None)
        out = self.root / "auth-run"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = ce.main(["run", "--url", self.url, "--allow-other-url", "--levels", "4", "--duration", "1", "--warmup", "0", "--pause", "0", "--processes", "2", "--out", str(out), "--label", "t"])
        self.assertEqual(code, 0)
        expected = "Basic " + base64.b64encode(b"staging-test:s3cret-token").decode()
        self.assertTrue(Handler.seen_auth and all(h == expected for h in Handler.seen_auth), "every request, the preflight included, carried the credentials")
        self.assertIn("profile staging-test", buf.getvalue())
        self.assertIn("preflight: one request as the profile was answered normally", buf.getvalue())
        self.assertNotIn("s3cret-token", buf.getvalue())
        for f in out.iterdir():
            self.assertNotIn("s3cret-token", f.read_text(), f.name)
        self.assertEqual(json.loads((out / "meta.json").read_text())["profile"], "staging-test")

    def test_a_wrong_token_or_an_unreachable_service_stops_before_the_ramp(self):
        Handler.require_auth = True
        self.assertIn("refused the credentials", ce.preflight(load.Target(self.url), None) or "")
        self.assertIsNone(ce.preflight(load.Target(self.url), "p:t"))
        self.assertIn("cannot reach", ce.preflight(load.Target("http://127.0.0.1:9"), "p:t"))
        Handler.bucket = Bucket(rate=0.0, burst=0)
        Handler.require_auth = False
        self.assertIn("rate limited", ce.preflight(load.Target(self.url), "p:t"))

    def test_merge_and_report_commands(self):
        code, out = self.run_ramp()
        merged = self.root / "merged"
        self.assertEqual(ce.main(["merge", str(out), str(out), "--out", str(merged)]), 0)
        rows = list(csv.DictReader(open(merged / "levels.csv")))
        self.assertEqual(len(rows), 3)
        self.assertEqual(ce.main(["merge", str(self.root / "nowhere"), "--out", str(merged)]), 2)


if __name__ == "__main__":
    unittest.main()
