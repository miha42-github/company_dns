"""Tests for origin_check.py. Run: python3 perf_tests/test_origin_check.py

A stand-in server with a real token bucket, and (optionally) the same trusted-header rule as the service, lets the check run for real.
"""
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import origin_check as oc  # noqa: E402


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


def host(value):
    rest = value.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
    return rest


def trusted(origin, referer):
    value = origin or referer
    if not value:
        return False
    h = host(value)
    return h in ("localhost", "127.0.0.1") or h == "mediumroast.io" or h.endswith(".mediumroast.io")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    bucket = None
    honour_trusted = True

    def do_GET(self):
        skip = Handler.honour_trusted and trusted(self.headers.get("Origin"), self.headers.get("Referer"))
        status = 200 if (skip or Handler.bucket.take()) else 429
        body = b"{}"
        self.send_response(status)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class Check(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def run_check(self, honour, *extra):
        Handler.bucket = Bucket(rate=40.0, burst=30)
        Handler.honour_trusted = honour
        argv = ["--url", self.url, "--allow-other-url", "--requests", "200", "--concurrency", "8", "--pause", "1.2", *extra]
        return oc.main(argv)

    def test_a_service_that_honours_the_headers_is_reported_as_bypassed(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = self.run_check(True)
        out = buf.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("BYPASS PRESENT", out)
        for name in ("trusted", "trusted-subdomain", "trusted-referer", "local-dev"):
            self.assertIn(f"`{name}`", out.split("BYPASS PRESENT")[1].split("\n")[0])
        self.assertNotIn("`lookalike`", out.split("BYPASS PRESENT")[1].split("\n")[0], "a lookalike host must not be trusted")
        self.assertNotIn("`foreign`", out.split("BYPASS PRESENT")[1].split("\n")[0])

    def test_a_service_that_ignores_them_is_closed_and_expect_closed_passes(self):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code = self.run_check(False, "--expect", "closed")
        self.assertEqual(code, 0)
        self.assertIn("**CLOSED.**", buf.getvalue())

    def test_expect_closed_fails_when_a_header_skips_the_limit(self):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.run_check(True, "--expect", "closed"), 1)

    def test_it_refuses_another_url_without_the_flag(self):
        self.assertEqual(oc.main(["--url", "https://example.org"]), 2)

    def test_the_judging_needs_a_limited_baseline(self):
        rows = [{"name": "plain", "what": "x", "must_be_limited": True, "requests": 100, "ok": 100, "limited": 0, "errors": 0},
                {"name": "trusted", "what": "y", "must_be_limited": None, "requests": 100, "ok": 100, "limited": 0, "errors": 0}]
        v = oc.judge(rows)
        self.assertFalse(v["valid"])


if __name__ == "__main__":
    unittest.main()
