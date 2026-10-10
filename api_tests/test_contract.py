"""L1 contract: every route answers in the right shape, errors are the JSON envelope, and the spec documents what happens.

The table below lists every route in the live spec with a sample that matches and (where it can) one that does not. A test
fails if the server has a route this table does not (so a new endpoint cannot ship without a contract test) or documents a
status it does not return, or returns one it does not document.
"""
import re
import unittest
from urllib.parse import quote

from common import ENVELOPE_KEYS, NETWORK, ServerTestCase, get, post
from test_non_us_sic import LOOKUPS, NO_MATCH

APPLE = quote("Apple Inc.")
NOMATCH = "zzqqxx"


def norm(path):
    """A route with its path parameters blanked, so templates and samples compare."""
    return re.sub(r"\{[^}]+\}", "{}", path.split("?")[0])


def build_table():
    """(route template with {} parameters, matching sample path, no-match sample path or None, needs the network)."""
    t = []
    for prefix, sic in (("/V4.0/na/sic", "/V4.0/na/sic"), ("/V3.0/na/sic", "/V3.0/na/sic"), ("/V2.0/sic", "/V2.0/sic")):
        for leaf, ok, no in (("description", "oil", NOMATCH), ("code", "3571", "9999999"), ("division", "E", "ZZ"),
                             ("industry", "357", "zzz"), ("major", "35", "zz")):
            t.append((f"{prefix}/{leaf}/{{}}", f"{prefix}/{leaf}/{ok}", f"{prefix}/{leaf}/{no}", False))
    for _, _, suffix, _ in LOOKUPS:
        for version in ("V4.0", "V3.0"):
            group = suffix.rsplit("/", 1)[0]
            ok = suffix.rsplit("/", 1)[1]
            t.append((f"/{version}/{group}/{{}}", f"/{version}/{suffix}", f"/{version}/{group}/{NO_MATCH[group]}", False))
    for base in ("/V4.0/na/companies/edgar", "/V3.0/na/companies/edgar", "/V2.0/companies/edgar"):
        t.append((f"{base}/ciks/{{}}", f"{base}/ciks/Apple", f"{base}/ciks/{NOMATCH}", False))
        t.append((f"{base}/summary/{{}}", f"{base}/summary/{APPLE}", f"{base}/summary/{NOMATCH}", False))
        t.append((f"{base}/detail/{{}}", f"{base}/detail/{APPLE}", f"{base}/detail/{NOMATCH}", True))
    for base in ("/V4.0/na/company/edgar", "/V3.0/na/company/edgar", "/V2.0/company/edgar"):
        t.append((f"{base}/firmographics/{{}}", f"{base}/firmographics/320193", None, True))
    for kind in ("wikipedia", "merged"):
        for base in ("/V4.0/global/company", "/V3.0/global/company", "/V2.0/company"):
            t.append((f"{base}/{kind}/firmographics/{{}}", f"{base}/{kind}/firmographics/{APPLE}", None, True))
        t.append((f"/V3.0/global/company/{kind}/v2/firmographics/{{}}", f"/V3.0/global/company/{kind}/v2/firmographics/{APPLE}", None, True))
    for base in ("/V4.0/global/sic/description", "/V3.0/global/sic/description"):
        t.append((f"{base}/{{}}", f"{base}/software", f"{base}/{NOMATCH}", False))
    q = quote("software for banks")
    for base in ("/V4.0/na/sic/similarity", "/V4.0/global/sic/similarity", "/V4.0/global/sic/hybrid"):
        t.append((f"{base}/{{}}", f"{base}/{q}", None, False))
    t.append(("/V4.0/na/sic/similarity-check", "/V4.0/na/sic/similarity-check?q=software", None, False))
    t.append(("/health", "/health", None, False))
    return t


TABLE = build_table()
POSTS = {"/V4.0/global/sic/match", "/V4.0/global/sic/map", "/V4.0/sql"}


class Table(ServerTestCase):
    def setUp(self):
        status, self.spec, _ = get("/openapi.json")
        self.assertEqual(status, 200)

    def test_every_route_in_the_spec_has_a_contract_test(self):
        spec_gets = {norm(p) for p, ops in self.spec["paths"].items() if "get" in ops}
        ours = {norm(t[0]) for t in TABLE}
        self.assertEqual(sorted(spec_gets - ours), [], "routes with no entry in the contract table")
        self.assertEqual(sorted(ours - spec_gets), [], "table entries the server does not document")
        posts = {p for p, ops in self.spec["paths"].items() if "post" in ops}
        if "/V4.0/sql" in self.spec["paths"]:
            self.assertEqual(posts, POSTS)
        else:
            # SQL is off (the production default): the route must be absent from the spec AND from the server, not just undocumented
            self.assertEqual(posts, POSTS - {"/V4.0/sql"})
            status, _, _ = post("/V4.0/sql", {"sql": "select 1", "dataset": "sic"})
            self.assertEqual(status, 404, "with SQL off the route must not exist")


