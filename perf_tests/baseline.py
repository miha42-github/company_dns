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
        "v4_path": "/health",
        "category": "control",
        "per_company": False,
        "description": (
            "Liveness endpoint, no DB/network calls. V4's handler "
            "(docs/plans/v4-server-prototype.md sec5.3) matches V3's "
            "response shape exactly ({status, version, timestamp}) - "
            "version differs on purpose (each server reports its own)."
        ),
    },
    {
        "key": "sic_lookup",
        "path": "/V3.0/na/sic/description/{sic_desc}",
        "v4_path": "/V4.0/na/sic/description/{sic_desc}",
        "category": "control",
        "per_company": False,
        "fixed_param": "oil",
        "description": "SIC description search (SQLite on V3, DataFusion/.feather on V4 - see docs/plans/v4-server-prototype.md sec6 for the matching-semantics decision behind this being a fair comparison)",
    },
    {
        "key": "edgar_ciks",
        "path": "/V3.0/na/companies/edgar/ciks/{company_name}",
        "v4_path": "/V4.0/na/companies/edgar/ciks/{company_name}",
        "category": "control",
        "per_company": True,
        "param_field": "edgar_name",
        "description": "CIK lookup by fuzzy name (SQLite `companies` table on V3, DataFusion/.feather catalog on V4 - see docs/plans/v4-server-prototype.md sec6, the EDGAR-catalog-scope caveat, for why V4 may legitimately miss companies outside its ingested quarter)",
    },
    {
        "key": "edgar_detail",
        "path": "/V3.0/na/companies/edgar/detail/{company_name}",
        "v4_path": "/V4.0/na/companies/edgar/detail/{company_name}",
        "category": "external-io",
        "per_company": True,
        "param_field": "edgar_name",
        "description": (
            "Fuzzy EDGAR filing search + one live data.sec.gov call per "
            "unique matched company (fixed from a per-filing-row bug - see "
            "lib/edgar.py get_all_details). V4's equivalent is catalog-only "
            "(no per-match live enrichment yet - docs/plans/"
            "v4-server-prototype.md sec5.3), so this is not yet an "
            "apples-to-apples I/O comparison against V3 for this one "
            "endpoint specifically, only a correctness/coverage one."
        ),
    },
    {
        "key": "edgar_firmographics_by_cik",
        "path": "/V3.0/na/company/edgar/firmographics/{cik_no}",
        "v4_path": "/V4.0/na/company/edgar/firmographics/{cik_no}",
        "category": "external-io",
        "per_company": True,
        "param_field": "cik",
        "description": "Single direct live data.sec.gov call by CIK - the one true apples-to-apples external-io comparison in the V4 profile (same live upstream call on both sides, V3's requests.Session() vs. V4's edgarkit + docs/plans/go-duckdb-rewrite.md sec5.1's cache)",
    },
    {
        "key": "wikipedia_firmographics",
        "path": "/V3.0/global/company/wikipedia/firmographics/{company_name}",
        "v4_path": "/V4.0/global/company/wikipedia/firmographics/{company_name}",
        "category": "external-io",
        "per_company": True,
        "param_field": "wiki_name",
        "description": (
            "Wikipedia/Wikidata lookup - V3 via wptools (fixed from a "
            "duplicate-fetch bug - see lib/wikipedia.py get_firmographics), "
            "V4 via a hand-rolled reqwest client (docs/plans/"
            "v4-server-prototype.md sec8.1, promoted 2026-09-28 from "
            "experiments/wikipedia-spike/ - narrowed field requests, "
            "maxlag/429/503 backoff, V3's corporate-suffix hint restored "
            "and actually executed as a REST call instead of just "
            "suggested). V4's cache is separate from V3's request-per-call "
            "model (docs/plans/go-duckdb-rewrite.md sec5.1's moka TTL+LRU "
            "cache, 1hr TTL) - a repeat name within that window is a pure "
            "cache hit on V4 with no real network call, unlike V3."
        ),
    },
    {
        "key": "merged_firmographics",
        "path": "/V3.0/global/company/merged/firmographics/{company_name}",
        "v4_path": "/V4.0/global/company/merged/firmographics/{company_name}",
        "category": "external-io",
        "per_company": True,
        "param_field": "wiki_name",
        "description": (
            "V3's heaviest real-world path: Wikipedia lookup, conditionally "
            "EDGAR too, plus ArcGIS geocoding. V4's merged endpoint "
            "(sec8.2, promoted 2026-09-28) is EDGAR + Wikipedia only - no "
            "ArcGIS geocoding call at all - a real, disclosed scope "
            "difference, not an apples-to-apples latency comparison for "
            "this specific endpoint (V4 is missing a whole network call "
            "V3 makes), same caveat sec6 already applies to the EDGAR "
            "catalog-scope difference."
        ),
    },
]

