#!/usr/bin/env python3
"""Draw the V3-versus-V4 results report (docs/plans/v4-results-report.md, section 4) from a matrix directory written by run_matrix.py.

    perf_tests/.venv/bin/python perf_tests/report.py --matrix perf_tests/results/matrix-DATE-HOST --out docs/results/DATE [--format png|jpg] [--draft]

Needs matplotlib (perf_tests/requirements-report.txt, installed in the gitignored perf_tests/.venv); everything numeric comes from report_data.py, which is unit-tested.
Every picture states its finding in the title (computed from the data, never typed in), the conditions under it, and its provenance at the foot. A figure whose
inputs are not in the matrix directory is skipped and listed in index.md as skipped, with what it needed. --draft stamps every picture DRAFT.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import report_data as rd  # noqa: E402

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
except ImportError:  # the pure helpers below stay importable without matplotlib
    matplotlib = None
    plt = None

# Okabe-Ito colour-blind-safe palette; the same image has the same colour in every picture.
COLORS = {"v3": "#E69F00", "lean": "#0072B2", "small": "#56B4E9"}
LABELS = {"v3": "V3 (production image)", "lean": "V4 lean", "small": "V4 small"}
ROUTE_NAMES = {
    "health": "health", "sic_lookup": "SIC lookup", "edgar_ciks": "EDGAR search", "edgar_detail": "EDGAR detail",
    "edgar_firmographics_by_cik": "EDGAR by CIK", "wikipedia_firmographics": "Wikipedia", "merged_firmographics": "Merged",
}
VERDICT_COLORS = {"IDENTICAL": "#009E73", "SAME SHAPE": "#F0E442", "DIFFERENT": "#D55E00"}
GREY = "#6b7280"
W, H, DPI = 13.33, 7.5, 120  # 16:9, 1600 x 900


# ------------------------------------------------------------------ titles computed from the data (pure, tested)
def latency_title(counts: dict[str, int], phase: str, regime_label: str, runs: int = 3) -> str:
    base = _latency_title(counts, phase, regime_label)
    return base if runs >= 3 else f"{base} [indicative: {runs} run{'s' if runs != 1 else ''}, not 3]"


def _latency_title(counts: dict[str, int], phase: str, regime_label: str) -> str:
    n = sum(counts.values())
    better, same, worse = counts.get("improved", 0), counts.get("no difference", 0), counts.get("regression", 0)
    if n == 0:
        return f"{phase.capitalize()} latency: no comparable routes"
    if worse:
        return f"{phase.capitalize()} latency: V4 is slower than V3 on {worse} of {n} routes ({regime_label})"
    if better == n:
        return f"{phase.capitalize()} latency: V4 is faster than V3 on all {n} routes ({regime_label})"
    return f"{phase.capitalize()} latency: V4 is faster on {better} of {n} routes and level on {same}, slower on none ({regime_label})"


# Routes that make no upstream call: V4's advantage there is its code. The others call Wikipedia and SEC, where V4's result cache answers a repeat
# and V3 has none, so averaging the two groups together would credit the cache to the code.
LOCAL_ROUTES = ("health", "sic_lookup", "edgar_ciks")


def _times(ratio: float) -> str:
    if ratio >= 1.1:
        return f"{ratio:.1f}x faster" if ratio < 100 else f"{ratio:.0f}x faster"
    if ratio <= 1 / 1.1:
        return f"{1 / ratio:.1f}x slower"
    return "about the same speed"


def concurrency_title(local_ratio: float, upstream_ratio: float, n: int, regime_label: str) -> str:
    """Wall-time ratios V3 / V4 at the highest common concurrency level: for routes with no upstream call, and for routes that call Wikipedia and SEC."""
    parts = []
    if local_ratio == local_ratio:
        parts.append(f"{_times(local_ratio)} on routes with no upstream call")
    if upstream_ratio == upstream_ratio:
        parts.append(f"{_times(upstream_ratio)} on routes that call Wikipedia and SEC, where V4 answers repeats from its cache")
    if not parts:
        return f"Concurrency: no comparable data ({regime_label})"
    return f"At {n} concurrent requests V4 finishes batches " + " and ".join(parts) + f" ({regime_label})"


def throughput_title(local_ratio: float, upstream_ratio: float, cpu_ratio: float, n: int, regime_label: str) -> str:
    """Ratios V4 / V3 of requests per second (local routes; routes that call Wikipedia and SEC) and V3 / V4 of mean CPU drawn."""
    def more(r):
        if r >= 1.1:
            return f"{r:.1f}x more" if r < 100 else f"{r:.0f}x more"
        return f"{1 / r:.1f}x fewer" if r <= 1 / 1.1 else "about the same number of"
    parts = []
    if local_ratio == local_ratio:
        parts.append(f"{more(local_ratio)} requests per second on routes with no upstream call")
    if upstream_ratio == upstream_ratio:
        parts.append(f"{more(upstream_ratio)} on routes that call Wikipedia and SEC (V4 answers repeats from its cache)")
    if not parts:
        return f"Throughput and CPU at {n} concurrent requests ({regime_label})"
    s = f"At {n} concurrent requests V4 serves " + " and ".join(parts)
    if cpu_ratio == cpu_ratio:
        s += ", using " + (f"{cpu_ratio:.1f}x less" if cpu_ratio >= 1.1 else f"{1 / cpu_ratio:.1f}x more" if cpu_ratio <= 1 / 1.1 else "about the same") + " average CPU"
    return s + f" ({regime_label})"


def footprint_title(v3: dict, v4: dict) -> str:
    """One sentence from V3's and V4's size, start time and peak memory: what is better, and what is worse."""
    better, worse = [], []
    if v3.get("size_bytes") and v4.get("size_bytes"):
        r = v3["size_bytes"] / v4["size_bytes"]
        (better if r > 1.1 else worse if r < 1 / 1.1 else []).append(f"its image is {max(r, 1 / r):.1f}x {'smaller' if r > 1 else 'larger'}")
    if v3.get("healthy_s") and v4.get("healthy_s"):
        r = v3["healthy_s"] / v4["healthy_s"]
        (better if r > 1.1 else worse if r < 1 / 1.1 else []).append(f"it starts {max(r, 1 / r):.1f}x {'faster' if r > 1 else 'slower'}")
    if v3.get("peak_mem") and v4.get("peak_mem"):
        r = v3["peak_mem"] / v4["peak_mem"]
        (better if r > 1.1 else worse if r < 1 / 1.1 else []).append(
            f"its peak memory is {max(r, 1 / r):.1f}x {'lower' if r > 1 else 'higher'} ({v4['peak_mem']:.0f} against {v3['peak_mem']:.0f} MiB)")
    if not better and not worse:
        return "V4 lean and V3 have a similar footprint"
    s = "V4 lean: " + ", ".join(better) if better else "V4 lean"
    if worse:
        s += (", but " if better else ": ") + ", ".join(worse)
    return s


def compare_phrase(v3_ms: float, v4_ms: float) -> str:
    """'V4 is 3.2x faster than V3', 'level with V3' (within 10%) or 'N x slower', from two medians."""
    ratio = v3_ms / v4_ms if v4_ms else float("nan")
    if ratio != ratio:
        return "no comparison"
    if 1 / 1.1 <= ratio <= 1.1:
        return f"V4 is level with V3 ({fmt_ms(v4_ms)} against {fmt_ms(v3_ms)} ms)"
    return f"V4 is {ratio:.1f}x faster than V3" if ratio > 1 else f"V4 is {1 / ratio:.1f}x slower than V3"


def fmt_ms(v: float) -> str:
    return f"{v:.1f}" if v < 100 else f"{v:.0f}"


# ------------------------------------------------------------------ context
class Ctx:
    def __init__(self, matrix: dict, out: Path, ext: str, draft: bool, evidence: dict, differences: list[dict]):
        self.m, self.out, self.ext, self.draft = matrix, out, ext, draft
        self.evidence, self.differences = evidence, differences
        self.skipped: list[tuple[str, str]] = []
        self.made: list[tuple[str, str, str]] = []  # file, title, conditions
        self.regimes = [r for r in ("limited", "headroom") if any(k[0] == r for k in matrix["runs"])]

    def runs(self, regime: str, image: str) -> list[dict]:
        return self.m["runs"].get((regime, image), [])

    def images(self, regime: str) -> list[str]:
        return [i for i in ("v3", "lean", "small") if self.runs(regime, i)]

    def regime_label(self, regime: str) -> str:
        lim = (self.m.get("manifest") or {}).get("regimes", {}).get(regime)
        return {"limited": "production limits", "headroom": "headroom"}[regime] + (f": {lim[0]} CPU, {lim[1]}" if lim else "")

    def footer(self) -> str:
        man = self.m.get("manifest") or {}
        host = man.get("host", {})
        imgs = man.get("images", {})
        parts = [f"host {host.get('hostname', '?')} ({host.get('system', '?')}, {host.get('cpus', '?')} CPUs)",
                 f"commit {host.get('git_commit', '?')}{'+dirty' if host.get('git_dirty') else ''}"]
        parts += [f"{k}: {v.rsplit('/', 1)[-1]}" for k, v in imgs.items()]
        parts.append(f"run {str(man.get('started', '?'))[:16]}")
        return "  |  ".join(parts)

    def repeats(self, regime: str) -> int:
        return max((len(self.runs(regime, i)) for i in self.images(regime)), default=0)

    def skip(self, name: str, why: str) -> None:
        self.skipped.append((name, why))


def finish(ctx: Ctx, fig, name: str, title: str, conditions: str) -> None:
    import textwrap
    t_lines = textwrap.fill(title, 80).count("\n") + 1
    c_text = textwrap.fill(conditions, 170)
    fig.text(0.02, 0.985, textwrap.fill(title, 80), ha="left", va="top", fontsize=16.5, fontweight="bold", linespacing=1.15)
    y_sub = 0.985 - 0.052 * t_lines - 0.008
    fig.text(0.02, y_sub, c_text, ha="left", va="top", fontsize=10, color=GREY, linespacing=1.25)
    fig.text(0.02, 0.012, ctx.footer(), ha="left", va="bottom", fontsize=7.5, color=GREY)
    if ctx.draft:
        fig.text(0.5, 0.5, "DRAFT", ha="center", va="center", fontsize=110, color="#000000", alpha=0.06, rotation=25, fontweight="bold")
    path = ctx.out / f"{name}.{ctx.ext}"
    fig.savefig(path, dpi=DPI, format="jpeg" if ctx.ext == "jpg" else ctx.ext, pil_kwargs={"quality": 92} if ctx.ext == "jpg" else None)
    plt.close(fig)
    ctx.made.append((path.name, title, conditions))


def new_fig(rows=1, cols=1, **kw):
    fig, axes = plt.subplots(rows, cols, figsize=(W, H), **kw)
    fig.subplots_adjust(top=0.76, bottom=0.17, left=0.07, right=0.98, hspace=0.45, wspace=0.25)
    return fig, axes


def style_axis(ax):
    ax.grid(axis="y", color="#e5e7eb", linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def legend_for(fig, images, loc=(0.98, 0.985)):
    handles = [Patch(color=COLORS[i], label=LABELS[i]) for i in images]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 0.028), ncol=len(handles), frameon=False, fontsize=11)


# ------------------------------------------------------------------ P1 / P2: latency
def fig_latency_cold(ctx: Ctx, regime: str) -> None:
    name = f"p1-latency-cold-{regime}"
    images = ctx.images(regime)
    stats = {i: rd.phase_stats(ctx.runs(regime, i), "cold") for i in images}
    if "v3" not in images or len(images) < 2:
        return ctx.skip(name, f"needs V3 and at least one V4 image in the '{regime}' regime")
    routes = [r for r in ROUTE_NAMES if all(r in stats[i] for i in images)]
    verdicts = {i: rd.paired_verdicts(stats["v3"], stats[i]) for i in images if i != "v3"}
    counts = rd.verdict_counts(verdicts.get("lean", next(iter(verdicts.values()))))
    fig, ax = new_fig()
    width = 0.8 / len(images)
    for j, img in enumerate(images):
        xs = [k + (j - (len(images) - 1) / 2) * width for k in range(len(routes))]
        med = [rd.spread(stats[img][r]["median"])["median"] for r in routes]
        lo = [m - rd.spread(stats[img][r]["median"])["min"] for m, r in zip(med, routes)]
        hi = [rd.spread(stats[img][r]["median"])["max"] - m for m, r in zip(med, routes)]
        ax.bar(xs, med, width * 0.92, color=COLORS[img], yerr=[lo, hi], error_kw={"elinewidth": 1.2, "capsize": 3, "ecolor": "#111827"})
        p95 = [rd.spread(stats[img][r]["p95"])["median"] for r in routes]
        ax.scatter(xs, p95, marker="D", s=22, color="white", edgecolor="#111827", zorder=5)
        for x, m, q in zip(xs, med, p95):
            ax.text(x, max(m, q) * 1.25, fmt_ms(m), ha="center", va="bottom", fontsize=8)
    ax.set_yscale("log")
    ax.set_xticks(range(len(routes)), [ROUTE_NAMES[r] for r in routes], fontsize=10)
    ax.set_ylabel("median latency, ms (log scale)")
    ymax = max(max(rd.spread(stats[i][r]["median"])["max"], rd.spread(stats[i][r]["p95"])["median"]) for i in images for r in routes)
    ax.set_ylim(top=ymax * 3)
    style_axis(ax)
    legend_for(fig, images)
    n = ctx.repeats(regime)
    finish(ctx, fig, name, latency_title(counts, "cold", ctx.regime_label(regime), n),
           f"Each route restarted from nothing before its first request (empty caches); 10 companies per route. Bars are the median over {n} run{'s' if n != 1 else ''}, whiskers the lowest and "
           f"highest run, diamonds the p95; the number is the median in ms. Lower is better.")


def fig_latency_warm(ctx: Ctx, regime: str) -> None:
    name = f"p2-latency-warm-{regime}"
    if not ctx.runs(regime, "v3") or not ctx.runs(regime, "lean"):
        return ctx.skip(name, f"needs V3 and V4 lean in the '{regime}' regime")
    v3w = rd.phase_stats(ctx.runs(regime, "v3"), "warm")
    lc = rd.phase_stats(ctx.runs(regime, "lean"), "cold")
    lw = rd.phase_stats(ctx.runs(regime, "lean"), "warm")
    routes = [r for r in ROUTE_NAMES if r in v3w and r in lc and r in lw]
    series = [("V3 (no result cache)", v3w, COLORS["v3"]), ("V4 lean, cold", lc, COLORS["lean"]), ("V4 lean, repeat request (cache hit)", lw, "#1b5e20")]
    fig, ax = new_fig()
    width = 0.8 / len(series)
    for j, (label, st, col) in enumerate(series):
        xs = [k + (j - 1) * width for k in range(len(routes))]
        med = [rd.spread(st[r]["median"])["median"] for r in routes]
        ax.bar(xs, med, width * 0.92, color=col, label=label)
        for x, m in zip(xs, med):
            ax.text(x, m * 1.12, fmt_ms(m), ha="center", va="bottom", fontsize=7.5, rotation=90)
    ax.set_yscale("log")
    ax.set_xticks(range(len(routes)), [ROUTE_NAMES[r] for r in routes], fontsize=10)
    ax.set_ylabel("median latency, ms (log scale)")
    ax.set_ylim(top=max(rd.spread(st[r]["median"])["max"] for _, st, _ in series for r in routes) * 6)
    ax.legend(frameon=False, loc="upper left", fontsize=10)
    style_axis(ax)
    cache_routes = [r for r in ("wikipedia_firmographics", "merged_firmographics") if r in routes]
    if cache_routes:
        r = cache_routes[0]
        cold, warm = rd.spread(lc[r]["median"])["median"], rd.spread(lw[r]["median"])["median"]
        title = (f"With repeat traffic V4's caches answer {ROUTE_NAMES[r]} in {fmt_ms(warm)} ms against {fmt_ms(cold)} ms cold; V3, which has no result cache, "
                 f"takes {fmt_ms(rd.spread(v3w[r]['median'])['median'])} ms every time")
    else:
        title = "Repeat traffic: cold against warm latency"
    finish(ctx, fig, name, title,
           f"{ctx.regime_label(regime)}. The warm pass repeats the same 10 companies on the same running container. This chart measures the caches, not the code: "
           f"read it with the cold chart. Medians over {ctx.repeats(regime)} run{'s' if ctx.repeats(regime) != 1 else ''}.")


# ------------------------------------------------------------------ P3: concurrency
def fig_concurrency(ctx: Ctx, regime: str) -> None:
    name = f"p3-concurrency-{regime}"
    images = ctx.images(regime)
    tables = {i: rd.concurrency_table(ctx.runs(regime, i)) for i in images}
    if "v3" not in images or len(images) < 2 or not all(tables.values()):
        return ctx.skip(name, f"needs concurrency results for V3 and a V4 image in the '{regime}' regime")
    routes = [r for r in ROUTE_NAMES if all(any(k[0] == r for k in tables[i]) for i in images)]
    levels = sorted(set.intersection(*[{k[1] for k in tables[i]} for i in images]))  # only levels every image was measured at
    top = levels[-1]
    v4img = "lean" if "lean" in images else images[1]

    def ratios(subset):
        return [rd.spread(tables["v3"][(r, top)]["wall"])["median"] / rd.spread(tables[v4img][(r, top)]["wall"])["median"]
                for r in routes if r in subset and (r, top) in tables["v3"] and (r, top) in tables[v4img]]
    local_r = rd.geometric_mean(ratios(set(LOCAL_ROUTES)))
    upstream_r = rd.geometric_mean(ratios(set(routes) - set(LOCAL_ROUTES)))
    cols = min(4, len(routes))
    rows = -(-len(routes) // cols)
    fig, axes = new_fig(rows, cols, squeeze=False)
    for ax, r in zip(axes.flat, routes):
        for img in images:
            ys = [rd.spread(tables[img][(r, n)]["wall"])["median"] for n in levels if (r, n) in tables[img]]
            lo = [rd.spread(tables[img][(r, n)]["wall"])["min"] for n in levels if (r, n) in tables[img]]
            hi = [rd.spread(tables[img][(r, n)]["wall"])["max"] for n in levels if (r, n) in tables[img]]
            ax.plot(levels[:len(ys)], ys, marker="o", color=COLORS[img], linewidth=2)
            ax.fill_between(levels[:len(ys)], lo, hi, color=COLORS[img], alpha=0.15, linewidth=0)
        ax.set_yscale("log")
        ax.set_xscale("log", base=2)
        ax.set_xticks(levels, [str(n) for n in levels])
        ax.set_title(ROUTE_NAMES[r], fontsize=11, loc="left")
        style_axis(ax)
    for ax in axes.flat[len(routes):]:
        ax.axis("off")
    for row in axes:
        row[0].set_ylabel("batch wall time, ms (log)")
    for ax in axes.flat[:len(routes)]:
        ax.set_xlabel("concurrent requests")
    legend_for(fig, images)
    finish(ctx, fig, name, concurrency_title(local_r, upstream_r, top, ctx.regime_label(regime)),
           f"A batch is N requests sent at the same moment; its wall time is the slowest one. Lines are medians over {ctx.repeats(regime)} run{'s' if ctx.repeats(regime) != 1 else ''}, shaded bands the lowest and highest run. "
           f"Lower is better. Ratios in the title are geometric means of V3 wall time over V4's at the highest level every image was measured at. V4's caches are warm here (the batches follow the warm pass), "
           f"so on the upstream routes V4 answers from memory and V3 does the full work every time.")


# ------------------------------------------------------------------ P4: throughput and CPU
def fig_throughput(ctx: Ctx, regime: str) -> None:
    name = f"p4-throughput-cpu-{regime}"
    images = ctx.images(regime)
    tables = {i: rd.concurrency_table(ctx.runs(regime, i)) for i in images}
    if not images or not all(tables.values()):
        return ctx.skip(name, f"needs concurrency results in the '{regime}' regime")
    common = set.intersection(*[{n for _, n in tables[i]} for i in images])
    if not common:
        return ctx.skip(name, "the images share no concurrency level")
    top = max(common)  # the highest level every image was measured at
    routes = [r for r in ROUTE_NAMES if all((r, top) in tables[i] for i in images)]
    fig, (a1, a2) = new_fig(1, 2)
    width = 0.8 / len(images)
    v4img = "lean" if "lean" in images else next((i for i in images if i != "v3"), None)

    def cps_ratio(subset):  # V4 over V3, geometric mean over routes
        vals = [rd.spread(tables[v4img][(r, top)]["cps"])["median"] / rd.spread(tables["v3"][(r, top)]["cps"])["median"] for r in routes if r in subset]
        return rd.geometric_mean(vals)
    for j, img in enumerate(images):
        xs = [k + (j - (len(images) - 1) / 2) * width for k in range(len(routes))]
        a1.bar(xs, [rd.spread(tables[img][(r, top)]["cps"])["median"] for r in routes], width * 0.92, color=COLORS[img])
    a1.set_xticks(range(len(routes)), [ROUTE_NAMES[r] for r in routes], rotation=30, ha="right", fontsize=9)
    a1.set_yscale("log")
    a1.set_ylabel(f"requests per second at {top} concurrent (log)")
    a1.set_title("Throughput", loc="left", fontsize=12)
    style_axis(a1)
    lim = (ctx.m.get("manifest") or {}).get("regimes", {}).get(regime)
    mean_cpu = {}
    for j, img in enumerate(images):
        res = [rd.resource_summary(r["resources"]) for r in ctx.runs(regime, img) if r.get("resources")]
        if not res:
            continue
        mean = sum(x["mean_cpu"] for x in res) / len(res)
        mean_cpu[img] = mean
        peak = max(x["peak_cpu"] for x in res)
        a2.bar(j - 0.18, mean, 0.34, color=COLORS[img])
        a2.bar(j + 0.18, peak, 0.34, color=COLORS[img], alpha=0.5)
        a2.text(j - 0.18, mean, f"{mean:.0f}", ha="center", va="bottom", fontsize=9)
        a2.text(j + 0.18, peak, f"{peak:.0f}", ha="center", va="bottom", fontsize=9)
    if lim:
        a2.axhline(float(lim[0]) * 100, color="#111827", linestyle="--", linewidth=1)
        a2.text(-0.45, float(lim[0]) * 100 * 1.03, f"CPU limit {lim[0]} core", ha="left", va="bottom", fontsize=9)
        a2.set_ylim(top=max(float(lim[0]) * 100, max((x for x in [rd.resource_summary(r["resources"]).get("peak_cpu", 0) for i in images for r in ctx.runs(regime, i) if r.get("resources")]), default=0)) * 1.2)
    a2.set_xticks(range(len(images)), [LABELS[i] for i in images], fontsize=9)
    a2.set_ylabel("CPU, % of one core (docker stats)")
    a2.set_title("CPU over the whole run: mean (solid) and peak (pale)", loc="left", fontsize=12)
    style_axis(a2)
    if v4img and "v3" in images:
        cpu_r = mean_cpu["v3"] / mean_cpu[v4img] if mean_cpu.get("v3") and mean_cpu.get(v4img) else float("nan")
        title = throughput_title(cps_ratio(set(LOCAL_ROUTES)), cps_ratio(set(routes) - set(LOCAL_ROUTES)), cpu_r, top, ctx.regime_label(regime))
    else:
        title = f"Throughput at {top} concurrent requests and the CPU each image used ({ctx.regime_label(regime)})"
    finish(ctx, fig, name, title,
           f"Higher throughput is better; CPU is what the container drew, with the limit marked. Medians over {ctx.repeats(regime)} run{'s' if ctx.repeats(regime) != 1 else ''}.")


# ------------------------------------------------------------------ P5: footprint
def fig_footprint(ctx: Ctx) -> None:
    name = "p5-footprint"
    facts = (ctx.m.get("manifest") or {}).get("image_facts") or {}
    regime = next((r for r in ctx.regimes if ctx.images(r)), None)
    if not facts or regime is None:
        return ctx.skip(name, "needs image_facts in manifest.json (recorded by run_matrix.py)")
    images = [i for i in ("v3", "lean", "small") if facts.get(i, {}).get("present")]
    fig, axes = new_fig(1, 4)
    mb = 1e6
    ax = axes[0]
    ax.bar(range(len(images)), [facts[i]["size_bytes"] / mb for i in images], color=[COLORS[i] for i in images])
    ax.set_title("Image size, MB", loc="left", fontsize=11)
    ax = axes[1]
    for k, i in enumerate(images):
        if "binary_bytes" in facts[i]:
            ax.bar(k, facts[i]["binary_bytes"] / mb, color=COLORS[i])
            ax.bar(k, facts[i].get("onnx_library_bytes", 0) / mb, bottom=facts[i]["binary_bytes"] / mb, color=COLORS[i], alpha=0.45)
    ax.set_title("Server binary (solid)\n+ ONNX library (pale), MB", loc="left", fontsize=11)
    if "binary_bytes" not in facts.get("v3", {}):
        ax.text(0, 6, "V3 is Python:\nno binary", ha="center", va="bottom", fontsize=9, color=GREY)
    ax = axes[2]
    for k, i in enumerate(images):
        t = [r["container"]["time_to_healthy_s"] for r in ctx.runs(regime, i) if r.get("container")]
        if t:
            ax.bar(k, sorted(t)[len(t) // 2], color=COLORS[i])
    ax.set_title("Time to healthy, s", loc="left", fontsize=11)
    ax = axes[3]
    for k, i in enumerate(images):
        res = [rd.resource_summary(r["resources"]) for r in ctx.runs(regime, i) if r.get("resources")]
        if res:
            idle = sorted(x["idle_mem_mib"] for x in res)[len(res) // 2]
            peak = max(x["peak_mem_mib"] for x in res)
            ax.bar(k - 0.18, idle, 0.34, color=COLORS[i])
            ax.bar(k + 0.18, peak, 0.34, color=COLORS[i], alpha=0.5)
    ax.set_title("Memory, MiB\nidle (solid), peak (pale)", loc="left", fontsize=11)
    for ax in axes:
        ax.set_xticks(range(len(images)), [LABELS[i].replace(" (production image)", "") for i in images], fontsize=9)
        style_axis(ax)
    sizes = {i: facts[i]["size_bytes"] / mb for i in images}
    sub = ", ".join(f"{LABELS[i].replace(' (production image)', '')} {sizes[i]:.0f} MB" for i in images)
    def fact(img):
        healthy = [r["container"]["time_to_healthy_s"] for r in ctx.runs(regime, img) if r.get("container")]
        res = [rd.resource_summary(r["resources"]) for r in ctx.runs(regime, img) if r.get("resources")]
        return {"size_bytes": facts.get(img, {}).get("size_bytes"), "healthy_s": sorted(healthy)[len(healthy) // 2] if healthy else None,
                "peak_mem": max((x["peak_mem_mib"] for x in res), default=None)}
    title = footprint_title(fact("v3"), fact("lean")) if "v3" in images and "lean" in images else "What each image costs to carry and to start"
    finish(ctx, fig, name, title, f"Image sizes as Docker reports them ({sub}); memory and start time at the {ctx.regime_label(regime)}. Smaller is better.")


# ------------------------------------------------------------------ P6: reliability
def fig_reliability(ctx: Ctx) -> None:
    name = "p6-reliability"
    rows = []
    for regime in ctx.regimes:
        for img in ctx.images(regime):
            rows.append((regime, img, rd.status_totals(ctx.runs(regime, img))))
    if not rows:
        return ctx.skip(name, "needs raw runs")
    fig, ax = new_fig()
    labels = [f"{LABELS[i].replace(' (production image)', '')}\n{r}" for r, i, _ in rows]
    cols = [("ok", "#009E73", "answered 200"), ("not_found", "#F0E442", "404 (expected for unknown names)"), ("other_status", "#CC79A7", "other status"), ("incorrect", "#882255", "200 but wrong or incomplete (lacks the CIK asked for)"), ("error", "#D55E00", "no answer (timeout or connection error)")]
    left = [0.0] * len(rows)
    for key, col, text in cols:
        vals = [100.0 * t[key] / max(1, sum(t.values())) for _, _, t in rows]
        ax.barh(range(len(rows)), vals, left=left, color=col, label=text)
        for k, (v, t) in enumerate(zip(vals, [t for _, _, t in rows])):
            if t[key]:
                ax.text(left[k] + v / 2, k, str(t[key]), ha="center", va="center", fontsize=9)
        left = [a + b for a, b in zip(left, vals)]
    ax.set_yticks(range(len(rows)), labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("share of all measured calls, %")
    ax.legend(frameon=False, ncol=3, loc="lower center", bbox_to_anchor=(0.5, -0.24), fontsize=9)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    errs = {i: sum(t["error"] for r, im, t in rows if im == i) for i in {x[1] for x in rows}}
    wrong = {i: sum(t["incorrect"] for r, im, t in rows if im == i) for i in {x[1] for x in rows}}
    bad = [i for i in errs if errs[i] or wrong[i]]
    if not bad:
        title = "Every image answered every request, and every answer was complete"
    else:
        title = "Failed or incomplete answers: " + ", ".join(
            f"{LABELS[i]} {errs[i]} unanswered" + (f", {wrong[i]} incomplete" if wrong[i] else "") for i in bad)
    finish(ctx, fig, name, title, "All cold, warm and concurrent calls of all runs; counts inside the bars. 'No answer' is a timeout or connection error (the request timeout is in the manifest); "
           "'wrong or incomplete' is a 200 whose answer lacked the company's CIK under concurrent load.")


# ------------------------------------------------------------------ P7: why
def fig_why(ctx: Ctx) -> None:
    name = "p7-why"
    regime = "limited" if "limited" in ctx.regimes else (ctx.regimes[0] if ctx.regimes else None)
    if regime is None:
        return ctx.skip(name, "needs raw runs")
    ev = ctx.evidence
    v3w = rd.phase_stats(ctx.runs(regime, "v3"), "warm") if ctx.runs(regime, "v3") else {}
    lc = rd.phase_stats(ctx.runs(regime, "lean"), "cold") if ctx.runs(regime, "lean") else {}
    lw = rd.phase_stats(ctx.runs(regime, "lean"), "warm") if ctx.runs(regime, "lean") else {}
    fig, axes = new_fig(2, 2)
    fig.subplots_adjust(hspace=0.65, wspace=0.28)
    a = axes[0][0]
    vals_a = []
    if "wikipedia_firmographics" in lc and "wikipedia_firmographics" in lw and "wikipedia_firmographics" in v3w:
        r = "wikipedia_firmographics"
        vals_a = [rd.spread(v3w[r]["median"])["median"], rd.spread(lc[r]["median"])["median"], rd.spread(lw[r]["median"])["median"]]
        a.bar(range(3), vals_a, color=[COLORS["v3"], COLORS["lean"], "#1b5e20"])
        for k, v in enumerate(vals_a):
            a.text(k, v * 1.1, f"{fmt_ms(v)} ms", ha="center", fontsize=9)
        a.set_yscale("log")
        a.set_xticks(range(3), ["V3", "V4 cold", "V4 repeat"], fontsize=9)
        a.set_ylim(top=max(vals_a) * 4)
    if vals_a:
        a.set_title(f"A. Result cache  [MEASURED]\nWikipedia lookup, cold: {compare_phrase(vals_a[0], vals_a[1])}; a repeat is {vals_a[1] / vals_a[2]:.0f}x faster than cold (a cache hit)",
                    loc="left", fontsize=10.5)
    else:
        a.set_title("A. Result cache  [MEASURED]\nneeds V3 and V4 lean cold and warm Wikipedia data", loc="left", fontsize=10.5)
    style_axis(a)
    b = axes[0][1]
    g = ev.get("gzip_wikidata")
    if g:
        b.bar([0, 1], [g["plain_ms_median"], g["gzip_ms_median"]], color=["#9ca3af", COLORS["lean"]])
        for k, v in enumerate([g["plain_ms_median"], g["gzip_ms_median"]]):
            b.text(k, v * 1.03, f"{v} ms", ha="center", fontsize=9)
        b.set_xticks([0, 1], [f"plain\n{g['plain_bytes_median'] // 1000} KB", f"gzip\n{g['gzip_bytes_median'] // 1000} KB"], fontsize=9)
        b.set_ylim(0, g["plain_ms_median"] * 1.25)
        b.set_title(f"B. gzip on the Wikidata call  [{g['status'].upper()}]\n{g['date']}: the same request, plain against gzip", loc="left", fontsize=10.5)
    style_axis(b)
    c = axes[1][0]
    ctrl = [r for r in ("health", "sic_lookup", "edgar_ciks") if r in v3w and r in lc]
    if ctrl:
        for j, (img, st) in enumerate((("v3", v3w), ("lean", lc))):
            c.bar([k + (j - 0.5) * 0.38 for k in range(len(ctrl))], [rd.spread(st[r]["median"])["median"] for r in ctrl], 0.36, color=COLORS[img], label=LABELS[img])
        c.set_xticks(range(len(ctrl)), [ROUTE_NAMES[r] for r in ctrl], fontsize=9)
        c.legend(frameon=False, fontsize=9)
    if "health" in v3w and "health" in lc:
        c.set_title(f"C. Local work and framework  [OBSERVED]\nRoutes with no upstream call; on 'health', which does no work, "
                    f"{compare_phrase(rd.spread(v3w['health']['median'])['median'], rd.spread(lc['health']['median'])['median'])}", loc="left", fontsize=10.5)
    else:
        c.set_title("C. Local work and framework  [OBSERVED]\nneeds V3 and V4 lean data", loc="left", fontsize=10.5)
    style_axis(c)
    d = axes[1][1]
    t = ev.get("v3_old_image_timeouts")
    if t:
        d.bar([0, 1], [t["old_errors"], t["current_errors"]], color=["#D55E00", "#009E73"])
        for k, v in enumerate([t["old_errors"], t["current_errors"]]):
            d.text(k, v + 1, str(v), ha="center", fontsize=10)
        d.set_xticks([0, 1], [f"V3 {t['old_image']}\n(before the Wikipedia v2 backend)", f"V3 {t['current_image']}\n(production now)"], fontsize=9)
        d.set_ylabel(f"calls with no answer of {t['old_calls']}", fontsize=9)
        d.set_title(f"D. V3's own improvement  [{t['status'].upper()}]\nWhy the comparison uses the current V3 image", loc="left", fontsize=10.5)
    style_axis(d)
    finish(ctx, fig, name, "Where V4's gains come from, and which of them we measured",
           "MEASURED = isolated with a before-and-after on the same work; OBSERVED = seen in the matrix but not isolated (for example 'health' shows the framework overhead, not its share of every gain).")


# ------------------------------------------------------------------ function figures
def family(name: str) -> str:
    return {"eu": "EU NACE", "intl": "ISIC", "japan": "Japan SIC", "us": "US SIC", "v2": "V2.0 alias", "edgar": "EDGAR", "wikipedia": "Wikipedia", "merged": "Merged"}.get(name.split("_")[0], "other")


def fig_parity(ctx: Ctx) -> None:
    name = "f2-parity"
    rows = next(iter(ctx.m.get("parity", {}).values()), None)
    if not rows:
        return ctx.skip(name, "needs parity/<image>.json from parity_report.py --json")
    fams: dict[str, dict[str, int]] = {}
    for r in rows:
        fams.setdefault(family(r["name"]), {}).setdefault(r["verdict"], 0)
        fams[family(r["name"])][r["verdict"]] += 1
    order = ["US SIC", "EU NACE", "ISIC", "Japan SIC", "V2.0 alias", "EDGAR", "Wikipedia", "Merged"]
    names = [f for f in order if f in fams]
    fig, ax = new_fig()
    left = [0] * len(names)
    for verdict in ("IDENTICAL", "SAME SHAPE", "DIFFERENT"):
        vals = [fams[f].get(verdict, 0) for f in names]
        ax.barh(range(len(names)), vals, left=left, color=VERDICT_COLORS[verdict], label=verdict.lower().capitalize())
        for k, v in enumerate(vals):
            if v:
                ax.text(left[k] + v / 2, k, str(v), ha="center", va="center", fontsize=10)
        left = [a + b for a, b in zip(left, vals)]
    ax.set_yticks(range(len(names)), names, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlabel("requests compared with the live V3 service")
    ax.legend(frameon=False, ncol=3, loc="lower center", bbox_to_anchor=(0.5, -0.2))
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    summary = rd.parity_summary(rows)
    c = summary["counts"]
    finish(ctx, fig, name, f"{c.get('IDENTICAL', 0)} of {summary['total']} requests return exactly what V3 returns; the other {summary['total'] - c.get('IDENTICAL', 0)} differ for recorded reasons",
           "Identical = equal once V4's own dependencies and timing fields are set aside. Same shape = same fields and types, data differs (live upstream values, corrected Japan data). "
           "Different = structure differs (see the differences ledger).")


def fig_differences(ctx: Ctx) -> None:
    name = "f3-differences"
    if not ctx.differences:
        return ctx.skip(name, "needs docs/results/differences.json")
    import textwrap
    fig, ax = new_fig()
    ax.axis("off")
    cols = ["Area", "V3", "V4", "Why"]
    widths = [0.14, 0.26, 0.26, 0.34]
    y = 0.98
    x0 = [0.0]
    for w in widths[:-1]:
        x0.append(x0[-1] + w)
    for x, c in zip(x0, cols):
        ax.text(x, y, c, fontsize=11, fontweight="bold", va="top", transform=ax.transAxes)
    y -= 0.05
    for d in ctx.differences:
        cells = [d["area"], d["v3"], d["v4"], d["reason"]]
        wrapped = [textwrap.fill(t, int(w * 140)) for t, w in zip(cells, widths)]
        height = max(t.count("\n") + 1 for t in wrapped) * 0.034
        for x, t in zip(x0, wrapped):
            ax.text(x, y, t, fontsize=8.6, va="top", transform=ax.transAxes)
        ax.plot([0, 1], [y - height - 0.006] * 2, color="#e5e7eb", linewidth=0.8, transform=ax.transAxes)
        y -= height + 0.022
    finish(ctx, fig, name, f"All {len(ctx.differences)} intentional differences from V3, each with its reason",
           "Everything V4 answers differently on purpose. A difference that is not on this list is a defect.")


def fig_suite(ctx: Ctx) -> None:
    name = "f4-tests"
    rep = next(iter(ctx.m.get("suite", {}).values()), None)
    if not rep:
        return ctx.skip(name, "needs suite/<image>.json from api_tests/run.py --report")
    layers = rd.suite_by_layer(rep)
    order = sorted(layers)
    fig, ax = new_fig()
    cols = [("passed", "#009E73", "passed"), ("expected_failure", "#F0E442", "expected failure (a recorded difference)"), ("skipped", "#9ca3af", "skipped"),
            ("failed", "#D55E00", "failed"), ("error", "#8B0000", "error")]
    left = [0] * len(order)
    for key, col, text in cols:
        vals = [layers[l].get(key, 0) for l in order]
        if not any(vals):
            continue
        ax.barh(range(len(order)), vals, left=left, color=col, label=text)
        for k, v in enumerate(vals):
            if v:
                ax.text(left[k] + v / 2, k, str(v), ha="center", va="center", fontsize=10)
        left = [a + b for a, b in zip(left, vals)]
    ax.set_yticks(range(len(order)), order, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlabel("tests")
    ax.legend(frameon=False, ncol=3, loc="lower center", bbox_to_anchor=(0.5, -0.22), fontsize=9)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    tot = {k: sum(l.get(k, 0) for l in layers.values()) for k, _, _ in cols}
    bad = tot["failed"] + tot["error"]
    finish(ctx, fig, name, f"{tot['passed']} of {sum(tot.values())} tests pass, {bad} fail, and the one expected failure is a recorded difference" if bad == 0 else f"{bad} tests fail: see below",
           "The API test suite run against V4, by layer: smoke, contract (every route in the spec), data readiness, parity with V3, V4-only functions, limits and profiles.")


def fig_coverage(ctx: Ctx) -> None:
    name = "f1-route-coverage"
    v3, v4 = ctx.m["specs"].get("v3"), ctx.m["specs"].get("v4")
    if not v3 or not v4:
        return ctx.skip(name, "needs specs/v3-openapi.json and specs/v4-openapi.json (run_matrix.py --extras)")
    cov = rd.route_coverage(v3, v4)
    n = len(cov["served"]) + len(cov["excluded"]) + len(cov["missing"])
    fig, (a1, a2) = new_fig(1, 2, gridspec_kw={"width_ratios": [1, 1.6]})
    vals = [len(cov["served"]), len(cov["excluded"]), len(cov["missing"])]
    a1.bar(range(3), vals, color=["#009E73", GREY, "#D55E00"])
    for k, v in enumerate(vals):
        a1.text(k, v + 0.4, str(v), ha="center", fontsize=12)
    a1.set_xticks(range(3), ["served by V4", "left out\nby decision", "missing"], fontsize=10)
    a1.set_ylabel("V3 routes")
    style_axis(a1)
    a2.axis("off")
    lines = ["Left out by decision:"] + [f"  {p}\n     {why}" for p, why in cov["excluded"]] + ([""] + ["Missing, with no recorded decision:"] + [f"  {p}" for p in cov["missing"]] if cov["missing"] else [])
    a2.text(0, 1, "\n".join(lines), va="top", fontsize=9, family="monospace")
    finish(ctx, fig, name, f"V4 serves {len(cov['served'])} of V3's {n} routes; {len(cov['excluded'])} are left out by recorded decision and {len(cov['missing'])} are missing",
           f"Read from the two live OpenAPI documents; path parameter names are ignored. V4 also has {len(cov['v4_only'])} routes V3 does not.")


def fig_adds(ctx: Ctx) -> None:
    name = "f5-what-v4-adds"
    v3, v4 = ctx.m["specs"].get("v3"), ctx.m["specs"].get("v4")
    if not v3 or not v4:
        return ctx.skip(name, "needs specs/v3-openapi.json and specs/v4-openapi.json (run_matrix.py --extras)")
    cov = rd.route_coverage(v3, v4)
    only = cov["v4_only"]
    tags: dict[str, int] = {}
    for p in only:
        ops = v4["paths"][p]
        for m, op in ops.items():
            if isinstance(op, dict):
                t = (op.get("tags") or ["other"])[0]
                tags[t] = tags.get(t, 0) + 1
    names = sorted(tags, key=lambda t: -tags[t])
    fig, ax = new_fig()
    ax.barh(range(len(names)), [tags[t] for t in names], color=COLORS["lean"])
    for k, t in enumerate(names):
        ax.text(tags[t] + 0.2, k, str(tags[t]), va="center", fontsize=10)
    ax.set_yticks(range(len(names)), names, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlabel("operations")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    finish(ctx, fig, name, f"V4 adds {len(only)} routes V3 does not have", "Routes in V4's OpenAPI document with no counterpart in V3's, grouped by the API tag they are documented under (SQL is experimental and off by default).")


# ------------------------------------------------------------------ driver
def build(matrix_dir: Path, out: Path, ext: str = "png", draft: bool = False, evidence_path: Path | None = None, differences_path: Path | None = None) -> Ctx:
    if plt is None:
        raise SystemExit("matplotlib is not installed: use perf_tests/.venv (see perf_tests/requirements-report.txt)")
    m = rd.load_matrix(matrix_dir)
    root = HERE.parent / "docs" / "results"
    ev = json.loads((evidence_path or root / "evidence.json").read_text()) if (evidence_path or root / "evidence.json").exists() else {}
    diff = (json.loads((differences_path or root / "differences.json").read_text()).get("differences", [])
            if (differences_path or root / "differences.json").exists() else [])
    out.mkdir(parents=True, exist_ok=True)
    ctx = Ctx(m, out, ext, draft, ev, diff)
    plt.rcParams.update({"font.size": 10, "axes.titlesize": 12, "figure.facecolor": "white", "axes.facecolor": "white"})
    for regime in ctx.regimes:
        fig_latency_cold(ctx, regime)
        fig_latency_warm(ctx, regime)
        fig_concurrency(ctx, regime)
        fig_throughput(ctx, regime)
    fig_footprint(ctx)
    fig_reliability(ctx)
    fig_why(ctx)
    fig_coverage(ctx)
    fig_parity(ctx)
    fig_differences(ctx)
    fig_suite(ctx)
    fig_adds(ctx)
    write_index(ctx)
    return ctx


def write_index(ctx: Ctx) -> None:
    lines = ["# V3 versus V4: results figures", "", f"Generated by `perf_tests/report.py`{' (DRAFT)' if ctx.draft else ''}. Provenance: {ctx.footer()}", ""]
    for f, title, cond in ctx.made:
        lines += [f"## {title}", "", f"![{title}]({f})", "", cond, ""]
    if ctx.skipped:
        lines += ["## Not drawn", ""] + [f"- `{n}`: {why}" for n, why in ctx.skipped] + [""]
    (ctx.out / "index.md").write_text("\n".join(lines))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--matrix", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--format", choices=["png", "jpg"], default="png")
    p.add_argument("--draft", action="store_true")
    a = p.parse_args(argv)
    ctx = build(a.matrix, a.out, a.format, a.draft)
    for f, title, _ in ctx.made:
        print(f"{f}: {title}")
    for n, why in ctx.skipped:
        print(f"SKIPPED {n}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
