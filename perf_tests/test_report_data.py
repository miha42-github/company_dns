"""Unit tests for report_data.py (standard library). Run: python3 -m unittest perf_tests/test_report_data.py"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_data as rd  # noqa: E402


def call(key, ms, status=200, error=None, level=1, run=0, mode="sequential", cat="control"):
    return {"endpoint_key": key, "category": cat, "company_key": "-", "url": "/x", "status_code": status, "latency_ms": ms,
            "error": error, "mode": mode, "concurrency_level": level, "run_index": run}


class Latency(unittest.TestCase):
    def test_median_p95_and_error_counts(self):
        seq = [call("a", v) for v in (10, 20, 30, 40, 100)] + [call("a", 5000, status=None, error="timeout")]
        s = rd.sequential_stats(seq)["a"]
        self.assertEqual((s["n"], s["ok"], s["errors"]), (6, 5, 1))
        self.assertEqual(s["median"], 35)
        self.assertGreater(s["p95"], 100)

    def test_concurrent_wall_time_is_the_slowest_call_and_speedup_compares_with_serial(self):
        seq = [call("a", 100), call("a", 100)]
        conc = [call("a", 120, level=4, run=0, mode="concurrent"), call("a", 150, level=4, run=0, mode="concurrent"),
                call("a", 130, level=4, run=0, mode="concurrent"), call("a", 110, level=4, run=0, mode="concurrent")]
        c = rd.concurrency_stats(conc, seq)[("a", 4)]
        self.assertEqual(c["wall_median"], 150)
        self.assertAlmostEqual(c["speedup"], 400 / 150)
        self.assertAlmostEqual(c["calls_per_second"], 4 / 0.150)

    def test_percentile_matches_the_baseline_tool(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from baseline import percentile
        for q in (0.5, 0.95):
            self.assertAlmostEqual(rd.percentile([1, 5, 9, 20, 300], q), percentile([1, 5, 9, 20, 300], q))


class RegressionRule(unittest.TestCase):
    def test_a_regression_needs_two_of_three_repeats_over_ten_percent(self):
        self.assertEqual(rd.regression_verdict([100, 100, 100], [115, 120, 100]), "regression")
        self.assertEqual(rd.regression_verdict([100, 100, 100], [115, 100, 100]), "no difference", "one bad repeat is noise")
        self.assertEqual(rd.regression_verdict([100, 100, 100], [109, 109, 109]), "no difference", "under the threshold")

    def test_improvement_mirrors_it(self):
        self.assertEqual(rd.regression_verdict([100, 100, 100], [50, 60, 100]), "improved")
        self.assertEqual(rd.regression_verdict([100, 100, 100], [50, 100, 100]), "no difference")

    def test_too_few_repeats_is_said_not_guessed(self):
        self.assertEqual(rd.regression_verdict([100], [50]), "not enough repeats")

    def test_spread(self):
        self.assertEqual(rd.spread([3, 1, 2]), {"median": 2, "min": 1, "max": 3, "n": 3})


class Coverage(unittest.TestCase):
    def test_served_excluded_missing_and_v4_only(self):
        v3 = {"paths": {"/V3.0/na/sic/code/{sic_no}": {}, "/V3.0/uk/sic/code/{c}": {}, "/V3.0/global/company/wikipedia/v1/firmographics/{n}": {}, "/V3.0/gone/{x}": {}}}
        v4 = {"paths": {"/V3.0/na/sic/code/{code}": {}, "/V4.0/global/sic/map": {}}}
        c = rd.route_coverage(v3, v4)
        self.assertEqual(c["served"], ["/V3.0/na/sic/code/{sic_no}"], "parameter names do not matter")
        self.assertEqual([p for p, _ in c["excluded"]], ["/V3.0/global/company/wikipedia/v1/firmographics/{n}", "/V3.0/uk/sic/code/{c}"])
        self.assertTrue(all(why for _, why in c["excluded"]))
        self.assertEqual(c["missing"], ["/V3.0/gone/{x}"], "a route that is neither served nor excluded is reported missing")
        self.assertEqual(c["v4_only"], ["/V4.0/global/sic/map"])


class Summaries(unittest.TestCase):
    def test_parity_counts_and_the_rows_to_explain(self):
        rows = [{"verdict": "IDENTICAL", "name": "a"}, {"verdict": "IDENTICAL", "name": "b"}, {"verdict": "DIFFERENT", "name": "c"}]
        s = rd.parity_summary(rows)
        self.assertEqual(s["counts"], {"IDENTICAL": 2, "DIFFERENT": 1})
        self.assertEqual([r["name"] for r in s["not_identical"]], ["c"])

    def test_suite_by_layer(self):
        rep = {"results": [
            {"id": "test_smoke.Smoke.test_health", "status": "passed"},
            {"id": "test_contract.Table.test_x", "status": "failed"},
            {"id": "test_edgar_wikipedia_parity.KnownGaps.test_m", "status": "expected_failure"},
            {"id": "setUpModule (test_limits_and_profiles)", "status": "skipped"},
            {"id": "test_v4_functions.Map.test_a", "status": "passed"},
        ]}
        s = rd.suite_by_layer(rep)
        self.assertEqual(s["L0 smoke"], {"passed": 1})
        self.assertEqual(s["L1 contract"], {"failed": 1})
        self.assertEqual(s["L3 parity"], {"expected_failure": 1})
        self.assertEqual(s["L5 limits and profiles"], {"skipped": 1})

    def test_resources(self):
        rows = [{"t": i, "cpu": 10.0 + i, "mem": 100.0 + (50 if i == 7 else 0)} for i in range(10)]
        s = rd.resource_summary(rows)
        self.assertEqual((s["idle_mem_mib"], s["peak_mem_mib"], s["peak_cpu"]), (100.0, 150.0, 19.0))
        self.assertEqual(rd.resource_summary([]), {})


class Matrix(unittest.TestCase):
    def test_reads_the_layout_the_harness_writes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run = root / "raw" / "limited" / "v3" / "run1"
            run.mkdir(parents=True)
            (run / "sequential-cold.json").write_text(json.dumps({"sequential_results": []}))
            (run / "resources.csv").write_text("t_seconds,cpu_percent,mem_mib\n0,5.0,100\n1,7.0,110\n")
            (root / "manifest.json").write_text(json.dumps({"host": "cafe-1"}))
            m = rd.load_matrix(root)
            self.assertEqual(m["manifest"]["host"], "cafe-1")
            r = m["runs"][("limited", "v3")][0]
            self.assertEqual((r["k"], r["cold"], r["warm"]), (1, {"sequential_results": []}, None))
            self.assertEqual(r["resources"][1], {"t": 1.0, "cpu": 7.0, "mem": 110.0})
            self.assertEqual(m["specs"], {"v3": None, "v4": None})


class RealFiles(unittest.TestCase):
    """If an earlier result file is in the repository, the aggregation must run on it."""

    def test_an_existing_report_aggregates(self):
        p = Path(__file__).resolve().parent / "results" / "v3-full-20260928.json"
        if not p.exists():
            self.skipTest("no stored result file")
        r = json.loads(p.read_text())
        seq = rd.sequential_stats(r["sequential_results"])
        self.assertIn("health", seq)
        self.assertTrue(rd.concurrency_stats(r["concurrency_results"], r["sequential_results"]))


if __name__ == "__main__":
    unittest.main()
