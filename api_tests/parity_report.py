#!/usr/bin/env python3
"""Live V3-vs-V4 report: for each fixture's request, asks both services, compares the answers and times them.

    python3 api_tests/parity_report.py [--v3 URL] [--v4 URL] [--repeats N] [--json out.json]

V3 is the production service, so it is asked politely: one request at a time, a pause between, a self-identifying User-Agent.
Variances are reported as: IDENTICAL (equal once `dependencies` is dropped), SAME SHAPE (same keys and types, data differs),
DIFFERENT (structure differs; the differing keys are listed). Times are the median of N requests, in milliseconds; the first
V4 request of a cache-able route is reported separately as "cold".
"""
import argparse, json, statistics, sys, time, urllib.request, urllib.error
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
from common import shape, fixture  # noqa: E402

APPLE = quote("Apple Inc.")
CASES = [  # (fixture, path)
    ("eu_section_A", "/V3.0/eu/sic/section/A"), ("eu_division_25", "/V3.0/eu/sic/division/25"),
    ("eu_group_259", "/V3.0/eu/sic/group/25.9"), ("eu_class_2591", "/V3.0/eu/sic/class/25.91"),
    ("eu_desc_steel", "/V3.0/eu/sic/description/steel"),
    ("intl_section_A", "/V3.0/international/sic/section/A"), ("intl_division_25", "/V3.0/international/sic/division/25"),
    ("intl_group_259", "/V3.0/international/sic/group/259"), ("intl_class_2591", "/V3.0/international/sic/class/2591"),
    ("intl_desc_steel", "/V3.0/international/sic/description/steel"),
    ("japan_major_09", "/V3.0/japan/sic/major_group/09"), ("japan_group_091", "/V3.0/japan/sic/group/091"),
    ("japan_desc_food", "/V3.0/japan/sic/description/food"),
    ("us_division_E", "/V3.0/na/sic/division/E"), ("us_major_35", "/V3.0/na/sic/major/35"),
    ("us_industry_357", "/V3.0/na/sic/industry/357"), ("us_code_3571", "/V3.0/na/sic/code/3571"),
    ("us_desc_computers", "/V3.0/na/sic/description/computers"), ("v2_code_3571", "/V2.0/sic/code/3571"),
    ("edgar_ciks_apple", "/V3.0/na/companies/edgar/ciks/Apple"),
    ("edgar_summary_appleinc", f"/V3.0/na/companies/edgar/summary/{APPLE}"),
    ("edgar_detail_appleinc", f"/V3.0/na/companies/edgar/detail/{APPLE}"),
    ("edgar_firmo_320193", "/V3.0/na/company/edgar/firmographics/320193"),
    ("wikipedia_appleinc", f"/V3.0/global/company/wikipedia/firmographics/{APPLE}"),
    ("merged_appleinc", f"/V3.0/global/company/merged/firmographics/{APPLE}"),
]
UA = "company_dns-parity-report/1.0 (michael.hay@mediumroast.io)"


def ask(base, path):
    req = urllib.request.Request(base + path, headers={"User-Agent": UA})
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    ms = (time.perf_counter() - t) * 1000
    try:
        body = json.loads(raw)
    except ValueError:
        body = None
    return status, body, ms, len(raw)


def strip(b):
    # dependencies is V4's own; performance holds timings, which differ on every request (its presence is covered by the tests)
    return {k: v for k, v in b.items() if k not in ("dependencies", "performance")} if isinstance(b, dict) else b


def diff_keys(a, b, prefix="", depth=0):
    """Paths whose presence or type differs, three levels down at most."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict) and depth < 3:
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"+{prefix}{k} (V4 only)")
            elif k not in b:
                out.append(f"+{prefix}{k} (V3 only)")
            else:
                out += diff_keys(a[k], b[k], f"{prefix}{k}.", depth + 1)
    elif type(a) is not type(b):
        out.append(f"{prefix.rstrip('.')}: V3 {type(a).__name__}, V4 {type(b).__name__}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v3", default="https://company-dns.mediumroast.io")
    ap.add_argument("--v4", default="http://localhost:4000")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--pause", type=float, default=1.0)
    ap.add_argument("--json")
    a = ap.parse_args()
    rows = []
    for name, path in CASES:
        base = fixture(name)
        v4_first = ask(a.v4, path)
        v4_t = [v4_first[2]] + [ask(a.v4, path)[2] for _ in range(a.repeats - 1)]
        v3_t = []
        v3_status = v3_body = v3_size = None
        for _ in range(a.repeats):
            time.sleep(a.pause)
            v3_status, v3_body, ms, v3_size = ask(a.v3, path)
            v3_t.append(ms)
        v4_status, v4_body = v4_first[0], v4_first[1]
        if v4_body is None or v3_body is None:
            verdict, detail = "DIFFERENT", [f"non-JSON answer (V3 {v3_status}, V4 {v4_status})"]
        elif strip(v3_body) == strip(v4_body):
            verdict, detail = "IDENTICAL", []
        elif shape(strip(v3_body)) == shape(strip(v4_body)):
            verdict, detail = "SAME SHAPE", [k for k in ("code", "message", "module") if v3_body.get(k) != v4_body.get(k)] + ["data values differ"]
        else:
            verdict, detail = "DIFFERENT", diff_keys(strip(v3_body.get("data")), strip(v4_body.get("data")), "data.")[:6] or diff_keys(strip(v3_body), strip(v4_body))[:6]
        rows.append(dict(name=name, path=path, verdict=verdict, detail=detail, v3_status=v3_status, v4_status=v4_status,
                         v3_ms=statistics.median(v3_t), v4_ms=statistics.median(v4_t), v4_cold_ms=v4_first[2],
                         v3_bytes=v3_size, v4_bytes=v4_first[3]))
        print(f"{verdict:10s} {name:24s} V3 {rows[-1]['v3_ms']:7.0f} ms  V4 {rows[-1]['v4_ms']:7.1f} ms  (cold {v4_first[2]:7.1f})", flush=True)
    print()
    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print("Verdicts:", counts)
    for r in rows:
        if r["detail"]:
            print(f"  {r['verdict']:10s} {r['name']}: " + "; ".join(r["detail"]))
    local = [r for r in rows if r["path"].startswith(("/V3.0/eu", "/V3.0/inter", "/V3.0/japan", "/V3.0/na/sic", "/V2.0"))]
    live = [r for r in rows if r not in local]
    for label, grp in (("Local lookups (SIC, no network)", local), ("Upstream-backed (SEC / Wikipedia)", live)):
        v3, v4 = [r["v3_ms"] for r in grp], [r["v4_ms"] for r in grp]
        print(f"{label}: n={len(grp)} V3 median {statistics.median(v3):.0f} ms, V4 median {statistics.median(v4):.1f} ms, "
              f"speedup x{statistics.median(v3) / max(statistics.median(v4), 0.01):.0f}")
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=2)


if __name__ == "__main__":
    main()
