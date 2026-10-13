"""A soak test for a company_dns server, run from outside its network (standard library only; Python 3.10 or newer).

It ramps the load up in steps, then holds it for as long as you ask, and writes one line of numbers to disk for every window (a minute by default),
so the results can be reviewed later, or while it runs, and survive a crash or a Ctrl-C. Every window it also asks a few fixed questions with known
answers (the "canaries") to catch a server that is fast but wrong, and probes /health.

    python3 perf_tests/soak.py --label johns-home                       # staging, 24 hours: ramp 4, 8, 16, 32 then hold 16
    python3 perf_tests/soak.py --label johns-home --hours 0.1 --window 10 --steps 2,4 --step-minutes 0.2    # a short trial first

Without credentials the server limits each address to a standard quota (a per-minute rate and a burst; ask for the figures) and answers `429`s beyond it,
which the test counts on their own; use --rps to stay under it. With a profile that has no limit, put "PROFILE:TOKEN" in the environment variable
SOAK_AUTH (never on the command line) to measure the server rather than the quota.

Output, in the --out directory (default perf_tests/results/soak-<time>): windows.csv and windows.jsonl (one line per window), canaries.jsonl, meta.json
and summary.md (rewritten after every window, so a partial run can be read). The test never changes anything on the server: it only sends GET requests.
"""
import argparse
import csv
import json
import os
import platform
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402

DEFAULT_URL = "https://company-dns-staging.mediumroast.io"
CSV_FIELDS = ["time_utc", "elapsed_s", "step", "concurrency", "requests", "ok", "errors", "rate_limited", "rps", "p50_ms", "p95_ms", "p99_ms", "max_ms",
              "error_rate", "canaries_ok", "canaries_total", "health_ms", "window_ok", "note"]


# ---------------------------------------------------------------- canaries: fixed questions with known answers
def _json(body: bytes):
    try:
        return json.loads(body)
    except ValueError:
        return None


def check_health(body):
    j = _json(body)
    return (None if isinstance(j, dict) and j.get("status") == "healthy" else "not healthy")


def envelope_with(marker: str | None):
    """200 in the envelope with a count of at least one, and (if given) the marker somewhere in the data."""
    def check(body):
        j = _json(body)
        if not isinstance(j, dict) or j.get("code") != 200:
            return "no 200 envelope"
        if not isinstance(j.get("total"), int) or j["total"] < 1:
            return f"total is {j.get('total')!r}"
        if marker and marker not in json.dumps(j.get("data")):
            return f"{marker!r} is not in the data"
        return None
    return check


CANARIES = (
    ("health", "/health", check_health),
    ("us_sic_code", "/V4.0/na/sic/code/3571", envelope_with("3571")),
    ("us_sic_code_v3_path", "/V3.0/na/sic/code/3571", envelope_with("3571")),
    ("eu_nace_class", "/V4.0/eu/sic/class/25.91", envelope_with("25.91")),
    ("japan_sic_industry_group", "/V4.0/japan/sic/industry_group/0911", envelope_with(None)),
)


CANARY_RETRY_WAIT = 2.0  # seconds before the second try of a failed question


def run_canaries(target: load.Target, headers: dict, retry_wait: float | None = None) -> list[dict]:
    """Ask each question once on a fresh connection (a second try after a pause, so a blip on the way is not a failure of the server)."""
    retry_wait = CANARY_RETRY_WAIT if retry_wait is None else retry_wait
    out = []
    for name, path, check in CANARIES:
        result = {"name": name, "path": path}
        for attempt in (1, 2):
            started = time.monotonic()
            try:
                conn = target.connect()
                try:
                    conn.request("GET", path, headers=headers)
                    resp = conn.getresponse()
                    body = resp.read()
                finally:
                    conn.close()
                problem = None if resp.status == 200 else f"HTTP {resp.status}"
                problem = problem or check(body)
            except Exception as e:  # a timeout, a reset, a certificate problem
                problem = f"{type(e).__name__}: {e}"[:160]
            result.update({"ok": problem is None, "problem": problem, "ms": round((time.monotonic() - started) * 1000, 1), "attempt": attempt})
            if problem is None:
                break
            if attempt == 1:
                time.sleep(retry_wait)
        out.append(result)
    return out


