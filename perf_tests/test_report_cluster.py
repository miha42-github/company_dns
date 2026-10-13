"""Tests for report_cluster.py's numbers (not the drawing). Run: python3 perf_tests/test_report_cluster.py

They run against the committed result files, so a change to the data or to the arithmetic that moves a number in docs/performance-report.md shows up here.
"""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import report_cluster as rc  # noqa: E402

ROOT = HERE.parent
SIZING = json.loads((ROOT / "docs/results/2026-10-12-cluster/sizing.json").read_text())
SOAK = ROOT / "docs/results/2026-10-12-soak"


class Numbers(unittest.TestCase):
    def test_config_names(self):
        self.assertEqual((rc.cores_of("12x1000m/1Gi"), rc.pods_of("12x1000m/1Gi")), (12.0, 12))
        self.assertEqual(rc.cores_of("3x4000m/4Gi"), 12.0)

    def test_best_sustained_needs_the_p95_bar(self):
        rows = [{"n": 8, "rps": 50, "p95_ms": 200}, {"n": 16, "rps": 90, "p95_ms": 1500}]
        self.assertEqual(rc.best_sustained(rows)["rps"], 50)
        self.assertIsNone(rc.best_sustained([{"n": 8, "rps": 50, "p95_ms": 1500}]))

    def test_the_twelve_core_comparison_is_what_the_report_says(self):
        s = rc.sizing_summary(SIZING)
        self.assertEqual(s["twelve_core_embedding"], {"3x4000m/4Gi": 76.2, "6x2000m/2Gi": 139.5, "12x1000m/1Gi": 230.5})
        self.assertAlmostEqual(s["embedding_ratio"], 3.02, places=2)
        self.assertAlmostEqual(s["lookups_ratio"], 1.05, places=2)

    def test_lookups_scale_with_pods_at_about_76_more_each(self):
        s = rc.sizing_summary(SIZING)
        self.assertEqual([v["rps"] for v in s["scaling"].values()], [1261.6, 1600.1, 1873.0])
        self.assertAlmostEqual(s["per_pod"], 76.4, places=1)
        self.assertTrue(0.83 < min(s["utilisation"].values()) < max(s["utilisation"].values()) < 0.91)

    def test_the_soak_numbers(self):
        k = rc.soak_summary(rc.read_soak(SOAK / "windows.csv"))
        self.assertEqual((k["windows"], k["requests"], k["errors"], k["rate_limited"]), (1440, 5181863, 0, 0))
        self.assertEqual((k["canaries_ok"], k["canaries_total"], k["windows_missed"]), (7200, 7200, 0))
        self.assertAlmostEqual(k["hours"], 24.36, places=2)
        self.assertEqual((round(k["p95_min"], 1), round(k["p95_max"], 1)), (109.7, 125.8))
        self.assertEqual(len(k["hourly_p95"]), 24)
        self.assertLess(abs(k["last_quarter_p95"] - k["first_quarter_p95"]), 3.0, "no drift")

    def test_the_committed_soak_copy_names_no_person(self):
        for f in ("summary.md", "meta.json", "windows.csv"):
            self.assertNotIn("john", (SOAK / f).read_text().lower(), f)

    def test_the_summary_in_the_repo_agrees_with_the_data(self):
        k = rc.soak_summary(rc.read_soak(SOAK / "windows.csv"))
        text = (SOAK / "summary.md").read_text()
        self.assertIn(f"| requests | {k['requests']} |", text)
        self.assertIn("# Soak test: PASS", text)


if __name__ == "__main__":
    unittest.main()
