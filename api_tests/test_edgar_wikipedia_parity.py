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


class KnownGaps(ServerTestCase):
    """V3's shape that V4's /V3.0/ aliases do not yet return. Each is a decision for the owner: build an adapter, or record the
    difference as intentional (see docs/plans/v4-release-to-staging.md, step 4)."""

    @unittest.expectedFailure
    def test_edgar_ciks_is_wrapped_in_companies_and_totalcompanies_with_string_ciks(self):
        v4, v3 = data_of("/V3.0/na/companies/edgar/ciks/Apple"), fixture("edgar_ciks_apple")["data"]
        self.assertEqual(shape(v4), shape(v3))  # V4 returns {name: cik} directly, and the cik as a number

    @unittest.expectedFailure
    @unittest.skipUnless(NETWORK, "calls SEC; set API_TESTS_NETWORK=1")
    def test_edgar_detail_has_v3s_per_company_structure(self):
        v4, v3 = data_of(f"/V3.0/na/companies/edgar/detail/{APPLE}"), fixture("edgar_detail_appleinc")["data"]
        self.assertEqual(shape(v4), shape(v3))  # V3 nests a response (code, data, message...) per company; V4 flattens the firmographics

    @unittest.expectedFailure
    @unittest.skipUnless(NETWORK, "calls SEC; set API_TESTS_NETWORK=1")
    def test_edgar_firmographics_carries_the_sic_hierarchy_fields(self):
        v4, v3 = data_of("/V3.0/na/company/edgar/firmographics/320193"), fixture("edgar_firmo_320193")["data"]
        self.assertEqual(sorted(v4), sorted(v3))  # V3 adds division, majorGroup, industryGroup and their descriptions

    @unittest.expectedFailure
    @unittest.skipUnless(NETWORK, "calls Wikipedia and SEC; set API_TESTS_NETWORK=1")
    def test_merged_is_one_flat_record(self):
        v4, v3 = data_of(f"/V3.0/global/company/merged/firmographics/{APPLE}"), fixture("merged_appleinc")["data"]
        self.assertEqual(sorted(v4), sorted(v3))  # V3 returns one flat 41-field record; V4 returns {edgar, edgar_match, query, source, wikipedia}


if __name__ == "__main__":
    unittest.main()
