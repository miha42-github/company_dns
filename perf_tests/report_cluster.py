#!/usr/bin/env python3
"""Pictures for the cluster sizing and the soak test (docs/performance-report.md), from the committed result files.

    perf_tests/.venv/bin/python perf_tests/report_cluster.py \\
        --sizing docs/results/2026-10-12-cluster/sizing.json --soak docs/results/2026-10-12-soak --out docs/results/2026-10-12

Needs matplotlib (perf_tests/requirements-report.txt in the gitignored perf_tests/.venv). The numbers and the findings in the titles are computed here
from the data (never typed in), in pure functions that are unit-tested (test_report_cluster.py); the drawing only draws them.
Same conventions as report.py: 16:9, the finding in the title, the conditions underneath, the provenance at the foot.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:  # the pure functions stay importable without matplotlib
    matplotlib = None
    plt = None

COLORS = ["#E69F00", "#0072B2", "#009E73", "#CC79A7", "#56B4E9"]  # Okabe-Ito, colour-blind safe
GREY = "#6b7280"
W, H, DPI = 13.33, 7.5, 120
P95_BAR_MS = 1000.0


# ---------------------------------------------------------------- the numbers (pure)
def cores_of(config: str) -> float:
    """`12x1000m/1Gi` -> 12.0 cores of limit."""
    replicas, rest = config.split("x", 1)
    return int(replicas) * int(rest.split("m", 1)[0]) / 1000.0


def pods_of(config: str) -> int:
    return int(config.split("x", 1)[0])


def best_sustained(rows: list[dict], p95_ms: float = P95_BAR_MS) -> dict | None:
    """The run with the most requests a second whose p95 is within the bar (the sizing test's own definition; no errors occurred in any run)."""
    good = [r for r in rows if r["p95_ms"] <= p95_ms]
    return max(good, key=lambda r: r["rps"]) if good else None


def at_level(rows: list[dict], n: int) -> dict | None:
    return next((r for r in rows if r["n"] == n), None)


def sizing_summary(data: dict) -> dict:
    """The comparisons the report states, computed: 12 cores at three shapes, and lookups against the number of one-core pods."""
    runs = data["runs"]
    twelve = ["3x4000m/4Gi", "6x2000m/2Gi", "12x1000m/1Gi"]
    emb = {c: best_sustained(runs["embedding"][c]) for c in twelve}
    look = {c: at_level(runs["lookups"][c], 256) for c in twelve}
    pods = ["12x1000m/1Gi", "16x1000m/1Gi", "20x1000m/1Gi"]
    scale = {c: at_level(runs["lookups"][c], 256) for c in pods}
    xs, ys = [pods_of(c) for c in pods], [scale[c]["rps"] for c in pods]
    slope = (ys[-1] - ys[0]) / (xs[-1] - xs[0])  # requests a second gained per extra one-core pod
    return {
        "twelve_core_embedding": {c: (emb[c]["rps"] if emb[c] else None) for c in twelve},
        "twelve_core_lookups": {c: look[c]["rps"] for c in twelve},
        "embedding_ratio": emb[twelve[2]]["rps"] / emb[twelve[0]]["rps"],
        "lookups_ratio": look[twelve[2]]["rps"] / look[twelve[0]]["rps"],
        "scaling": {c: {"rps": scale[c]["rps"], "p95_ms": scale[c]["p95_ms"], "cores_used": scale[c]["cpu_cores_used"]} for c in pods},
        "per_pod": slope,
        "per_core_used": {c: scale[c]["rps"] / scale[c]["cpu_cores_used"] for c in pods},
        "utilisation": {c: scale[c]["cpu_cores_used"] / cores_of(c) for c in pods},
    }


def read_soak(path: Path) -> list[dict]:
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            def num(k):
                return float(r[k]) if r.get(k) not in (None, "") else None
            rows.append({"time": r["time_utc"], "hours": num("elapsed_s") / 3600.0, "step": r["step"], "concurrency": int(r["concurrency"]), "requests": int(r["requests"]),
                         "errors": int(r["errors"]), "rate_limited": int(r["rate_limited"]), "rps": num("rps"), "p50": num("p50_ms"), "p95": num("p95_ms"),
                         "p99": num("p99_ms"), "max": num("max_ms"), "canaries_ok": int(r["canaries_ok"]), "canaries_total": int(r["canaries_total"]),
                         "health": num("health_ms"), "ok": r["window_ok"] == "True"})
    return rows


def soak_summary(rows: list[dict]) -> dict:
    hold = [r for r in rows if r["step"] == "hold"]
    q = max(1, len(hold) // 4)
    p95 = [r["p95"] for r in rows]
    by_hour = [statistics.median(r["p95"] for r in rows[i:i + 60]) for i in range(0, len(rows), 60)]
    return {
        "windows": len(rows), "hours": rows[-1]["hours"], "requests": sum(r["requests"] for r in rows), "errors": sum(r["errors"] for r in rows),
        "rate_limited": sum(r["rate_limited"] for r in rows), "canaries_ok": sum(r["canaries_ok"] for r in rows), "canaries_total": sum(r["canaries_total"] for r in rows),
        "windows_missed": sum(1 for r in rows if not r["ok"]), "p95_min": min(p95), "p95_max": max(p95), "p95_median": statistics.median(p95),
        "p50_median": statistics.median(r["p50"] for r in rows), "rps_median": statistics.median(r["rps"] for r in rows),
        "first_quarter_p95": statistics.median(r["p95"] for r in hold[:q]), "last_quarter_p95": statistics.median(r["p95"] for r in hold[-q:]),
        "slowest_request_ms": max(r["max"] for r in rows), "hourly_p95": by_hour,
    }


# ---------------------------------------------------------------- drawing
def _frame(title: str, subtitle: str, foot: str):
    """Title and subtitle wrapped by hand so a long finding never runs into what is under it; returns the figure and the height (0 to 1) left for the plot."""
    import textwrap
    t = textwrap.fill(title, 84)
    st = textwrap.fill(subtitle, 150)
    nt, ns = t.count("\n") + 1, st.count("\n") + 1
    fig = plt.figure(figsize=(W, H), dpi=DPI)
    fig.text(0.04, 0.965, t, fontsize=18, fontweight="bold", va="top", linespacing=1.15)
    y_sub = 0.965 - 0.052 * nt - 0.012
    fig.text(0.04, y_sub, st, fontsize=11, color=GREY, va="top", linespacing=1.3)
    fig.text(0.04, 0.02, foot, fontsize=8.5, color=GREY, va="bottom")
    top = y_sub - 0.034 * ns - 0.05
    return fig, top


def fig_shapes(data: dict, s: dict, out: Path, foot: str) -> None:
    twelve = list(s["twelve_core_embedding"])
    fig, top = _frame(f"At 12 cores, twelve 1-core pods carry {s['embedding_ratio']:.1f}x the embedding throughput of three 4-core pods; lookups are level ({s['lookups_ratio']:.2f}x)",
                 "Same 12 cores of limit in three shapes. Embedding: best requests/s with p95 under 1 s. Lookups: requests/s at 256 concurrent requests. One run per cell, shared nodes: "
                 "differences under about 20% are noise.", foot)
    for i, (key, label, vals) in enumerate((("embedding", "Embedding searches (requests/s, p95 under 1 s)", s["twelve_core_embedding"]),
                                            ("lookups", "Code and description lookups (requests/s at N=256)", s["twelve_core_lookups"]))):
        ax = fig.add_axes([0.07 + i * 0.47, 0.12, 0.4, top - 0.12])
        bars = ax.bar(range(3), [vals[c] or 0 for c in twelve], color=COLORS[:3])
        for b, c in zip(bars, twelve):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{vals[c]:.0f}", ha="center", va="bottom", fontsize=12, fontweight="bold")
        ax.set_xticks(range(3))
        ax.set_xticklabels([c.replace("/", "\n") for c in twelve], fontsize=10)
        ax.set_title(label, fontsize=12)
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_ylim(0, max(vals.values()) * 1.15)
    fig.savefig(out, dpi=DPI)
    plt.close(fig)


def fig_scaling(data: dict, s: dict, out: Path, foot: str) -> None:
    cfgs = list(s["scaling"])
    pods = [pods_of(c) for c in cfgs]
    fig, top = _frame(f"Lookups keep scaling with the number of 1-core pods: {s['scaling'][cfgs[0]]['rps']:.0f} to {s['scaling'][cfgs[-1]]['rps']:.0f} requests/s from {pods[0]} to {pods[-1]} pods "
                 f"(about {s['per_pod']:.0f} more for each pod added)",
                 f"Random lookups at 256 concurrent requests, 1000m / 1Gi pods. The pods used {min(s['utilisation'].values()):.0%} to {max(s['utilisation'].values()):.0%} of their CPU limit, so the ceiling is a little above these figures. p95 fell as pods were added.",
                 foot)
    ax = fig.add_axes([0.08, 0.12, 0.82, top - 0.12 - 0.05])
    ax.plot(pods, [s["scaling"][c]["rps"] for c in cfgs], "o-", color=COLORS[1], lw=2.5, ms=9)
    for p, c in zip(pods, cfgs):
        ax.annotate(f"{s['scaling'][c]['rps']:.0f} req/s\np95 {s['scaling'][c]['p95_ms']:.0f} ms", (p, s["scaling"][c]["rps"]), textcoords="offset points", xytext=(0, 12), ha="center", fontsize=11)
    ax.set_xticks(pods)
    ax.set_xlabel("pods (1 core each)")
    ax.set_ylabel("requests per second")
    ax.set_ylim(0, max(s["scaling"][c]["rps"] for c in cfgs) * 1.25)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(out, dpi=DPI)
    plt.close(fig)


def fig_soak(rows: list[dict], s: dict, out: Path, foot: str, label: str) -> None:
    fig, top = _frame(f"{s['hours']:.0f} hours at {s['rps_median']:.0f} requests/s from outside the network: p95 stayed between {s['p95_min']:.0f} and {s['p95_max']:.0f} ms, "
                 f"{s['errors']} errors, {s['canaries_ok']:,} of {s['canaries_total']:,} canary answers correct",
                 f"{s['requests']:,} requests in {s['windows']:,} one-minute windows ({label}). The run was capped at 60 requests/s, so this shows stability for that workload, not capacity. "
                 f"Median p95 {s['first_quarter_p95']:.0f} ms in the first quarter of the hold, {s['last_quarter_p95']:.0f} ms in the last.", foot)
    xs = [r["hours"] for r in rows]
    mid = 0.12 + (top - 0.12) * 0.48
    a1 = fig.add_axes([0.08, mid + 0.03, 0.84, top - mid - 0.05])
    a1.plot(xs, [r["p95"] for r in rows], color=COLORS[1], lw=1.2, label="p95")
    a1.plot(xs, [r["p50"] for r in rows], color=COLORS[2], lw=1.2, label="p50")
    a1.set_ylabel("latency (ms)")
    a1.set_ylim(0, max(r["p95"] for r in rows) * 1.5)
    a1.legend(loc="upper right", frameon=False, ncol=2)
    a1.spines[["top", "right"]].set_visible(False)
    a1.tick_params(labelbottom=False)
    a2 = fig.add_axes([0.08, 0.12, 0.84, mid - 0.12 - 0.03], sharex=a1)
    a2.plot(xs, [r["max"] for r in rows], color=COLORS[0], lw=0.9)
    a2.set_ylabel("slowest request\nin each window (ms)")
    a2.set_xlabel("hours since the start")
    a2.spines[["top", "right"]].set_visible(False)
    fig.savefig(out, dpi=DPI)
    plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sizing", type=Path, required=True)
    ap.add_argument("--soak", type=Path, required=True, help="a directory with windows.csv and meta.json")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if plt is None:
        print("matplotlib is not installed: use perf_tests/.venv (perf_tests/requirements-report.txt)", file=sys.stderr)
        return 2
    sizing = json.loads(a.sizing.read_text())
    rows = read_soak(a.soak / "windows.csv")
    meta = json.loads((a.soak / "meta.json").read_text())
    s, k = sizing_summary(sizing), soak_summary(rows)
    a.out.mkdir(parents=True, exist_ok=True)
    foot_c = f"Cluster sizing, recorded {sizing['recorded']}: perf_tests/run_cluster.py, staging namespace, closed-loop load from the build node. Data: docs/results/2026-10-12-cluster/sizing.json"
    foot_s = f"Soak test started {meta['started_utc']}, perf_tests/soak.py, label {meta['label']}, {meta['python']} on {meta['platform'].split('-with')[0]}. Data: docs/results/2026-10-12-soak/"
    fig_shapes(sizing, s, a.out / "c1-shapes-at-12-cores.png", foot_c)
    fig_scaling(sizing, s, a.out / "c2-lookups-scale-with-pods.png", foot_c)
    fig_soak(rows, k, a.out / "s1-soak-24h.png", foot_s, meta["label"])
    print(json.dumps({"sizing": s, "soak": {x: v for x, v in k.items() if x != "hourly_p95"}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
