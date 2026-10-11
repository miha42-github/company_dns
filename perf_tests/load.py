"""A small closed-loop load generator for company_dns (standard library only).

`baseline.py` measures a *batch* of N simultaneous calls; this measures what a deployment sustains: N workers each send a request, wait for
the answer and send the next, for a fixed time, and the answers are summarised (throughput, p50/p95/p99 latency, errors). That is the number
that decides how big a replica should be and how many to run (docs/plans/v4-sizing-test.md).

Requests are built to be different every time (random words), so the server's result caches cannot answer them and the CPU work is real:
the embedding routes in particular cost CPU. `404` is a valid answer ("no match") and counts as success; `429` is counted on its own; anything
else, and a timeout, is an error.

    python3 perf_tests/load.py --url https://example.org --mix embedding --concurrency 16 --duration 20
    python3 perf_tests/load.py --url https://example.org --connect-to 192.0.2.10   # reach the server at that address, with the URL's host name for TLS

The workers are processes (several threads each), so the generator itself does not become the limit at a few thousand requests a second.
"""
import argparse
import base64
import http.client
import json
import multiprocessing
import random
import socket
import ssl
import sys
import threading
import time
import urllib.parse

WORDS = ("software bank steel oil gas food retail hotel airline shipping trucking farming mining chemical paper plastic glass textile apparel "
         "furniture hospital pharmacy insurance real estate telecom wireless cable broadcast publishing printing education consulting accounting "
         "engineering construction plumbing electrical machinery aircraft automobile tire railroad pipeline utility water solar wind coal "
         "cement lumber seafood dairy bakery brewery winery tobacco jewelry toys sporting goods cosmetics laundry funeral security staffing "
         "advertising research testing laboratory semiconductor computer storage network cloud payments lending brokerage leasing rental "
         "warehouse freight courier postal travel tourism restaurant catering casino theater museum library daycare nursing dental veterinary").split()
SIC_CODES = ("0111 0211 0711 1311 1521 1611 2011 2211 2511 2711 2834 2911 3011 3312 3571 3674 3711 3812 4011 4213 4512 4813 4911 5012 5411 "
             "5812 5912 6021 6311 6512 7011 7372 7389 7512 7812 8011 8062 8211 8711").split()

# route templates, by kind: {w} a random word, {q} three random words, {c} a real SIC code
LOOKUPS = (("sic_description", "/V4.0/na/sic/description/{w}", 4), ("sic_code", "/V4.0/na/sic/code/{c}", 3), ("edgar_ciks", "/V4.0/na/companies/edgar/ciks/{w}", 3))
EMBEDDING = (("similarity", "/V4.0/na/sic/similarity/{q}", 6), ("hybrid", "/V4.0/global/sic/hybrid/{q}", 4))
MIXES = {
    "lookups": LOOKUPS,
    "embedding": EMBEDDING,
    "mixed": tuple((n, p, w * 7) for n, p, w in LOOKUPS) + tuple((n, p, w * 3) for n, p, w in EMBEDDING),
}
OK_STATUSES = (200, 404)


class Target:
    """Where to send requests: the URL's host name (for TLS and routing) and, optionally, the address to connect to instead of resolving it."""

    def __init__(self, url: str, connect_to: str | None = None, timeout: float = 30.0, insecure: bool = False):
        u = urllib.parse.urlparse(url)
        self.tls = u.scheme == "https"
        self.host = u.hostname
        self.port = u.port or (443 if self.tls else 80)
        self.connect_to = connect_to
        self.timeout = timeout
        self.insecure = insecure

    def connect(self) -> http.client.HTTPConnection:
        if not self.tls:
            conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
            if self.connect_to:  # connect to the given address but keep the URL's host name in the Host header
                conn.sock = socket.create_connection((self.connect_to, self.port), self.timeout)
            return conn
        ctx = ssl.create_default_context()
        if self.insecure:
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        conn = http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=ctx)
        if self.connect_to:
            # connect to the given address but keep the host name for SNI, certificate checking and the Host header
            raw = socket.create_connection((self.connect_to, self.port), self.timeout)
            conn.sock = ctx.wrap_socket(raw, server_hostname=self.host)
        return conn


