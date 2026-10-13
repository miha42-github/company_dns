"""Tests for pod_watch.py and soak_analyze.py. Run: python3 perf_tests/test_soak_tools.py

The watcher runs against a fake cluster (and is checked to only ever read); the analyses run on made-up results.
"""
import argparse
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pod_watch as pw  # noqa: E402
import run_cluster as rc  # noqa: E402
import soak_analyze as sa  # noqa: E402



def pod(name, ready=True, restarts=0, node="n1", terminating=False, phase="Running", oom=False):
    meta = {"name": name}
    if terminating:
        meta["deletionTimestamp"] = "2026-10-12T21:00:00Z"
    cs = {"ready": ready, "restartCount": restarts}
    if oom:
        cs["lastState"] = {"terminated": {"reason": "OOMKilled"}}
    return {"metadata": meta, "spec": {"nodeName": node}, "status": {"phase": phase, "containerStatuses": [cs]}}


def cgroup(usage, periods, throttled, mem_bytes):
    return f"usage_usec {usage}\nuser_usec 1\nnr_periods {periods}\nnr_throttled {throttled}\nthrottled_usec 5\n---\n{mem_bytes}\n"


class FakeCluster(rc.Cluster):
    def __init__(self):
        self.kubectl = ["kubectl"]
        self.calls = []
        self.pod_list = []
        self.reads = {}
        self.fail = set()

    def pods(self, namespace=rc.NAMESPACE):
        self.calls.append(("pods", namespace))
        return self.pod_list

    def run(self, *args, namespace=rc.NAMESPACE, stdin=None, check=True):
        self.calls.append(args)
        if args[0] == "exec":
            if args[1] in self.fail:
                raise RuntimeError("gone")
            return self.reads[args[1]]
        raise AssertionError(f"the watcher ran {args}")


class Watch(unittest.TestCase):
    def test_a_cgroup_read_becomes_numbers_and_a_bad_one_becomes_gaps(self):
        r = pw.parse_cgroup_text(cgroup(4_000_000, 100, 10, 200 * 1048576))
        self.assertEqual((r["usage_us"], r["periods"], r["throttled"], r["mem_mib"]), (4_000_000, 100, 10, 200.0))
        self.assertEqual(pw.parse_cgroup_text("garbage")["usage_us"], None)

    def test_the_row_has_cpu_throttling_memory_and_new_restarts(self):
        states = [pw.pod_state(pod("a")), pw.pod_state(pod("b", restarts=2)), pw.pod_state(pod("c", ready=False)), pw.pod_state(pod("d", terminating=True))]
        prev = {n: pw.parse_cgroup_text(cgroup(0, 0, 0, 100 * 1048576)) for n in "abc"}
        now = {"a": pw.parse_cgroup_text(cgroup(10_000_000, 100, 20, 200 * 1048576)), "b": pw.parse_cgroup_text(cgroup(20_000_000, 100, 0, 300 * 1048576)),
               "c": pw.parse_cgroup_text(cgroup(0, 100, 0, 150 * 1048576))}
        row, _ = pw.combine("t", states, now, prev, 10.0, 0)
        self.assertEqual((row["pods"], row["ready"], row["terminating"], row["not_ready"]), (4, 2, 1, 1))
        self.assertEqual((row["restarts_total"], row["new_restarts"]), (2, 2))
        self.assertEqual(row["cpu_cores_used"], 3.0, "30 CPU-seconds over 10 s")
        self.assertEqual(row["throttled_share"], round(20 / 300, 3))
        self.assertEqual((row["mem_mib_max"], row["mem_mib_median"]), (300.0, 200.0))
        self.assertEqual(row["unreadable"], 0)

    def test_oom_kills_and_unreadable_pods_are_counted(self):
        states = [pw.pod_state(pod("a", oom=True)), pw.pod_state(pod("b"))]
        row, _ = pw.combine("t", states, {"a": pw.parse_cgroup_text(cgroup(1, 1, 0, 1048576))}, None, 0.0, None)
        self.assertEqual((row["oom_killed"], row["unreadable"], row["cpu_cores_used"], row["new_restarts"]), (1, 1, None, 0))

    def test_it_only_reads_and_writes_a_row_per_sample(self):
        c = FakeCluster()
        c.pod_list = [pod("a"), pod("b")]
        c.reads = {"a": cgroup(1_000_000, 10, 0, 100 * 1048576), "b": cgroup(2_000_000, 10, 1, 120 * 1048576)}
        with tempfile.TemporaryDirectory() as d:
            clock = [1_000_000.0]
            args = argparse.Namespace(out=d, namespace="company-dns-staging", interval=30.0, hours=0.0042)  # 15 s: two samples
            code = pw.run(args, cluster=c, log=lambda *_: None, sleep=lambda s: clock.__setitem__(0, clock[0] + 10), now=lambda: clock[0])
            self.assertEqual(code, 0)
            rows = list(csv.DictReader(open(Path(d) / "watch.csv")))
            self.assertGreaterEqual(len(rows), 2)
            self.assertEqual(rows[0]["pods"], "2")
            lines = [json.loads(x) for x in open(Path(d) / "pods.jsonl")]
            self.assertEqual({x["name"] for x in lines}, {"a", "b"})
        for call in c.calls:
            self.assertIn(call[0], ("pods", "exec"), call)
            if call[0] == "exec":
                self.assertEqual(call[3:5], ("sh", "-c"))
                self.assertNotIn(";", " ".join(call[5:]).replace("; echo ---; cat", ""), "only cat")

    def test_a_pod_that_cannot_be_read_does_not_stop_the_watch(self):
        c = FakeCluster()
        c.pod_list = [pod("a"), pod("b")]
        c.reads = {"a": cgroup(1, 1, 0, 1048576), "b": cgroup(1, 1, 0, 1048576)}
        c.fail = {"b"}
        states, cg = pw.Watcher(c, "x").sample()
        self.assertEqual((len(states), list(cg)), (2, ["a"]))

    def test_a_tiny_interval_is_refused(self):
        self.assertEqual(pw.main(["--interval", "1"]), 2)


