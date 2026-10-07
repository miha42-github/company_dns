"""New E: the per-system SIC endpoints (EU NACE, ISIC, Japan), the V3-shaped US aliases, and the V2.0 aliases.

L1 contract (every endpoint answers in the right shape) and L3 parity (V3's real answers, fixtures captured from
production on 2026-10-07, are matched). Differences from V3 that are intentional are asserted as such, not skipped.
"""
import json
import unittest

from common import NETWORK, ServerTestCase, fixture, get

# (system, level, V3 path suffix, a query that matches, the key of V3's data dictionary)
LOOKUPS = [
    ("eu", "section", "eu/sic/section/A", "sections"),
    ("eu", "division", "eu/sic/division/25", "divisions"),
    ("eu", "group", "eu/sic/group/25.9", "groups"),
    ("eu", "class", "eu/sic/class/25.91", "classes"),
    ("eu", "description", "eu/sic/description/steel", "classes"),
    ("isic", "section", "international/sic/section/A", "sections"),
    ("isic", "division", "international/sic/division/25", "divisions"),
    ("isic", "group", "international/sic/group/259", "groups"),
    ("isic", "class", "international/sic/class/2591", "classes"),
    ("isic", "description", "international/sic/description/steel", "classes"),
    ("japan", "division", "japan/sic/division/E", "divisions"),
    ("japan", "major_group", "japan/sic/major_group/09", "major_groups"),
    ("japan", "group", "japan/sic/group/091", "groups"),
    ("japan", "industry_group", "japan/sic/industry_group/0911", "industry_groups"),
    ("japan", "description", "japan/sic/description/food", "industry_groups"),
]
NO_MATCH = {  # a query that matches nothing, per path prefix
    "eu/sic/section": "ZZ", "eu/sic/division": "ZZ", "eu/sic/group": "ZZ", "eu/sic/class": "ZZ", "eu/sic/description": "zzqq",
    "international/sic/section": "ZZ", "international/sic/division": "ZZ", "international/sic/group": "ZZ",
    "international/sic/class": "ZZ", "international/sic/description": "zzqq",
    "japan/sic/division": "ZZ", "japan/sic/major_group": "ZZ", "japan/sic/group": "ZZ",
    "japan/sic/industry_group": "ZZ", "japan/sic/description": "zzqq",
}


def drop_volatile(env):
    """The envelope minus what legitimately differs between V3 and V4 (the dependencies block)."""
    return {k: v for k, v in env.items() if k != "dependencies"}


class NonUsContract(ServerTestCase):
    """L1: all 15 lookups answer in both shapes."""

    def test_v4_paths_return_a_list_of_matches_with_their_parents(self):
        for system, level, suffix, _ in LOOKUPS:
            with self.subTest(path=f"/V4.0/{suffix}"):
                status, body, _ = get(f"/V4.0/{suffix}")
                self.assertEqual(status, 200)
                self.assertEqual(body["code"], 200)
                self.assertIsInstance(body["data"], list)
                self.assertTrue(body["data"], "at least one match")
                self.assertIn("section_id", body["data"][0])

    def test_v3_paths_return_v3s_dictionary_with_a_total(self):
        for system, level, suffix, key in LOOKUPS:
            with self.subTest(path=f"/V3.0/{suffix}"):
                status, body, _ = get(f"/V3.0/{suffix}")
                self.assertEqual(status, 200)
                self.assertEqual(sorted(body["data"]), sorted([key, "total"]))
                self.assertEqual(body["data"]["total"], len(body["data"][key]))
                self.assertGreater(body["data"]["total"], 0)

    def test_no_match_is_a_json_404_in_both_shapes(self):
        for system, level, suffix, key in LOOKUPS:
            prefix = suffix.rsplit("/", 1)[0]
            q = NO_MATCH[prefix]
            for version in ("V4.0", "V3.0"):
                with self.subTest(path=f"/{version}/{prefix}/{q}"):
                    status, body, _ = get(f"/{version}/{prefix}/{q}")
                    self.assertEqual(status, 404)
                    self.assertIsNotNone(body, "JSON envelope (V3 answered with an HTML page: intentional difference)")
                    self.assertEqual(body["code"], 404)
                    if version == "V3.0":
                        self.assertEqual(body["data"], {key: {}, "total": 0})