# docs/plans/v4-server-prototype.md sec7: the V4 prototype implements a
# real subset of V3's endpoints - as of 2026-09-28 that's US SIC, EDGAR,
# AND Wikipedia/merged (sec8.1/8.2, promoted from experiments/
# wikipedia-spike/ the same day) - only the five non-US SIC systems and
# UX are still out of scope (sec1). --profile v4 restricts the run to
# endpoints that have a v4_path, so the comparison stays honest rather
# than either refusing to run (today's verify_endpoints_exist behavior)
# or silently producing a misleading result for an endpoint V4 doesn't
# have at all.
PROFILES = {
    "v3": {"version_key": "path", "require_v4_path": False},
    "v4": {"version_key": "v4_path", "require_v4_path": True},
}

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


def profile_endpoints(profile: str) -> list[dict]:
    """docs/plans/v4-server-prototype.md sec7: V4 implements a real
    subset of V3's endpoints (US SIC + EDGAR). --profile v4 restricts
    the call matrix to endpoints that have a v4_path, so the comparison
    stays honest instead of either failing outright (today's
    verify_endpoints_exist behavior) or silently producing a misleading
    result for endpoints V4 doesn't have yet (Wikipedia, merged
    firmographics - staged, not built, sec8)."""
    cfg = PROFILES[profile]
    if not cfg["require_v4_path"]:
        return ENDPOINTS
    included = [ep for ep in ENDPOINTS if "v4_path" in ep]
    excluded = [ep["key"] for ep in ENDPOINTS if "v4_path" not in ep]
    if excluded:
        print(
            f"==> --profile v4: excluding {excluded} (no v4_path - not yet "
            "implemented on V4, docs/plans/v4-server-prototype.md sec8)"
        )
    return included


def endpoint_path(ep: dict, profile: str) -> str:
    return ep[PROFILES[profile]["version_key"]]


def build_call_matrix(companies=COMPANIES, profile: str = "v3") -> list[Call]:
    calls = []
    for ep in profile_endpoints(profile):
        path = endpoint_path(ep, profile)
        if not ep["per_company"]:
            param = ep.get("fixed_param", "")
            url = path.format(**{path[path.find("{") + 1: path.find("}")]: param}) if "{" in path else path
            calls.append(Call(ep["key"], ep["category"], "-", url))
            continue
        for company in companies:
            value = company[ep["param_field"]]
            field_name = path[path.find("{") + 1: path.find("}")]
            url = path.format(**{field_name: quote(value, safe="")})
            calls.append(Call(ep["key"], ep["category"], company["key"], url))
    return calls


def verify_endpoints_exist(base_url: str, timeout: float, profile: str = "v3") -> None:
    """Best-effort: FastAPI (V3) serves /openapi.json, so this can check
    real drift there. The hand-rolled V4 prototype server doesn't serve
    one (docs/plans/v4-server-prototype.md sec9 notes an OpenAPI-
    equivalent discovery endpoint as worth adding later, not built yet)
    - rather than hard-failing a V4 run over a missing spec, this warns
    and skips verification when the spec isn't available at all."""
    try:
        resp = new_session().get(f"{base_url}/openapi.json", timeout=timeout)
        resp.raise_for_status()
        spec_paths = set(resp.json().get("paths", {}).keys())
    except (requests.RequestException, ValueError) as e:
        print(
            f"==> WARNING: could not fetch/parse {base_url}/openapi.json "
            f"({e}) - skipping endpoint-drift verification for this target. "
            "This is expected for the V4 prototype server, which has no "
            "OpenAPI spec yet."
        )
        return

    missing = [
        endpoint_path(ep, profile)
        for ep in profile_endpoints(profile)
        if endpoint_path(ep, profile) not in spec_paths
    ]
    if missing:
        raise SystemExit(
            "ERROR: the following endpoint(s) this suite depends on are not "
            f"in {base_url}/openapi.json - the deployment's API has drifted "
            f"from this suite's assumptions, refusing to run:\n  "
            + "\n  ".join(missing)
        )


