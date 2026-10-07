"""A V4 server started by the tests themselves, with known credentials and limits.

The limits-and-profiles tests (L5) need to know exactly how the server is configured, and they deliberately hammer it
(runaway queries, floods of bad logins), so they never run against a server somebody else started. This starts the
V4 binary on a free port with throwaway profiles, small limits, and SQL on, and stops it afterwards. Nothing is
written outside a temporary directory, and no real credential is involved.

    V4_BINARY   the binary to run (default: the most recently built of v4/target/{release-lean,debug,release}/company-dns-server)
"""
import hashlib
import json
import os
import random
import secrets
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from collections import namedtuple
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CANDIDATES = [REPO / "v4/target" / d / "company-dns-server" for d in ("release-lean", "debug", "release")]
CWD = REPO / "v4/crates/server"  # the embedding model's cache (.fastembed_cache) is relative to the working directory
GENERIC_UA = "curl/8.4.0"
SELF_UA = "api-tests/1.0 (contact@example.com)"

# profile -> its rules (see v4/README.md "Profiles"); every profile inherits the defaults
DEFAULTS = {"rate_limit": {"bypass": True}}
RULES = {
    "tester": {"sql": {"datasets": ["sic", "edgar"]}},
    "sic-only": {"sql": {"datasets": ["sic"]}},
    "no-sql": {"rate_limit": None},
    "unlimited": {},
    "capped": {"rate_limit": {"requests_per_minute": 20, "burst": 20}},
    "sql-small": {"sql": {"datasets": ["sic"], "limits": {"max_rows": 5, "timeout_secs": 2, "concurrency": 1}}},
    "sql-rpm": {"sql": {"datasets": ["sic"], "limits": {"requests_per_minute": 20}}},
}
LIMITS = {  # the server-wide limits, small so they are easy to reach
    "COMPANY_DNS_SQL_DEFAULT_ROWS": "50", "COMPANY_DNS_SQL_MAX_ROWS": "200", "COMPANY_DNS_SQL_TIMEOUT_SECS": "5",
    "COMPANY_DNS_SQL_MEMORY_MB": "128", "COMPANY_DNS_SQL_MAX_CONCURRENT": "2", "COMPANY_DNS_SQL_PARALLELISM": "2",
}
SLOW_SQL = "select count(*) from generate_series(1, 5000000000) a cross join generate_series(1, 5000000000) b"

Reply = namedtuple("Reply", "status json headers seconds")


def fresh_ip():
    """A source address nobody has used: the server keys its limits on X-Forwarded-For, so this gives a clean bucket."""
    return f"10.{random.randint(1, 250)}.{random.randint(1, 250)}.{random.randint(1, 250)}"


def find_binary():
    explicit = os.environ.get("V4_BINARY")
    if explicit:
        return Path(explicit)
    # the most recently built one: an older profile's binary may predate the code under test
    built = [c for c in CANDIDATES if c.exists()]
    return max(built, key=lambda c: c.stat().st_mtime) if built else None


class ManagedServer:
    def __init__(self):
        self.proc = None
        self.tokens = {}
        self.tmp = None

    def start(self):
        binary = find_binary()
        if not binary or not binary.exists():
            raise unittest.SkipTest("no V4 binary to start (build one with `cargo build -p company-dns-server`, or set V4_BINARY)")
        self.tmp = tempfile.TemporaryDirectory(prefix="company-dns-api-tests-")
        d = Path(self.tmp.name)
        lines = ["# throwaway test profiles"]
        for name in RULES:
            token = secrets.token_hex(32)
            self.tokens[name] = token
            lines.append(f"{name}:{hashlib.sha256(token.encode()).hexdigest()}")
        (d / "credentials").write_text("\n".join(lines) + "\n")
        (d / "rules.json").write_text(json.dumps({"defaults": DEFAULTS, "profiles": RULES}))
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            self.port = sk.getsockname()[1]
        env = dict(os.environ, PORT=str(self.port), COMPANY_DNS_SQL_ENABLED="true",
                   COMPANY_DNS_CREDENTIALS_FILE=str(d / "credentials"), COMPANY_DNS_RULES_FILE=str(d / "rules.json"), **LIMITS)
        self.log = d / "server.log"
        self.proc = subprocess.Popen([str(binary)], cwd=CWD if CWD.exists() else None, env=env,
                                     stdout=open(self.log, "wb"), stderr=subprocess.STDOUT)
        self.base = f"http://127.0.0.1:{self.port}"
        deadline = time.time() + 120
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"the server exited at start-up:\n{self.log.read_text()[-1500:]}")
            try:
                with urllib.request.urlopen(self.base + "/health", timeout=2):
                    return
            except Exception:  # noqa: BLE001 - not up yet
                time.sleep(0.3)
        raise RuntimeError(f"the server did not become healthy:\n{self.log.read_text()[-1500:]}")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.tmp:
            self.tmp.cleanup()

    def call(self, who=None, method="GET", path="/health", body=None, ua=SELF_UA, headers=None, ip=None, token=None):
        """One request. `who` is a profile name (HTTP Basic with its token) or None (anonymous). `ip` sets the
        source address the limits see; `headers` can add or override (for example a forged Origin)."""
        h = {"User-Agent": ua}
        if who:
            import base64
            h["Authorization"] = "Basic " + base64.b64encode(f"{who}:{token or self.tokens[who]}".encode()).decode()
        h["X-Forwarded-For"] = ip or fresh_ip()
        h.update(headers or {})
        data = None
        if body is not None:
            data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw, status, hdrs = r.read(), r.status, r.headers
        except urllib.error.HTTPError as e:
            raw, status, hdrs = e.read(), e.code, e.headers
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        return Reply(status, parsed, hdrs, time.time() - t0)

    def sql(self, who, sql, dataset="sic", limit=None, **kw):
        body = {"dataset": dataset, "sql": sql}
        if limit is not None:
            body["limit"] = limit
        return self.call(who, "POST", "/V4.0/sql", body, **kw)