class V3Parity(ServerTestCase):
    """L3: V4's /V3.0/ answers against V3's real ones."""

    IDENTICAL = [
        ("eu_section_A", "/V3.0/eu/sic/section/A"), ("eu_division_25", "/V3.0/eu/sic/division/25"),
        ("eu_group_259", "/V3.0/eu/sic/group/25.9"), ("eu_class_2591", "/V3.0/eu/sic/class/25.91"),
        ("eu_desc_steel", "/V3.0/eu/sic/description/steel"),
        ("intl_section_A", "/V3.0/international/sic/section/A"), ("intl_division_25", "/V3.0/international/sic/division/25"),
        ("intl_group_259", "/V3.0/international/sic/group/259"), ("intl_class_2591", "/V3.0/international/sic/class/2591"),
        ("intl_desc_steel", "/V3.0/international/sic/description/steel"),
        ("us_major_35", "/V3.0/na/sic/major/35"), ("us_industry_357", "/V3.0/na/sic/industry/357"),
        ("us_code_3571", "/V3.0/na/sic/code/3571"), ("us_desc_computers", "/V3.0/na/sic/description/computers"),
        ("v2_code_3571", "/V2.0/sic/code/3571"),
    ]

    def test_identical_to_v3(self):
        for name, path in self.IDENTICAL:
            with self.subTest(fixture=name):
                status, body, _ = get(path)
                v3 = fixture(name)
                self.assertEqual(status, 200)
                self.assertEqual(drop_volatile(body), drop_volatile(v3))

    def test_japan_equivalent_to_v3(self):
        """Same shape, messages and codes. V4's Japan data is the corrected file: division and group descriptions are
        upper-case in it, and a description search finds more classes (V3's file lost some)."""
        for name, path in [("japan_major_09", "/V3.0/japan/sic/major_group/09"), ("japan_group_091", "/V3.0/japan/sic/group/091")]:
            with self.subTest(fixture=name):
                _, body, _ = get(path)
                v3 = fixture(name)
                self.assertEqual((body["code"], body["message"], body["module"]), (v3["code"], v3["message"], v3["module"]))
                lowered = lambda d: json.loads(json.dumps(d).lower())  # noqa: E731 - descriptions differ only in case
                self.assertEqual(lowered(body["data"]), lowered(v3["data"]))
        with self.subTest(fixture="japan_desc_food"):
            _, body, _ = get("/V3.0/japan/sic/description/food")
            v3 = fixture("japan_desc_food")
            self.assertEqual((body["code"], body["message"], body["module"]), (v3["code"], v3["message"], v3["module"]))
            self.assertEqual(sorted(body["data"]), sorted(v3["data"]))
            entry = next(iter(body["data"]["industry_groups"].values()))
            self.assertEqual(sorted(entry), sorted(next(iter(v3["data"]["industry_groups"].values()))))
            self.assertEqual(body["data"]["total"], len(body["data"]["industry_groups"]))
            self.assertGreaterEqual(body["data"]["total"], v3["data"]["total"])

    def test_us_division_matches_including_the_narrative(self):
        """The division narrative (`full_description`) is served from the same text V3 uses."""
        _, body, _ = get("/V3.0/na/sic/division/E")
        v3 = fixture("us_division_E")
        self.assertEqual((body["code"], body["message"], body["module"]), (v3["code"], v3["message"], v3["module"]))
        self.assertEqual(body["data"], v3["data"])


class V2Aliases(ServerTestCase):
    """V3's limited legacy /V2.0/ set: answered exactly like the /V3.0/ twins."""

    TWINS = [
        ("/V2.0/sic/description/computers", "/V3.0/na/sic/description/computers"),
        ("/V2.0/sic/code/3571", "/V3.0/na/sic/code/3571"),
        ("/V2.0/sic/division/E", "/V3.0/na/sic/division/E"),
        ("/V2.0/sic/industry/357", "/V3.0/na/sic/industry/357"),
        ("/V2.0/sic/major/35", "/V3.0/na/sic/major/35"),
        ("/V2.0/companies/edgar/ciks/Apple", "/V3.0/na/companies/edgar/ciks/Apple"),
        ("/V2.0/companies/edgar/summary/Apple", "/V3.0/na/companies/edgar/summary/Apple"),
    ]
    NETWORK_TWINS = [  # these make the server call SEC / Wikipedia
        ("/V2.0/company/edgar/firmographics/320193", "/V3.0/na/company/edgar/firmographics/320193"),
        ("/V2.0/company/wikipedia/firmographics/Apple Inc.", "/V3.0/global/company/wikipedia/firmographics/Apple Inc."),
        ("/V3.0/global/company/wikipedia/v2/firmographics/Apple Inc.", "/V3.0/global/company/wikipedia/firmographics/Apple Inc."),
        ("/V2.0/company/merged/firmographics/Apple Inc.", "/V3.0/global/company/merged/firmographics/Apple Inc."),
        ("/V3.0/global/company/merged/v2/firmographics/Apple Inc.", "/V3.0/global/company/merged/firmographics/Apple Inc."),
    ]

    @staticmethod
    def _stable(body):
        text = json.dumps(drop_volatile(body), sort_keys=True)
        return json.loads(text)

    def _same(self, pairs):
        for legacy, current in pairs:
            with self.subTest(legacy=legacy):
                s1, b1, _ = get(legacy.replace(" ", "%20"))
                s2, b2, _ = get(current.replace(" ", "%20"))
                self.assertEqual(s1, s2)
                self.assertEqual(self._stable(b1), self._stable(b2))

    def test_local_aliases_equal_their_twins(self):
        self._same(self.TWINS)

    @unittest.skipUnless(NETWORK, "calls Wikipedia / SEC; set API_TESTS_NETWORK=1")
    def test_network_aliases_equal_their_twins(self):
        self._same(self.NETWORK_TWINS)


class Spec(ServerTestCase):
    """The documentation lists all of it."""

    def test_new_paths_are_in_the_openapi_document(self):
        status, spec, _ = get("/openapi.json")
        self.assertEqual(status, 200)
        paths = set(spec["paths"])
        missing = []
        for _, _, suffix, _ in LOOKUPS:
            for version in ("V4.0", "V3.0"):
                template = f"/{version}/" + suffix.rsplit("/", 1)[0] + "/{"
                if not any(p.startswith(template) for p in paths):
                    missing.append(template)
        self.assertEqual(missing, [])
        v2 = [p for p in paths if p.startswith("/V2.0/")]
        self.assertEqual(len(v2), 11, sorted(v2))
        for p in ("/V3.0/global/company/wikipedia/v2/firmographics/{company_name}", "/V3.0/global/company/merged/v2/firmographics/{company_name}"):
            self.assertIn(p, paths)


if __name__ == "__main__":
    unittest.main()
