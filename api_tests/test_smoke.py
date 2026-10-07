"""L0 smoke: is it up and sane? Fast, safe against any server, no upstream calls."""
import unittest
from urllib.parse import quote

from common import ServerTestCase, get, post


class Smoke(ServerTestCase):
    def test_health(self):
        status, body, _ = get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "healthy")
        self.assertEqual(body["version"], "4.0.0")
        self.assertIn("timestamp", body)

    def test_the_spec_loads_and_describes_the_api(self):
        status, spec, _ = get("/openapi.json")
        self.assertEqual(status, 200)
        self.assertEqual(spec["info"]["title"], "company_dns API (V4)")
        self.assertEqual(spec["info"]["version"], "4.0.0")
        self.assertGreaterEqual(len(spec["paths"]), 70)
        self.assertTrue(spec["info"]["description"])
        self.assertTrue(spec["info"]["license"]["name"])

    def test_the_documentation_pages_are_served(self):
        for path in ("/docs/", "/redoc"):
            with self.subTest(path=path):
                req_status, _, headers = get(path)
                self.assertEqual(req_status, 200)
        import urllib.request
        from common import BASE_URL, _headers
        for path, ctype in (("/redoc/redoc.standalone.js", "application/javascript"), ("/redoc", "text/html")):
            with self.subTest(path=path):
                with urllib.request.urlopen(urllib.request.Request(BASE_URL + path, headers=_headers()), timeout=30) as r:
                    body = r.read()
                    self.assertTrue(r.headers["Content-Type"].startswith(ctype))
                    self.assertGreater(len(body), 1000)
                    if path == "/redoc":
                        text = body.decode()
                        self.assertNotIn("cdn.redoc.ly", text)
                        self.assertNotIn("googleapis", text)

    def test_one_lookup_per_family_answers(self):
        for path in (
            "/V4.0/na/sic/code/3571", "/V4.0/eu/sic/section/A", "/V4.0/international/sic/section/A", "/V4.0/japan/sic/division/E",
            "/V4.0/na/companies/edgar/ciks/Apple", "/V4.0/global/sic/description/software",
            "/V4.0/na/sic/similarity/" + quote("software for banks"), "/V4.0/global/sic/hybrid/" + quote("oil and gas"),
            "/V3.0/na/sic/code/3571", "/V2.0/sic/code/3571",
        ):
            with self.subTest(path=path):
                status, body, _ = get(path)
                self.assertEqual(status, 200)
                self.assertEqual(body["code"], 200)

    def test_industry_match_answers(self):
        status, body, _ = post("/V4.0/global/sic/match", {"text": "We design and sell personal computers."})
        self.assertEqual(status, 200)
        self.assertTrue(body["data"]["systems"][0]["recommended"])


if __name__ == "__main__":
    unittest.main()
