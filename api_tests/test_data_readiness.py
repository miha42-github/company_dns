"""L2 data readiness: the data the server needs is actually loaded, and complete enough.

These are the checks that would have caught a missing EDGAR catalog (every company came back Wikipedia-only) or a classification
file that lost levels. Counts are lower bounds, because the data files are refreshed. A whole system is counted by searching its
class level with `%` (a match-all pattern, the way V3's substring match works).
"""
import re
import unittest
from urllib.parse import quote

from common import NETWORK, ServerTestCase, get

ALL = quote("%")


class ClassificationSystems(ServerTestCase):
    def count(self, path):
        status, body, _ = get(path)
        self.assertEqual(status, 200, path)
        return len(body["data"])

    def test_each_system_has_at_least_the_classes_it_shipped_with(self):
        for name, path, minimum in (
            ("US SIC", f"/V4.0/na/sic/code/{ALL}", 1005), ("EU NACE Rev. 2", f"/V4.0/eu/sic/class/{ALL}", 615),
            ("ISIC Rev. 4", f"/V4.0/international/sic/class/{ALL}", 419), ("Japan SIC (JSIC Rev. 13)", f"/V4.0/japan/sic/industry_group/{ALL}", 1460),
        ):
            with self.subTest(system=name):
                self.assertGreaterEqual(self.count(path), minimum)

    def test_the_hierarchies_are_complete(self):
        for name, path, minimum in (("EU NACE sections", f"/V4.0/eu/sic/section/{ALL}", 21), ("ISIC sections", f"/V4.0/international/sic/section/{ALL}", 21),
                                    ("Japan divisions", f"/V4.0/japan/sic/division/{ALL}", 20), ("EU NACE divisions", f"/V4.0/eu/sic/division/{ALL}", 88),
                                    ("ISIC divisions", f"/V4.0/international/sic/division/{ALL}", 88)):
            with self.subTest(level=name):
                self.assertGreaterEqual(self.count(path), minimum)

    def test_a_class_knows_its_parents(self):
        _, body, _ = get("/V4.0/eu/sic/class/25.91")
        row = body["data"][0]
        self.assertEqual((row["section_id"], row["division_id"], row["group_id"]), ("C", "25", "25.9"))
        _, body, _ = get("/V4.0/japan/sic/industry_group/0911")
        row = body["data"][0]
        self.assertEqual((row["section_id"], row["division_id"], row["group_id"]), ("E", "09", "091"))

    def test_global_search_reaches_all_four_systems(self):
        _, body, _ = get("/V4.0/global/sic/description/manufactur")
        self.assertEqual(sorted({h["source_type"] for h in body["data"]}), ["EU NACE", "ISIC", "Japan SIC", "US SIC"])

    def test_the_embedding_model_is_loaded(self):
        status, body, _ = get("/V4.0/na/sic/similarity/" + quote("software for banks") + "?k=3")
        self.assertEqual((status, len(body["data"])), (200, 3))


class UsDivisionNarratives(ServerTestCase):
    """Every US SIC section (A-J) has its narrative, from the data file's `section_full_desc` column (docs/plans/v4-data-gaps.md)."""

    LENGTHS = {"A": 2649, "B": 1901, "C": 5549, "D": 4981, "E": 1970, "F": 3161, "G": 3311, "H": 699, "I": 588, "J": 510}

    def test_each_division_has_its_trimmed_narrative(self):
        for letter, length in self.LENGTHS.items():
            with self.subTest(division=letter):
                status, body, _ = get(f"/V3.0/na/sic/division/{letter}")
                self.assertEqual(status, 200)
                text = body["data"]["division"][letter]["full_description"]
                self.assertEqual(text, text.strip(), "no leading or trailing whitespace")
                self.assertEqual(len(text), length)


class EdgarCatalog(ServerTestCase):
    def filings(self, name):
        status, body, _ = get("/V4.0/na/companies/edgar/summary/" + quote(name))
        self.assertEqual(status, 200, f"{name}: the EDGAR catalog must find it")
        keys = [k for c in body["data"]["companies"].values() for k in c["forms"]]
        return [tuple(int(x) for x in re.match(r"(\d{4})-(\d{1,2})-", k).groups()) for k in keys]

    def test_the_catalog_is_loaded_and_finds_known_companies(self):
        status, body, _ = get("/V4.0/na/companies/edgar/ciks/Apple")
        self.assertEqual(status, 200)
        self.assertEqual(str(body["data"].get("Apple Inc.")), "320193")

    def test_it_spans_the_expected_quarters_for_known_filers(self):
        for name in ("Apple Inc.", "Microsoft", "International Business Machines"):
            with self.subTest(company=name):
                dated = self.filings(name)
                quarters = {(y, (m - 1) // 3) for y, m in dated}
                self.assertGreaterEqual(len(dated), 6, "the catalog is a rolling two-year window")
                self.assertGreaterEqual(len({y for y, _ in dated}), 2)
                self.assertGreaterEqual(len(quarters), 5)

    @unittest.skipUnless(NETWORK, "calls Wikipedia / SEC; set API_TESTS_NETWORK=1")
    def test_merged_firmographics_finds_edgar_data_for_known_companies(self):
        for name in ("Apple Inc.", "Microsoft", "IBM"):
            with self.subTest(company=name):
                status, body, _ = get("/V4.0/global/company/merged/firmographics/" + quote(name))
                self.assertEqual(status, 200)
                self.assertIn("edgar", body["data"]["source"], f"{name}: merged answer came from {body['data']['source']}")


if __name__ == "__main__":
    unittest.main()