def write_soak(d: Path, rows, label="site-a", window_s=60):
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps({"url": "https://example.org", "label": label, "window_s": window_s, "started_utc": rows[0]["time_utc"], "mix": "lookups", "platform": "Linux-x-with-glibc", "python": "3.11",
                                             "max_error_rate": 0.01, "max_p95_ms": 2000.0}))
    with open(d / "windows.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["time_utc", "elapsed_s", "step", "concurrency", "requests", "ok", "errors", "rate_limited", "rps", "p50_ms", "p95_ms", "p99_ms", "max_ms",
                                          "error_rate", "canaries_ok", "canaries_total", "health_ms", "window_ok", "note"])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def make_rows(n=40, bad_at=(), start=1_800_000_000):
    import time
    rows = []
    for i in range(n):
        bad = i in bad_at
        rows.append({"time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start + 61 * i)), "elapsed_s": 61 * (i + 1), "step": "hold", "concurrency": 16, "requests": 3600,
                     "ok": 3600 - (30 if bad else 0), "errors": 30 if bad else 0, "rate_limited": 0, "rps": 60.0, "p50_ms": 28.0, "p95_ms": 117.0, "p99_ms": 130.0, "max_ms": 250.0,
                     "error_rate": 0.008 if bad else 0.0, "canaries_ok": 5, "canaries_total": 5, "health_ms": 100.0, "window_ok": True, "note": ""})
    return rows


