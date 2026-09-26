#!/usr/bin/env python3
"""
Performance baseline suite for company_dns.

Hits a curated set of endpoints - discovered from the deployment's own
OpenAPI spec (https://company-dns.mediumroast.io/docs -> /openapi.json),
not hardcoded URL strings - across several well-known companies, first
sequentially (to get a clean per-call latency baseline) and then at
increasing concurrency levels (to see whether the server actually serves
requests in parallel, or serializes them - see docs/plans/onprem-k8s-migration.md
and the EDGAR/Wikipedia performance-fix work for why that question matters:
company_dns's query methods are synchronous and run inline on FastAPI's
event loop rather than via run_in_threadpool, so a slow external call can
block every other concurrent request for its duration).

Usage:
    python3 perf_tests/baseline.py
    python3 perf_tests/baseline.py --base-url http://localhost:8000
    python3 perf_tests/baseline.py --concurrency 1 2 4 8 --repeat 3
    python3 perf_tests/baseline.py --out perf_tests/results/my-run.json
    python3 perf_tests/baseline.py --skip-concurrency   # sequential only, fast
    python3 perf_tests/baseline.py --list                # show the call matrix, don't run

Requires only `requests` (already a company_dns dependency) and the
standard library.
"""

import argparse
import json
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from companies import COMPANIES  # noqa: E402

DEFAULT_BASE_URL = "https://company-dns.mediumroast.io"

# --------------------------------------------------------------------- #
# BEGIN: Endpoint catalog
#
# Path templates below are verified against the live OpenAPI spec at
# startup (see verify_endpoints_exist) rather than assumed - if the
# deployment's actual paths ever drift from this list, the suite refuses
# to run instead of silently hitting 404s and calling that "fast".
#
# "category" separates endpoints that should be fast and local-only
# (control group: no external network calls, no reason concurrency should
# hurt them) from the external-I/O-bound ones this whole investigation is
# about. The concurrency experiment below runs against both groups so the
# control group's behavior under load is visible for comparison.
ENDPOINTS = [
    {
        "key": "health",
        "path": "/health",
        "category": "control",
        "per_company": False,
        "description": "Liveness endpoint, no DB/network calls",
    },
    {
        "key": "sic_lookup",
        "path": "/V3.0/na/sic/description/{sic_desc}",
        "category": "control",
        "per_company": False,
        "fixed_param": "oil",
        "description": "SQLite-only SIC description search (no external calls)",
    },
    {
        "key": "edgar_ciks",
        "path": "/V3.0/na/companies/edgar/ciks/{company_name}",
        "category": "control",
        "per_company": True,
        "param_field": "edgar_name",
        "description": "SQLite-only CIK lookup by fuzzy name (no external calls)",
    },
    {
        "key": "edgar_detail",
        "path": "/V3.0/na/companies/edgar/detail/{company_name}",
        "category": "external-io",
        "per_company": True,
        "param_field": "edgar_name",
        "description": (
            "Fuzzy EDGAR filing search + one live data.sec.gov call per "
            "unique matched company (fixed from a per-filing-row bug - see "
            "lib/edgar.py get_all_details)"
        ),
    },
    {
        "key": "edgar_firmographics_by_cik",
        "path": "/V3.0/na/company/edgar/firmographics/{cik_no}",
        "category": "external-io",
        "per_company": True,
        "param_field": "cik",
        "description": "Single direct live data.sec.gov call by CIK",
    },
    {
        "key": "wikipedia_firmographics",
        "path": "/V3.0/global/company/wikipedia/firmographics/{company_name}",
        "category": "external-io",
        "per_company": True,
        "param_field": "wiki_name",
        "description": (
            "Wikipedia/Wikidata lookup via wptools (fixed from a "
            "duplicate-fetch bug - see lib/wikipedia.py get_firmographics)"
        ),
    },
    {
        "key": "merged_firmographics",
        "path": "/V3.0/global/company/merged/firmographics/{company_name}",
        "category": "external-io",
        "per_company": True,
        "param_field": "wiki_name",
        "description": (
            "The heaviest real-world path: Wikipedia lookup, conditionally "
            "EDGAR too, plus ArcGIS geocoding"
        ),
    },
]

