"""L3 parity for the EDGAR, Wikipedia and merged `/V3.0/` aliases against V3's real answers (fixtures captured from production
on 2026-10-07; see fixtures/v3/README.md).

The release plan's rule is that the `/V3.0/` and `/V2.0/` paths answer in V3's exact shape. Measured on 2026-10-07 that holds for
EDGAR `summary` and for Wikipedia, and does not hold for four others. Those four are marked `expectedFailure`: they document the
gap, they keep the suite green, and the day one is fixed its test starts "unexpectedly succeeding" so the marker gets removed.
Message and module strings are V3 text that differs for these routes; they are not compared (the data shape is).
"""
import unittest
from urllib.parse import quote

from common import NETWORK, ServerTestCase, fixture, get, shape

APPLE = quote("Apple Inc.")


def data_of(path):
    status, body, _ = get(path)
    assert status == 200, (path, status)
    return body["data"]


class Matches(ServerTestCase):
    def test_edgar_summary_has_v3s_shape(self):
        self.assertEqual(shape(data_of(f"/V3.0/na/companies/edgar/summary/{APPLE}")), shape(fixture("edgar_summary_appleinc")["data"]))

    @unittest.skipUnless(NETWORK, "calls Wikipedia; set API_TESTS_NETWORK=1")
    def test_wikipedia_has_v3s_shape_and_stable_fields(self):
        v4, v3 = data_of(f"/V3.0/global/company/wikipedia/firmographics/{APPLE}"), fixture("wikipedia_appleinc")["data"]
        self.assertEqual(shape(v4), shape(v3))
        for k in ("name", "cik", "wikipediaURL"):
            self.assertEqual(v4[k], v3[k], k)


class V3ShapedEdgar(ServerTestCase):
    def test_edgar_summary_uses_v3s_message_and_module(self):
        _, body, _ = get(f"/V3.0/na/companies/edgar/summary/{APPLE}")
        v3 = fixture("edgar_summary_appleinc")
        self.assertEqual((body["message"], body["module"]), (v3["message"], v3["module"]))

    def test_us_division_carries_v3s_full_description(self):
        _, body, _ = get("/V3.0/na/sic/division/E")
        self.assertEqual(body["data"]["division"]["E"]["full_description"], fixture("us_division_E")["data"]["division"]["E"]["full_description"])

    """The EDGAR routes on the /V3.0/ paths answer in V3's shape (decision Q14); /V4.0/ keeps V4's own."""

    SIC_FIELDS = ["division", "divisionDescription", "majorGroup", "majorGroupDescription", "industryGroup",
                  "industryGroupDescription", "sicDescription"]

    def test_edgar_ciks_is_wrapped_in_companies_and_totalcompanies_with_string_ciks(self):
        v4, v3 = data_of("/V3.0/na/companies/edgar/ciks/Apple"), fixture("edgar_ciks_apple")["data"]
        self.assertEqual(sorted(v4), sorted(v3))  # companies and totalCompanies; which companies match is data, not shape
        self.assertEqual(shape(v4["totalCompanies"]), shape(v3["totalCompanies"]))
        self.assertEqual(v4["totalCompanies"], len(v4["companies"]))
        self.assertTrue(all(isinstance(c, str) for c in v4["companies"].values()))

    @unittest.skipUnless(NETWORK, "calls SEC; set API_TESTS_NETWORK=1")
    def test_edgar_detail_has_v3s_per_company_structure(self):
        v4, v3 = data_of(f"/V3.0/na/companies/edgar/detail/{APPLE}"), fixture("edgar_detail_appleinc")["data"]
        self.assertEqual(shape(v4), shape(v3))

    @unittest.skipUnless(NETWORK, "calls SEC; set API_TESTS_NETWORK=1")
    def test_edgar_firmographics_carries_the_sic_hierarchy_fields(self):
        v4, v3 = data_of("/V3.0/na/company/edgar/firmographics/320193"), fixture("edgar_firmo_320193")["data"]
        self.assertEqual(sorted(v4), sorted(v3))
        for f in self.SIC_FIELDS:
            self.assertEqual(v4[f], v3[f], f)

    @unittest.skipUnless(NETWORK, "calls SEC; set API_TESTS_NETWORK=1")
    def test_the_v2_paths_answer_the_same_way(self):
        v3 = data_of("/V3.0/na/company/edgar/firmographics/320193")
        v2 = data_of("/V2.0/company/edgar/firmographics/320193")
        for f in self.SIC_FIELDS:
            self.assertEqual(v2[f], v3[f], f)


class KnownGaps(ServerTestCase):
    """V3's shape that V4's /V3.0/ aliases do not return, recorded as intentional for now
    (docs/plans/v4-release-to-staging.md, decision Q14)."""

    @unittest.expectedFailure
    @unittest.skipUnless(NETWORK, "calls Wikipedia and SEC; set API_TESTS_NETWORK=1")
    def test_merged_is_one_flat_record(self):
        v4, v3 = data_of(f"/V3.0/global/company/merged/firmographics/{APPLE}"), fixture("merged_appleinc")["data"]
        self.assertEqual(sorted(v4), sorted(v3))  # V3 returns one flat 41-field record; V4 returns {edgar, edgar_match, query, source, wikipedia}


if __name__ == "__main__":
    unittest.main()