class Responses(ServerTestCase):
    def setUp(self):
        _, self.spec, _ = get("/openapi.json")
        self.documented = {norm(p): set(ops["get"]["responses"]) for p, ops in self.spec["paths"].items() if "get" in ops}

    def routes(self, network):
        return [t for t in TABLE if t[3] == network]

    def check_envelope(self, status, body, path):
        self.assertIsNotNone(body, f"{path}: not JSON")
        self.assertTrue(ENVELOPE_KEYS <= set(body), f"{path}: envelope keys {sorted(body)}")
        self.assertEqual(body["code"], status, f"{path}: code in the body matches the HTTP status")

    def test_a_match_is_a_200_envelope_and_is_documented(self):
        for template, ok, _, _ in self.routes(False):
            with self.subTest(path=ok):
                status, body, _ = get(ok)
                self.assertEqual(status, 200)
                if template == "/health":
                    self.assertEqual(sorted(body), ["status", "timestamp", "version"], "V3's health shape, not an envelope")
                else:
                    self.check_envelope(status, body, ok)
                self.assertIn("200", self.documented[norm(template)])

    def test_no_match_is_a_404_envelope_and_is_documented(self):
        for template, _, no, _ in self.routes(False):
            if not no:
                continue
            with self.subTest(path=no):
                status, body, _ = get(no)
                self.assertEqual(status, 404)
                self.check_envelope(status, body, no)
                self.assertIn("404", self.documented[norm(template)], "the spec must document the 404 the server returns")

    def test_every_route_documents_the_access_and_rate_limit_answers(self):
        for template, *_ in TABLE:
            if template == "/health":
                continue
            with self.subTest(path=template):
                self.assertTrue({"200", "401", "429"} <= self.documented[norm(template)])

    @unittest.skipUnless(NETWORK, "these make the server call Wikipedia / SEC; set API_TESTS_NETWORK=1")
    def test_routes_that_call_upstream_answer_in_the_envelope(self):
        for template, ok, no, _ in self.routes(True):
            with self.subTest(path=ok):
                status, body, _ = get(ok)
                self.assertEqual(status, 200)
                self.check_envelope(status, body, ok)
                self.assertIn("200", self.documented[norm(template)])
            if no:
                with self.subTest(path=no):
                    self.assertEqual(get(no)[0], 404)


class ErrorShapes(ServerTestCase):
    """Every error, including the framework's own, is the JSON envelope; and what the spec documents is what happens."""

    def setUp(self):
        _, self.spec, _ = get("/openapi.json")

    def documented(self, path, method="get"):
        """The statuses the spec documents for the route a sample path belongs to."""
        base = path.split("?")[0]
        wanted = {norm(base), base.rsplit("/", 1)[0] + "/{}"}
        key = next(p for p in self.spec["paths"] if norm(p) in wanted)
        return set(self.spec["paths"][key][method]["responses"])

    def envelope(self, status, body):
        self.assertIsNotNone(body, "an error must be JSON")
        self.assertTrue(ENVELOPE_KEYS <= set(body), sorted(body))
        self.assertEqual(body["code"], status)

    def test_an_unknown_route_is_a_json_404(self):
        status, body, _ = get("/V4.0/nope")
        self.assertEqual(status, 404)
        self.envelope(status, body)

    def test_a_wrong_method_is_a_json_405_with_allow(self):
        status, body, headers = get("/V4.0/global/sic/match")
        self.assertEqual(status, 405)
        self.envelope(status, body)
        self.assertIn("POST", headers["Allow"])

    def test_a_wrong_content_type_is_a_json_415(self):
        status, body, _ = post("/V4.0/global/sic/match", "x", headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        self.envelope(status, body)

    def test_invalid_json_is_a_json_400(self):
        status, body, _ = post("/V4.0/global/sic/match", "not json")
        self.assertEqual(status, 400)
        self.envelope(status, body)

    def test_unknown_model_and_bad_parameters_are_400s_and_documented(self):
        cases = [
            "/V4.0/na/sic/similarity/x?model=nope", "/V4.0/global/sic/similarity/x?model=nope", "/V4.0/global/sic/hybrid/x?model=nope",
            "/V4.0/na/sic/similarity-check?q=x&model=nope", "/V4.0/na/sic/similarity-check",
            "/V4.0/na/sic/similarity/x?k=abc", "/V4.0/global/sic/hybrid/x?k=abc",
        ]
        for path in cases:
            with self.subTest(path=path):
                status, body, _ = get(path)
                self.assertEqual(status, 400)
                self.envelope(status, body)
                self.assertIn("400", self.documented(path.split("?")[0]), "the spec must document the 400")

    def test_k_is_clamped_not_rejected(self):
        self.assertEqual(len(get("/V4.0/na/sic/similarity/software?k=0")[1]["data"]), 1)
        self.assertEqual(len(get("/V4.0/na/sic/similarity/software?k=100000")[1]["data"]), 50)

    def test_match_and_map_reject_bad_input_with_a_documented_400(self):
        bad_match = [{"text": ""}, {"text": "x", "model": "nope"}, {"text": "x", "systems": ["Nope SIC"]}, {"text": "software", "systems": []},
                     {"text": "x" * 30001}]
        bad_map = [{"from": "Nope", "codes": ["1"]}, {"from": "US SIC", "codes": []}, {"from": "US SIC", "codes": ["3571"], "to": ["Nope"]}]
        for path, bodies in (("/V4.0/global/sic/match", bad_match), ("/V4.0/global/sic/map", bad_map)):
            self.assertIn("400", self.documented(path, "post"))
            for body in bodies:
                with self.subTest(path=path, body=str(body)[:60]):
                    status, resp, _ = post(path, body)
                    self.assertEqual(status, 400)
                    self.envelope(status, resp)

    def test_the_sql_operation_documents_every_answer_it_can_give(self):
        if "/V4.0/sql" not in self.spec["paths"]:
            self.skipTest("SQL is off on this server (the production default); start it with COMPANY_DNS_SQL_ENABLED=true to check")
        self.assertEqual(self.documented("/V4.0/sql", "post"), {"200", "400", "401", "403", "422", "429", "504"})


if __name__ == "__main__":
    unittest.main()
