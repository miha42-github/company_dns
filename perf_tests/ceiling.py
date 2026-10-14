#!/usr/bin/env python3
"""Find where a deployment buckles: ramp the load in steps until errors or latency say it has had enough (standard library only).

    python3 perf_tests/ceiling.py run --machines 3 --label studio          # on each of the machines at once (see --start-at)
    python3 perf_tests/ceiling.py merge DIR DIR DIR --out merged/          # the machines' results as one
    python3 perf_tests/ceiling.py report --run merged/ --watch WATCHDIR    # with what the pods did (pod_watch.py)

`run` raises the number of requests in flight step by step (`--levels` are the TOTAL across all machines; with `--machines N` each machine sends 1/N of each level), holds each step for
--duration seconds after a warm-up, and writes one line per step as it goes: requests/s, p50/p95/p99, errors, and the load generator's own CPU. It stops at the first step where the
service is clearly over its limit (error rate above --max-error-rate, or p95 above --max-p95-ms) or throughput has fallen --drop below its best for two steps in a row.
It needs credentials with no rate limit (LOAD_AUTH="PROFILE:TOKEN" in the environment, never on the command line): a rate-limited caller would only measure the limiter.

Where it is safe to run: the staging service (the default URL; another needs --allow-other-url), at a time that has been agreed, with pod_watch.py running on the cluster side for both the
service's namespace and production's, and `--max-total-concurrency` (default 4096) as the ceiling on the ramp. The pods are CPU-limited, so staging cannot take more than its own limit from the nodes;
the shared parts are the ingress and the network.
"""
import argparse
import csv
import json
import os
import resource
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402

STAGING_URL = "https://company-dns-staging.mediumroast.io"
DEFAULT_LEVELS = [256, 512, 768, 1024, 1536, 2048, 3072]
LEVEL_FIELDS = ["level", "machine_concurrency", "start_utc", "end_utc", "requests", "ok", "errors", "rate_limited", "rps", "p50_ms", "p95_ms", "p99_ms", "max_ms", "error_rate", "generator_cores", "note"]
GOOD_P95_MS = 1000.0
GOOD_ERROR_RATE = 0.01