# Endpoints exercised in the concurrency experiment. Kept to a subset (not
# every endpoint x every company) to keep total request volume modest
# against a shared production service - see --concurrency/--repeat for how
# to widen this deliberately.
CONCURRENCY_ENDPOINT_KEYS = ["health", "edgar_ciks", "wikipedia_firmographics", "merged_firmographics"]
# END: Endpoint catalog
# --------------------------------------------------------------------- #


@dataclass
class Call:
    endpoint_key: str
    category: str
    company_key: str
    url: str


@dataclass
class CallResult:
    endpoint_key: str
    category: str
    company_key: str
    url: str
    status_code: int | None
    latency_ms: float
    error: str | None
    mode: str  # "sequential" | "concurrent"
    concurrency_level: int
    run_index: int


def build_call_matrix(companies=COMPANIES) -> list[Call]:
    calls = []
    for ep in ENDPOINTS:
        if not ep["per_company"]:
            param = ep.get("fixed_param", "")
            url = ep["path"].format(**{ep["path"][ep["path"].find("{") + 1: ep["path"].find("}")]: param}) if "{" in ep["path"] else ep["path"]
            calls.append(Call(ep["key"], ep["category"], "-", url))
            continue
        for company in companies:
            value = company[ep["param_field"]]
            field_name = ep["path"][ep["path"].find("{") + 1: ep["path"].find("}")]
            url = ep["path"].format(**{field_name: quote(value, safe="")})
            calls.append(Call(ep["key"], ep["category"], company["key"], url))
    return calls


def verify_endpoints_exist(base_url: str, timeout: float) -> None:
    resp = requests.get(f"{base_url}/openapi.json", timeout=timeout)
    resp.raise_for_status()
    spec_paths = set(resp.json().get("paths", {}).keys())
    missing = [ep["path"] for ep in ENDPOINTS if ep["path"] not in spec_paths]
    if missing:
        raise SystemExit(
            "ERROR: the following endpoint(s) this suite depends on are not "
            f"in {base_url}/openapi.json - the deployment's API has drifted "
            f"from this suite's assumptions, refusing to run:\n  "
            + "\n  ".join(missing)
        )


def do_request(session: requests.Session, base_url: str, call: Call, timeout: float) -> tuple[int | None, float, str | None]:
    start = time.perf_counter()
    try:
        resp = session.get(f"{base_url}{call.url}", timeout=timeout)
        latency_ms = (time.perf_counter() - start) * 1000
        return resp.status_code, latency_ms, None
    except requests.RequestException as e:
        latency_ms = (time.perf_counter() - start) * 1000
        return None, latency_ms, str(e)


def run_sequential(base_url: str, calls: list[Call], delay: float, timeout: float) -> list[CallResult]:
    results = []
    session = requests.Session()
    for i, call in enumerate(calls):
        status, latency_ms, error = do_request(session, base_url, call, timeout)
        results.append(CallResult(call.endpoint_key, call.category, call.company_key, call.url, status, latency_ms, error, "sequential", 1, 0))
        marker = "OK " if status == 200 else f"!! {status}"
        print(f"  [{i + 1:>3}/{len(calls)}] {marker:>6}  {latency_ms:8.1f}ms  {call.endpoint_key:28s} {call.company_key:12s} {call.url}")
        if delay:
            time.sleep(delay)
    return results


