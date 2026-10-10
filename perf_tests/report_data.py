"""Numbers for the V3-versus-V4 results report (docs/plans/v4-results-report.md). Standard library only, so it runs anywhere and is unit-tested.

It turns raw files into the figures' inputs and holds the rules the report states in words, in one place:

- latency and concurrency statistics per route (the same definitions as `compare.py`: wall time of a concurrent batch is its slowest call);
- the regression rule: a route regresses only if V4's median is more than `PCT` worse than V3's in at least `MIN_REPEATS` of the repeated runs (default 10% in 2 of 3), improves
  under the mirror rule, and is otherwise "no difference";
- route coverage: every route in V3's OpenAPI spec is served by V4, or excluded by a recorded decision, or missing;
- summaries of the parity report and of the test suite report, by layer.

The matrix directory it reads (written by `run_matrix.py`) is described in `load_matrix`.
"""
from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

PCT = 10.0
MIN_REPEATS = 2

# test module -> layer (docs/plans/v4-release-to-staging.md, step 3)
LAYERS = {
    "test_smoke": "L0 smoke",
    "test_contract": "L1 contract",
    "test_data_readiness": "L2 data",
    "test_non_us_sic": "L3 parity",
    "test_edgar_wikipedia_parity": "L3 parity",
    "test_v4_functions": "L4 V4 functions",
    "test_limits_and_profiles": "L5 limits and profiles",
}

