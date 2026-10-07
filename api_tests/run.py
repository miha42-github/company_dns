#!/usr/bin/env python3
"""Run the API tests against a server.

    python3 api_tests/run.py                          # http://localhost:4000
    python3 api_tests/run.py --base-url https://staging-company-dns.mediumroast.io --profile ID --token TOKEN
    python3 api_tests/run.py --network                # include the tests that make the server call Wikipedia / SEC

Standard library only. See common.py for the environment variables this sets.
"""
import argparse
import os
import sys
import unittest
from pathlib import Path

here = Path(__file__).resolve().parent
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://localhost:4000"))
ap.add_argument("--profile", help="profile id for HTTP Basic Auth (non-local servers)")
ap.add_argument("--token", help="that profile's token")
ap.add_argument("--network", action="store_true", help="include tests that make the server call Wikipedia / SEC")
ap.add_argument("pattern", nargs="?", default="test_*.py")
args = ap.parse_args()
os.environ["BASE_URL"] = args.base_url
if args.profile and args.token:
    os.environ["API_TESTS_PROFILE"], os.environ["API_TESTS_TOKEN"] = args.profile, args.token
if args.network:
    os.environ["API_TESTS_NETWORK"] = "1"
sys.path.insert(0, str(here))
suite = unittest.defaultTestLoader.discover(str(here), pattern=args.pattern)
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
