#!/usr/bin/env python3
"""Does a client-set `Origin` or `Referer` header skip the per-address rate limit on lookups? A scripted yes or no (standard library only).

    python3 perf_tests/origin_check.py                         # staging: one table, one conclusion
    python3 perf_tests/origin_check.py --expect closed         # exit status 1 if any header still skips the limit (for after a fix)

The service does not limit a lookup that carries a trusted `Origin` (or, without one, `Referer`): the first-party web sites and local development origins. The header is set by the caller, so
anyone who sends it is not limited. This sends the same flood of lookups (more than one burst's worth) several ways, one after another with a pause for the allowance to refill, and counts the `429`s:

    plain             no Origin or Referer: the baseline, which must be limited or nothing can be judged
    trusted           Origin: https://mediumroast.io                 (a first-party site)
    trusted-subdomain Origin: https://app.mediumroast.io             (its subdomains are trusted too)
    trusted-referer   Referer: https://mediumroast.io/page           (used when there is no Origin)
    local-dev         Origin: http://localhost:3000                  (a web app on a developer's machine)
    foreign           Origin: https://partner.example                (must be limited)
    lookalike         Origin: https://mediumroast.io.evil.example    (must be limited: only the real host counts)

A row that is not limited is a header that skips the limit. It sends about 1,500 requests per row in a few seconds: only run it against a service you operate (the default is the staging service;
another URL needs --allow-other-url).
"""
import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402

STAGING_URL = "https://company-dns-staging.mediumroast.io"
UA = "company_dns-origin-check/1.0 (+https://github.com/miha42-github/company_dns)"
# (name, headers, must be limited?, what it is)
CASES = [
    ("plain", {}, True, "the baseline"),
    ("trusted", {"Origin": "https://mediumroast.io"}, None, "a first-party site"),
    ("trusted-subdomain", {"Origin": "https://app.mediumroast.io"}, None, "a first-party subdomain"),
    ("trusted-referer", {"Referer": "https://mediumroast.io/page"}, None, "a first-party page, by Referer"),
    ("local-dev", {"Origin": "http://localhost:3000"}, None, "a web app on a developer's machine"),
    ("foreign", {"Origin": "https://partner.example"}, True, "another site"),
    ("lookalike", {"Origin": "https://mediumroast.io.evil.example"}, True, "a host that only contains the name"),
]


def flood(target: load.Target, headers: dict, requests: int, concurrency: int) -> dict:
    """`requests` lookups from `concurrency` threads as fast as they go; the answers counted."""
    h = {"User-Agent": UA, "Accept": "application/json", **headers}
    counts = {"ok": 0, "limited": 0, "errors": 0}
    lock = threading.Lock()
    remaining = [requests]

    def worker(seed: int) -> None:
        import random
        rng = random.Random(seed)
        conn = None
        mine = {"ok": 0, "limited": 0, "errors": 0}
        while True:
            with lock:
                if remaining[0] <= 0:
                    break
                remaining[0] -= 1
            path = load.build_path(rng, "/V4.0/na/sic/code/{c}")
            try:
                if conn is None:
                    conn = target.connect()
                conn.request("GET", path, headers=h)
                resp = conn.getresponse()
                resp.read()
                if resp.status in load.OK_STATUSES:
                    mine["ok"] += 1
                elif resp.status == 429:
                    mine["limited"] += 1
                else:
                    mine["errors"] += 1
                if resp.getheader("connection", "").lower() == "close":
                    conn.close()
                    conn = None
            except Exception:
                mine["errors"] += 1
                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass
                conn = None
        with lock:
            for k, v in mine.items():
                counts[k] += v

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return counts


