#!/usr/bin/env python3
"""Diff two reports written by `run.py --report`: what changed between two runs (two builds, or V3 and V4).

    python3 api_tests/compare.py before.json after.json

Prints each test whose status changed, new and removed tests, and the counts. Exits 1 when a test that passed (or was an expected
failure) now fails or errors, or a known gap unexpectedly passes.
"""
import json
import sys

GOOD = {"passed", "expected_failure", "skipped"}


def load(path):
    return json.load(open(path))


def main(a_path, b_path):
    a, b = load(a_path), load(b_path)
    ra, rb = {r["id"]: r for r in a["results"]}, {r["id"]: r for r in b["results"]}
    print(f"before: {a['git_commit']} {a['started']} {a['base_url']} {a['counts']}")
    print(f"after : {b['git_commit']} {b['started']} {b['base_url']} {b['counts']}\n")
    regressions = 0
    for tid in sorted(set(ra) | set(rb)):
        x, y = ra.get(tid), rb.get(tid)
        if x is None:
            print(f"NEW      {y['status']:18s} {tid}")
        elif y is None:
            print(f"REMOVED  {x['status']:18s} {tid}")
        elif x["status"] != y["status"]:
            worse = x["status"] in GOOD and y["status"] not in GOOD or y["status"] == "unexpected_success"
            regressions += worse
            print(f"{'WORSE' if worse else 'CHANGED':8s} {x['status']} -> {y['status']}  {tid}" + (f"\n         {y.get('detail', '')[:160]}" if worse else ""))
    if not regressions:
        print("no regressions")
    return 1 if regressions else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(*sys.argv[1:]))
