#!/usr/bin/env python3
"""Run the API tests against a server.

    python3 api_tests/run.py                                  # everything, against http://localhost:4000
    python3 api_tests/run.py --layers L0,L1                   # just the fast layers
    python3 api_tests/run.py --base-url https://staging-company-dns.mediumroast.io --profile ID --token TOKEN
    python3 api_tests/run.py --network                        # also the tests that make the server call Wikipedia and SEC
    python3 api_tests/run.py --report results/v4.json         # write a JSON report (diff two with compare.py)
    python3 api_tests/run.py test_contract.py                 # or name files directly

Layers: L0 smoke, L1 contract, L2 data readiness, L3 parity with V3, L4 V4-only functions, L5 limits and profiles (starts its own
server; skipped without a built binary). Standard library only. See common.py for the environment variables this sets.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

here = Path(__file__).resolve().parent

LAYERS = {
    "L0": ["test_smoke.py"],
    "L1": ["test_contract.py", "test_non_us_sic.py"],
    "L2": ["test_data_readiness.py"],
    "L3": ["test_non_us_sic.py", "test_edgar_wikipedia_parity.py"],
    "L4": ["test_v4_functions.py"],
    "L5": ["test_limits_and_profiles.py"],
}


class RecordingResult(unittest.TextTestResult):
    """Records every test's outcome and time for the JSON report."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.records = {}
        self._t0 = {}

    def startTest(self, test):
        self._t0[test.id()] = time.time()
        super().startTest(test)

    def _record(self, test, status, detail=None):
        entry = self.records.setdefault(test.id(), {"id": test.id(), "status": status, "seconds": round(time.time() - self._t0.get(test.id(), time.time()), 3)})
        if status != "passed" and entry["status"] == "passed":
            entry["status"] = status  # a failed subtest outranks the passes before it
        if detail:
            entry["detail"] = detail

    def addSuccess(self, test):
        self._record(test, "passed"); super().addSuccess(test)

    def addFailure(self, test, err):
        self._record(test, "failed", str(err[1])[:300]); super().addFailure(test, err)

    def addError(self, test, err):
        self._record(test, "error", str(err[1])[:300]); super().addError(test, err)

    def addSkip(self, test, reason):
        self._record(test, "skipped", reason); super().addSkip(test, reason)

    def addExpectedFailure(self, test, err):
        self._record(test, "expected_failure"); super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test):
        self._record(test, "unexpected_success", "a known gap now passes: remove its expectedFailure marker"); super().addUnexpectedSuccess(test)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            self._record(test, "failed", str(err[1])[:300])
        super().addSubTest(test, subtest, err)


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=here, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://localhost:4000"))
    ap.add_argument("--profile", help="profile id for HTTP Basic Auth (non-local servers)")
    ap.add_argument("--token", help="that profile's token")
    ap.add_argument("--network", action="store_true", help="include tests that make the server call Wikipedia / SEC")
    ap.add_argument("--layers", help="comma-separated layers, for example L0,L1 (default: all)")
    ap.add_argument("--report", help="write a JSON report here")
    ap.add_argument("patterns", nargs="*", help="test files or globs (overrides --layers)")
    args = ap.parse_args()
    os.environ["BASE_URL"] = args.base_url
    if args.profile and args.token:
        os.environ["API_TESTS_PROFILE"], os.environ["API_TESTS_TOKEN"] = args.profile, args.token
    if args.network:
        os.environ["API_TESTS_NETWORK"] = "1"
    if args.patterns:
        patterns = args.patterns
    elif args.layers:
        wanted = [x.strip().upper() for x in args.layers.split(",") if x.strip()]
        unknown = [x for x in wanted if x not in LAYERS]
        if unknown:
            ap.error(f"unknown layer(s) {unknown}; choose from {', '.join(LAYERS)}")
        patterns = list(dict.fromkeys(f for layer in wanted for f in LAYERS[layer]))
    else:
        patterns = ["test_*.py"]
    sys.path.insert(0, str(here))
    suite = unittest.TestSuite()
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(here), pattern=pattern))
    started = time.time()
    runner = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult)
    result = runner.run(suite)
    if args.report:
        counts = {}
        for r in result.records.values():
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        report = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)), "seconds": round(time.time() - started, 1),
                  "base_url": args.base_url, "git_commit": git_commit(), "network": bool(args.network), "layers": args.layers or "all",
                  "counts": counts, "results": sorted(result.records.values(), key=lambda r: r["id"])}
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
        print(f"report written to {args.report}")
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
