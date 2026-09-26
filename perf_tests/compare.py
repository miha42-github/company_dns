#!/usr/bin/env python3
"""
Diff two perf_tests/baseline.py JSON reports.

Turns "eyeball two summary tables" into an actual delta report: per-endpoint
median/p95 latency change (sequential), and per (endpoint, concurrency
level) wall-time and speedup-vs-serial change (concurrency), with
REGRESSION/IMPROVED flags so the interesting rows are obvious at a glance.

Usage:
    python3 perf_tests/compare.py before.json after.json
    python3 perf_tests/compare.py before.json after.json --out diff.json
    python3 perf_tests/compare.py before.json after.json --regression-pct 10 --improvement-pct 20

Caveat this tool cannot fix (see perf_tests/README.md and
docs/plans/performance-improvements.md, item 4's "what this does not try to
solve"): external-API-bound endpoints (wikipedia_firmographics,
merged_firmographics) carry real variance from Wikipedia/Wikidata's own
response times and upstream caching that has nothing to do with company_dns
code changes. A REGRESSION/IMPROVED flag on those endpoints when the actual
change was e.g. a DB fix unrelated to Wikipedia is noise, not signal - read
the endpoint's category (control / external-io) before trusting a flag.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from baseline import percentile  # noqa: E402


def load_report(path: Path) -> dict:
    return json.loads(path.read_text())


def print_provenance(label: str, report: dict) -> None:
    print(
        f"{label}: {report.get('base_url', '?')}  "
        f"git_commit={report.get('git_commit') or '(unavailable)'}  "
        f"deployed_image={report.get('deployed_image') or '(unavailable)'}  "
        f"generated_at={report.get('generated_at', '?')}"
    )


def sequential_stats_by_endpoint(results: list[dict]) -> dict[str, dict]:
    by_endpoint: dict[str, list[dict]] = {}
    for r in results:
        by_endpoint.setdefault(r["endpoint_key"], []).append(r)
    stats = {}
    for key, rs in by_endpoint.items():
        latencies = [r["latency_ms"] for r in rs]
        ok = sum(1 for r in rs if r["status_code"] == 200)
        stats[key] = {
            "category": rs[0]["category"],
            "n": len(rs),
            "ok_pct": 100 * ok / len(rs),
            "median": statistics.median(latencies),
            "p95": percentile(latencies, 0.95),
        }
    return stats


def concurrency_stats_by_key(
    concurrency_results: list[dict], sequential_results: list[dict]
) -> dict[tuple[str, int], dict]:
    seq_median_by_endpoint = {}
    by_endpoint_seq: dict[str, list[dict]] = {}
    for r in sequential_results:
        by_endpoint_seq.setdefault(r["endpoint_key"], []).append(r)
    for key, rs in by_endpoint_seq.items():
        seq_median_by_endpoint[key] = statistics.median(r["latency_ms"] for r in rs)

    by_key: dict[tuple[str, int], list[dict]] = {}
    for r in concurrency_results:
        by_key.setdefault((r["endpoint_key"], r["concurrency_level"]), []).append(r)

    stats = {}
    for (key, level), rs in by_key.items():
        by_run: dict[int, list[dict]] = {}
        for r in rs:
            by_run.setdefault(r["run_index"], []).append(r)
        wall_times = [max(r["latency_ms"] for r in run_calls) for run_calls in by_run.values()]
        seq_baseline = seq_median_by_endpoint.get(key, float("nan"))
        ideal_if_serial = seq_baseline * level
        wall_median = statistics.median(wall_times)
        speedup = ideal_if_serial / wall_median if wall_median else float("nan")
        stats[(key, level)] = {"wall_median": wall_median, "speedup": speedup}
    return stats


def flag(before: float, after: float, regression_pct: float, improvement_pct: float) -> str:
    if before == 0 or before != before or after != after:  # nan guard
        return ""
    pct_change = 100 * (after - before) / before
    if pct_change >= regression_pct:
        return f"REGRESSION (+{pct_change:.0f}%)"
    if pct_change <= -improvement_pct:
        return f"IMPROVED ({pct_change:.0f}%)"
    return ""


def print_sequential_diff(before: dict, after: dict, regression_pct: float, improvement_pct: float) -> None:
    print("\n=== Sequential latency: before -> after ===")
    header = f"{'endpoint':28s} {'category':12s} {'before(median)':>15s} {'after(median)':>14s} {'p95 before':>11s} {'p95 after':>10s} {'flag':>22s}"
    print(header)
    print("-" * len(header))
    all_keys = sorted(set(before) | set(after))
    for key in all_keys:
        b = before.get(key)
        a = after.get(key)
        if b is None:
            print(f"{key:28s} {'(new in after)':>66s}")
            continue
        if a is None:
            print(f"{key:28s} {'(missing in after)':>66s}")
            continue
        f = flag(b["median"], a["median"], regression_pct, improvement_pct)
        print(
            f"{key:28s} {a['category']:12s} {b['median']:>13.1f}m {a['median']:>12.1f}m "
            f"{b['p95']:>9.1f}m {a['p95']:>8.1f}m {f:>22s}"
        )


def print_concurrency_diff(before: dict, after: dict, regression_pct: float, improvement_pct: float) -> None:
    if not before and not after:
        return
    print("\n=== Concurrency scaling: before -> after ===")
    header = f"{'endpoint':28s} {'N':>3s} {'wall before':>12s} {'wall after':>11s} {'speedup before':>15s} {'speedup after':>14s} {'flag (wall time)':>22s}"
    print(header)
    print("-" * len(header))
    all_keys = sorted(set(before) | set(after), key=lambda kv: (kv[0], kv[1]))
    for key in all_keys:
        b = before.get(key)
        a = after.get(key)
        if b is None or a is None:
            endpoint, level = key
            status = "(new in after)" if b is None else "(missing in after)"
            print(f"{endpoint:28s} {level:>3d} {status:>63s}")
            continue
        endpoint, level = key
        f = flag(b["wall_median"], a["wall_median"], regression_pct, improvement_pct)
        print(
            f"{endpoint:28s} {level:>3d} {b['wall_median']:>11.1f}m {a['wall_median']:>10.1f}m "
            f"{b['speedup']:>14.2f}x {a['speedup']:>13.2f}x {f:>22s}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("before", type=Path, help="earlier perf_tests/baseline.py JSON report")
    parser.add_argument("after", type=Path, help="later perf_tests/baseline.py JSON report")
    parser.add_argument("--regression-pct", type=float, default=10.0, help="flag as REGRESSION if median got this much worse (%%), default: 10")
    parser.add_argument("--improvement-pct", type=float, default=20.0, help="flag as IMPROVED if median got this much better (%%), default: 20")
    parser.add_argument("--out", type=Path, default=None, help="also write the diff as JSON")
    args = parser.parse_args()

    before_report = load_report(args.before)
    after_report = load_report(args.after)

    print_provenance("BEFORE", before_report)
    print_provenance("AFTER ", after_report)

    before_seq = sequential_stats_by_endpoint(before_report.get("sequential_results", []))
    after_seq = sequential_stats_by_endpoint(after_report.get("sequential_results", []))
    print_sequential_diff(before_seq, after_seq, args.regression_pct, args.improvement_pct)

    before_conc = concurrency_stats_by_key(
        before_report.get("concurrency_results", []), before_report.get("sequential_results", [])
    )
    after_conc = concurrency_stats_by_key(
        after_report.get("concurrency_results", []), after_report.get("sequential_results", [])
    )
    print_concurrency_diff(before_conc, after_conc, args.regression_pct, args.improvement_pct)

    print(
        "\n(Reminder: external-io endpoints hitting Wikipedia/EDGAR carry real "
        "upstream variance unrelated to code changes - see this file's "
        "docstring before treating every flag above as caused by your change.)"
    )

    if args.out:
        diff = {
            "before": {"path": str(args.before), "base_url": before_report.get("base_url"), "git_commit": before_report.get("git_commit"), "deployed_image": before_report.get("deployed_image"), "generated_at": before_report.get("generated_at")},
            "after": {"path": str(args.after), "base_url": after_report.get("base_url"), "git_commit": after_report.get("git_commit"), "deployed_image": after_report.get("deployed_image"), "generated_at": after_report.get("generated_at")},
            "sequential": {
                key: {
                    "before": before_seq.get(key),
                    "after": after_seq.get(key),
                }
                for key in sorted(set(before_seq) | set(after_seq))
            },
            "concurrency": {
                f"{key[0]}@{key[1]}": {
                    "before": before_conc.get(key),
                    "after": after_conc.get(key),
                }
                for key in sorted(set(before_conc) | set(after_conc), key=lambda kv: (kv[0], kv[1]))
            },
        }
        args.out.write_text(json.dumps(diff, indent=2))
        print(f"\n==> Diff written to {args.out}")


if __name__ == "__main__":
    main()
