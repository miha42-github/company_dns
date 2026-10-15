#!/usr/bin/env python3
"""Pictures that explain the test runs, from their result files: pods coming and going under a steady load, the ceiling, and the rate-limit probe.

    perf_tests/.venv/bin/python perf_tests/report_runs.py rollout docs/results/2026-10-13-rollout docs/results/2026-10-14-shutdown --out docs/results/2026-10-14 --zoom "restart all pods"
    perf_tests/.venv/bin/python perf_tests/report_runs.py ceiling --run ./tmp/ceiling-merged --watch ./tmp/watch-ceiling-staging --out docs/results/2026-10-14
    perf_tests/.venv/bin/python perf_tests/report_runs.py limit ./tmp/limit-studio ./tmp/limit-mini ./tmp/limit-laptop --out docs/results/2026-10-14

Needs matplotlib (perf_tests/requirements-report.txt, the gitignored perf_tests/.venv). Same conventions as report.py and report_cluster.py: 16:9, the finding in the title computed from the data (never
typed in), the conditions underneath, the provenance at the foot. The numbers come from pure functions that are unit-tested (test_report_runs.py); the drawing only draws them.

A rollout directory is what a scenario-2 run leaves: windows.csv and meta.json (soak.py), events.txt (your marks) and watch.csv (pod_watch.py). The soak's clock is lined up with the watcher's from the
load itself, as soak_analyze.py does.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ceiling as ce  # noqa: E402
import report_cluster as rcl  # noqa: E402
import soak_analyze as sa  # noqa: E402

plt = rcl.plt
BLUE, ORANGE, GREEN, PINK, SKY = rcl.COLORS[1], rcl.COLORS[0], rcl.COLORS[2], rcl.COLORS[3], rcl.COLORS[4]
GREY = rcl.GREY
RED = "#D55E00"


# ---------------------------------------------------------------- rollouts: pods coming and going under a steady load
def load_rollout(d: Path) -> dict:
    rows, meta = sa.read_windows(d)
    watch = sa.read_watch(d)
    events, _ = sa.read_events(d / "events.txt")
    window_s = float(meta["window_s"])
    shift, note = sa.align(rows, watch, window_s, None, False)
    for r in rows:
        r["t"] += shift  # the soak's windows on the watcher's clock (the clock the marks were made on)
    return {"dir": d, "rows": rows, "meta": meta, "watch": watch, "events": events, "window_s": window_s, "shift": shift, "note": note}


def rollout_findings(run: dict, span_min: float = 5.0) -> dict:
    rows, watch, events, window_s = run["rows"], run["watch"], run["events"], run["window_s"]
    results, baseline = sa.judge_events(rows, window_s, events, watch, span_min)
    changes = [r for r in results if r["verdict"] != "NOT JUDGED" and "soak started" not in r["text"].lower()]
    t0, t1 = rows[0]["t"], rows[-1]["t"] + window_s
    during = [w for w in watch if t0 <= w["t"] <= t1]
    unscaled = [r for r in changes if "scale" not in r["text"].lower()]
    worst = max((r["p95_max"] for r in changes if r["p95_max"] is not None), default=baseline)
    return {"changes": changes, "n_changes": len(changes), "baseline": baseline, "worst_p95": worst, "errors": sum(r["errors"] for r in rows), "requests": sum(r["requests"] for r in rows),
            "rps": statistics.median(r["rps"] for r in rows), "max_terminating": max((int(w["terminating"]) for w in during), default=0), "max_pods": max((int(w["pods"]) for w in during), default=0),
            "min_ready_unscaled": min((r["min_ready"] for r in unscaled if r["min_ready"] is not None), default=None), "all_pass": all(r["verdict"] == "PASS" for r in changes),
            "canary_bad": sum(r["canaries_total"] - r["canaries_ok"] for r in rows), "interval": statistics.median(b["t"] - a["t"] for a, b in zip(watch, watch[1:])) if len(watch) > 1 else None,
            "results": results}


def _step(ax, xs, ys, **kw):
    ax.step(xs, ys, where="post", **kw)


def fig_rollout(run: dict, f: dict, out: Path, foot: str) -> None:
    rows, watch, window_s = run["rows"], run["watch"], run["window_s"]
    t0 = rows[0]["t"]
    end_min = (rows[-1]["t"] + window_s - t0) / 60
    changes = f["changes"]
    labels = "   ".join(f"{i + 1} {c['text']}" for i, c in enumerate(changes))
    word = "request errors" if f["errors"] != 1 else "request error"
    fig, top = rcl._frame(f"{f['n_changes']} changes to the pods under a steady {f['rps']:.0f} requests/s: {f['errors']} {word}, p95 within {max(0.0, f['worst_p95'] - f['baseline']):.0f} ms of its {f['baseline']:.0f} ms baseline",
                          f"{labels}. Pods are sampled every {f['interval']:.0f} s; the client's numbers are one-minute windows ({f['requests']:,} requests in all). {run['note'].replace('Alignment: ', 'Clocks: ')}", foot)
    xs = [(w["t"] - t0) / 60 for w in watch]
    sel = [i for i, x in enumerate(xs) if -2 <= x <= end_min + 2]
    wx = [xs[i] for i in sel]
    h = top - 0.12
    a1 = fig.add_axes([0.07, 0.12 + h * 0.52, 0.89, h * 0.46])
    a2 = fig.add_axes([0.07, 0.12 + h * 0.20, 0.89, h * 0.28], sharex=a1)
    a3 = fig.add_axes([0.07, 0.12, 0.89, h * 0.14], sharex=a1)
    _step(a1, wx, [int(watch[i]["pods"]) for i in sel], color=GREY, lw=1.6, label="pods that exist")
    _step(a1, wx, [int(watch[i]["ready"]) for i in sel], color=BLUE, lw=2.4, label="ready")
    _step(a1, wx, [int(watch[i]["terminating"]) for i in sel], color=ORANGE, lw=1.8, label="stopping (Terminating)")
    a1.set_ylabel("pods")
    a1.set_ylim(0, max(int(watch[i]["pods"]) for i in sel) * 1.25)
    a1.legend(loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=3, frameon=False, fontsize=9)
    wmid = [(r["t"] + window_s / 2 - t0) / 60 for r in rows]
    a2.plot(wmid, [r["p95_ms"] for r in rows], color=BLUE, lw=1.6, marker="o", ms=2.5, label="p95")
    a2.plot(wmid, [r["p50_ms"] for r in rows], color=GREEN, lw=1.4, label="p50")
    a2.axhline(f["baseline"], color=GREY, ls=":", lw=1)
    a2.set_ylim(0, max(r["p95_ms"] for r in rows) * 1.8)
    a2.set_ylabel("client latency (ms)")
    a2.legend(loc="upper right", ncol=2, frameon=False, fontsize=9)
    a3.bar(wmid, [r["errors"] for r in rows], width=0.8, color=RED)
    a3.set_ylabel("errors per\nminute")
    a3.set_ylim(0, max(1, max(r["errors"] for r in rows)))
    a3.set_xlabel("minutes since the load started")
    for k, (ev, c) in enumerate(zip(changes, changes), 1):
        x = (sa.parse_utc(c["time"]) - t0) / 60
        for ax in (a1, a2, a3):
            ax.axvline(x, color="#374151", ls="--", lw=0.9, alpha=0.7)
        a1.text(x, a1.get_ylim()[1], f" {k}", va="top", ha="left", fontsize=12, fontweight="bold", color="#374151")
    for ax in (a1, a2, a3):
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_xlim(-1, end_min + 1)
    a1.tick_params(labelbottom=False)
    a2.tick_params(labelbottom=False)
    fig.savefig(out, dpi=rcl.DPI)
    plt.close(fig)


def fig_rollout_zoom(run: dict, f: dict, match: str, out: Path, foot: str) -> bool:
    """One change at the sampling resolution: the pods every few seconds against the client's one-minute windows. False if no change matches."""
    change = next((c for c in f["changes"] if match.lower() in c["text"].lower()), None)
    if change is None:
        return False
    rows, watch, window_s = run["rows"], run["watch"], run["window_s"]
    t = sa.parse_utc(change["time"])
    lo, hi = -60, 240
    seg = [w for w in watch if t + lo <= w["t"] <= t + hi]
    if not seg:
        return False
    ready, term, pods = [int(w["ready"]) for w in seg], [int(w["terminating"]) for w in seg], [int(w["pods"]) for w in seg]
    stopping_at = [w["t"] - t for w in seg if int(w["terminating"]) > 0]
    stopping = (f"Pods were in Terminating from {min(stopping_at):.0f} s to {max(stopping_at):.0f} s after the command (as sampled every {f['interval']:.0f} s)." if stopping_at else "No pod was in Terminating in this stretch.")
    fig, top = rcl._frame(f"“{change['text']}”: {max(term)} pods stopping at once, never fewer than {min(ready)} ready, and the client saw p95 of {change['p95_max']:.0f} ms against {f['baseline']:.0f} ms",
                          f"The pods every {f['interval']:.0f} s around the change (the line marks the command), and the client's one-minute windows over the same minutes ({change['errors']} request errors). "
                          f"{stopping}", foot)
    h = top - 0.12
    a1 = fig.add_axes([0.07, 0.12 + h * 0.42, 0.89, h * 0.56])
    a2 = fig.add_axes([0.07, 0.12, 0.89, h * 0.32], sharex=a1)
    xs = [w["t"] - t for w in seg]
    _step(a1, xs, pods, color=GREY, lw=1.6, label="pods that exist")
    _step(a1, xs, ready, color=BLUE, lw=2.6, label="ready")
    _step(a1, xs, term, color=ORANGE, lw=2.0, label="stopping (Terminating)")
    a1.set_ylabel("pods")
    a1.set_ylim(0, max(pods) * 1.25)
    a1.legend(loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=3, frameon=False, fontsize=9)
    ws = [r for r in rows if t + lo - window_s <= r["t"] <= t + hi]
    a2.plot([r["t"] + window_s / 2 - t for r in ws], [r["p95_ms"] for r in ws], color=BLUE, marker="o", lw=1.4, label="client p95 (one point per minute window)")
    a2.axhline(f["baseline"], color=GREY, ls=":", lw=1, label="baseline")
    a2.set_ylim(0, max(max(r["p95_ms"] for r in ws), f["baseline"]) * 1.6)
    a2.set_ylabel("client p95 (ms)")
    a2.set_xlabel("seconds from the command")
    a2.legend(loc="upper right", ncol=2, frameon=False, fontsize=9)
    for ax in (a1, a2):
        ax.axvline(0, color="#374151", ls="--", lw=1)
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_xlim(lo, hi)
    a1.tick_params(labelbottom=False)
    fig.savefig(out, dpi=rcl.DPI)
    plt.close(fig)
    return True


