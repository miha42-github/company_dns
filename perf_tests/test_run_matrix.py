"""Unit tests for the pure parts of run_matrix.py. Run: python3 -m unittest perf_tests/test_run_matrix.py"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_matrix as rm  # noqa: E402

try:
    import requests  # noqa: F401  (baseline.py needs it; the report virtual environment does not have it)
    HAVE_REQUESTS = True
except ImportError:
    HAVE_REQUESTS = False


class Plan(unittest.TestCase):
    def test_rotation_gives_every_image_every_position(self):
        self.assertEqual(rm.rotate(["a", "b", "c"], 0), ["a", "b", "c"])
        self.assertEqual(rm.rotate(["a", "b", "c"], 1), ["b", "c", "a"])
        self.assertEqual(rm.rotate(["a", "b", "c"], 4), ["b", "c", "a"], "wraps")
        self.assertEqual(rm.rotate([], 3), [])

    def test_plan_is_regime_then_repeat_then_rotated_images(self):
        p = rm.plan(["v3", "lean", "small"], ["limited", "headroom"], 3)
        self.assertEqual(len(p), 18)
        self.assertEqual(p[:3], [("limited", 1, "v3"), ("limited", 1, "lean"), ("limited", 1, "small")])
        self.assertEqual(p[3:6], [("limited", 2, "lean"), ("limited", 2, "small"), ("limited", 2, "v3")])
        self.assertEqual({img for _, _, img in p[:9]}, {"v3", "lean", "small"})
        first_places = {img: [i for i, (_, k, im) in enumerate(p[:9]) if im == img and k == k] for img in ("v3", "lean", "small")}
        self.assertTrue(all(len(v) == 3 for v in first_places.values()))


class Docker(unittest.TestCase):
    def test_parse_stats_in_each_unit(self):
        self.assertEqual(rm.parse_stats("0.53%,123.4MiB / 1GiB"), (0.53, 123.4))
        self.assertEqual(rm.parse_stats("12.5%, 2GiB / 64GiB"), (12.5, 2048.0))
        self.assertAlmostEqual(rm.parse_stats("1%,512KiB / 1GiB")[1], 0.5)
        self.assertIsNone(rm.parse_stats("--,-- / --"))
        self.assertIsNone(rm.parse_stats("Error response from daemon"))

    def test_baseline_command_per_phase(self):
        kw = dict(auth="perf:t", label="V4", repeat=3, timeout=120, levels=[1, 4])
        cold = rm.baseline_command("py", "http://x", Path("/o/c.json"), kind="cold", **kw)
        self.assertIn("--skip-concurrency", cold)
        self.assertNotIn("--skip-sequential", cold)
        self.assertEqual(cold[cold.index("--auth") + 1], "perf:t")
        conc = rm.baseline_command("py", "http://x", Path("/o/k.json"), kind="concurrency", **kw)
        self.assertIn("--skip-sequential", conc)
        self.assertIn("--record-incorrect", conc, "a wrong answer from one service is counted, not allowed to stop the matrix")
        self.assertEqual(conc[conc.index("--concurrency") + 1:], ["1", "4"])
        v3 = rm.baseline_command("py", "http://x", Path("/o/c.json"), kind="warm", **{**kw, "auth": None})
        self.assertNotIn("--auth", v3, "V3 is called without a credential")


class ColdPass(unittest.TestCase):
    def test_a_cold_command_can_be_limited_to_one_route(self):
        cmd = rm.baseline_command("py", "http://x", Path("/o/c.json"), kind="cold", auth=None, label="L", repeat=1, timeout=1, levels=[1], endpoint="wikipedia_firmographics")
        self.assertEqual(cmd[cmd.index("--endpoints") + 1], "wikipedia_firmographics")
        self.assertIn("--skip-concurrency", cmd)
        warm = rm.baseline_command("py", "http://x", Path("/o/w.json"), kind="warm", auth=None, label="L", repeat=1, timeout=1, levels=[1])
        self.assertNotIn("--endpoints", warm, "the warm pass runs every route")

    def test_single_route_passes_merge_into_one_report(self):
        a = {"base_url": "u", "sequential_results": [{"endpoint_key": "a"}]}
        b = {"base_url": "u", "sequential_results": [{"endpoint_key": "b"}, {"endpoint_key": "b"}]}
        m = rm.merge_sequential([a, b])
        self.assertEqual([r["endpoint_key"] for r in m["sequential_results"]], ["a", "b", "b"])
        self.assertEqual(m["base_url"], "u")
        self.assertEqual(len(a["sequential_results"]), 1, "the inputs are not modified")

    @unittest.skipUnless(HAVE_REQUESTS, "baseline.py needs the requests package")
    def test_the_route_keys_come_from_baseline_in_its_order(self):
        keys = rm.endpoint_keys()
        self.assertIn("wikipedia_firmographics", keys)
        self.assertIn("merged_firmographics", keys)
        self.assertEqual(len(keys), len(set(keys)))


class Resume(unittest.TestCase):
    def test_a_run_is_done_only_when_every_phase_file_exists(self):
        with tempfile.TemporaryDirectory() as t:
            d = rm.run_dir(Path(t), "limited", "v3", 1)
            d.mkdir(parents=True)
            self.assertFalse(rm.run_done(d))
            for n in ("sequential-cold.json", "sequential-warm.json", "concurrency.json"):
                (d / n).write_text("{}")
            self.assertFalse(rm.run_done(d), "container.json is written last, so a half run is redone")
            (d / "container.json").write_text("{}")
            self.assertTrue(rm.run_done(d))


if __name__ == "__main__":
    unittest.main()
