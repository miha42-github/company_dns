#!/usr/bin/env python3
"""Two analyses of soak results (standard library only).

    python3 perf_tests/soak_analyze.py merge DIR DIR ... --out merged/     # several testers' soak directories into one summary
    python3 perf_tests/soak_analyze.py events --soak DIR --events events.txt [--watch WATCHDIR] [--span 5]   # what the soak and the pods did around each thing you did

`merge` reads each directory's windows.csv and meta.json (written by soak.py), judges each site with the same bar as the soak's own summary, and writes the sites side by side
(summary.md, windows.csv with a `site` column). The run passes only if every site passed.

`events` takes the marks you made during a run (events.txt, one per line: `2026-10-12T21:05:00Z rolling update to <tag>`, UTC; make them with `echo "$(date -u +%FT%TZ) text" >> events.txt`),
and for each one shows the soak windows that overlap it (errors, `429`s, p95, the slowest request, the canaries) and, with pod_watch.py's directory, the pods around it
(ready, terminating, restarts). Each event is judged: PASS if no errors, every canary right, and p95 within 1.5 times the quiet baseline, else REVIEW with the reason.
"""
import argparse
import csv
import json
import statistics
import sys
import time
from calendar import timegm
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import soak  # noqa: E402

P95_FACTOR = 1.5


def parse_utc(text: str) -> float:
    return timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ"))


def read_windows(directory: Path) -> tuple[list[dict], dict]:
    meta = json.loads((directory / "meta.json").read_text())
    rows = []
    with open(directory / "windows.csv", newline="") as f:
        for r in csv.DictReader(f):
            def num(k):
                return float(r[k]) if r.get(k) not in (None, "") else None
            rows.append({"time_utc": r["time_utc"], "t": parse_utc(r["time_utc"]), "step": r["step"], "concurrency": int(r["concurrency"]), "requests": int(r["requests"]),
                         "ok": int(r["ok"]), "errors": int(r["errors"]), "rate_limited": int(r["rate_limited"]), "rps": num("rps"), "p50_ms": num("p50_ms"), "p95_ms": num("p95_ms"),
                         "p99_ms": num("p99_ms"), "max_ms": num("max_ms"), "error_rate": num("error_rate") or 0.0, "canaries_ok": int(r["canaries_ok"]),
                         "canaries_total": int(r["canaries_total"]), "health_ms": num("health_ms"), "window_ok": r["window_ok"] == "True", "note": r.get("note", "")})
    return rows, meta


# ---------------------------------------------------------------- merge
def merge(dirs: list[Path], out: Path) -> tuple[str, str]:
    sites = []
    for d in dirs:
        rows, meta = read_windows(d)
        verdict, _ = soak.summarise(rows, meta, True, meta.get("max_error_rate", 0.01), meta.get("max_p95_ms", 2000.0))
        sites.append((meta["label"], rows, meta, verdict))
    overall = "PASS" if sites and all(v == "PASS" for *_, v in sites) else "FAIL"
    total = sum(r["requests"] for _, rows, _, _ in sites for r in rows)
    errors = sum(r["errors"] for _, rows, _, _ in sites for r in rows)
    lines = [f"# Soak test, {len(sites)} sites: {overall}", "",
             f"{total:,} requests in all, {errors} errors. Each site is judged on its own (error rate, p95, canaries); the run passes only if every site passed.", "",
             "| site | verdict | started (UTC) | windows | requests | errors | 429s | p50 ms | p95 ms (median) | worst p95 ms | canaries correct | mix | requests/s (median) | platform |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for label, rows, meta, verdict in sites:
        p95 = [r["p95_ms"] for r in rows if r["p95_ms"] is not None]
        c_ok, c_total = sum(r["canaries_ok"] for r in rows), sum(r["canaries_total"] for r in rows)
        mix = meta["mix"] + (f" ({meta['embedding_share']:.0%} embedding)" if meta.get("embedding_share") is not None else "")
        lines.append(f"| {label} | {verdict} | {meta['started_utc']} | {len(rows)} | {sum(r['requests'] for r in rows):,} | {sum(r['errors'] for r in rows)} | "
                     f"{sum(r['rate_limited'] for r in rows)} | {statistics.median(r['p50_ms'] for r in rows if r['p50_ms'] is not None):.1f} | "
                     f"{statistics.median(p95):.1f} | {max(p95):.1f} | {c_ok:,} of {c_total:,} | {mix} | {statistics.median(r['rps'] for r in rows):.1f} | {meta['platform'].split('-with')[0]} |")
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "windows.csv", "w", newline="") as f:
        fields = ["site"] + soak.CSV_FIELDS
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for label, rows, _, _ in sites:
            for r in rows:
                w.writerow({"site": label, **r, "elapsed_s": ""})
    text = "\n".join(lines) + "\n"
    (out / "summary.md").write_text(text)
    return overall, text


# ---------------------------------------------------------------- events
def read_events(path: Path) -> tuple[list[tuple[float, str, str]], list[str]]:
    events, bad = [], []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        stamp, _, text = line.partition(" ")
        try:
            events.append((parse_utc(stamp), stamp, text.strip() or "(no text)"))
        except ValueError:
            bad.append(line)
    return sorted(events), bad


def read_watch(directory: Path | None) -> list[dict]:
    if not directory or not (directory / "watch.csv").exists():
        return []
    with open(directory / "watch.csv", newline="") as f:
        out = []
        for r in csv.DictReader(f):
            r["t"] = parse_utc(r["time_utc"])
            out.append(r)
        return out


