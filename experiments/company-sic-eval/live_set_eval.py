#!/usr/bin/env python3
"""Score the LIVE POST /V4.0/global/sic/match endpoint against the reviewed
acceptable sets (stdlib only; server must be running).

    python3 live_set_eval.py [base_url]

set = the 2-5 recommended codes; pool = recommended + alternatives (what the
stepper offers). hit = at least one accepted code present; precision/recall as
in select_eval.py. Backs off on 429.
"""
import collections, json, sys, time, urllib.error, urllib.request
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:4000"
UA = "company-sic-eval/1.0 (michael.hay@mediumroast.io)"
KEY = {"US SIC": "us_sic", "ISIC": "isic_rev4", "EU NACE": "nace_rev2"}
companies = [c for c in json.loads((Path(__file__).parent / "companies.json").read_text())["companies"] if c.get("labels_status") == "reviewed"]


def match(text):
    req = urllib.request.Request(f"{BASE}/V4.0/global/sic/match", data=json.dumps({"text": text, "systems": ["US SIC", "ISIC", "EU NACE", "Japan SIC"]}).encode(),
                                 headers={"User-Agent": UA, "Content-Type": "application/json"})
    for attempt in range(6):
        try:
            return json.load(urllib.request.urlopen(req, timeout=120))["data"]
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(2 + 2 * attempt)
    raise RuntimeError("rate limited")


stat = collections.defaultdict(lambda: collections.defaultdict(list))
sizes = []
for c in companies:
    d = match(c["description"])
    time.sleep(0.6)
    for s in d["systems"]:
        k = KEY.get(s["system"])
        acc = set(c["acceptable"].get(k, [])) if k else set()
        if not acc:
            continue
        rec = {e["code"] for e in s["recommended"]}
        pool = rec | {e["code"] for e in s["alternatives"]}
        sizes.append(len(rec))
        st = stat[k]
        st["set hit"].append(1 if rec & acc else 0)
        st["set precision"].append(len(rec & acc) / len(rec))
        st["set recall"].append(len(rec & acc) / len(acc))
        st["pool hit"].append(1 if pool & acc else 0)
        st["pool recall"].append(len(pool & acc) / len(acc))
m = lambda x: sum(x) / len(x)
print(f"{len(companies)} reviewed companies; mean recommended-set size {m(sizes):.1f}")
cols = ["set hit", "set precision", "set recall", "pool hit", "pool recall"]
print(f"{'system':10s}" + "".join(f"{c:>15s}" for c in cols))
for k, st in stat.items():
    print(f"{k:10s}" + "".join(f"{m(st[c]):15.2f}" for c in cols))