# Set by main() from --user-agent and --auth. V4 treats a generic User-Agent (python-requests) as the strictest rate-limit tier
# (5 requests a minute) and an anonymous identified caller as 200 a minute, so a V4 run needs an identifying User-Agent and,
# for load, a profile with a rate-limit bypass (v4/scripts/perf-profile.sh). V3 ignores both.
SESSION_CONFIG = {"user_agent": "company_dns-perf-tests/1.0 (+https://github.com/miha42-github/company_dns)", "auth": None}


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = SESSION_CONFIG["user_agent"]
    if SESSION_CONFIG["auth"]:
        session.auth = SESSION_CONFIG["auth"]
    return session


def do_request(session: requests.Session, base_url: str, call: Call, timeout: float) -> tuple[int | None, float, str | None]:
    start = time.perf_counter()
    try:
        resp = session.get(f"{base_url}{call.url}", timeout=timeout)
        latency_ms = (time.perf_counter() - start) * 1000
        return resp.status_code, latency_ms, None
    except requests.RequestException as e:
        latency_ms = (time.perf_counter() - start) * 1000
        return None, latency_ms, str(e)


def do_request_with_body(
    session: requests.Session, base_url: str, call: Call, timeout: float
) -> tuple[int | None, float, str | None, str | None]:
    """Same as do_request but also returns the response body, for the
    concurrency correctness check below - not used in the main sequential/
    concurrency timing paths, since keeping full response bodies for every
    call would bloat the JSON report for no benefit there."""
    start = time.perf_counter()
    try:
        resp = session.get(f"{base_url}{call.url}", timeout=timeout)
        latency_ms = (time.perf_counter() - start) * 1000
        return resp.status_code, latency_ms, None, resp.text
    except requests.RequestException as e:
        latency_ms = (time.perf_counter() - start) * 1000
        return None, latency_ms, str(e), None


def run_sequential(base_url: str, calls: list[Call], delay: float, timeout: float) -> list[CallResult]:
    results = []
    session = new_session()
    for i, call in enumerate(calls):
        status, latency_ms, error = do_request(session, base_url, call, timeout)
        results.append(CallResult(call.endpoint_key, call.category, call.company_key, call.url, status, latency_ms, error, "sequential", 1, 0))
        marker = "OK " if status == 200 else f"!! {status}"
        print(f"  [{i + 1:>3}/{len(calls)}] {marker:>6}  {latency_ms:8.1f}ms  {call.endpoint_key:28s} {call.company_key:12s} {call.url}")
        if delay:
            time.sleep(delay)
    return results