def judge_events(rows: list[dict], window_s: float, events: list[tuple[float, str, str]], watch: list[dict], span_min: float) -> tuple[list[dict], float]:
    """Per event: the windows that overlap [event, event + span], the watch rows in it, and a verdict against the quiet baseline."""
    span = span_min * 60
    touched = set()
    spans = []
    for t, _, _ in events:
        spans.append([r for r in rows if r["t"] + window_s + 2 >= t and r["t"] <= t + span])
        touched.update(id(r) for r in spans[-1])
    quiet = [r["p95_ms"] for r in rows if id(r) not in touched and r["p95_ms"] is not None]
    baseline = statistics.median(quiet) if quiet else statistics.median(r["p95_ms"] for r in rows if r["p95_ms"] is not None)
    out = []
    for (t, stamp, text), ws in zip(events, spans):
        wt = [x for x in watch if t - 30 <= x["t"] <= t + span]
        errors = sum(r["errors"] for r in ws)
        canary_bad = sum(r["canaries_total"] - r["canaries_ok"] for r in ws)
        p95 = max((r["p95_ms"] for r in ws if r["p95_ms"] is not None), default=None)
        reasons = []
        if not ws:
            reasons.append("no soak window overlaps it")
        if errors:
            reasons.append(f"{errors} request errors")
        if canary_bad:
            reasons.append(f"{canary_bad} wrong or failed canary answers")
        if p95 is not None and p95 > baseline * P95_FACTOR:
            reasons.append(f"p95 reached {p95:.0f} ms (baseline {baseline:.0f} ms)")
        out.append({"time": stamp, "text": text, "windows": ws, "errors": errors, "canary_bad": canary_bad, "p95_max": p95, "verdict": "REVIEW" if reasons else "PASS",
                    "reasons": reasons, "watch": wt,
                    "min_ready": min((int(x["ready"]) for x in wt), default=None), "max_terminating": max((int(x["terminating"]) for x in wt), default=None),
                    "new_restarts": sum(int(x["new_restarts"]) for x in wt) if wt else None,
                    "max_mem": max((float(x["mem_mib_max"]) for x in wt if x["mem_mib_max"] not in ("", None)), default=None)})
    return out, baseline


def render_events(results: list[dict], baseline: float, bad: list[str], label: str, span_min: float) -> str:
    verdict = "PASS" if results and all(r["verdict"] == "PASS" for r in results) else "REVIEW"
    lines = [f"# Soak events: {verdict}", "", f"`{label}`: {len(results)} events, each judged over the next {span_min:g} minutes. The quiet baseline p95 is {baseline:.0f} ms; "
             f"an event passes with no errors, every canary right and p95 within {P95_FACTOR}x of it.", "",
             "| time (UTC) | what | verdict | windows | errors | wrong canaries | worst p95 ms | fewest ready | most terminating | restarts | peak memory MiB | |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['time']} | {r['text']} | **{r['verdict']}** | {len(r['windows'])} | {r['errors']} | {r['canary_bad']} | "
                     f"{'' if r['p95_max'] is None else round(r['p95_max'])} | {r['min_ready'] if r['min_ready'] is not None else 'no watch data'} | {r['max_terminating'] if r['max_terminating'] is not None else ''} | "
                     f"{r['new_restarts'] if r['new_restarts'] is not None else ''} | {r['max_mem'] if r['max_mem'] is not None else ''} | {'; '.join(r['reasons'])} |")
    for r in results:
        if r["verdict"] != "PASS" and r["windows"]:
            lines += ["", f"## {r['time']} {r['text']}: the windows", "", "| window start (UTC) | step | requests | errors | 429s | p95 ms | slowest ms | canaries |", "|---|---|---|---|---|---|---|---|"]
            for w in r["windows"]:
                lines.append(f"| {w['time_utc']} | {w['step']} | {w['requests']} | {w['errors']} | {w['rate_limited']} | {w['p95_ms']} | {w['max_ms']} | {w['canaries_ok']}/{w['canaries_total']} | {w['note']}".rstrip())
    if bad:
        lines += ["", "Lines in the events file that were not read (expected `YYYY-MM-DDTHH:MM:SSZ text`):"] + [f"- {b}" for b in bad]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge", help="combine several soak directories")
    m.add_argument("dirs", nargs="+", type=Path)
    m.add_argument("--out", type=Path, required=True)
    e = sub.add_parser("events", help="judge each marked event")
    e.add_argument("--soak", type=Path, required=True)
    e.add_argument("--events", type=Path, required=True)
    e.add_argument("--watch", type=Path, help="pod_watch.py's output directory")
    e.add_argument("--span", type=float, default=5.0, help="minutes after each event to look at")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "merge":
            overall, text = merge(a.dirs, a.out)
            print(text)
            return 0 if overall == "PASS" else 1
        rows, meta = read_windows(a.soak)
        events, bad = read_events(a.events)
        if not events:
            print("no events read from " + str(a.events), file=sys.stderr)
            return 2
        results, baseline = judge_events(rows, float(meta["window_s"]), events, read_watch(a.watch), a.span)
        text = render_events(results, baseline, bad, meta["label"], a.span)
        (a.soak / "events.md").write_text(text)
        print(text)
        return 0 if all(r["verdict"] == "PASS" for r in results) else 1
    except (OSError, KeyError, ValueError) as e:
        print(f"cannot read the results: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