def run_concurrency_experiment(
    base_url: str, companies, levels: list[int], repeat: int, timeout: float
) -> list[CallResult]:
    results = []
    endpoints_by_key = {ep["key"]: ep for ep in ENDPOINTS}

    for key in CONCURRENCY_ENDPOINT_KEYS:
        ep = endpoints_by_key[key]
        for level in levels:
            for run_index in range(repeat):
                # Build `level` calls to this endpoint, cycling through the
                # company list so concurrent calls hit *different* queries,
                # like real concurrent traffic would, rather than one query
                # repeated (which some code paths might special-case/cache
                # incidentally at the OS/network layer).
                if ep["per_company"]:
                    batch_companies = [companies[i % len(companies)] for i in range(level)]
                    field_name = ep["path"][ep["path"].find("{") + 1: ep["path"].find("}")]
                    batch = [
                        Call(key, ep["category"], c["key"], ep["path"].format(**{field_name: quote(c[ep["param_field"]], safe="")}))
                        for c in batch_companies
                    ]
                else:
                    param = ep.get("fixed_param", "")
                    field_name = ep["path"][ep["path"].find("{") + 1: ep["path"].find("}")] if "{" in ep["path"] else None
                    url = ep["path"].format(**{field_name: param}) if field_name else ep["path"]
                    batch = [Call(key, ep["category"], "-", url) for _ in range(level)]

                print(f"  concurrency={level:>2}  run={run_index + 1}/{repeat}  endpoint={key}")
                session = requests.Session()
                wall_start = time.perf_counter()
                with ThreadPoolExecutor(max_workers=level) as executor:
                    futures = {executor.submit(do_request, session, base_url, call, timeout): call for call in batch}
                    for future in as_completed(futures):
                        call = futures[future]
                        status, latency_ms, error = future.result()
                        results.append(
                            CallResult(call.endpoint_key, call.category, call.company_key, call.url, status, latency_ms, error, "concurrent", level, run_index)
                        )
                wall_ms = (time.perf_counter() - wall_start) * 1000
                print(f"    -> wall time for {level} concurrent calls: {wall_ms:.1f}ms")
    return results


# --------------------------------------------------------------------- #
# BEGIN: Reporting
def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def print_sequential_summary(results: list[CallResult]) -> None:
    print("\n=== Sequential baseline (per endpoint) ===")
    by_endpoint: dict[str, list[CallResult]] = {}
    for r in results:
        by_endpoint.setdefault(r.endpoint_key, []).append(r)

    header = f"{'endpoint':28s} {'category':12s} {'n':>3s} {'ok%':>5s} {'min':>8s} {'median':>8s} {'p95':>8s} {'max':>8s} {'mean':>8s}"
    print(header)
    print("-" * len(header))
    for key, rs in by_endpoint.items():
        latencies = [r.latency_ms for r in rs]
        ok = sum(1 for r in rs if r.status_code == 200)
        print(
            f"{key:28s} {rs[0].category:12s} {len(rs):>3d} {100 * ok / len(rs):>4.0f}% "
            f"{min(latencies):>7.1f}m {statistics.median(latencies):>7.1f}m "
            f"{percentile(latencies, 0.95):>7.1f}m {max(latencies):>7.1f}m {statistics.mean(latencies):>7.1f}m"
        )