class Analyse(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_merge_judges_each_site_and_passes_only_if_all_pass(self):
        write_soak(self.root / "one", make_rows(1440), label="remote-tester")
        write_soak(self.root / "two", make_rows(), label="site-b")
        overall, text = sa.merge([self.root / "one", self.root / "two"], self.root / "out")
        self.assertEqual(overall, "PASS", text)
        self.assertIn("remote-tester", text)
        self.assertIn("site-b", text)
        self.assertEqual(len(list(csv.DictReader(open(self.root / "out" / "windows.csv")))), 1440 + 40)
        rows = make_rows()
        for r in rows[:20]:
            r.update(errors=2000, ok=1600, error_rate=0.55, window_ok=False)
        write_soak(self.root / "bad", rows, label="site-c")
        overall, text = sa.merge([self.root / "one", self.root / "bad"], self.root / "out2")
        self.assertEqual(overall, "FAIL")
        self.assertIn("| site-c | FAIL |", text)

    def test_events_pass_when_the_soak_is_clean_around_them(self):
        write_soak(self.root / "s", make_rows())
        (self.root / "events.txt").write_text("# a comment\n2027-01-15T08:20:00Z rolling update to tag-2\nnonsense line\n")
        rows, meta = sa.read_windows(self.root / "s")
        events, bad = sa.read_events(self.root / "events.txt")
        results, baseline = sa.judge_events(rows, 60.0, events, [], 5)
        self.assertEqual(bad, ["nonsense line"])
        self.assertEqual((len(results), results[0]["verdict"], baseline), (1, "PASS", 117.0))
        self.assertGreaterEqual(len(results[0]["windows"]), 4)

    def test_an_error_a_wrong_canary_or_a_slow_window_makes_the_event_review(self):
        import time
        start = 1_800_000_000
        ev = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start + 61 * 20))
        for name, change, expect in (("err", {"errors": 12}, "request errors"), ("canary", {"canaries_ok": 4}, "canary"), ("slow", {"p95_ms": 400.0}, "p95 reached")):
            rows = make_rows()
            rows[21].update(change)
            write_soak(self.root / name, rows)
            (self.root / f"{name}.txt").write_text(f"{ev} kill a pod\n")
            r, meta = sa.read_windows(self.root / name)
            events, _ = sa.read_events(self.root / f"{name}.txt")
            results, baseline = sa.judge_events(r, 60.0, events, [], 5)
            self.assertEqual(results[0]["verdict"], "REVIEW", name)
            self.assertIn(expect, "; ".join(results[0]["reasons"]))
            text = sa.render_events(results, baseline, [], "site-a", 5)
            self.assertIn("REVIEW", text)
            self.assertIn("the windows", text)

    def test_the_pods_around_an_event_are_shown_from_the_watch(self):
        import time
        start = 1_800_000_000
        write_soak(self.root / "s", make_rows())
        (self.root / "w").mkdir()
        with open(self.root / "w" / "watch.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=pw.CSV_FIELDS)
            w.writeheader()
            for i in range(10):
                w.writerow({"time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start + 61 * 20 + 10 * i - 20)), "pods": 20, "ready": 19 if i == 3 else 20,
                            "terminating": 1 if i == 3 else 0, "not_ready": 0, "restarts_total": 0, "new_restarts": 0, "oom_killed": 0, "mem_mib_median": 200, "mem_mib_max": 230 + i,
                            "cpu_cores_used": 5, "throttled_share": 0.01, "nodes": 2, "unreadable": 0})
        ev = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start + 61 * 20))
        (self.root / "e.txt").write_text(f"{ev} delete a pod\n")
        rows, meta = sa.read_windows(self.root / "s")
        events, _ = sa.read_events(self.root / "e.txt")
        results, baseline = sa.judge_events(rows, 60.0, events, sa.read_watch(self.root / "w"), 5)
        self.assertEqual((results[0]["min_ready"], results[0]["max_terminating"], results[0]["new_restarts"]), (19, 1, 0))
        self.assertEqual(results[0]["max_mem"], 239.0)
        code = sa.main(["events", "--soak", str(self.root / "s"), "--events", str(self.root / "e.txt"), "--watch", str(self.root / "w")])
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "s" / "events.md").exists())


def write_watch(d: Path, load_start: float, load_end: float, interval=15.0, before=240.0, after=240.0, spikes=(), idle=0.1, busy=0.9):
    """A watch.csv: idle CPU before and after, busy between (times on the watcher's clock); `spikes` are times with a short CPU burst inside the load, as a rollout makes."""
    import time
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "watch.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=pw.CSV_FIELDS)
        w.writeheader()
        t = load_start - before
        while t <= load_end + after:
            # the CPU of the interval ending at t, averaged over it: the share of the interval that was inside the load
            inside = max(0.0, min(t, load_end) - max(t - interval, load_start)) / interval
            cpu = idle + (busy - idle) * inside + (2.0 if any(t - interval < s_ <= t for s_ in spikes) else 0.0)
            w.writerow({"time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)), "pods": 20, "ready": 20, "terminating": 0, "not_ready": 0, "restarts_total": 0, "new_restarts": 0,
                        "oom_killed": 0, "mem_mib_median": 200, "mem_mib_max": 220, "cpu_cores_used": round(cpu, 3), "throttled_share": 0.01, "nodes": 2, "unreadable": 0})
            t += interval


