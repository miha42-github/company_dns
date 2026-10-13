"""Tests for soak.py (and the request-rate cap in load.py). Run: python3 perf_tests/test_soak.py

A local server stands in for company_dns: it answers the canary questions correctly (or wrongly, or with 401) so the run, its files and its verdict can be checked
without a network.
"""
import argparse
import csv
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402
import soak  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    mode = "good"  # good | wrong | denied
    user_agents: list = []
    methods: list = []

    def do_GET(self):
        Handler.user_agents.append(self.headers.get("User-Agent"))
        Handler.methods.append("GET")
        if Handler.mode == "denied":
            return self.send(401, {"code": 401, "message": "no"})
        if self.path == "/health":
            return self.send(200, {"status": "healthy", "version": "4.0.0"})
        data = {"code": 200, "message": "ok", "total": 1, "data": [{"code": self.path.rsplit("/", 1)[-1]}]}
        if Handler.mode == "wrong" and "/na/sic/code/3571" in self.path:
            data["data"] = [{"code": "9999"}]
        self.send(200, data)

    def send(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def args(url, out, **kw):
    d = dict(url=url, label="test-rig", mix="lookups", steps="2,3", step_minutes=0.0167, hold_concurrency=2, hours=0.0017, window=1.0, rps=None, processes=2,
             max_error_rate=0.01, max_p95_ms=2000.0, out=out, embedding_share=None)
    d.update(kw)
    return argparse.Namespace(**d)


class Soak(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        Handler.mode = "good"
        self.addCleanup(setattr, soak, "CANARY_RETRY_WAIT", soak.CANARY_RETRY_WAIT)
        soak.CANARY_RETRY_WAIT = 0.05
        Handler.user_agents.clear()
        Handler.methods.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "run"

    def rows(self):
        with open(self.out / "windows.csv") as f:
            return list(csv.DictReader(f))

    def run_soak(self, **kw):
        logs = []
        code = soak.run(args(self.url, self.out, **kw), log=logs.append)
        return code, "\n".join(logs)

    def test_the_schedule_ramps_then_holds(self):
        got = list(soak.schedule([4, 8], 2, 16, 7))
        self.assertEqual([c for _, c in got], [4, 4, 8, 8, 16, 16, 16])
        self.assertEqual([s for s, _ in got][-1], "hold")
        self.assertEqual(len(list(soak.schedule([4], 1, 2, 1))), 1)

    def test_canary_checks_catch_wrong_and_empty_answers(self):
        good = json.dumps({"code": 200, "total": 1, "data": [{"sic": "3571"}]}).encode()
        check = soak.envelope_with("3571")
        self.assertIsNone(check(good))
        self.assertIn("not in the data", check(json.dumps({"code": 200, "total": 1, "data": ["x"]}).encode()))
        self.assertIn("total", check(json.dumps({"code": 200, "total": 0, "data": ["3571"]}).encode()))
        self.assertIn("envelope", check(b"<html>"))
        self.assertIsNone(soak.check_health(b'{"status": "healthy"}'))
        self.assertIsNotNone(soak.check_health(b'{"status": "degraded"}'))

    def test_a_run_writes_its_files_and_passes_against_a_good_server(self):
        code, text = self.run_soak()
        self.assertEqual(code, 0, text)
        for name in ("windows.csv", "windows.jsonl", "canaries.jsonl", "meta.json", "summary.md"):
            self.assertTrue((self.out / name).exists(), name)
        rows = self.rows()
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows[0]["concurrency"], "2")
        self.assertTrue(all(r["window_ok"] == "True" for r in rows))
        self.assertEqual(rows[0]["canaries_ok"], rows[0]["canaries_total"])
        self.assertTrue((self.out / "summary.md").read_text().startswith("# Soak test: PASS"))
        meta = json.loads((self.out / "meta.json").read_text())
        self.assertEqual((meta["label"], meta["authenticated"]), ("test-rig", False))

    def test_it_only_sends_gets_and_identifies_itself_with_a_contact(self):
        self.run_soak()
        self.assertEqual(set(Handler.methods), {"GET"})
        ua = Handler.user_agents[0]
        self.assertIn("test-rig", ua)
        self.assertIn("https://", ua, "a contact signal, so the server treats it as a self-identifying caller")

    def test_a_server_that_answers_wrongly_fails_the_run_even_though_it_is_fast(self):
        Handler.mode = "wrong"
        code, text = self.run_soak()
        self.assertEqual(code, 1)
        self.assertIn("# Soak test: FAIL", (self.out / "summary.md").read_text())
        self.assertIn("canary", (self.out / "summary.md").read_text())

    def test_refused_credentials_stop_the_run_with_a_clear_message(self):
        Handler.mode = "denied"
        code, text = self.run_soak(hours=0.05)
        self.assertEqual(code, 2)
        self.assertIn("401/403", (self.out / "summary.md").read_text())
        rows = self.rows()
        self.assertEqual(len(rows), 1, "it stopped after the first window, not after an hour of refusals")

    def test_an_unreachable_server_is_a_failed_run_not_a_crash(self):
        code = soak.run(args("http://127.0.0.1:9", self.out), log=lambda *_: None)
        self.assertEqual(code, 1)
        self.assertIn("FAIL", (self.out / "summary.md").read_text())

    def test_the_summary_verdict_and_drift(self):
        def w(i, p95=100.0, ok=True, step="hold"):
            return {"time_utc": f"t{i}", "elapsed_s": i, "step": step, "concurrency": 8, "requests": 100, "ok": 100, "errors": 0 if ok else 50, "rate_limited": 0,
                    "rps": 50.0, "p50_ms": 50.0, "p95_ms": p95, "p99_ms": 200.0, "max_ms": 300.0, "error_rate": 0.0 if ok else 0.5, "canaries_ok": 5,
                    "canaries_total": 5, "health_ms": 40.0, "window_ok": ok, "note": ""}
        meta = {"url": "u", "label": "l", "started_utc": "s", "mix": "lookups", "window_s": 60, "python": "3", "platform": "p"}
        windows = [w(i, p95=100.0 + i * 20) for i in range(12)]
        verdict, text = soak.summarise(windows, meta, True, 0.01, 2000.0)
        self.assertEqual(verdict, "PASS")
        self.assertIn("Drift while holding", text)
        self.assertEqual(soak.summarise(windows, meta, False, 0.01, 2000.0)[0], "RUNNING")
        windows += [w(20 + i, ok=False) for i in range(3)]
        verdict, text = soak.summarise(windows, meta, True, 0.01, 2000.0)
        self.assertEqual(verdict, "FAIL")
        self.assertIn("Windows that missed the bar", text)

    def test_the_run_ends_on_the_clock_not_only_on_the_window_count(self):
        import time
        real = soak.run_canaries
        self.addCleanup(setattr, soak, "run_canaries", real)
        soak.run_canaries = lambda *a, **k: (time.sleep(0.6), real(*a, **k))[1]  # each window pays 0.6 s for its checks, as a real one pays a second or two
        started = time.monotonic()
        # 10 s in windows of 1 s (10 of them by the count): the clock must end it after about 6 windows of 1.6 s
        code, _ = self.run_soak(hours=10 / 3600, steps="2", step_minutes=1.0, hold_concurrency=2)
        elapsed = time.monotonic() - started
        self.assertEqual(code, 0)
        self.assertLess(elapsed, 10 + 3, elapsed)
        self.assertLess(len(self.rows()), 10, "fewer windows than planned: each took longer than its load time")

    def test_the_breadth_mix_sends_v3_paths_and_a_few_embedding_searches(self):
        self.run_soak(mix="breadth", embedding_share=0.2)
        meta = json.loads((self.out / "meta.json").read_text())
        self.assertEqual((meta["mix"], meta["embedding_share"]), ("breadth", 0.2))

    def test_main_refuses_nonsense_arguments(self):
        self.assertEqual(soak.main(["--embedding-share", "0.1", "--out", str(self.out)]), 2)  # needs --mix breadth
        self.assertEqual(soak.main(["--mix", "breadth", "--embedding-share", "2", "--out", str(self.out)]), 2)
        self.assertEqual(soak.main(["--steps", "a,b", "--out", str(self.out)]), 2)
        self.assertEqual(soak.main(["--window", "1", "--out", str(self.out)]), 2)
        self.assertEqual(soak.main(["--label", "two words", "--out", str(self.out)]), 2)
        self.assertEqual(soak.main(["--url", "ftp://x", "--out", str(self.out)]), 2)

    def test_the_rate_cap_holds_the_request_rate_down(self):
        r = load.run_level(load.Target(self.url), "lookups", 4, 3.0, 0.0, processes=2, rps=20.0)
        self.assertLessEqual(r["requests"], 3 * 20 + 8, r)
        self.assertGreaterEqual(r["requests"], 30, r)


if __name__ == "__main__":
    unittest.main()
