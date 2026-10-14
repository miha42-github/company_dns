#!/usr/bin/env python3
"""Measure what one address can actually get through the per-IP rate limiter (standard library only).

    python3 perf_tests/limit_probe.py --expect-per-minute 6000 --expect-burst 600
    python3 perf_tests/limit_probe.py --origin https://mediumroast.io        # does a trusted Origin header skip the limit? (it does, by design)

It sends requests as fast as it can from this machine for --seconds, as an identified caller (a User-Agent with a contact), and counts the answers every second:
`200` (and `404`, a valid "no match") are let through, `429` is limited. From that it reports the **burst** (how many were let through before the first `429`), the **sustained rate**
(let through per second once the burst is spent), the `Retry-After` values, and, if you give the configured numbers, how the observed figures compare. The limiter is per address and
each pod enforces its share, so the observed figures can differ from the configured ones when requests do not spread evenly across the pods: this shows the effective numbers.

The aggregate a service can give many callers is the sustained rate times the number of distinct addresses, up to what the pods can carry (perf_tests/ceiling.py measures that).
It sends thousands of requests in seconds: only run it against a service you operate (the default is the staging service; another URL needs --allow-other-url).
"""
import argparse
import json
import os
import random
import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402

STAGING_URL = "https://company-dns-staging.mediumroast.io"


def run_probe(target: load.Target, seconds: float, concurrency: int, headers: dict) -> dict:
    """Closed-loop requests from `concurrency` threads for `seconds`; the answers binned by the second they came back in."""
    deadline = time.monotonic() + seconds
    t0 = time.monotonic()
    lock = threading.Lock()
    samples: list[tuple[float, int, str | None]] = []  # (second since start the answer came back, status, retry-after)

    def worker(seed: int) -> None:
        rng = random.Random(seed)
        names = [m[0] for m in load.LOOKUPS]
        templates = {m[0]: m[1] for m in load.LOOKUPS}
        weights = [m[2] for m in load.LOOKUPS]
        conn = None
        mine = []
        while time.monotonic() < deadline:
            path = load.build_path(rng, templates[rng.choices(names, weights)[0]])
            retry = None
            try:
                if conn is None:
                    conn = target.connect()
                conn.request("GET", path, headers=headers)
                resp = conn.getresponse()
                resp.read()
                status, retry = resp.status, resp.getheader("retry-after")
                if resp.getheader("connection", "").lower() == "close":
                    conn.close()
                    conn = None
            except Exception:
                status = 0
                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass
                conn = None
            mine.append((time.monotonic() - t0, status, retry))  # when the answer came back: the burst is counted in the order the limiter answered
        with lock:
            samples.extend(mine)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return summarise(samples, seconds)