def print_concurrency_summary(results: list[CallResult], sequential_results: list[CallResult]) -> None:
    print("\n=== Concurrency scaling (does parallel traffic actually run in parallel?) ===")
    seq_median_by_endpoint = {}
    by_endpoint_seq: dict[str, list[CallResult]] = {}
    for r in sequential_results:
        by_endpoint_seq.setdefault(r.endpoint_key, []).append(r)
    for key, rs in by_endpoint_seq.items():
        seq_median_by_endpoint[key] = statistics.median(r.latency_ms for r in rs)

    by_key: dict[tuple[str, int], list[CallResult]] = {}
    for r in results:
        by_key.setdefault((r.endpoint_key, r.concurrency_level), []).append(r)

    header = (
        f"{'endpoint':28s} {'N':>3s} {'wall(median)':>13s} {'per-call(median)':>17s} "
        f"{'ideal-if-serial':>16s} {'speedup vs serial':>18s}"
    )
    print(header)
    print("-" * len(header))
    for (key, level), rs in sorted(by_key.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        # group by run_index to get one wall-time-per-run, then take the median across repeats
        by_run: dict[int, list[CallResult]] = {}
        for r in rs:
            by_run.setdefault(r.run_index, []).append(r)
        wall_times = [max(r.latency_ms for r in run_calls) for run_calls in by_run.values()]
        per_call_latencies = [r.latency_ms for r in rs]
        seq_baseline = seq_median_by_endpoint.get(key, float("nan"))
        ideal_if_serial = seq_baseline * level
        wall_median = statistics.median(wall_times)
        speedup = ideal_if_serial / wall_median if wall_median else float("nan")
        print(
            f"{key:28s} {level:>3d} {wall_median:>12.1f}m {statistics.median(per_call_latencies):>16.1f}m "
            f"{ideal_if_serial:>15.1f}m {speedup:>17.2f}x"
        )
    print(
        "\n(speedup near 1.0x at N>1 means requests are effectively serialized "
        "server-side - no parallel benefit; speedup near N means true "
        "concurrent handling.)"
    )
# END: Reporting
# --------------------------------------------------------------------- #


def capture_provenance(namespace: str = "company-dns", deployment: str = "company-dns") -> dict:
    """Best-effort record of what code was actually running when a
    measurement was taken, so a report from next month can be matched back
    to the PR(s) live at the time instead of relying on memory. Never
    raises - a run against a host with no git checkout or no kubectl access
    should still produce a usable report, just with these fields as null.
    """
    provenance = {"git_commit": None, "deployed_image": None}

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            provenance["git_commit"] = result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        result = subprocess.run(
            [
                "kubectl", "-n", namespace, "get", "deployment", deployment,
                "-o", "jsonpath={.spec.template.spec.containers[0].image}",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            provenance["deployed_image"] = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass

    return provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"default: {DEFAULT_BASE_URL}")
    parser.add_argument("--concurrency", nargs="+", type=int, default=[1, 4, 8], help="concurrency levels to test, default: 1 4 8")
    parser.add_argument("--repeat", type=int, default=2, help="repeats per concurrency level, default: 2")
    parser.add_argument("--delay", type=float, default=0.15, help="seconds between sequential calls, default: 0.15")
    parser.add_argument("--timeout", type=float, default=30.0, help="per-request timeout in seconds, default: 30")
    parser.add_argument("--skip-concurrency", action="store_true", help="only run the sequential baseline")
    parser.add_argument("--list", action="store_true", help="print the call matrix and exit, without making requests")
    parser.add_argument("--out", type=Path, default=None, help="JSON output path, default: perf_tests/results/<timestamp>.json")
    args = parser.parse_args()

    calls = build_call_matrix()

    if args.list:
        for c in calls:
            print(f"{c.endpoint_key:28s} {c.category:12s} {c.company_key:12s} {c.url}")
        print(f"\n{len(calls)} sequential calls total.")
        return

    provenance = capture_provenance()
    print(
        f"==> Provenance: git_commit={provenance['git_commit'] or '(unavailable)'} "
        f"deployed_image={provenance['deployed_image'] or '(unavailable)'}"
    )

    print(f"==> Verifying endpoints against {args.base_url}/openapi.json")
    verify_endpoints_exist(args.base_url, args.timeout)

    print(f"\n==> Running {len(calls)} sequential calls against {args.base_url}")
    sequential_results = run_sequential(args.base_url, calls, args.delay, args.timeout)
    print_sequential_summary(sequential_results)

    concurrency_results = []
    if not args.skip_concurrency:
        print(f"\n==> Running concurrency experiment: levels={args.concurrency}, repeat={args.repeat}")
        concurrency_results = run_concurrency_experiment(args.base_url, COMPANIES, args.concurrency, args.repeat, args.timeout)
        print_concurrency_summary(concurrency_results, sequential_results)

    out_path = args.out or Path(__file__).resolve().parent / "results" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "base_url": args.base_url,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": provenance["git_commit"],
        "deployed_image": provenance["deployed_image"],
        "concurrency_levels": args.concurrency,
        "repeat": args.repeat,
        "sequential_results": [r.__dict__ for r in sequential_results],
        "concurrency_results": [r.__dict__ for r in concurrency_results],
    }
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\n==> Full results written to {out_path}")


if __name__ == "__main__":
    main()
