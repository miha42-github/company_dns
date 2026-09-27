#!/usr/bin/env python3
"""
Shadow comparison tool for docs/plans/performance-improvements.md item 6.

Post-cutover (2026-09-27): the default wikipedia/merged endpoints now run
the v2 (direct-HTTP) backend; the wptools-based legacy backend moved to
/v1/ and is kept for reference/rollback only. This tool still diffs /v1/
(legacy) against /v2/ field-by-field for the same companies, reporting
latency side-by-side - useful as an ongoing regression check on the
legacy path in case rollback is ever needed. `--endpoint wikipedia-cutover`
/ `merged-cutover` instead compare the *default* path against /v2/, which
is what actually validates the cutover itself (they should always match,
since default now just calls the v2 backend).

Usage:
    python3 perf_tests/shadow_compare.py
    python3 perf_tests/shadow_compare.py --base-url http://localhost:8000
    python3 perf_tests/shadow_compare.py --include-hard-set
    python3 perf_tests/shadow_compare.py --endpoint wikipedia
    python3 perf_tests/shadow_compare.py --endpoint wikipedia-cutover
    python3 perf_tests/shadow_compare.py --out perf_tests/results/shadow-20261001.json

Exit code is non-zero if any mismatch was found this run, so this can be
dropped into a cron/loop later if desired - not required for manual use.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from companies import COMPANIES  # noqa: E402

DEFAULT_BASE_URL = "https://company-dns.mediumroast.io"

# Deliberately harder than the primary 10 (perf_tests/companies.py, all
# large, English-language, unambiguous Wikidata entries): non-US
# companies that may have no US CIK at all (both backends should agree on
# that absence too, not just on successes), and less-common page shapes.
# Expand this over time per the plan doc - this is a starting point, not
# exhaustive edge-case coverage.
HARD_COMPANIES = [
    {"key": "toyota", "wiki_name": "Toyota"},
    {"key": "nestle", "wiki_name": "Nestlé"},
    {"key": "samsung", "wiki_name": "Samsung Electronics"},
    {"key": "shopify", "wiki_name": "Shopify"},
    {"key": "spotify", "wiki_name": "Spotify Technology"},
]

ENDPOINTS = {
    "wikipedia": {
        "legacy": "/V3.0/global/company/wikipedia/v1/firmographics/{name}",
        "v2": "/V3.0/global/company/wikipedia/v2/firmographics/{name}",
    },
    "merged": {
        "legacy": "/V3.0/global/company/merged/v1/firmographics/{name}",
        "v2": "/V3.0/global/company/merged/v2/firmographics/{name}",
    },
    "wikipedia-cutover": {
        "legacy": "/V3.0/global/company/wikipedia/firmographics/{name}",
        "v2": "/V3.0/global/company/wikipedia/v2/firmographics/{name}",
    },
    "merged-cutover": {
        "legacy": "/V3.0/global/company/merged/firmographics/{name}",
        "v2": "/V3.0/global/company/merged/v2/firmographics/{name}",
    },
}


def fetch(session, base_url, path, timeout):
    start = time.perf_counter()
    try:
        resp = session.get(f"{base_url}{path}", timeout=timeout)
        latency_ms = (time.perf_counter() - start) * 1000
        try:
            body = resp.json()
        except ValueError:
            body = None
        return resp.status_code, latency_ms, body, None
    except requests.RequestException as e:
        latency_ms = (time.perf_counter() - start) * 1000
        return None, latency_ms, None, str(e)


def diff_data(legacy_data, v2_data):
    """List of (field, legacy_value, v2_value) for every field that
    differs between the two responses' `data` objects. `performance` is
    intentionally excluded - it's timing metadata, expected to differ."""
    if legacy_data is None or v2_data is None:
        return [("<entire response>", legacy_data, v2_data)]
    mismatches = []
    for key in sorted(set(legacy_data) | set(v2_data)):
        if key == 'performance':
            continue
        if legacy_data.get(key) != v2_data.get(key):
            mismatches.append((key, legacy_data.get(key), v2_data.get(key)))
    return mismatches


