"""Tests for report_runs.py's numbers (and, where matplotlib is installed, that the pictures draw). Run: python3 perf_tests/test_report_runs.py

The rollout numbers are checked against the committed results of the two rollout runs, so a change to the arithmetic that moves a number the report quotes shows up here.
"""
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ceiling as ce  # noqa: E402
import report_runs as rr  # noqa: E402

ROOT = HERE.parent
R13 = ROOT / "docs/results/2026-10-13-rollout"
R14 = ROOT / "docs/results/2026-10-14-shutdown"
HAVE_PLOT = rr.plt is not None


class Rollouts(unittest.TestCase):
    def test_the_first_run_numbers(self):
        f = rr.rollout_findings(rr.load_rollout(R13))
        self.assertEqual((f["n_changes"], f["errors"], f["canary_bad"]), (3, 0, 0))
        self.assertAlmostEqual(f["baseline"], 96.0, delta=1.0)
        self.assertLess(f["worst_p95"] - f["baseline"], 6)
        self.assertEqual(f["max_terminating"], 20, "before the graceful shutdown all 20 old pods were stopping at once")
        self.assertTrue(f["all_pass"])

    def test_the_graceful_shutdown_run_numbers(self):
        f = rr.rollout_findings(rr.load_rollout(R14))
        self.assertEqual((f["n_changes"], f["errors"], f["requests"]), (5, 0, 236830))
        self.assertAlmostEqual(f["baseline"], 93.0, delta=1.0)
        self.assertEqual(f["max_terminating"], 8)
        self.assertEqual(f["min_ready_unscaled"], 18, "two pods lost at once")
        self.assertEqual(f["interval"], 5.0)
        self.assertTrue(f["all_pass"])

    def test_the_clock_alignment_is_the_one_the_analysis_reports(self):
        self.assertEqual(round(rr.load_rollout(R14)["shift"]), -2)


def lv(level, rps, p95, p50=100.0):
    return {"level": level, "machine_concurrency": level, "start_utc": "2027-01-15T08:00:00Z", "end_utc": "2027-01-15T08:00:30Z", "requests": 1000, "ok": 1000, "errors": 0, "rate_limited": 0, "rps": rps,
            "p50_ms": p50, "p95_ms": p95, "p99_ms": p95 * 1.2, "max_ms": p95 * 2, "error_rate": 0.0, "generator_cores": 1.0, "note": ""}


def jn(level, rps, cpu, ready=20, throttled=0.05):
    return {**lv(level, rps, 100.0), "cpu_median": cpu, "cpu_max": cpu + 1, "throttled_max": throttled, "mem_max": 170.0, "restarts": 0, "min_ready": ready, "oom": 0}


class Ceiling(unittest.TestCase):
    def test_the_plateau_the_best_step_and_the_pods_side(self):
        levels = [lv(256, 1756, 470), lv(512, 1931, 875), lv(768, 2066, 1140), lv(1024, 2061, 1550), lv(2048, 2145, 2722), lv(3072, 2080, 3623)]
        joined = [jn(256, 1756, 17.4), jn(512, 1931, 18.1), jn(768, 2066, 19.3), jn(1024, 2061, 19.2), jn(2048, 2145, 18.3), jn(3072, 2080, 19.3, ready=18)]
        f = rr.ceiling_findings(levels, joined, 20.0)
        self.assertEqual((f["peak"]["level"], f["plateau"]["level"], f["best"]["level"]), (2048, 768, 512), "the plateau is the first step within 5% of the peak")
        self.assertEqual(f["first_low_ready"]["level"], 3072)
        self.assertAlmostEqual(f["utilisation"], 19.3 / 20, places=2)
        self.assertEqual((f["errors"], f["restarts"]), (0, 0))

    def test_limit_findings(self):
        runs = [("a", {"sustained_per_second": 98.0, "burst": 540}), ("b", {"sustained_per_second": 101.0, "burst": 575}), ("c", {"sustained_per_second": 100.0, "burst": 560})]
        f = rr.limit_findings(runs, 6000)
        self.assertEqual((f["sustained_total"], f["burst_total"], f["expected_per_second"]), (299.0, 1675, 100.0))


@unittest.skipUnless(HAVE_PLOT, "matplotlib is not installed (use perf_tests/.venv)")
class Drawing(unittest.TestCase):
    def test_the_rollout_pictures_draw(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            self.assertEqual(rr.main(["rollout", str(R13), str(R14), "--out", d, "--zoom", "restart all pods"]), 0)
            self.assertTrue((out / "r1-2026-10-13-rollout.png").stat().st_size > 20000)
            self.assertTrue((out / "r2-2026-10-14-shutdown-zoom.png").exists())
            self.assertFalse((out / "r2-2026-10-13-rollout-zoom.png").exists(), "no change by that name in the first run")

    def test_the_ceiling_and_limit_pictures_draw(self):
        import csv
        import json
        import time
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            base = 1_800_000_000
            levels = [dict(lv(l, r, p), start_utc=ce.utc(base + 100 + 50 * i), end_utc=ce.utc(base + 130 + 50 * i)) for i, (l, r, p) in enumerate([(256, 1700, 400), (512, 1900, 800), (1024, 2050, 1500), (2048, 2100, 2700)])]
            (root / "run").mkdir()
            ce.write_levels(root / "run", levels)
            (root / "watch").mkdir()
            with open(root / "watch" / "watch.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["time_utc", "pods", "ready", "terminating", "not_ready", "restarts_total", "new_restarts", "oom_killed", "mem_mib_median", "mem_mib_max", "cpu_cores_used", "throttled_share", "nodes", "unreadable"])
                w.writeheader()
                for i in range(80):
                    t = base + 5 * i * 4 - 100 + 100 * 0
                    busy = base + 100 <= t - 0 <= base + 100 + 200
                    w.writerow({"time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)), "pods": 20, "ready": 20, "terminating": 0, "not_ready": 0, "restarts_total": 0, "new_restarts": 0, "oom_killed": 0,
                                "mem_mib_median": 160, "mem_mib_max": 170, "cpu_cores_used": 18.0 if busy else 0.3, "throttled_share": 0.05, "nodes": 2, "unreadable": 0})
            self.assertEqual(rr.main(["ceiling", "--run", str(root / "run"), "--watch", str(root / "watch"), "--out", str(root / "figs")]), 0)
            self.assertTrue((root / "figs" / "k1-ceiling.png").exists())
            for name in ("limit-a", "limit-b"):
                (root / name).mkdir()
                (root / name / "per_second.json").write_text(json.dumps({"burst": 560, "sustained_per_second": 100.0, "per_second": [{"second": s, "ok": 560 if s == 0 else 100, "limited": 5, "errors": 0} for s in range(30)]}))
            self.assertEqual(rr.main(["limit", str(root / "limit-a"), str(root / "limit-b"), "--out", str(root / "figs")]), 0)
            self.assertTrue((root / "figs" / "l1-limit-per-address.png").exists())


if __name__ == "__main__":
    unittest.main()