# ---------------------------------------------------------------- the ceiling
def ceiling_findings(levels: list[dict], joined: list[dict], cpu_limit: float) -> dict:
    peak = max(levels, key=lambda r: r["rps"])
    plateau = next(r for r in levels if r["rps"] >= 0.95 * peak["rps"])
    best = ce.best_sustained(levels)
    at_peak = next(j for j in joined if j["level"] == plateau["level"])
    low_ready = [j for j in joined if j["min_ready"] is not None and j["min_ready"] < max(x["min_ready"] for x in joined if x["min_ready"] is not None)]
    return {"peak": peak, "plateau": plateau, "best": best, "errors": sum(r["errors"] for r in levels), "limited": sum(r["rate_limited"] for r in levels),
            "cpu_at_plateau": at_peak["cpu_median"], "cpu_limit": cpu_limit, "utilisation": (at_peak["cpu_median"] or 0) / cpu_limit, "throttled_max": max((j["throttled_max"] or 0) for j in joined),
            "first_low_ready": low_ready[0] if low_ready else None, "last": levels[-1], "restarts": sum(j["restarts"] or 0 for j in joined), "oom": sum(j["oom"] or 0 for j in joined)}


def fig_ceiling(levels: list[dict], joined: list[dict], f: dict, note: str, out: Path, foot: str) -> None:
    n = len(levels)
    xs = list(range(n))
    nothing = "nothing failed" if f["errors"] == 0 and f["restarts"] == 0 else f"{f['errors']} request errors"
    fig, top = rcl._frame(f"Throughput levels off at about {round(f['peak']['rps'], -2):,.0f} requests/s from {f['plateau']['level']:,} in flight while latency keeps climbing: the pods use about {f['cpu_at_plateau']:.0f} of "
                          f"{f['cpu_limit']:.0f} cores; {nothing}",
                          f"Closed-loop load from three machines, each step held 30 s. Best sustained (p95 within 1 s, no errors): {f['best']['rps']:,.0f} requests/s at {f['best']['level']:,} in flight. Requests in flight are the total across the machines. "
                          f"Pods’ clock: {note}.", foot)
    h = top - 0.12
    a1 = fig.add_axes([0.07, 0.12 + h * 0.46, 0.84, h * 0.52])
    a2 = fig.add_axes([0.07, 0.12, 0.84, h * 0.34], sharex=a1)
    a1.plot(xs, [r["rps"] for r in levels], color=BLUE, lw=2.6, marker="o", ms=8)
    for x, r in zip(xs, levels):
        a1.annotate(f"{r['rps']:,.0f}", (x, r["rps"]), textcoords="offset points", xytext=(0, 10), ha="center", fontsize=10, color=BLUE)
    a1.set_ylabel("requests per second", color=BLUE)
    a1.set_ylim(0, max(r["rps"] for r in levels) * 1.3)
    bx = f["best"]["level"]
    a1.axvline(levels.index(f["best"]), color=GREEN, ls="--", lw=1.2)
    a1.text(levels.index(f["best"]), a1.get_ylim()[1] * 0.97, " best sustained", color=GREEN, fontsize=10, va="top")
    a1b = a1.twinx()
    a1b.plot(xs, [r["p95_ms"] for r in levels], color=ORANGE, lw=2, marker="s", ms=6, label="p95")
    a1b.plot(xs, [r["p50_ms"] for r in levels], color=PINK, lw=1.6, marker="^", ms=5, label="p50")
    a1b.set_ylabel("latency (ms): worst machine", color=ORANGE)
    a1b.legend(loc="upper left", frameon=False, fontsize=9)
    a1b.set_ylim(0, max(r["p95_ms"] for r in levels) * 1.3)
    a2.bar(xs, [j["cpu_median"] for j in joined], width=0.5, color=SKY, label="pods’ CPU, median (cores)")
    a2.plot(xs, [j["cpu_max"] for j in joined], color=BLUE, marker="_", ms=14, lw=0, label="highest sample")
    a2.axhline(f["cpu_limit"], color=RED, ls="--", lw=1.4)
    a2.text(-0.45, f["cpu_limit"] * 1.08, f"CPU limit of the pods ({f['cpu_limit']:.0f} cores)", color=RED, fontsize=9, va="bottom", ha="left")
    for x, j in zip(xs, joined):
        extra = f"throttled {j['throttled_max']:.0%}" + (f"\n{j['min_ready']} ready" if j["min_ready"] is not None and j["min_ready"] < 20 else "")
        a2.text(x, 0.4, extra, ha="center", va="bottom", fontsize=8.5, color="#1f2937" if "ready" not in extra else RED)
    a2.set_ylabel("cores")
    a2.set_ylim(0, f["cpu_limit"] * 1.45)
    a2.set_xticks(xs)
    a2.set_xticklabels([f"{r['level']:,}" for r in levels])
    a2.set_xlabel("requests in flight, in total")
    a2.legend(loc="lower right", frameon=False, fontsize=9, ncol=2, bbox_to_anchor=(1.0, 1.0))
    for ax in (a1, a2):
        ax.spines[["top"]].set_visible(False)
    a1.tick_params(labelbottom=False)
    fig.savefig(out, dpi=rcl.DPI)
    plt.close(fig)


