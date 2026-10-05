#!/usr/bin/env python3
"""Pick the evaluation set (companies.json) from companies_pool.json.

    arch -x86_64 python3.11 select_set.py [--size 200]     # needs `tokenizers`

Deterministic (fixed seed). Stratified so the set is not just large caps:
  * by description length, tokenised with the model's own tokenizer:
    long (>256, the case chunking exists for), mid (129-256), short (<=128)
  * by SIC division (first two digits), round-robin, so one sector (73,
    software and services) cannot fill the set
Rows with no filer SIC, or whose Wikipedia page is clearly not the company
(listed in EXCLUDE below, each with the reason), are never chosen. Hand-judged
`acceptable`/`notes` already in companies.json are carried over.
"""
import glob, json, random, sys
from pathlib import Path
from tokenizers import Tokenizer

HERE = Path(__file__).parent
SIZE = int(sys.argv[sys.argv.index("--size") + 1]) if "--size" in sys.argv else 200
QUOTA = {"long": 0.40, "mid": 0.32, "short": 0.28}
EXCLUDE = {
    "LendingClub": "Wikipedia/Wikidata returned an unrelated entity ('Happen Inc.')",
}
tk = Tokenizer.from_file(glob.glob(str(HERE / "../../v4/.fastembed_cache/models--Qdrant--all-MiniLM-L6-v2-onnx/snapshots/*/tokenizer.json"))[0])
tk.no_truncation()

pool = json.loads((HERE / "companies_pool.json").read_text())["companies"]
old = {}
if (HERE / "companies.json").exists():
    old = {c["name"]: c for c in json.loads((HERE / "companies.json").read_text())["companies"]}
for c in pool:
    c["tokens"] = len(tk.encode(c["description"]).ids)
eligible = [c for c in pool if c["filer_sic"] and c["name"] not in EXCLUDE]
bin_of = lambda c: "long" if c["tokens"] > 256 else "mid" if c["tokens"] > 128 else "short"

rng = random.Random(20261004)
chosen = []
for b, share in QUOTA.items():
    want = round(SIZE * share)
    by_div = {}
    for c in eligible:
        if bin_of(c) == b:
            by_div.setdefault(c["filer_sic"][:2], []).append(c)
    for v in by_div.values():
        rng.shuffle(v)
    divs = sorted(by_div)
    picked = []
    while len(picked) < want and any(by_div.values()):
        for d in divs:
            if by_div[d] and len(picked) < want:
                picked.append(by_div[d].pop())
    chosen += picked
if len(chosen) < SIZE:  # a bin ran short: top up from whatever is left
    left = [c for c in eligible if c not in chosen]
    rng.shuffle(left)
    chosen += left[: SIZE - len(chosen)]
chosen = sorted(chosen[:SIZE], key=lambda c: c["name"])
for c in chosen:
    prev = old.get(c["name"], {})
    c["acceptable"] = prev.get("acceptable", c.get("acceptable", {}))
    c["notes"] = prev.get("notes", c.get("notes", ""))
    c["length_bin"] = bin_of(c)
(HERE / "companies.json").write_text(json.dumps({"format": 1, "companies": chosen}, indent=1, ensure_ascii=False) + "\n")
from collections import Counter
print(f"wrote {len(chosen)} companies; bins {dict(Counter(c['length_bin'] for c in chosen))}; "
      f"SIC divisions {len({c['filer_sic'][:2] for c in chosen})}; median tokens {sorted(c['tokens'] for c in chosen)[len(chosen)//2]}")