def run_concurrency_experiment(
    base_url: str, companies, levels: list[int], repeat: int, timeout: float, profile: str = "v3"
) -> list[CallResult]:
    results = []
    profiled = profile_endpoints(profile)
    endpoints_by_key = {ep["key"]: ep for ep in profiled}
    concurrency_keys = [k for k in CONCURRENCY_ENDPOINT_KEYS if k in endpoints_by_key]
    skipped = [k for k in CONCURRENCY_ENDPOINT_KEYS if k not in endpoints_by_key]
    if skipped:
        print(f"==> --profile {profile}: skipping concurrency test for {skipped} (not in this profile)")

    for key in concurrency_keys:
        ep = endpoints_by_key[key]
        path = endpoint_path(ep, profile)
        for level in levels:
            for run_index in range(repeat):
                # Build `level` calls to this endpoint, cycling through the
                # company list so concurrent calls hit *different* queries,
                # like real concurrent traffic would, rather than one query
                # repeated (which some code paths might special-case/cache
                # incidentally at the OS/network layer).
                expected_marker_by_url = {}
                if ep["per_company"]:
                    batch_companies = [companies[i % len(companies)] for i in range(level)]
                    field_name = path[path.find("{") + 1: path.find("}")]
                    batch = []
                    for c in batch_companies:
                        raw_value = c[ep["param_field"]]
                        url = path.format(**{field_name: quote(raw_value, safe="")})
                        batch.append(Call(key, ep["category"], c["key"], url))
                        # Different companies can share a URL only if the same
                        # company appears twice in one batch (level > len(companies)) -
                        # that's fine, the correctness check below is still valid
                        # since they'd expect the same marker.
                        #
                        # Verify against CIK, not the raw query string: EDGAR-
                        # touching endpoints (merged_firmographics especially)
                        # legitimately replace the query with the resolved
                        # formal filer name once a match is found - e.g.
                        # querying "Amazon (company)" or "IBM" correctly
                        # returns "AMAZON COM INC" / "INTERNATIONAL BUSINESS
                        # MACHINES CORP", which will never literal-match the
                        # query string. CIK is the one identifier that's
                        # actually stable across every endpoint's response
                        # format: edgar_ciks returns it unpadded ("51143"),
                        # wikipedia_firmographics/merged_firmographics return
                        # it zero-padded ("0000051143") - but the unpadded
                        # digits are always a substring of the padded form,
                        # so checking the unpadded CIK works against both.
                        expected_marker_by_url[url] = c["cik"]
                else:
                    param = ep.get("fixed_param", "")
                    field_name = path[path.find("{") + 1: path.find("}")] if "{" in path else None
                    url = path.format(**{field_name: param}) if field_name else path
                    batch = [Call(key, ep["category"], "-", url) for _ in range(level)]

                print(f"  concurrency={level:>2}  run={run_index + 1}/{repeat}  endpoint={key}")
                session = new_session()
                wall_start = time.perf_counter()
                # Per-company batches fetch bodies too, to verify concurrent
                # requests don't cross-contaminate results (see
                # docs/plans/performance-improvements.md, item 2, "Risk /
                # correctness verification" - this is exactly the check that
                # section calls for). Non-per-company batches (e.g. health)
                # have nothing company-specific to verify, so skip the extra
                # body fetch/parse cost for those.
                request_fn = do_request_with_body if ep["per_company"] else do_request
                with ThreadPoolExecutor(max_workers=level) as executor:
                    futures = {executor.submit(request_fn, session, base_url, call, timeout): call for call in batch}
                    for future in as_completed(futures):
                        call = futures[future]
                        result = future.result()
                        if ep["per_company"]:
                            status, latency_ms, error, body = result
                            if status == 200 and body is not None:
                                expected_cik = expected_marker_by_url[call.url]
                                if expected_cik.lower() not in body.lower():
                                    raise AssertionError(
                                        f"CONCURRENCY CORRECTNESS FAILURE on {call.endpoint_key} "
                                        f"(concurrency={level}, run={run_index + 1}): expected "
                                        f"response for {call.company_key!r} (CIK {expected_cik!r}) "
                                        f"to contain that CIK, but it didn't - this is exactly the "
                                        f"cross-request contamination "
                                        f"docs/plans/performance-improvements.md item 2 warns "
                                        f"about. Body (truncated): {body[:500]!r}"
                                    )
                        else:
                            status, latency_ms, error = result
                        results.append(
                            CallResult(call.endpoint_key, call.category, call.company_key, call.url, status, latency_ms, error, "concurrent", level, run_index)
                        )
                wall_ms = (time.perf_counter() - wall_start) * 1000
                print(f"    -> wall time for {level} concurrent calls: {wall_ms:.1f}ms" + (" (correctness verified)" if ep["per_company"] else ""))
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


