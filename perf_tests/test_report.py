"""Tests for report.py and the pure parts of the figure tool. Run with the report venv for the figure tests:
   perf_tests/.venv/bin/python -m unittest perf_tests/test_report.py
Without matplotlib the figure tests are skipped and the title and phrase tests still run."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report as rp  # noqa: E402
import report_data as rd  # noqa: E402

ROUTES = {"health": "control", "sic_lookup": "control", "edgar_ciks": "control", "edgar_detail": "external-io",
          "edgar_firmographics_by_cik": "external-io", "wikipedia_firmographics": "external-io", "merged_firmographics": "external-io"}


def seq(scale, status=200, error=None):
    out = []
    for r, cat in ROUTES.items():
        for i in range(10 if cat == "external-io" or r == "edgar_ciks" else 1):
            out.append({"endpoint_key": r, "category": cat, "company_key": f"c{i}", "url": "/x", "status_code": status, "latency_ms": scale * (1 + i / 20) * (3 if cat == "external-io" else 1),
                        "error": error, "mode": "sequential", "concurrency_level": 1, "run_index": 0})
    return {"sequential_results": out}


def conc(scale, levels=(1, 4, 8)):
    out = []
    for r in ROUTES:
        for n in levels:
            for k in range(n):
                out.append({"endpoint_key": r, "category": "x", "company_key": "c", "url": "/x", "status_code": 200, "latency_ms": scale * (1 + 0.3 * n), "error": None,
                            "mode": "concurrent", "concurrency_level": n, "run_index": 0})
    return {"concurrency_results": out}


def make_matrix(root: Path, repeats=3):
    for img, scale in (("v3", 10.0), ("lean", 4.0), ("small", 4.5)):
        for k in range(1, repeats + 1):
            d = root / "raw" / "limited" / img / f"run{k}"
            d.mkdir(parents=True)
            (d / "sequential-cold.json").write_text(json.dumps(seq(scale * (1 + 0.02 * k))))
            (d / "sequential-warm.json").write_text(json.dumps(seq(scale * (0.3 if img != "v3" else 1))))
            (d / "concurrency.json").write_text(json.dumps(conc(scale)))
            (d / "container.json").write_text(json.dumps({"time_to_healthy_s": 2.0 + k, "limits": {"cpus": "0.5", "memory": "1g"}}))
            (d / "resources.csv").write_text("t_seconds,cpu_percent,mem_mib\n" + "".join(f"{i},{20 + i % 9},{200 + i % 4}\n" for i in range(30)))
    (root / "manifest.json").write_text(json.dumps({"host": {"hostname": "testhost", "system": "Linux x86_64", "cpus": 32, "git_commit": "abc1234"},
                                                    "images": {"v3": "r/v3:1", "lean": "v4:lean", "small": "v4:small"}, "started": "2026-10-10T00:00:00",
                                                    "regimes": {"limited": ["0.5", "1g"], "headroom": ["16", "64g"]},
                                                    "image_facts": {"v3": {"present": True, "size_bytes": 3e8}, "lean": {"present": True, "size_bytes": 5e8, "binary_bytes": 9e7, "onnx_library_bytes": 2.5e7},
                                                                    "small": {"present": True, "size_bytes": 4.5e8, "binary_bytes": 5.6e7, "onnx_library_bytes": 2.5e7}}}))
    (root / "specs").mkdir()
    (root / "specs" / "v3-openapi.json").write_text(json.dumps({"paths": {"/V3.0/na/sic/code/{sic_no}": {}, "/V3.0/uk/sic/{c}": {}}}))
    (root / "specs" / "v4-openapi.json").write_text(json.dumps({"paths": {"/V3.0/na/sic/code/{code}": {}, "/V4.0/global/sic/map": {"post": {"tags": ["Map (V4.0)"]}}}}))
    (root / "parity").mkdir()
    (root / "parity" / "lean.json").write_text(json.dumps([{"name": "us_code_3571", "verdict": "IDENTICAL"}, {"name": "japan_desc_food", "verdict": "DIFFERENT"}, {"name": "edgar_firmo_320193", "verdict": "SAME SHAPE"}]))
    (root / "suite").mkdir()
    (root / "suite" / "lean.json").write_text(json.dumps({"results": [{"id": "test_smoke.Smoke.test_health", "status": "passed"}, {"id": "test_contract.T.t", "status": "passed"}]}))


class Phrases(unittest.TestCase):
    def test_compare_phrase(self):
        self.assertEqual(rp.compare_phrase(100, 25), "V4 is 4.0x faster than V3")
        self.assertEqual(rp.compare_phrase(25, 100), "V4 is 4.0x slower than V3")
        self.assertIn("level with V3", rp.compare_phrase(741, 735))
        self.assertEqual(rp.compare_phrase(10, 0), "no comparison")

    def test_latency_title_states_the_finding_from_the_counts(self):
        t = rp.latency_title({"improved": 7, "no difference": 0, "regression": 0}, "cold", "production limits")
        self.assertIn("faster than V3 on all 7 routes", t)
        t = rp.latency_title({"improved": 4, "no difference": 2, "regression": 0}, "cold", "production limits")
        self.assertIn("faster on 4 of 6 routes and level on 2", t)
        t = rp.latency_title({"improved": 4, "no difference": 1, "regression": 1}, "warm", "headroom")
        self.assertIn("slower than V3 on 1 of 6 routes", t)
        self.assertIn("indicative: 1 run", rp.latency_title({"improved": 1}, "cold", "x", runs=1))
        self.assertNotIn("indicative", rp.latency_title({"improved": 1}, "cold", "x", runs=3))

    def test_concurrency_title_keeps_local_routes_and_cached_upstream_routes_apart(self):
        t = rp.concurrency_title(4.0, 1500.0, 16, "x")
        self.assertIn("4.0x faster on routes with no upstream call", t)
        self.assertIn("1500x faster on routes that call Wikipedia and SEC, where V4 answers repeats from its cache", t)
        self.assertIn("2.0x slower on routes with no upstream call", rp.concurrency_title(0.5, float("nan"), 16, "x"))
        self.assertIn("about the same speed", rp.concurrency_title(1.02, float("nan"), 16, "x"))
        self.assertIn("no comparable data", rp.concurrency_title(float("nan"), float("nan"), 16, "x"))

    def test_throughput_title(self):
        t = rp.throughput_title(5.0, 400.0, 3.4, 16, "x")
        self.assertIn("5.0x more requests per second on routes with no upstream call", t)
        self.assertIn("400x more on routes that call Wikipedia and SEC", t)
        self.assertIn("using 3.4x less average CPU", t)
        self.assertIn("2.0x fewer requests per second", rp.throughput_title(0.5, float("nan"), 1.0, 16, "x"))
        self.assertIn("using 2.0x more average CPU", rp.throughput_title(2.0, float("nan"), 0.5, 16, "x"))

    def test_footprint_title_says_what_is_better_and_what_is_worse(self):
        t = rp.footprint_title({"size_bytes": 1.1e9, "healthy_s": 3.0, "peak_mem": 171.0}, {"size_bytes": 5.3e8, "healthy_s": 1.5, "peak_mem": 338.0})
        self.assertIn("its image is 2.1x smaller", t)
        self.assertIn("it starts 2.0x faster", t)
        self.assertIn(", but its peak memory is 2.0x higher (338 against 171 MiB)", t)
        self.assertEqual(rp.footprint_title({"size_bytes": 100, "healthy_s": 1, "peak_mem": 10}, {"size_bytes": 101, "healthy_s": 1, "peak_mem": 10}), "V4 lean and V3 have a similar footprint")
        self.assertTrue(rp.footprint_title({"size_bytes": 100, "peak_mem": 100}, {"size_bytes": 300, "peak_mem": 300}).startswith("V4 lean: its image is 3.0x larger"))

    def test_family(self):
        self.assertEqual(rp.family("japan_desc_food"), "Japan SIC")
        self.assertEqual(rp.family("us_code_3571"), "US SIC")
        self.assertEqual(rp.family("merged_appleinc"), "Merged")


class PairedVerdicts(unittest.TestCase):
    def test_a_single_run_is_judged_on_that_run(self):
        a = {"r": {"median": [100.0], "k": [1]}}
        b = {"r": {"median": [50.0], "k": [1]}}
        self.assertEqual(rd.paired_verdicts(a, b), {"r": "improved"})

    def test_repeats_are_paired_by_run_number(self):
        a = {"r": {"median": [100.0, 100.0, 100.0], "k": [1, 2, 3]}}
        b = {"r": {"median": [120.0, 130.0, 90.0], "k": [1, 2, 3]}}
        self.assertEqual(rd.paired_verdicts(a, b), {"r": "regression"})
        c = {"r": {"median": [120.0, 90.0, 90.0], "k": [1, 2, 3]}}
        self.assertEqual(rd.paired_verdicts(a, c), {"r": "no difference"})


@unittest.skipIf(rp.plt is None, "matplotlib is not installed (use perf_tests/.venv)")
class Figures(unittest.TestCase):
    def test_every_figure_is_drawn_from_a_full_matrix_and_the_index_lists_them(self):
        with tempfile.TemporaryDirectory() as d:
            root, out = Path(d) / "m", Path(d) / "out"
            make_matrix(root)
            ctx = rp.build(root, out, "png", True)
            names = {f for f, _, _ in ctx.made}
            for want in ("p1-latency-cold-limited.png", "p2-latency-warm-limited.png", "p3-concurrency-limited.png", "p4-throughput-cpu-limited.png", "p5-footprint.png",
                         "p6-reliability.png", "p7-why.png", "f1-route-coverage.png", "f2-parity.png", "f3-differences.png", "f4-tests.png", "f5-what-v4-adds.png"):
                self.assertIn(want, names)
                self.assertGreater((out / want).stat().st_size, 15_000, want)
            self.assertEqual(ctx.skipped, [])
            idx = (out / "index.md").read_text()
            self.assertIn("p1-latency-cold-limited.png", idx)
            self.assertIn("DRAFT", idx)
            titles = {f: t for f, t, _ in ctx.made}
            self.assertIn("faster than V3 on all 7 routes", titles["p1-latency-cold-limited.png"])
            self.assertIn("serves 1 of V3's 2 routes", titles["f1-route-coverage.png"].replace("V4 serves 1 of V3's 2", "serves 1 of V3's 2"))

    def test_figures_without_their_inputs_are_skipped_and_said_so(self):
        with tempfile.TemporaryDirectory() as d:
            root, out = Path(d) / "m", Path(d) / "out"
            make_matrix(root, repeats=1)
            for p in ("specs", "parity", "suite"):
                import shutil
                shutil.rmtree(root / p)
            ctx = rp.build(root, out, "png", False)
            skipped = {n for n, _ in ctx.skipped}
            self.assertTrue({"f1-route-coverage", "f2-parity", "f4-tests", "f5-what-v4-adds"} <= skipped)
            self.assertIn("Not drawn", (out / "index.md").read_text())

    def test_a_matrix_without_v3_does_not_draw_comparisons(self):
        with tempfile.TemporaryDirectory() as d:
            root, out = Path(d) / "m", Path(d) / "out"
            make_matrix(root)
            import shutil
            shutil.rmtree(root / "raw" / "limited" / "v3")
            ctx = rp.build(root, out, "png", False)
            self.assertIn("p1-latency-cold-limited", {n for n, _ in ctx.skipped})

    def test_jpg_output(self):
        with tempfile.TemporaryDirectory() as d:
            root, out = Path(d) / "m", Path(d) / "out"
            make_matrix(root, repeats=2)
            ctx = rp.build(root, out, "jpg", False)
            self.assertTrue((out / "p1-latency-cold-limited.jpg").exists())


if __name__ == "__main__":
    unittest.main()