def build_path(rng: random.Random, template: str) -> str:
    return template.format(w=rng.choice(WORDS), q="%20".join(rng.sample(WORDS, 3)), c=rng.choice(SIC_CODES))


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return float("nan")
    k = (len(sorted_values) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def _worker(target: Target, mix, headers: dict, deadline: float, seed: int, out: list, lock: threading.Lock) -> None:
    rng = random.Random(seed)
    names = [m[0] for m in mix]
    templates = {m[0]: m[1] for m in mix}
    weights = [m[2] for m in mix]
    samples = []
    conn = None
    while time.monotonic() < deadline:
        name = rng.choices(names, weights)[0]
        path = build_path(rng, templates[name])
        started = time.monotonic()
        try:
            if conn is None:
                conn = target.connect()
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            resp.read()
            status = resp.status
            if resp.getheader("connection", "").lower() == "close":
                conn.close()
                conn = None
        except Exception:  # a timeout or a dropped connection: an error, then a fresh connection
            status = 0
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
            conn = None
        samples.append((started, (time.monotonic() - started) * 1000.0, status, name))
    with lock:
        out.extend(samples)


def _process_main(target, mix, headers, duration, threads, seed, queue) -> None:
    deadline = time.monotonic() + duration
    out: list = []
    lock = threading.Lock()
    workers = [threading.Thread(target=_worker, args=(target, mix, headers, deadline, seed * 1000 + i, out, lock)) for i in range(threads)]
    t0 = time.monotonic()
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    # times are sent relative to this process's start so the parent can cut the warm-up
    queue.put([(s - t0, lat, st, name) for s, lat, st, name in out])


def summarise(samples: list, duration: float, concurrency: int) -> dict:
    ok = [s for s in samples if s[2] in OK_STATUSES]
    lat = sorted(s[1] for s in ok)
    by_status: dict = {}
    for s in samples:
        by_status[str(s[2])] = by_status.get(str(s[2]), 0) + 1
    errors = sum(1 for s in samples if s[2] not in OK_STATUSES and s[2] != 429)
    routes: dict = {}
    for name in {s[3] for s in samples}:
        rl = sorted(s[1] for s in ok if s[3] == name)
        routes[name] = {"requests": sum(1 for s in samples if s[3] == name), "p50_ms": round(percentile(rl, 50), 1), "p95_ms": round(percentile(rl, 95), 1)}
    return {
        "concurrency": concurrency, "seconds": duration, "requests": len(samples), "ok": len(ok), "errors": errors,
        "rate_limited": by_status.get("429", 0), "by_status": by_status,
        "rps": round(len(ok) / duration, 1) if duration else 0.0,
        "p50_ms": round(percentile(lat, 50), 1), "p95_ms": round(percentile(lat, 95), 1), "p99_ms": round(percentile(lat, 99), 1), "max_ms": round(lat[-1], 1) if lat else None,
        "error_rate": round((errors + by_status.get("429", 0)) / len(samples), 4) if samples else 0.0,
        "routes": routes,
    }


def run_level(target: Target, mix_name: str, concurrency: int, duration: float, warmup: float = 5.0, auth: str | None = None, processes: int = 4,
              extra_headers: dict | None = None) -> dict:
    """N closed-loop workers for `warmup + duration` seconds; the warm-up is thrown away."""
    mix = MIXES[mix_name]
    headers = {"User-Agent": "company_dns-load/1.0 (+https://github.com/miha42-github/company_dns)", "Accept": "application/json"}
    headers.update(extra_headers or {})
    if auth:
        headers["Authorization"] = "Basic " + base64.b64encode(auth.encode()).decode()
    processes = max(1, min(processes, concurrency))
    per = [concurrency // processes + (1 if i < concurrency % processes else 0) for i in range(processes)]
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    procs = [ctx.Process(target=_process_main, args=(target, mix, headers, warmup + duration, n, i + 1, queue)) for i, n in enumerate(per)]
    for p in procs:
        p.start()
    samples: list = []
    for _ in procs:
        samples.extend(queue.get())
    for p in procs:
        p.join()
    kept = [s for s in samples if s[0] >= warmup]
    return summarise(kept, duration, concurrency)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True)
    ap.add_argument("--connect-to", help="address to connect to instead of resolving the URL's host name")
    ap.add_argument("--mix", choices=sorted(MIXES), default="mixed")
    ap.add_argument("--concurrency", type=int, nargs="+", default=[8, 16, 32])
    ap.add_argument("--duration", type=float, default=20.0)
    ap.add_argument("--warmup", type=float, default=5.0)
    ap.add_argument("--header", action="append", default=[], metavar="NAME:VALUE", help="an extra request header (for a local server: Origin:http://localhost)")
    ap.add_argument("--auth", help="PROFILE:TOKEN (Basic auth); prefer the environment variable LOAD_AUTH so it is not on a command line")
    a = ap.parse_args(argv)
    import os
    auth = a.auth or os.environ.get("LOAD_AUTH")
    target = Target(a.url, a.connect_to)
    for n in a.concurrency:
        r = run_level(target, a.mix, n, a.duration, a.warmup, auth, extra_headers=dict(h.split(":", 1) for h in a.header))
        print(json.dumps({k: v for k, v in r.items() if k != "routes"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
