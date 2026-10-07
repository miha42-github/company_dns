"""Shared plumbing for the API tests: the server under test, an HTTP helper, and the V3 fixtures.

Standard library only, so a laptop or a CI runner can run it unchanged (docs/plans/v4-deployment.md section 3.9).

    BASE_URL              server under test (default http://localhost:4000)
    API_TESTS_PROFILE     optional profile id, with API_TESTS_TOKEN: HTTP Basic Auth for servers that are not local
    API_TESTS_TOKEN
    API_TESTS_NETWORK=1   also run the tests that make the server call Wikipedia / SEC (off by default)

On a local server the client sends an `Origin: http://localhost` header, which the server's rate limiter trusts, so a run
is not throttled. Against any other server use a profile (a trusted Origin is not identity there).
"""
import base64
import json
import os
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = os.environ.get("BASE_URL", "http://localhost:4000").rstrip("/")
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "v3"
USER_AGENT = "company_dns-api-tests/1.0 (https://github.com/miha42-github/company_dns)"
NETWORK = os.environ.get("API_TESTS_NETWORK") == "1"


def _headers():
    h = {"User-Agent": USER_AGENT}
    profile, token = os.environ.get("API_TESTS_PROFILE"), os.environ.get("API_TESTS_TOKEN")
    if profile and token:
        h["Authorization"] = "Basic " + base64.b64encode(f"{profile}:{token}".encode()).decode()
    elif urllib.parse.urlparse(BASE_URL).hostname in ("localhost", "127.0.0.1", "::1"):
        h["Origin"] = "http://localhost"
    return h


def get(path):
    """GET `path` on the server under test; returns (status, parsed JSON or None, headers)."""
    req = urllib.request.Request(BASE_URL + path, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body, status, hdrs = r.read(), r.status, r.headers
    except urllib.error.HTTPError as e:
        body, status, hdrs = e.read(), e.code, e.headers
    try:
        return status, json.loads(body), hdrs
    except ValueError:
        return status, None, hdrs


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


class ServerTestCase(unittest.TestCase):
    """Skips (with the reason) instead of failing when the server under test is not running."""

    @classmethod
    def setUpClass(cls):
        try:
            status, body, _ = get("/health")
        except Exception as e:  # noqa: BLE001 - any connection problem means "not there"
            raise unittest.SkipTest(f"no server at {BASE_URL}: {e}")
        if status != 200:
            raise unittest.SkipTest(f"{BASE_URL}/health answered {status}")