def utc(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def parse_utc(text: str) -> float:
    from calendar import timegm
    return timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ"))


# ---------------------------------------------------------------- judging a ramp (pure)
def best_sustained(levels: list[dict]) -> dict | None:
    """The step with the highest requests/s whose p95 is within a second and whose error rate is within 1%."""
    good = [r for r in levels if r["p95_ms"] is not None and r["p95_ms"] <= GOOD_P95_MS and r["error_rate"] <= GOOD_ERROR_RATE and r["rate_limited"] == 0]
    return max(good, key=lambda r: r["rps"]) if good else None


def buckled(levels: list[dict], max_error_rate: float, max_p95_ms: float, drop: float) -> str | None:
    """Why the ramp should stop after the latest step, or None. Judged on the latest steps only."""
    last = levels[-1]
    if last["rate_limited"] > 0.01 * max(1, last["requests"]):
        return f"{last['rate_limited']} requests were rate limited: the credentials have a limit, so this measures the limiter"
    if last["error_rate"] > max_error_rate:
        return f"error rate {last['error_rate']:.1%} is above {max_error_rate:.1%}"
    if last["p95_ms"] is not None and last["p95_ms"] > max_p95_ms:
        return f"p95 {last['p95_ms']:.0f} ms is above {max_p95_ms:.0f} ms"
    if len(levels) >= 3:
        peak = max(r["rps"] for r in levels)
        if all(r["rps"] < peak * (1 - drop) for r in levels[-2:]):
            return f"throughput fell more than {drop:.0%} below its peak ({peak:.0f}/s) for two steps in a row"
    return None


def summary_text(levels: list[dict], title: str, stopped: str | None, machines: int) -> str:
    best = best_sustained(levels)
    peak = max(levels, key=lambda r: r["rps"]) if levels else None
    lines = [f"# {title}", ""]
    if best:
        lines += [f"**Best sustained: {best['rps']:.0f} requests/s** at {best['level']} requests in flight (p95 {best['p95_ms']:.0f} ms, error rate {best['error_rate']:.2%}).", ""]
    else:
        lines += ["**No step stayed within p95 of 1 s and an error rate of 1%.**", ""]
    if peak:
        lines += [f"Peak throughput {peak['rps']:.0f} requests/s at {peak['level']} in flight (p95 {peak['p95_ms']:.0f} ms)." if peak["p95_ms"] is not None else f"Peak throughput {peak['rps']:.0f} requests/s.", ""]
    lines += [f"Stopped: {stopped}" if stopped else "The ramp ended without a stop condition (the last level was reached).", ""]
    lines += [f"{machines} machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.", "",
              "| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in levels:
        lines.append(f"| {r['level']} | {r['rps']:.0f} | {r['p50_ms']} | {r['p95_ms']} | {r['p99_ms']} | {r['errors']} | {r['error_rate']:.2%} | {r['rate_limited']} | {r.get('generator_cores', '')} | {r.get('note', '')} |")
    return "\n".join(lines) + "\n"


def merge_levels(runs: list[list[dict]]) -> list[dict]:
    """The machines' runs as one: per step, requests and rates add up; the latencies are the worst machine's (an upper bound)."""
    out = []
    for i in range(min(len(r) for r in runs)):
        rows = [r[i] for r in runs]
        requests = sum(x["requests"] for x in rows)
        errors = sum(x["errors"] for x in rows)
        pick = lambda k: max((x[k] for x in rows if x[k] is not None), default=None)
        out.append({"level": rows[0]["level"], "machine_concurrency": sum(x["machine_concurrency"] for x in rows), "start_utc": min(x["start_utc"] for x in rows), "end_utc": max(x["end_utc"] for x in rows),
                    "requests": requests, "ok": sum(x["ok"] for x in rows), "errors": errors, "rate_limited": sum(x["rate_limited"] for x in rows), "rps": round(sum(x["rps"] for x in rows), 1),
                    "p50_ms": pick("p50_ms"), "p95_ms": pick("p95_ms"), "p99_ms": pick("p99_ms"), "max_ms": pick("max_ms"), "error_rate": round(errors / requests, 4) if requests else 0.0,
                    "generator_cores": round(sum(x.get("generator_cores") or 0 for x in rows), 2), "note": ""})
    return out


def read_levels(directory: Path) -> list[dict]:
    rows = []
    with open(directory / "levels.csv", newline="") as f:
        for r in csv.DictReader(f):
            def num(k, cast=float):
                return cast(r[k]) if r.get(k) not in (None, "") else None
            rows.append({"level": int(r["level"]), "machine_concurrency": int(r["machine_concurrency"]), "start_utc": r["start_utc"], "end_utc": r["end_utc"], "requests": int(r["requests"]),
                         "ok": int(r["ok"]), "errors": int(r["errors"]), "rate_limited": int(r["rate_limited"]), "rps": num("rps"), "p50_ms": num("p50_ms"), "p95_ms": num("p95_ms"),
                         "p99_ms": num("p99_ms"), "max_ms": num("max_ms"), "error_rate": num("error_rate") or 0.0, "generator_cores": num("generator_cores"), "note": r.get("note", "")})
    return rows


def write_levels(directory: Path, levels: list[dict]) -> None:
    with open(directory / "levels.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEVEL_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in levels:
            w.writerow(r)


# ---------------------------------------------------------------- the cluster side (joined by the load itself, as soak_analyze does)
def join_watch(levels: list[dict], watch: list[dict], window_s: float = 1.0) -> tuple[list[dict], str]:
    """Add what the pods did during each step. The watcher's clock is lined up with the run's from the load's start and end (soak_analyze.estimate_offset)."""
    import soak_analyze as sa
    rows = [{"t": parse_utc(levels[0]["start_utc"])}, {"t": parse_utc(levels[-1]["end_utc"]) - window_s}]
    est = sa.estimate_offset(watch, rows, window_s)
    shift = est["offset"] if est["offset"] is not None else 0.0
    note = (f"the run's times were shifted by {shift:+.0f} s onto the watcher's clock, found from the pods' CPU rising and falling" if est["offset"] is not None
            else "**alignment unknown** (the watch has no idle stretch before or after the run): the clocks were trusted as they are")
    out = []
    for r in levels:
        a, b = parse_utc(r["start_utc"]) + shift, parse_utc(r["end_utc"]) + shift
        seg = [w for w in watch if a <= w["t"] <= b]
        cpu = [float(w["cpu_cores_used"]) for w in seg if w["cpu_cores_used"] not in ("", None)]
        thr = [float(w["throttled_share"]) for w in seg if w["throttled_share"] not in ("", None)]
        mem = [float(w["mem_mib_max"]) for w in seg if w["mem_mib_max"] not in ("", None)]
        out.append({**r, "cpu_median": round(statistics.median(cpu), 2) if cpu else None, "cpu_max": max(cpu) if cpu else None, "throttled_max": max(thr) if thr else None,
                    "mem_max": max(mem) if mem else None, "restarts": sum(int(w["new_restarts"]) for w in seg) if seg else None, "min_ready": min((int(w["ready"]) for w in seg), default=None),
                    "oom": sum(int(w["oom_killed"]) for w in seg) if seg else None})
    return out, note


def render_join(rows: list[dict], note: str) -> str:
    lines = ["# What the pods did during each step", "", f"Alignment: {note}.", "",
             "| in flight | requests/s | pods' CPU, median (cores) | max | CPU throttled, max | memory, largest pod (MiB) | fewest ready | new restarts | OOM kills |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        throttled = "" if r["throttled_max"] is None else "{:.1%}".format(r["throttled_max"])
        lines.append(f"| {r['level']} | {r['rps']:.0f} | {r['cpu_median']} | {r['cpu_max']} | {throttled} | {r['mem_max']} | {r['min_ready']} | {r['restarts']} | {r['oom']} |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- the commands
def cmd_run(a) -> int:
    auth = os.environ.get("LOAD_AUTH")
    problems = []
    if a.url.rstrip("/") != STAGING_URL and not a.allow_other_url:
        problems.append(f"{a.url} is not the staging service; add --allow-other-url only for a service you operate")
    if not auth and not a.anonymous:
        problems.append('no credentials: set LOAD_AUTH="PROFILE:TOKEN" for a profile with no rate limit (a limited caller only measures the limiter)')
    if max(a.levels) > a.max_total_concurrency:
        problems.append(f"level {max(a.levels)} is above --max-total-concurrency {a.max_total_concurrency}")
    if a.machines < 1 or min(a.levels) < a.machines:
        problems.append("--machines must be at least 1 and no larger than the smallest level")
    if a.mix not in load.MIXES:
        problems.append(f"unknown mix {a.mix}")
    if problems:
        print("cannot start:\n  - " + "\n  - ".join(problems), file=sys.stderr)
        return 2
    steps = len(a.levels)
    est = steps * (a.duration + a.warmup + a.pause) / 60
    print(f"plan: levels {a.levels} in flight in total, {a.machines} machine(s), mix {a.mix}, {a.duration:g} s each: up to {est:.0f} minutes. Stops early when the service buckles.")
    if a.dry_run:
        return 0
    if a.start_at:
        start = parse_utc(a.start_at)
        wait = start - time.time()
        if wait > 3600 or wait < -5:
            print(f"--start-at {a.start_at} is not within the next hour (now is {utc(time.time())})", file=sys.stderr)
            return 2
        print(f"waiting until {a.start_at} (UTC) so the machines start together")
        while time.time() < start:
            time.sleep(min(0.5, max(0.0, start - time.time())))
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "meta.json").write_text(json.dumps({"label": a.label, "url": a.url, "mix": a.mix, "levels": a.levels, "machines": a.machines, "duration": a.duration, "warmup": a.warmup, "pause": a.pause,
                                                "processes": a.processes, "started_utc": utc(time.time())}, indent=1))
    target = load.Target(a.url, connect_to=a.connect_to)
    levels: list[dict] = []
    stopped = None
    try:
        for total in a.levels:
            n = max(1, round(total / a.machines))
            t0 = time.time()
            cpu0 = resource.getrusage(resource.RUSAGE_CHILDREN)
            r = load.run_level(target, a.mix, n, a.duration, a.warmup, auth, processes=min(a.processes, n))
            t1 = time.time()
            cpu1 = resource.getrusage(resource.RUSAGE_CHILDREN)
            gen = round((cpu1.ru_utime + cpu1.ru_stime - cpu0.ru_utime - cpu0.ru_stime) / (t1 - t0), 2)
            row = {"level": total, "machine_concurrency": n, "start_utc": utc(t0 + a.warmup), "end_utc": utc(t1), "requests": r["requests"], "ok": r["ok"], "errors": r["errors"], "rate_limited": r["rate_limited"],
                   "rps": r["rps"], "p50_ms": r["p50_ms"] if r["ok"] else None, "p95_ms": r["p95_ms"] if r["ok"] else None, "p99_ms": r["p99_ms"] if r["ok"] else None, "max_ms": r["max_ms"],
                   "error_rate": r["error_rate"], "generator_cores": gen, "note": "generator near its limit" if gen >= 0.8 * min(a.processes, n) else ""}
            levels.append(row)
            write_levels(a.out, levels)
            (a.out / "summary.md").write_text(summary_text(levels, f"Ceiling test: {a.label} (running)", None, a.machines))
            print(f"[{utc(t1)}] {total:5d} in flight ({n} here) {row['rps']:8.1f} req/s  p50 {row['p50_ms']}  p95 {row['p95_ms']}  p99 {row['p99_ms']} ms  errors {row['errors']} ({row['error_rate']:.2%})  429s {row['rate_limited']}  generator {gen} cores{'  <- generator near its limit' if row['note'] else ''}")
            stopped = buckled(levels, a.max_error_rate, a.max_p95_ms, a.drop)
            if stopped:
                print(f"STOP: {stopped}")
                break
            time.sleep(a.pause)
    except KeyboardInterrupt:
        stopped = "interrupted"
    text = summary_text(levels, f"Ceiling test: {a.label}", stopped, a.machines)
    (a.out / "summary.md").write_text(text)
    print(text)
    print(f"written to {a.out}/ (the cluster side: pod_watch.py on the build node, then `ceiling.py report`)")
    return 0


def cmd_merge(a) -> int:
    try:
        runs = [read_levels(d) for d in a.dirs]
    except (OSError, KeyError, ValueError) as e:
        print(f"cannot read the results: {e}", file=sys.stderr)
        return 2
    levels = merge_levels(runs)
    a.out.mkdir(parents=True, exist_ok=True)
    write_levels(a.out, levels)
    stopped = buckled(levels, 0.02, 5000.0, 0.15)
    text = summary_text(levels, f"Ceiling test, {len(runs)} machines merged", stopped, len(runs))
    (a.out / "summary.md").write_text(text)
    print(text)
    return 0


def cmd_report(a) -> int:
    import soak_analyze as sa
    try:
        levels = read_levels(a.run)
        watch = sa.read_watch(a.watch)
    except (OSError, KeyError, ValueError) as e:
        print(f"cannot read the results: {e}", file=sys.stderr)
        return 2
    if not watch:
        print("no watch.csv in " + str(a.watch), file=sys.stderr)
        return 2
    rows, note = join_watch(levels, watch)
    text = render_join(rows, note)
    (a.run / "cluster.md").write_text(text)
    print(text)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="ramp the load until the service buckles")
    r.add_argument("--url", default=STAGING_URL)
    r.add_argument("--allow-other-url", action="store_true")
    r.add_argument("--anonymous", action="store_true", help="no credentials (for a local test server only)")
    r.add_argument("--mix", default="lookups")
    r.add_argument("--levels", type=int, nargs="+", default=DEFAULT_LEVELS, help="requests in flight in TOTAL across all machines")
    r.add_argument("--machines", type=int, default=1, help="how many machines run this at the same time; each sends 1/N of every level")
    r.add_argument("--duration", type=float, default=30.0)
    r.add_argument("--warmup", type=float, default=5.0)
    r.add_argument("--pause", type=float, default=15.0)
    r.add_argument("--processes", type=int, default=8)
    r.add_argument("--max-error-rate", type=float, default=0.02)
    r.add_argument("--max-p95-ms", type=float, default=5000.0)
    r.add_argument("--drop", type=float, default=0.15)
    r.add_argument("--max-total-concurrency", type=int, default=4096)
    r.add_argument("--start-at", metavar="YYYY-MM-DDTHH:MM:SSZ", help="wait until this UTC time (within the next hour) so several machines start together")
    r.add_argument("--connect-to", metavar="ADDRESS")
    r.add_argument("--label", default=os.environ.get("USER", "tester"))
    r.add_argument("--out", type=Path, default=Path("perf_tests/results") / f"ceiling-{time.strftime('%Y%m%d-%H%M')}")
    r.add_argument("--dry-run", action="store_true")
    m = sub.add_parser("merge", help="combine the machines' results")
    m.add_argument("dirs", nargs="+", type=Path)
    m.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("report", help="join a run with what the pods did")
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--watch", type=Path, required=True)
    a = ap.parse_args(argv)
    return {"run": cmd_run, "merge": cmd_merge, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