def judge(results: list[dict], threshold: float = 0.05) -> dict:
    """Per case: LIMITED when more than `threshold` of the requests were `429`s. Then the conclusion about the header bypass."""
    for r in results:
        r["limited_share"] = r["limited"] / max(1, r["requests"])
        r["is_limited"] = r["limited_share"] > threshold
    by = {r["name"]: r for r in results}
    out = {"valid": True, "problems": [], "bypass": [], "closed": []}
    if r_ := by.get("plain"):
        if not r_["is_limited"]:
            out["valid"] = False
            out["problems"].append("the baseline was not limited, so nothing can be judged (is the quota higher than the flood, or does this address bypass the limit?)")
    if any(r["errors"] > 0.05 * max(1, r["requests"]) for r in results):
        out["valid"] = False
        out["problems"].append("more than 5% of the requests of some row failed: the service was not reachable or was failing")
    for r in results:
        if r["must_be_limited"] and not r["is_limited"] and r["name"] != "plain":
            out["problems"].append(f"`{r['name']}` ({r['what']}) was NOT limited but must be: the limiter has a bigger hole than the trusted headers")
        if r["must_be_limited"] is None:
            (out["closed"] if r["is_limited"] else out["bypass"]).append(r["name"])
    return out


def render(results: list[dict], verdict: dict, url: str) -> str:
    lines = [f"# Origin and Referer bypass check: {url}", "", f"{results[0]['requests']:,} lookups per row, one flood after another.", "",
             "| header sent | what it is | let through | `429` | errors | limited? |", "|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['name']} | {r['what']} | {r['ok']:,} | {r['limited']:,} | {r['errors']} | {'**yes**' if r['is_limited'] else 'no'} |")
    lines.append("")
    if not verdict["valid"]:
        lines += ["**Cannot judge:** " + "; ".join(verdict["problems"]), ""]
    elif verdict["bypass"]:
        lines += [f"**BYPASS PRESENT.** Sending {', '.join('`' + b + '`' for b in verdict['bypass'])} skips the per-address limit on lookups: anyone can send these headers. Ordinary callers are limited (the baseline and the foreign origin).", ""]
        if verdict["closed"]:
            lines += [f"Limited even with the header: {', '.join('`' + c + '`' for c in verdict['closed'])}.", ""]
    else:
        lines += ["**CLOSED.** No `Origin` or `Referer` skips the limit: every row was limited like the baseline.", ""]
    for p in verdict["problems"] if verdict["valid"] else []:
        lines.append(f"- **Problem:** {p}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=STAGING_URL)
    ap.add_argument("--allow-other-url", action="store_true", help="allow a URL other than the staging service (only one you operate)")
    ap.add_argument("--requests", type=int, default=1500, help="lookups per row (more than the burst, 600 by default)")
    ap.add_argument("--concurrency", type=int, default=40)
    ap.add_argument("--pause", type=float, default=12.0, help="seconds between rows, for the allowance to refill")
    ap.add_argument("--connect-to", metavar="ADDRESS")
    ap.add_argument("--expect", choices=["closed", "bypass"], help="exit with status 1 unless the result is this (a check for after a fix)")
    ap.add_argument("--out", type=Path, help="also write the table to this file")
    a = ap.parse_args(argv)
    problems = []
    if a.url.rstrip("/") != STAGING_URL and not a.allow_other_url:
        problems.append(f"{a.url} is not the staging service: this sends thousands of requests in seconds; add --allow-other-url only for a service you operate")
    if a.requests < 50 or not 1 <= a.concurrency <= 256:
        problems.append("--requests must be at least 50 and --concurrency 1 to 256")
    if problems:
        print("cannot start:\n  - " + "\n  - ".join(problems), file=sys.stderr)
        return 2
    target = load.Target(a.url, connect_to=a.connect_to)
    results = []
    for i, (name, headers, must, what) in enumerate(CASES):
        if i:
            time.sleep(a.pause)
        c = flood(target, headers, a.requests, a.concurrency)
        results.append({"name": name, "what": what, "must_be_limited": must, "requests": a.requests, **c})
        print(f"{name:18s} let through {c['ok']:5d}  429 {c['limited']:5d}  errors {c['errors']}")
    verdict = judge(results)
    text = render(results, verdict, a.url)
    print()
    print(text)
    if a.out:
        a.out.write_text(text)
    if not verdict["valid"]:
        return 3
    if a.expect == "closed" and (verdict["bypass"] or verdict["problems"]):
        return 1
    if a.expect == "bypass" and not verdict["bypass"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
