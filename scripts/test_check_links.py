"""Tests for scripts/check_links.py. Run: python3 scripts/test_check_links.py"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_links as cl  # noqa: E402


class Links(unittest.TestCase):
    def test_a_missing_target_is_found_and_the_rest_are_not(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.md").write_text("[ok](b.md) [anchor](b.md#x) [web](https://example.org) [page](#top) [gone](missing.md)\n```\n[in a block](nowhere.md)\n```\n[also gone](sub/none.md)\n")
            (root / "b.md").write_text("x")
            found = cl.broken_links(str(root / "a.md"))
            self.assertEqual([(n, t) for _, n, t in found], [(1, "missing.md"), (5, "sub/none.md")])

    def test_the_repository_has_no_broken_links(self):
        self.assertEqual(cl.main([]), 0)


if __name__ == "__main__":
    unittest.main()
