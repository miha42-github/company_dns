#!/usr/bin/env python3
"""Rust chunker and phrase extractor == the Python ones (the spec), on every description in companies.json.

    arch -x86_64 python3.11 parity_check.py [base_url] [target]     # needs `tokenizers`; server running

POSTs each description to /V4.0/global/sic/match and compares the returned
chunk texts with chunker.chunk() using the model's own tokenizer.
"""
import glob, json, sys, time, urllib.error, urllib.request
from pathlib import Path
from tokenizers import Tokenizer
from chunker import chunk, phrases

HERE = Path(__file__).parent
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:4000"
TARGET = int(sys.argv[2]) if len(sys.argv) > 2 else 64
tk = Tokenizer.from_file(glob.glob(str(HERE / "../../v4/.fastembed_cache/models--Qdrant--all-MiniLM-L6-v2-onnx/snapshots/*/tokenizer.json"))[0])
tk.no_truncation()
count = lambda s: len(tk.encode(s).ids)


def post(text):
    req = urllib.request.Request(f"{BASE}/V4.0/global/sic/match", data=json.dumps({"text": text}).encode(),
                                 headers={"User-Agent": "company-sic-eval/1.0 (michael.hay@mediumroast.io)", "Content-Type": "application/json"})
    for attempt in range(6):
        try:
            return json.load(urllib.request.urlopen(req, timeout=120))["data"]
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(2 + 2 * attempt)


bad = 0
cs = json.loads((HERE / "companies.json").read_text())["companies"]
for c in cs:
    resp = post(c["description"])
    got = [x["text"] for x in resp["chunks"]]
    want = chunk(c["description"], count, TARGET, max(200, TARGET))
    if resp["input"]["phrases"] != phrases(c["description"])[:24]:
        bad += 1
        print(f"PHRASE MISMATCH {c['name']}: rust {resp['input']['phrases'][:4]} python {phrases(c['description'])[:4]}")
    time.sleep(0.5)
    if got != want:
        bad += 1
        print(f"MISMATCH {c['name']}: rust {len(got)} chunks, python {len(want)}")
        for i, (a, b) in enumerate(zip(got, want)):
            if a != b:
                print(f"   first difference at chunk {i}:\n   rust  : {a[:140]!r}\n   python: {b[:140]!r}")
                break
print(f"{len(cs) - bad}/{len(cs)} descriptions chunk identically (target {TARGET})")
sys.exit(1 if bad else 0)
