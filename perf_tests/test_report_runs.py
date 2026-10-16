"""Tests for report_runs.py's numbers (and, where matplotlib is installed, that the pictures draw). Run: python3 perf_tests/test_report_runs.py

The rollout numbers are checked against the committed results of the two rollout runs, so a change to the arithmetic that moves a number the report quotes shows up here.
"""
import statistics
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

    def test_the_ceiling_numbers_from_the_committed_run(self):
        import soak_analyze as sa
        levels = ce.read_levels(ROOT / "docs/results/2026-10-14-ceiling/merged")
        joined, note = ce.join_watch(levels, sa.read_watch(ROOT / "docs/results/2026-10-14-ceiling/watch-staging"))
        f = rr.ceiling_findings(levels, joined, 20.0)
        self.assertAlmostEqual(f["peak"]["rps"], 2144.7, delta=0.5)
        self.assertEqual((f["best"]["level"], f["plateau"]["level"], f["errors"], f["restarts"]), (512, 768, 0, 0))
        self.assertEqual(f["first_low_ready"]["level"], 3072)
        self.assertIn("shifted by -4", note)

    def test_a_run_with_no_step_inside_the_bar_has_no_best_step(self):
        levels = [lv(192, 284, 1987), lv(384, 284, 3201), lv(768, 286, 4999)]
        joined = [jn(192, 284, 19.7), jn(384, 284, 19.8), jn(768, 286, 19.8)]
        f = rr.ceiling_findings(levels, joined, 20.0)
        self.assertIsNone(f["best"])
        self.assertEqual(f["plateau"]["level"], 192)

    def test_routes_peak_cost_per_request_and_the_mix_predicted_from_them(self):
        runs = [("similarity", [lv(192, 800, 700)]), ("global", [lv(192, 280, 2000)]), ("hybrid", [lv(192, 200, 2600)]), ("head", [lv(48, 330, 400)])]
        f = rr.route_findings(runs, 20)
        self.assertAlmostEqual(f["routes"]["similarity"]["per_pod"], 40.0)
        self.assertAlmostEqual(f["routes"]["hybrid"]["ms_per_request"], 100.0)
        self.assertAlmostEqual(f["predicted_mix"], 1 / (0.4 / 800 + 0.3 / 280 + 0.3 / 200), places=6)
        self.assertEqual(f["measured_mix"], 330)
        self.assertIsNone(rr.route_findings(runs[:2], 20)["predicted_mix"], "no prediction without all three routes and the mix")

    def test_the_real_two_address_probe_looks_like_a_shared_allowance(self):
        runs = [(n, rr.read_limit_run(ROOT / "docs/results/2026-10-14-limit" / n)) for n in ("studio", "laptop")]
        f = rr.limit_findings(runs, 6000)
        self.assertEqual(f["names"], ["studio", "laptop"])
        self.assertAlmostEqual(f["sustained_total"], 200.0, delta=3)
        self.assertLess(f["correlation"], -0.9)
        self.assertTrue(f["shared"])
        self.assertEqual((f["burst_each"]), [707, 518])

    def test_independent_addresses_are_not_called_shared(self):
        def run(rates, burst=600):
            ps = [{"second": i, "ok": burst if i == 0 else r, "limited": 5, "errors": 0} for i, r in enumerate(rates)] + [{"second": len(rates), "ok": 0, "limited": 0, "errors": 0}]
            return {"ok": sum(p["ok"] for p in ps), "burst": burst, "sustained_per_second": float(statistics.median(rates[10:])), "per_second": ps}
        a = [101, 99, 100, 102, 98] * 12
        b = [100, 103, 97, 99, 101] * 12
        f = rr.limit_findings([("a", run(a)), ("b", run(b))], 6000)
        self.assertFalse(f["shared"], "each got its own 100 a second")
        self.assertAlmostEqual(f["sustained_total"], 200, delta=5)

    def test_an_address_that_only_saw_errors_is_left_out(self):
        failed = {"ok": 0, "burst": None, "sustained_per_second": 0.0, "per_second": [{"second": 0, "ok": 0, "limited": 0, "errors": 5}, {"second": 1, "ok": 0, "limited": 0, "errors": 0}]}
        good = rr.read_limit_run(ROOT / "docs/results/2026-10-14-limit/studio")
        f = rr.limit_findings([("mini", failed), ("studio", good)], 6000)
        self.assertEqual(f["names"], ["studio"])


@unittest.skipUnless(HAVE_PLOT, "matplotlib is not installed (use perf_tests/.venv)")
class Drawing(unittest.TestCase):
    def test_the_rollout_pictures_draw(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            self.assertEqual(rr.main(["rollout", str(R13), str(R14), "--out", d, "--zoom", "restart all pods"]), 0)
            self.assertTrue((out / "r1-2026-10-13-rollout.png").stat().st_size > 20000)
            self.assertTrue((out / "r2-2026-10-14-shutdown-zoom.png").exists())
            self.assertFalse((out / "r2-2026-10-13-rollout-zoom.png").exists(), "no change by that name in the first run")

    def test_the_ceiling_and_limit_pictures_draw_from_the_committed_runs(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            self.assertEqual(rr.main(["ceiling", "--run", str(ROOT / "docs/results/2026-10-14-ceiling/merged"), "--watch", str(ROOT / "docs/results/2026-10-14-ceiling/watch-staging"), "--out", d]), 0)
            self.assertTrue((out / "k1-ceiling.png").stat().st_size > 20000)
            self.assertEqual(rr.main(["limit", str(ROOT / "docs/results/2026-10-14-limit/studio"), str(ROOT / "docs/results/2026-10-14-limit/laptop"), "--out", d]), 0)
            self.assertTrue((out / "l1-limit-per-address.png").stat().st_size > 20000)

    def test_the_semantic_route_pictures_draw_from_the_committed_runs(self):
        base = ROOT / "docs/results/2026-10-16-semantic"
        if not base.exists():
            self.skipTest("the 16 October results are not in this checkout")
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            for name in ("global", "similarity"):
                self.assertEqual(rr.main(["ceiling", "--run", str(base / name / "merged"), "--watch", str(base / "watch-staging"), "--out", d, "--name", name]), 0)
                self.assertTrue((out / f"k1-{name}.png").stat().st_size > 20000)
            self.assertEqual(rr.main(["routes", *[str(base / n / "merged") for n in ("similarity", "global", "hybrid", "head")], "--out", d]), 0)
            self.assertTrue((out / "k2-routes.png").stat().st_size > 20000)


if __name__ == "__main__":
    unittest.main()