# V3 routes V4 leaves out on purpose: (substring of the path, reason)
EXCLUDED_BY_DECISION = [
    ("/uk/", "UK SIC left out by decision (plan question Q3)"),
    ("/v1/", "the wptools v1 backends are not carried over"),
]


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank interpolation, the same as perf_tests/baseline.py."""
    s = sorted(values)
    if not s:
        return float("nan")
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


# ---------------------------------------------------------------- latency and concurrency
def sequential_stats(results: list[dict]) -> dict[str, dict]:
    """Per route: count, ok count, error count, median and p95 latency (ms)."""
    by: dict[str, list[dict]] = {}
    for r in results:
        by.setdefault(r["endpoint_key"], []).append(r)
    out = {}
    for key, rs in by.items():
        lat = [r["latency_ms"] for r in rs]
        out[key] = {
            "category": rs[0]["category"],
            "n": len(rs),
            "ok": sum(1 for r in rs if r["status_code"] == 200),
            "errors": sum(1 for r in rs if r.get("error")),
            "median": statistics.median(lat),
            "p95": percentile(lat, 0.95),
        }
    return out


def concurrency_stats(conc: list[dict], seq: list[dict]) -> dict[tuple[str, int], dict]:
    """Per (route, N): median wall time of a batch of N concurrent calls, speedup against N sequential calls, calls per second."""
    seq_median = {k: v["median"] for k, v in sequential_stats(seq).items()}
    groups: dict[tuple[str, int], dict[int, list[dict]]] = {}
    for r in conc:
        groups.setdefault((r["endpoint_key"], r["concurrency_level"]), {}).setdefault(r["run_index"], []).append(r)
    out = {}
    for (key, n), runs in groups.items():
        walls = [max(c["latency_ms"] for c in calls) for calls in runs.values()]
        wall = statistics.median(walls)
        errors = sum(1 for calls in runs.values() for c in calls if c.get("error"))
        out[(key, n)] = {
            "wall_median": wall,
            "speedup": (seq_median.get(key, float("nan")) * n) / wall if wall else float("nan"),
            "calls_per_second": n / (wall / 1000.0) if wall else float("nan"),
            "errors": errors,
            "batches": len(runs),
        }
    return out


def spread(values: list[float]) -> dict:
    """Median, min and max across repeated runs: what the error bars show."""
    return {"median": statistics.median(values), "min": min(values), "max": max(values), "n": len(values)}


def regression_verdict(v3_medians: list[float], v4_medians: list[float], pct: float = PCT, min_repeats: int = MIN_REPEATS) -> str:
    """'regression', 'improved' or 'no difference' for one route in one regime, from the medians of paired repeated runs."""
    pairs = list(zip(v3_medians, v4_medians))
    if len(pairs) < min_repeats:
        return "not enough repeats"
    worse = sum(1 for a, b in pairs if a > 0 and 100 * (b - a) / a > pct)
    better = sum(1 for a, b in pairs if a > 0 and 100 * (a - b) / a > pct)
    if worse >= min_repeats:
        return "regression"
    if better >= min_repeats:
        return "improved"
    return "no difference"


# ---------------------------------------------------------------- function evidence
def normalise_path(path: str) -> str:
    """A path template without its parameter names, so `/x/{sic_no}` and `/x/{code}` are the same route."""
    return re.sub(r"\{[^}]*\}", "{}", path)


def route_coverage(v3_spec: dict, v4_spec: dict) -> dict:
    """Every V3 route as served / excluded (with the reason) / missing, and the V4 routes V3 does not have."""
    v4_paths = {normalise_path(p) for p in v4_spec.get("paths", {})}
    served, excluded, missing = [], [], []
    for p in sorted(v3_spec.get("paths", {})):
        n = normalise_path(p)
        if n in v4_paths:
            served.append(p)
            continue
        reason = next((why for sub, why in EXCLUDED_BY_DECISION if sub in p.lower()), None)
        (excluded.append((p, reason)) if reason else missing.append(p))
    v3_norm = {normalise_path(p) for p in v3_spec.get("paths", {})}
    v4_only = sorted(p for p in v4_spec.get("paths", {}) if normalise_path(p) not in v3_norm)
    return {"served": served, "excluded": excluded, "missing": missing, "v4_only": v4_only}


def parity_summary(rows: list[dict]) -> dict:
    """Counts by verdict from `parity_report.py --json`, and the rows that are not identical."""
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {"counts": counts, "not_identical": [r for r in rows if r["verdict"] != "IDENTICAL"], "total": len(rows)}


def suite_by_layer(report: dict) -> dict[str, dict[str, int]]:
    """Test statuses by layer, from an `api_tests/run.py --report` file."""
    out: dict[str, dict[str, int]] = {}
    for r in report.get("results", []):
        module = r["id"].split(".")[0].split(" ")[-1].strip("()")
        layer = LAYERS.get(module, "other")
        status = r["status"]
        out.setdefault(layer, {})
        out[layer][status] = out[layer].get(status, 0) + 1
    return out


# ---------------------------------------------------------------- reading a matrix directory
def load_matrix(root: Path) -> dict:
    """Read a `matrix-<date>-<host>` directory written by `run_matrix.py`:

        manifest.json
        raw/<regime>/<image>/run<k>/{sequential-cold.json, sequential-warm.json, concurrency.json, resources.csv, container.json}
        specs/{v3,v4}-openapi.json     parity/<image>.json     suite/<image>.json

    Returns {"manifest": ..., "runs": {(regime, image): [{"k": k, "cold": report, "warm": report, "conc": report, "resources": [...]}]}, ...}.
    Missing optional files are simply absent from the result.
    """
    root = Path(root)

    def jload(p: Path):
        return json.loads(p.read_text()) if p.exists() else None

    runs: dict[tuple[str, str], list[dict]] = {}
    raw = root / "raw"
    if raw.is_dir():
        for regime in sorted(p for p in raw.iterdir() if p.is_dir()):
            for image in sorted(p for p in regime.iterdir() if p.is_dir()):
                for rd in sorted((p for p in image.iterdir() if p.is_dir() and p.name.startswith("run")), key=lambda p: int(p.name[3:])):
                    res = rd / "resources.csv"
                    runs.setdefault((regime.name, image.name), []).append({
                        "k": int(rd.name[3:]),
                        "cold": jload(rd / "sequential-cold.json"),
                        "warm": jload(rd / "sequential-warm.json"),
                        "conc": jload(rd / "concurrency.json"),
                        "container": jload(rd / "container.json"),
                        "resources": read_resources(res) if res.exists() else [],
                    })
    return {
        "manifest": jload(root / "manifest.json"),
        "runs": runs,
        "specs": {n: jload(root / "specs" / f"{n}-openapi.json") for n in ("v3", "v4")},
        "parity": {p.stem: jload(p) for p in sorted((root / "parity").glob("*.json"))} if (root / "parity").is_dir() else {},
        "suite": {p.stem: jload(p) for p in sorted((root / "suite").glob("*.json"))} if (root / "suite").is_dir() else {},
    }


def read_resources(path: Path) -> list[dict]:
    """`resources.csv`: t_seconds,cpu_percent,mem_mib, one row per second of sampling."""
    rows = []
    for line in Path(path).read_text().splitlines()[1:]:
        t, cpu, mem = line.split(",")[:3]
        rows.append({"t": float(t), "cpu": float(cpu), "mem": float(mem)})
    return rows


def resource_summary(rows: list[dict]) -> dict:
    """Idle (first 5 samples) and peak memory, and mean and peak CPU, from sampled rows."""
    if not rows:
        return {}
    mem = [r["mem"] for r in rows]
    cpu = [r["cpu"] for r in rows]
    return {
        "idle_mem_mib": statistics.median(mem[:5]),
        "peak_mem_mib": max(mem),
        "mean_cpu": statistics.mean(cpu),
        "peak_cpu": max(cpu),
        "seconds": rows[-1]["t"] - rows[0]["t"],
    }