class Alignment(unittest.TestCase):
    """The soak machine's clock is not trusted: the pods' CPU shows when the load really ran."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.start = 1_800_000_000  # the soak's own clock
        self.rows = make_rows(120, start=self.start)  # 120 windows of 61 s
        for r in self.rows:
            pass
        self.end = self.rows[-1]["time_utc"]

    def watch_for(self, skew, **kw):
        sa_rows, _ = None, None
        load_start = self.start + skew
        load_end = self.start + 61 * 120 + skew
        write_watch(self.root / "w", load_start, load_end, **kw)
        return sa.read_watch(self.root / "w")

    def rows_parsed(self):
        write_soak(self.root / "s", self.rows)
        return sa.read_windows(self.root / "s")[0]

    def test_the_offset_is_found_from_the_load_whatever_the_clock_difference(self):
        for skew in (0, 37, -90, 400, -1200):
            watch = self.watch_for(skew)
            est = sa.estimate_offset(watch, self.rows_parsed(), 60.0)
            self.assertIsNotNone(est["offset"], skew)
            self.assertLess(abs(est["offset"] - skew), 20.0, f"skew {skew}: found {est['offset']}")
            self.assertEqual(set(est["anchors"]), {"start", "end"})

    def test_rollout_spikes_inside_the_run_do_not_move_the_edges(self):
        skew = 400
        spikes = [self.start + skew + 61 * k for k in (10, 30, 31, 60, 90)]
        watch = self.watch_for(skew, spikes=spikes)
        est = sa.estimate_offset(watch, self.rows_parsed(), 60.0)
        self.assertLess(abs(est["offset"] - skew), 20.0, est)

    def test_no_idle_before_or_after_means_one_edge_or_unknown(self):
        watch = self.watch_for(0, before=-60.0)
        est = sa.estimate_offset(watch, self.rows_parsed(), 60.0)
        self.assertEqual(set(est["anchors"]), {"end"})
        self.assertTrue(any("one edge" in n or "no idle before" in n for n in est["notes"]), est["notes"])
        watch = self.watch_for(0, before=-60.0, after=-60.0)
        est = sa.estimate_offset(watch, self.rows_parsed(), 60.0)
        self.assertIsNone(est["offset"])

    def test_a_watch_with_no_difference_between_idle_and_running_is_not_guessed_at(self):
        watch = self.watch_for(0, busy=0.12)
        est = sa.estimate_offset(watch, self.rows_parsed(), 60.0)
        self.assertIsNone(est["offset"])
        self.assertTrue(any("no clear difference" in n for n in est["notes"]), est["notes"])

    def test_alignment_changes_which_windows_an_event_covers(self):
        # a window with errors at soak time T; the watcher's clock is 400 s ahead; the event is marked at T on the WATCHER's clock
        import time
        skew = 400
        self.rows[50].update(errors=30, ok=3570, error_rate=0.008)
        watch_rows = self.watch_for(skew)
        write_soak(self.root / "s", self.rows)
        ev = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.start + skew + 61 * 50 - 5))
        (self.root / "e.txt").write_text(f"{ev} kill a pod\n")
        code = sa.main(["events", "--soak", str(self.root / "s"), "--events", str(self.root / "e.txt"), "--watch", str(self.root / "w")])
        text = (self.root / "s" / "events.md").read_text()
        self.assertEqual(code, 1, text)
        self.assertIn("REVIEW", text)
        self.assertIn("shifted by +", text)
        code = sa.main(["events", "--soak", str(self.root / "s"), "--events", str(self.root / "e.txt"), "--watch", str(self.root / "w"), "--no-align"])
        self.assertEqual(code, 0, "unaligned, the error window is 400 s away from the event and is missed")
        code = sa.main(["events", "--soak", str(self.root / "s"), "--events", str(self.root / "e.txt"), "--watch", str(self.root / "w"), "--offset", "400"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