# ---------------------------------------------------------------- the schedule
def schedule(steps: list[int], step_windows: int, hold: int, total_windows: int):
    """The concurrency for window 0, 1, 2 ...: each step for `step_windows` windows, then `hold` until `total_windows` have run."""
    for i in range(total_windows):
        if i < len(steps) * step_windows:
            yield f"step {i // step_windows + 1}/{len(steps)}", steps[i // step_windows]
        else:
            yield "hold", hold


# ---------------------------------------------------------------- the summary
def window_ok(w: dict, max_error_rate: float, max_p95_ms: float) -> bool:
    return (w["requests"] > 0 and w["error_rate"] <= max_error_rate and (w["p95_ms"] is not None and w["p95_ms"] <= max_p95_ms)
            and w["canaries_ok"] == w["canaries_total"])


def _median(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 1) if values else None


def summarise(windows: list[dict], meta: dict, finished: bool, max_error_rate: float, max_p95_ms: float) -> tuple[str, str]:
    """(verdict, markdown). The verdict is PASS, FAIL, or RUNNING for a run still in progress."""
    total = sum(w["requests"] for w in windows)
    errors = sum(w["errors"] for w in windows)
    limited = sum(w["rate_limited"] for w in windows)
    bad = [w for w in windows if not w["window_ok"]]
    c_total = sum(w["canaries_total"] for w in windows)
    c_ok = sum(w["canaries_ok"] for w in windows)
    overall_error = round(errors / total, 4) if total else 1.0
    reasons = []
    if not windows:
        reasons.append("no windows were completed")
    if overall_error > max_error_rate:
        reasons.append(f"error rate {overall_error:.2%} is above {max_error_rate:.2%}")
    if windows and len(bad) / len(windows) > 0.05:
        reasons.append(f"{len(bad)} of {len(windows)} windows ({len(bad) / len(windows):.0%}) missed the error, latency or canary bar (more than 5%)")
    if c_total and c_ok / c_total < 0.99:
        reasons.append(f"canary answers: {c_ok} of {c_total} correct (under 99%)")
    verdict = "RUNNING" if not finished else ("FAIL" if reasons else "PASS")

    hold = [w for w in windows if w["step"] == "hold"]
    lines = [f"# Soak test: {verdict}", "",
             f"Target {meta['url']} from `{meta['label']}`, started {meta['started_utc']}; mix `{meta['mix']}`; {len(windows)} windows of {meta['window_s']} s"
             f"{' (still running)' if not finished else ''}.", ""]
    if finished and reasons:
        lines += ["Reasons:"] + [f"- {r}" for r in reasons] + [""]
    lines += ["| | |", "|---|---|",
              f"| requests | {total} |", f"| errors | {errors} ({overall_error:.2%}) |", f"| rate limited (`429`) | {limited} |",
              f"| windows that missed the bar | {len(bad)} of {len(windows)} (error rate above {max_error_rate:.2%}, p95 above {max_p95_ms:.0f} ms, or a wrong canary) |",
              f"| canary answers correct | {c_ok} of {c_total} |", ""]
    if limited:
        lines += ["Some requests were answered `429` (over the per-address quota). They are counted apart from errors; lower --rps, or ask for credentials with no limit.", ""]
    steps = []
    for w in windows:
        if not steps or steps[-1][0] != (w["step"], w["concurrency"]):
            steps.append([(w["step"], w["concurrency"]), []])
        steps[-1][1].append(w)
    lines += ["## By step", "", "| step | concurrency | windows | requests/s (median) | p50 ms | p95 ms (median) | worst p95 ms | errors | 429s |", "|---|---|---|---|---|---|---|---|---|"]
    for (name, conc), ws in steps:
        p95s = [w["p95_ms"] for w in ws if w["p95_ms"] is not None]
        lines.append(f"| {name} | {conc} | {len(ws)} | {_median([w['rps'] for w in ws])} | {_median([w['p50_ms'] for w in ws])} | {_median(p95s)} | "
                     f"{max(p95s) if p95s else None} | {sum(w['errors'] for w in ws)} | {sum(w['rate_limited'] for w in ws)} |")
    if len(hold) >= 8:
        q = len(hold) // 4
        first, last = hold[:q], hold[-q:]
        lines += ["", "## Drift while holding", "",
                  f"First quarter of the hold: median p95 {_median([w['p95_ms'] for w in first])} ms, {_median([w['rps'] for w in first])} requests/s. "
                  f"Last quarter: median p95 {_median([w['p95_ms'] for w in last])} ms, {_median([w['rps'] for w in last])} requests/s. "
                  "A steady climb in p95, or a fall in requests/s, at the same load is what a slow leak looks like."]
    if bad:
        lines += ["", "## Windows that missed the bar (first 20)", "", "| time (UTC) | step | p95 ms | error rate | canaries | note |", "|---|---|---|---|---|---|"]
        for w in bad[:20]:
            lines.append(f"| {w['time_utc']} | {w['step']} | {w['p95_ms']} | {w['error_rate']:.2%} | {w['canaries_ok']}/{w['canaries_total']} | {w['note']} |")
    lines += ["", f"Files: windows.csv, windows.jsonl, canaries.jsonl, meta.json (Python {meta['python']}, {meta['platform']})."]
    return verdict, "\n".join(lines) + "\n"


# ---------------------------------------------------------------- the run
def user_agent(label: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", label)[:40] or "soak"
    # a contact signal (the URL) makes the server treat this as a self-identifying caller (the standard tier), not the strictest one
    return f"company_dns-soak/1.0 (+https://github.com/miha42-github/company_dns; {safe})"


def probe_health(target: load.Target, headers: dict) -> float | None:
    started = time.monotonic()
    try:
        conn = target.connect()
        try:
            conn.request("GET", "/health", headers=headers)
            resp = conn.getresponse()
            resp.read()
        finally:
            conn.close()
        return round((time.monotonic() - started) * 1000, 1) if resp.status == 200 else None
    except Exception:
        return None


def run(a, log=print) -> int:
    auth = os.environ.get("SOAK_AUTH") or os.environ.get("LOAD_AUTH")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    steps = [int(x) for x in a.steps.split(",") if x.strip()]
    window_s = a.window
    total_windows = max(1, int(a.hours * 3600 / window_s))  # an upper bound: each window also takes a second or two to set up and check, so the clock ends the run first
    step_windows = max(1, round(a.step_minutes * 60 / window_s))
    target = load.Target(a.url)
    mix = load.blend(a.embedding_share) if getattr(a, "embedding_share", None) is not None else a.mix
    ua = user_agent(a.label)
    headers = {"User-Agent": ua, "Accept": "application/json"}
    meta = {"url": a.url, "label": a.label, "mix": a.mix, "embedding_share": getattr(a, "embedding_share", None), "window_s": window_s, "steps": steps, "step_windows": step_windows, "hold": a.hold_concurrency,
            "rps_cap": a.rps, "authenticated": bool(auth), "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "python": platform.python_version(), "platform": platform.platform(), "planned_windows": total_windows,
            "max_error_rate": a.max_error_rate, "max_p95_ms": a.max_p95_ms}
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    log(f"soak test of {a.url}: {total_windows} windows of {window_s} s (about {total_windows * window_s / 3600:.1f} hours), results in {out}/")
    windows: list[dict] = []
    t0 = time.monotonic()
    interrupted = False
    abort = None
    with open(out / "windows.csv", "w", newline="") as fcsv, open(out / "windows.jsonl", "a") as fjson, open(out / "canaries.jsonl", "a") as fcan:
        writer = csv.DictWriter(fcsv, fieldnames=CSV_FIELDS)
        writer.writeheader()
        try:
            for step, conc in schedule(steps, step_windows, a.hold_concurrency, total_windows):
                now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                if time.monotonic() - t0 >= a.hours * 3600:
                    break  # --hours is the length of the run, ramp included: stop on the clock, not only on the window count
                r = load.run_level(target, mix, conc, window_s, 0.0, auth, processes=min(a.processes, conc),
                                   extra_headers={"User-Agent": ua}, rps=a.rps)
                canaries = run_canaries(target, headers)
                health_ms = probe_health(target, headers)
                for c in canaries:
                    fcan.write(json.dumps({"time_utc": now, "step": step, **c}) + "\n")
                fcan.flush()
                notes = []
                denied = r["by_status"].get("401", 0) + r["by_status"].get("403", 0)
                if r["requests"] and denied / r["requests"] > 0.9:
                    notes.append("the server refused our credentials")
                    abort = "the server answered 401/403 to nearly every request: check SOAK_AUTH (the profile and token)"
                if r["rate_limited"]:
                    notes.append(f"{r['rate_limited']} rate limited")
                notes += [f"canary {c['name']}: {c['problem']}" for c in canaries if not c["ok"]]
                w = {"time_utc": now, "elapsed_s": round(time.monotonic() - t0), "step": step, "concurrency": conc, "requests": r["requests"], "ok": r["ok"],
                     "errors": r["errors"], "rate_limited": r["rate_limited"], "rps": r["rps"], "p50_ms": r["p50_ms"] if r["ok"] else None,
                     "p95_ms": r["p95_ms"] if r["ok"] else None, "p99_ms": r["p99_ms"] if r["ok"] else None, "max_ms": r["max_ms"],
                     "error_rate": r["error_rate"], "canaries_ok": sum(1 for c in canaries if c["ok"]), "canaries_total": len(canaries),
                     "health_ms": health_ms, "note": "; ".join(notes)}
                w["window_ok"] = window_ok(w, a.max_error_rate, a.max_p95_ms)
                windows.append(w)
                writer.writerow({k: w.get(k) for k in CSV_FIELDS})
                fcsv.flush()
                fjson.write(json.dumps(w) + "\n")
                fjson.flush()
                (out / "summary.md").write_text(summarise(windows, meta, False, a.max_error_rate, a.max_p95_ms)[1])
                log(f"[{now}] {step:9s} N={conc:<3d} {w['rps']:7.1f} req/s  p50 {w['p50_ms']}  p95 {w['p95_ms']} ms  errors {w['errors']}  429s {w['rate_limited']}  "
                    f"canaries {w['canaries_ok']}/{w['canaries_total']}  {'ok' if w['window_ok'] else 'MISSED: ' + w['note'][:80]}")
                if abort:
                    break
        except KeyboardInterrupt:
            interrupted = True
            log("interrupted: writing the summary of what ran")
    verdict, text = summarise(windows, meta, True, a.max_error_rate, a.max_p95_ms)
    if interrupted or abort:
        text = text.replace(f"# Soak test: {verdict}", f"# Soak test: {verdict} ({'stopped: ' + abort if abort else 'interrupted before the planned end'})", 1)
    (out / "summary.md").write_text(text)
    log(text)
    log(f"results are in {out}/ (send the whole directory)")
    return 2 if abort else (130 if interrupted else (0 if verdict == "PASS" else 1))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--label", default=os.environ.get("USER", "tester"), help="who and where, for the record (for example johns-home); no spaces")
    ap.add_argument("--mix", choices=sorted(load.MIXES), default="lookups",
                    help="lookups (default), repeated, breadth (V4 and V3 paths, 5%% embedding searches), mixed (30%% embedding searches), embedding")
    ap.add_argument("--embedding-share", type=float, help="with --mix breadth: the fraction of requests that are embedding searches, 0 to 1 (default 0.05)")
    ap.add_argument("--steps", default="4,8,16,32", help="concurrency of each ramp step, comma separated")
    ap.add_argument("--step-minutes", type=float, default=10.0)
    ap.add_argument("--hold-concurrency", type=int, default=16)
    ap.add_argument("--hours", type=float, default=24.0, help="total length, ramp included")
    ap.add_argument("--window", type=float, default=60.0, help="seconds per recorded window")
    ap.add_argument("--rps", type=float, help="cap the total request rate (use this without credentials, to stay under the per-address quota)")
    ap.add_argument("--processes", type=int, default=4)
    ap.add_argument("--max-error-rate", type=float, default=0.01)
    ap.add_argument("--max-p95-ms", type=float, default=2000.0, help="a window whose p95 is above this missed the bar (it includes your network)")
    ap.add_argument("--out", type=Path, default=Path("perf_tests/results") / f"soak-{time.strftime('%Y%m%d-%H%M')}")
    a = ap.parse_args(argv)
    problems = []
    if not a.url.startswith(("http://", "https://")):
        problems.append("--url must start with http:// or https://")
    try:
        if not [int(x) for x in a.steps.split(",") if x.strip()]:
            problems.append("--steps needs at least one number")
    except ValueError:
        problems.append("--steps must be numbers separated by commas, for example 4,8,16,32")
    if a.window < 5 or a.hours <= 0 or a.hold_concurrency < 1 or (a.rps is not None and a.rps <= 0):
        problems.append("--window must be at least 5 seconds; --hours and --hold-concurrency must be positive; --rps must be positive")
    if a.embedding_share is not None and (a.mix != "breadth" or not 0 <= a.embedding_share <= 1):
        problems.append("--embedding-share (0 to 1) goes with --mix breadth")
    if re.search(r"\s", a.label):
        problems.append("--label must not contain spaces")
    if problems:
        print("cannot start:\n  - " + "\n  - ".join(problems), file=sys.stderr)
        return 2
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