def summarise(samples: list, seconds: float) -> dict:
    samples = sorted(samples)
    secs = int(seconds)
    per_second = [{"second": s, "ok": 0, "limited": 0, "errors": 0} for s in range(secs + 1)]
    ok_before_first_limit = None
    ok = limited = errors = 0
    retries = []
    for started, status, retry in samples:
        row = per_second[min(int(started), secs)]
        if status in load.OK_STATUSES:
            row["ok"] += 1
            ok += 1
        elif status == 429:
            if ok_before_first_limit is None:
                ok_before_first_limit = ok
            row["limited"] += 1
            limited += 1
            if retry and retry.isdigit():
                retries.append(int(retry))
        else:
            row["errors"] += 1
            errors += 1
    settle = min(10, max(1, secs // 3))  # the burst is spent in the first seconds: the sustained rate is measured after them
    tail = [r["ok"] for r in per_second[settle:secs]]
    return {"seconds": seconds, "requests": len(samples), "ok": ok, "limited": limited, "errors": errors, "burst": ok_before_first_limit,
            "sustained_per_second": round(statistics.median(tail), 1) if tail else None,
            "sustained_mean_per_second": round(statistics.mean(tail), 1) if tail else None, "settle_seconds": settle,
            "retry_after": {"min": min(retries), "median": statistics.median(retries), "max": max(retries)} if retries else None, "per_second": per_second}


def render(r: dict, expect_per_minute: float | None, expect_burst: float | None, origin: str | None, label: str) -> tuple[str, str]:
    """(verdict, markdown)."""
    lines = [f"# Rate-limit probe: `{label}`", "", f"{r['requests']:,} requests in {r['seconds']:g} s from one address: {r['ok']:,} let through, {r['limited']:,} limited (`429`), {r['errors']} errors.", ""]
    verdict = "INFO"
    if origin:
        verdict = "UNLIMITED" if r["limited"] == 0 and r["errors"] == 0 else ("LIMITED" if r["limited"] else "ERRORS")
        lines += [f"**With the header `Origin: {origin}` the limiter {'did not act at all' if verdict == 'UNLIMITED' else 'acted'}** ({r['limited']} limited).",
                  "The service skips the per-address limit on lookups for requests that carry a trusted `Origin` or `Referer` (the first-party web sites). The header is set by the client, so anyone who sends it is not limited here; "
                  "the pods' capacity is then the only limit. The SQL route ignores it.", ""]
        return verdict, "\n".join(lines) + "\n"
    if r["errors"] > 0.01 * max(1, r["requests"]):
        verdict = "ERRORS"
    elif r["limited"] == 0:
        verdict = "NO LIMIT SEEN"
    else:
        verdict = "LIMITED"
    lines += ["| | observed | configured |", "|---|---|---|",
              f"| burst: let through before the first `429` | {r['burst']} | {expect_burst if expect_burst is not None else ''} |",
              f"| sustained, let through per second (median after the first {r['settle_seconds']} s) | {r['sustained_per_second']} | {round(expect_per_minute / 60, 1) if expect_per_minute else ''} |",
              f"| sustained, per minute | {round(r['sustained_per_second'] * 60) if r['sustained_per_second'] is not None else ''} | {expect_per_minute if expect_per_minute is not None else ''} |"]
    if r["retry_after"]:
        lines.append(f"| `Retry-After` (seconds) | {r['retry_after']['min']} to {r['retry_after']['max']} (median {r['retry_after']['median']}) | |")
    if verdict == "LIMITED" and expect_per_minute and r["sustained_per_second"] is not None:
        ratio = r["sustained_per_second"] / (expect_per_minute / 60)
        lines += ["", f"The effective sustained rate is **{ratio:.0%}** of the configured one."
                  + (" Each pod holds its share separately, so uneven spreading of requests across the pods lowers it." if ratio < 0.9 else "")]
    elif verdict == "NO LIMIT SEEN":
        lines += ["", "**No `429` appeared**: the requests were slower than the limit, or the limiter did not see this address as limited (a profile with no limit, a trusted Origin, or a quota above what this machine can send). Raise --seconds or --concurrency."]
    lines += ["", "**The most one address can get through** is therefore about the sustained rate above, after the burst. A service shared by many addresses gives each its own allowance, up to what the pods can carry."]
    return verdict, "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=STAGING_URL)
    ap.add_argument("--allow-other-url", action="store_true", help="allow a URL other than the staging service (only one you operate)")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--concurrency", type=int, default=48)
    ap.add_argument("--connect-to", metavar="ADDRESS")
    ap.add_argument("--start-at", metavar="YYYY-MM-DDTHH:MM:SSZ", help="wait until this UTC time (within the next hour), so several machines, each its own address, start together")
    ap.add_argument("--origin", help="send this Origin header (to see whether a trusted origin skips the limit)")
    ap.add_argument("--expect-per-minute", type=float, help="the configured per-address rate per minute, for the comparison")
    ap.add_argument("--expect-burst", type=float, help="the configured burst")
    ap.add_argument("--label", default=os.environ.get("USER", "tester"))
    ap.add_argument("--out", type=Path, default=Path("perf_tests/results") / f"limit-{time.strftime('%Y%m%d-%H%M')}")
    a = ap.parse_args(argv)
    problems = []
    if a.url.rstrip("/") != STAGING_URL and not a.allow_other_url:
        problems.append(f"{a.url} is not the staging service: this test sends thousands of requests in seconds; add --allow-other-url only for a service you operate")
    if a.seconds < 5 or not 1 <= a.concurrency <= 512:
        problems.append("--seconds must be at least 5 and --concurrency 1 to 512")
    if problems:
        print("cannot start:\n  - " + "\n  - ".join(problems), file=sys.stderr)
        return 2
    if a.start_at:
        from calendar import timegm
        start = timegm(time.strptime(a.start_at, "%Y-%m-%dT%H:%M:%SZ"))
        if not -5 <= start - time.time() <= 3600:
            print(f"--start-at {a.start_at} is not within the next hour", file=sys.stderr)
            return 2
        print(f"waiting until {a.start_at} (UTC) so the machines start together")
        while time.time() < start:
            time.sleep(min(0.5, max(0.0, start - time.time())))
    headers = {"User-Agent": "company_dns-limit-probe/1.0 (+https://github.com/miha42-github/company_dns)", "Accept": "application/json"}
    if a.origin:
        headers["Origin"] = a.origin
    target = load.Target(a.url, connect_to=a.connect_to)
    print(f"probing {a.url} for {a.seconds:g} s with {a.concurrency} threads" + (f" and Origin {a.origin}" if a.origin else ""))
    r = run_probe(target, a.seconds, a.concurrency, headers)
    verdict, text = render(r, a.expect_per_minute, a.expect_burst, a.origin, a.label)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "summary.md").write_text(text)
    (a.out / "per_second.json").write_text(json.dumps({k: v for k, v in r.items()}, indent=1))
    print(text)
    print(f"{verdict}; written to {a.out}/")
    return 0 if verdict in ("LIMITED", "UNLIMITED", "INFO") else 1


if __name__ == "__main__":
    sys.exit(main())