# ---------------------------------------------------------------- the rate-limit probe, per address
def limit_findings(runs: list[tuple[str, dict]], expect_per_minute: float | None = None) -> dict:
    """What each address got, what they got together, and whether the machines look like they were drawing on a shared allowance: the per-second counts of two machines running at the
    same time are negatively correlated (what one gains the other loses) while their total sits at a whole number of configured allowances."""
    ok_runs = [(n, r) for n, r in runs if r.get("sustained_per_second") is not None and r.get("ok", 0) > 0]
    sustained = [r["sustained_per_second"] for _, r in ok_runs]
    bursts = [r["burst"] for _, r in ok_runs if r.get("burst") is not None]
    expected = expect_per_minute / 60 if expect_per_minute else None
    series = [[p["ok"] for p in r["per_second"][:-1]] for _, r in ok_runs]
    n = min((len(s) for s in series), default=0)
    totals = [sum(s[i] for s in series) for i in range(n)]
    settle = min(10, max(1, n // 3))
    total_sustained = statistics.mean(totals[settle:]) if totals[settle:] else None
    corr = statistics.correlation(series[0][settle:n], series[1][settle:n]) if len(series) >= 2 and n - settle > 3 else None
    each_off = expected is not None and any(abs(s - expected) > 0.25 * expected for s in sustained)
    shared = bool(expected and len(series) >= 2 and corr is not None and corr < -0.7 and each_off and abs(total_sustained - len(series) * expected) <= 0.1 * len(series) * expected)
    return {"addresses": len(ok_runs), "names": [n_ for n_, _ in ok_runs], "sustained_each": sustained, "sustained_total": total_sustained, "burst_each": bursts, "burst_total": sum(bursts),
            "mean_sustained": statistics.mean(sustained) if sustained else None, "expected_per_second": expected, "correlation": corr, "shared": shared, "totals": totals,
            "first_second_total": totals[0] if totals else None}


def fig_limit(runs: list[tuple[str, dict]], f: dict, out: Path, foot: str) -> None:
    n = f["addresses"]
    expected = f["expected_per_second"]
    ok_runs = [(name, r) for name, r in runs if name in f["names"]]
    each = " and ".join(f"{name} {r['sustained_per_second']:.0f}" for name, r in ok_runs)
    if f["shared"]:
        title = (f"{n} machines, each on its own address, got {f['sustained_total']:.0f} requests/s together, exactly {n} configured allowances, but split {each} a second: "
                 "the limit does not tell them apart")
        sub = (f"Requests let through per second (answered 200 or 404) by the machines running flat out at the same time. Stacked, they sum to a steady {f['sustained_total']:.0f}/s (the dashed line is {n} x the configured "
               f"{expected:.0f}/s), yet what one gained the other lost (correlation {f['correlation']:.2f}): the limiter is counting them against the same allowance, not one each.")
    else:
        title = f"Each address got about {f['mean_sustained']:.0f} requests/s through the limit after a burst of about {statistics.mean(f['burst_each']):.0f}; {n} addresses together {f['sustained_total']:.0f}/s"
        sub = "Requests let through per second (answered 200 or 404) by each machine running flat out at the same time, each on its own address." + (f" The dashed line is {n} x the configured rate ({expected:.0f} a second)." if expected else "")
    fig, top = rcl._frame(title, sub, foot)
    ax = fig.add_axes([0.07, 0.12, 0.89, top - 0.12 - 0.04])
    secs = list(range(len(ok_runs[0][1]["per_second"]) - 1))
    ax.stackplot(secs, *[[p["ok"] for p in r["per_second"][:-1]] for _, r in ok_runs], colors=[rcl.COLORS[k % 5] for k in range(n)], alpha=0.85,
                 labels=[f"{name}: burst {r['burst']}, then {r['sustained_per_second']:.0f}/s" for name, r in ok_runs])
    if expected:
        ax.axhline(expected * n, color="#111827", ls="--", lw=1.4)
        ax.text(len(secs) - 0.5, expected * n, f" {n} x configured ({expected * n:.0f}/s)", ha="right", va="bottom", fontsize=10)
    ax.set_xlabel("seconds since the start")
    ax.set_ylabel("let through per second (stacked)")
    ax.set_ylim(0, max(expected * n * 1.6 if expected else 0, statistics.median(f["totals"][10:]) * 1.8 if len(f["totals"]) > 10 else 0) or None)
    ax.set_xlim(0, len(secs) - 1)
    ax.legend(loc="upper right", frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(out, dpi=rcl.DPI)
    plt.close(fig)


def fig_limit_before_after(before: list[tuple[str, dict]], after: list[tuple[str, dict]], expect_per_minute: float, out: Path, foot: str) -> None:
    fb, fa = limit_findings(before, expect_per_minute), limit_findings(after, expect_per_minute)
    expected = expect_per_minute / 60
    each_after = ", ".join(f"{name} {r['sustained_per_second']:.0f}" for name, r in after if name in fa["names"])
    fig, top = rcl._frame(f"Before the ingress fix {fb['addresses']} machines shared the limit ({fb['sustained_total']:.0f}/s together, split unevenly); after it each of {fa['addresses']} got its own {fa['mean_sustained']:.0f}/s "
                          f"({fa['sustained_total']:.0f}/s together)",
                          f"Requests let through per second by machines running flat out at the same time, each on its own address, against a limit of {expected:.0f} a second per address. Before: {fb['correlation']:.2f} correlation between "
                          f"the two machines (what one gained the other lost). After ({each_after} a second): no trade-off.", foot)
    axes = fig.subplots(1, 2, sharey=True, gridspec_kw={"left": 0.07, "right": 0.97, "bottom": 0.12, "top": top - 0.02, "wspace": 0.06})
    for ax, runs, f, title in ((axes[0], before, fb, "before: callers' addresses hidden by the ingress"), (axes[1], after, fa, "after: externalTrafficPolicy Local")):
        ok_runs = [(name, r) for name, r in runs if name in f["names"]]
        secs = list(range(len(ok_runs[0][1]["per_second"]) - 1))
        ax.stackplot(secs, *[[p["ok"] for p in r["per_second"][:-1]] for _, r in ok_runs], colors=[rcl.COLORS[k % 5] for k in range(len(ok_runs))], alpha=0.85,
                     labels=[f"{name}: {r['sustained_per_second']:.0f}/s" for name, r in ok_runs])
        ax.axhline(expected * len(ok_runs), color="#111827", ls="--", lw=1.2)
        ax.set_title(title, fontsize=12)
        ax.set_xlabel("seconds since the start")
        ax.set_xlim(0, len(secs) - 1)
        ax.legend(loc="upper right", frameon=False, fontsize=9)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("let through per second (stacked)")
    axes[0].set_ylim(0, expected * max(fb["addresses"], fa["addresses"]) * 1.7)
    fig.savefig(out, dpi=rcl.DPI)
    plt.close(fig)


def read_limit_run(d: Path) -> dict:
    return json.loads((d / "per_second.json").read_text())


# ---------------------------------------------------------------- the command
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rollout")
    r.add_argument("dirs", nargs="+", type=Path)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--zoom", help="also draw this change at sampling resolution (a word from its mark, for example 'restart all pods')")
    c = sub.add_parser("ceiling")
    c.add_argument("--run", type=Path, required=True)
    c.add_argument("--watch", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--cpu-limit", type=float, default=20.0, help="the pods' CPU limit in cores (20 pods of 1000m)")
    c.add_argument("--label", default="")
    li = sub.add_parser("limit")
    li.add_argument("dirs", nargs="+", type=Path, help="limit_probe.py output directories, one per address")
    li.add_argument("--out", type=Path, required=True)
    li.add_argument("--expect-per-minute", type=float, default=6000.0)
    li.add_argument("--before", nargs="+", type=Path, help="the same probe from before a fix: also draws the before-and-after picture, with these directories as the before")
    a = ap.parse_args(argv)
    if plt is None:
        print("matplotlib is not installed: use perf_tests/.venv (perf_tests/requirements-report.txt)", file=sys.stderr)
        return 2
    a.out.mkdir(parents=True, exist_ok=True)
    try:
        if a.cmd == "rollout":
            for d in a.dirs:
                run = load_rollout(d)
                f = rollout_findings(run)
                name = d.name
                foot = f"{name}: soak.py windows and pod_watch.py samples ({run['meta']['label']}, {run['meta']['started_utc']}); marks made by the operator. Data: {d}"
                fig_rollout(run, f, a.out / f"r1-{name}.png", foot)
                print(f"wrote {a.out / ('r1-' + name + '.png')}: {f['n_changes']} changes, {f['errors']} errors, worst p95 {f['worst_p95']:.0f} ms against {f['baseline']:.0f} ms, up to {f['max_terminating']} pods stopping at once")
                if a.zoom and fig_rollout_zoom(run, f, a.zoom, a.out / f"r2-{name}-zoom.png", foot):
                    print(f"wrote {a.out / ('r2-' + name + '-zoom.png')}")
        elif a.cmd == "ceiling":
            levels = ce.read_levels(a.run)
            watch = sa.read_watch(a.watch)
            joined, note = ce.join_watch(levels, watch)
            f = ceiling_findings(levels, joined, a.cpu_limit)
            meta = a.run / "meta.json"
            foot = f"Ceiling test {a.label}: perf_tests/ceiling.py from three machines, pods watched by pod_watch.py. Data: {a.run}"
            fig_ceiling(levels, joined, f, note, a.out / "k1-ceiling.png", foot)
            print(f"wrote {a.out / 'k1-ceiling.png'}: peak {f['peak']['rps']:.0f}/s, best sustained {f['best']['rps']:.0f}/s at {f['best']['level']}, pods' CPU at the plateau {f['cpu_at_plateau']} of {f['cpu_limit']:.0f}")
        else:
            runs = [(d.name.replace("limit-", ""), read_limit_run(d)) for d in a.dirs]
            print("addresses with usable results:", [n for n, r in runs if r.get("ok", 0) > 0], " without:", [n for n, r in runs if not r.get("ok", 0)])
            f = limit_findings(runs, a.expect_per_minute)
            fig_limit(runs, f, a.out / "l1-limit-per-address.png", "Rate-limit probe: perf_tests/limit_probe.py, one run per address at the same time. Data: " + ", ".join(str(d) for d in a.dirs))
            print(f"wrote {a.out / 'l1-limit-per-address.png'}: sustained {f['sustained_each']}, total {f['sustained_total']:.0f}/s")
            if a.before:
                before = [(d.name.replace("limit-", ""), read_limit_run(d)) for d in a.before]
                fig_limit_before_after(before, runs, a.expect_per_minute, a.out / "l2-limit-before-after.png",
                                       "Rate-limit probe: perf_tests/limit_probe.py, before (14 October) and after (15 October) the ingress fix. Data: docs/results/2026-10-14-limit, docs/results/2026-10-15-limit-after")
                print(f"wrote {a.out / 'l2-limit-before-after.png'}")
    except (OSError, KeyError, ValueError, StopIteration) as e:
        print(f"cannot read the results: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