def capture_provenance(namespace: str = "company-dns", deployment: str = "company-dns", base_url: str = "", image_label: str | None = None) -> dict:
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

    # kubectl reports what the PRODUCTION cluster runs. Asked about a container on this host (localhost) that would stamp a report
    # with an image that was not the one measured, so a local target is stamped from --image-label instead (or left unstamped).
    host = base_url.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    if host in ("localhost", "127.0.0.1", "::1") or image_label:
        provenance["deployed_image"] = image_label or "local container (not stamped; pass --image-label)"
        return provenance

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
    parser.add_argument(
        "--profile", choices=sorted(PROFILES), default="v3",
        help=(
            "'v3' (default): the full current-deployment endpoint catalog. "
            "'v4': restricted to endpoints the V4 prototype actually "
            "implements (US SIC + EDGAR - docs/plans/v4-server-prototype.md "
            "sec1/sec7), against V4.0-prefixed paths. Run once per profile "
            "against each target, then feed both reports into "
            "perf_tests/compare.py."
        ),
    )
    parser.add_argument("--concurrency", nargs="+", type=int, default=[1, 4, 8], help="concurrency levels to test, default: 1 4 8")
    parser.add_argument("--repeat", type=int, default=2, help="repeats per concurrency level, default: 2")
    parser.add_argument("--delay", type=float, default=0.15, help="seconds between sequential calls, default: 0.15")
    parser.add_argument("--timeout", type=float, default=30.0, help="per-request timeout in seconds, default: 30")
    parser.add_argument("--endpoints", default=None, help="comma-separated endpoint keys to run in the sequential pass (run_matrix.py uses one route per pass so a cold start is really cold)")
    parser.add_argument("--skip-sequential", action="store_true", help="only run the concurrency experiment (run_matrix.py takes the cold and warm sequential passes separately)")
    parser.add_argument("--skip-concurrency", action="store_true", help="only run the sequential baseline")
    parser.add_argument("--user-agent", default=SESSION_CONFIG["user_agent"], help="User-Agent sent with every request (a self-identifying one gets V4's normal rate limit)")
    parser.add_argument("--image-label", default=None, help="what was measured, stamped into the report as deployed_image (for example the image tag of a local container); a localhost target is never stamped from kubectl")
    parser.add_argument("--auth", metavar="PROFILE:TOKEN", default=None, help="HTTP Basic credential for V4 (a profile with rate_limit bypass, see v4/scripts/perf-profile.sh); ignored by V3")
    parser.add_argument("--list", action="store_true", help="print the call matrix and exit, without making requests")
    parser.add_argument("--out", type=Path, default=None, help="JSON output path, default: perf_tests/results/<timestamp>.json")
    args = parser.parse_args()
    SESSION_CONFIG['user_agent'] = args.user_agent
    if args.auth:
        SESSION_CONFIG['auth'] = tuple(args.auth.split(':', 1))

    calls = build_call_matrix(profile=args.profile)
    if args.endpoints:
        wanted = {e.strip() for e in args.endpoints.split(",") if e.strip()}
        unknown = wanted - {c.endpoint_key for c in calls}
        if unknown:
            parser.error(f"unknown endpoint key(s): {sorted(unknown)}")
        calls = [c for c in calls if c.endpoint_key in wanted]

    if args.list:
        for c in calls:
            print(f"{c.endpoint_key:28s} {c.category:12s} {c.company_key:12s} {c.url}")
        print(f"\n{len(calls)} sequential calls total.")
        return

    provenance = capture_provenance(base_url=args.base_url, image_label=args.image_label)
    provenance["profile"] = args.profile
    print(
        f"==> Provenance: git_commit={provenance['git_commit'] or '(unavailable)'} "
        f"deployed_image={provenance['deployed_image'] or '(unavailable)'} "
        f"profile={args.profile}"
    )

    print(f"==> Verifying endpoints against {args.base_url}/openapi.json")
    verify_endpoints_exist(args.base_url, args.timeout, args.profile)

    if args.skip_sequential:
        sequential_results = []
    else:
        print(f"\n==> Running {len(calls)} sequential calls against {args.base_url}")
        sequential_results = run_sequential(args.base_url, calls, args.delay, args.timeout)
        print_sequential_summary(sequential_results)

    concurrency_results = []
    if not args.skip_concurrency:
        print(f"\n==> Running concurrency experiment: levels={args.concurrency}, repeat={args.repeat}")
        concurrency_results = run_concurrency_experiment(args.base_url, COMPANIES, args.concurrency, args.repeat, args.timeout, args.profile)
        print_concurrency_summary(concurrency_results, sequential_results)

    out_path = args.out or Path(__file__).resolve().parent / "results" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "base_url": args.base_url,
        "profile": args.profile,
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
