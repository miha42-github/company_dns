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


# ---------------------------------------------------------------- aggregation across repeated runs (inputs of the figures)
def _by_k(runs: list[dict]) -> list[dict]:
    return sorted(runs, key=lambda r: r["k"])


def phase_stats(runs: list[dict], phase: str) -> dict[str, dict]:
    """Per route, over the repeated runs of one image: {route: {"median": [per-run medians], "p95": [per-run p95s], "n": calls per run, "category": ...}}.
    `phase` is 'cold' or 'warm'. Runs that lack the phase are skipped."""
    out: dict[str, dict] = {}
    for run in _by_k(runs):
        rep = run.get(phase)
        if not rep:
            continue
        for route, st in sequential_stats(rep["sequential_results"]).items():
            d = out.setdefault(route, {"median": [], "p95": [], "n": st["n"], "category": st["category"], "k": []})
            d["median"].append(st["median"])
            d["p95"].append(st["p95"])
            d["k"].append(run["k"])
    return out


def concurrency_table(runs: list[dict]) -> dict[tuple[str, int], dict]:
    """Per (route, N), over the repeated runs: lists of wall time (ms), speedup and calls per second, one entry per run. Speedup uses that run's warm pass."""
    out: dict[tuple[str, int], dict] = {}
    for run in _by_k(runs):
        conc, warm = run.get("conc"), run.get("warm")
        if not conc:
            continue
        seq = warm["sequential_results"] if warm else []
        for key, st in concurrency_stats(conc["concurrency_results"], seq).items():
            d = out.setdefault(key, {"wall": [], "speedup": [], "cps": [], "errors": 0})
            d["wall"].append(st["wall_median"])
            d["speedup"].append(st["speedup"])
            d["cps"].append(st["calls_per_second"])
            d["errors"] += st["errors"]
    return out


def status_totals(runs: list[dict]) -> dict[str, int]:
    """Every measured call of an image, by outcome: ok (200), not_found (404), other_status, error (no response, for example a timeout), and incorrect
    (a 200 whose answer lacked the expected CIK: contaminated with another company's data, or incomplete)."""
    t = {"ok": 0, "not_found": 0, "other_status": 0, "error": 0, "incorrect": 0}
    for run in runs:
        for phase, field in (("cold", "sequential_results"), ("warm", "sequential_results"), ("conc", "concurrency_results")):
            rep = run.get(phase)
            for r in (rep or {}).get(field, []):
                if str(r.get("error") or "").startswith("incorrect"):
                    t["incorrect"] += 1  # answered 200, but the answer was wrong or incomplete (recorded by baseline.py --record-incorrect)
                elif r.get("error") or r.get("status_code") is None:
                    t["error"] += 1
                elif r["status_code"] == 200:
                    t["ok"] += 1
                elif r["status_code"] == 404:
                    t["not_found"] += 1
                else:
                    t["other_status"] += 1
    return t


def paired_verdicts(a: dict[str, dict], b: dict[str, dict]) -> dict[str, str]:
    """The regression rule applied route by route: `a` is the baseline image's phase_stats, `b` the candidate's. Pairs repeats by run number."""
    out = {}
    for route in sorted(set(a) & set(b)):
        ka, kb = a[route]["k"], b[route]["k"]
        common = [k for k in ka if k in kb]
        va = [a[route]["median"][ka.index(k)] for k in common]
        vb = [b[route]["median"][kb.index(k)] for k in common]
        # With fewer repeats than the rule's minimum the verdict is indicative: it needs every available repeat to agree.
        out[route] = regression_verdict(va, vb, min_repeats=min(MIN_REPEATS, len(common))) if common else "not enough repeats"
    return out


def geometric_mean(values: list[float]) -> float:
    import math
    vals = [v for v in values if v and v > 0 and v == v]
    return math.exp(sum(math.log(v) for v in vals) / len(vals)) if vals else float("nan")


def verdict_counts(verdicts: dict[str, str]) -> dict[str, int]:
    c = {"improved": 0, "no difference": 0, "regression": 0, "not enough repeats": 0}
    for v in verdicts.values():
        c[v] = c.get(v, 0) + 1
    return c
