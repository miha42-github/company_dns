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


def request(method, path, body=None, headers=None, timeout=60):
    """Send a request to the server under test; returns (status, parsed JSON or None, headers)."""
    h = _headers()
    h.update(headers or {})
    data = None
    if body is not None:
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(BASE_URL + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, status, hdrs = r.read(), r.status, r.headers
    except urllib.error.HTTPError as e:
        raw, status, hdrs = e.read(), e.code, e.headers
    try:
        return status, json.loads(raw), hdrs
    except ValueError:
        return status, None, hdrs


def get(path, headers=None):
    """GET `path` on the server under test; returns (status, parsed JSON or None, headers)."""
    return request("GET", path, headers=headers)


def post(path, body, headers=None):
    """POST a JSON body (or a raw string) to `path`; returns (status, parsed JSON or None, headers)."""
    return request("POST", path, body=body, headers=headers)


ENVELOPE_KEYS = {"code", "message", "module", "data", "dependencies"}


def shape(value, depth=0):
    """A value's structure with the data stripped out: dict keys and types, the first list element. Stops three levels down,
    where dictionaries are keyed by data (a filing's date, a company's name) rather than by field name."""
    if isinstance(value, dict):
        return {k: shape(v, depth + 1) for k, v in sorted(value.items())} if depth < 3 else "object"
    if isinstance(value, list):
        return [shape(value[0], depth + 1)] if value else []
    return type(value).__name__


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