def run_comparison(base_url, endpoint_key, companies, timeout):
    session = requests.Session()
    paths = ENDPOINTS[endpoint_key]
    results = []
    for c in companies:
        name = quote(c["wiki_name"], safe="")
        legacy_status, legacy_ms, legacy_body, legacy_err = fetch(
            session, base_url, paths["legacy"].format(name=name), timeout)
        v2_status, v2_ms, v2_body, v2_err = fetch(
            session, base_url, paths["v2"].format(name=name), timeout)

        legacy_data = legacy_body.get('data') if isinstance(legacy_body, dict) else None
        v2_data = v2_body.get('data') if isinstance(v2_body, dict) else None

        status_match = legacy_status == v2_status
        mismatches = (diff_data(legacy_data, v2_data)
                      if (legacy_status == 200 and v2_status == 200) else [])

        results.append({
            "company": c["key"],
            "legacy_status": legacy_status, "v2_status": v2_status, "status_match": status_match,
            "legacy_latency_ms": legacy_ms, "v2_latency_ms": v2_ms,
            "legacy_error": legacy_err, "v2_error": v2_err,
            "field_mismatches": mismatches,
        })
    return results


def print_report(endpoint_key, results):
    print(f"\n=== {endpoint_key} ===")
    header = f"{'company':14s} {'status (legacy/v2)':20s} {'legacy_ms':>10s} {'v2_ms':>10s} {'speedup':>8s}  result"
    print(header)
    print("-" * len(header))
    total_mismatches = 0
    for r in results:
        status_str = f"{r['legacy_status']}/{r['v2_status']}"
        speedup = (r['legacy_latency_ms'] / r['v2_latency_ms']) if r['v2_latency_ms'] else float('nan')
        if not r['status_match']:
            result = "STATUS MISMATCH"
        elif r['field_mismatches']:
            result = f"{len(r['field_mismatches'])} FIELD MISMATCH(ES)"
        else:
            result = "OK"
        if result != "OK":
            total_mismatches += 1
        print(f"{r['company']:14s} {status_str:20s} {r['legacy_latency_ms']:>9.0f}m {r['v2_latency_ms']:>9.0f}m {speedup:>7.2f}x  {result}")
        for field, legacy_val, v2_val in r['field_mismatches']:
            print(f"    {field}: legacy={str(legacy_val)[:80]!r}  v2={str(v2_val)[:80]!r}")
        if r['legacy_error'] or r['v2_error']:
            print(f"    errors: legacy={r['legacy_error']!r}  v2={r['v2_error']!r}")
    print(f"\n{len(results) - total_mismatches}/{len(results)} companies matched cleanly.")
    return total_mismatches


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"default: {DEFAULT_BASE_URL}")
    parser.add_argument(
        "--endpoint",
        choices=["wikipedia", "merged", "both", "wikipedia-cutover", "merged-cutover"],
        default="both")
    parser.add_argument("--include-hard-set", action="store_true",
                         help="also run the deliberately-harder second company list (non-US, edge cases)")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--out", type=Path, default=None, help="also write full results as JSON")
    args = parser.parse_args()

    companies = list(COMPANIES)
    if args.include_hard_set:
        companies = companies + HARD_COMPANIES

    endpoints_to_run = ["wikipedia", "merged"] if args.endpoint == "both" else [args.endpoint]

    all_results = {}
    total_mismatches = 0
    for ep in endpoints_to_run:
        results = run_comparison(args.base_url, ep, companies, args.timeout)
        total_mismatches += print_report(ep, results)
        all_results[ep] = results

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(all_results, indent=2, default=str))
        print(f"\n==> Full results written to {args.out}")

    if total_mismatches:
        print(f"\n{total_mismatches} total mismatch(es) across all endpoints - NOT yet consistent.")
        sys.exit(1)
    print("\nAll comparisons clean this run.")


if __name__ == "__main__":
    main()
