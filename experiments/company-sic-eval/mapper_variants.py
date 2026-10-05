#!/usr/bin/env python3
"""Mapping a chosen US set into ISIC / NACE by similarity only (no crosswalk
tables), docs/plans/company-sic-match.md sec. 11.

    arch -x86_64 python3.11 mapper_variants.py <out_dir>

A person's choice is simulated as: the reviewer-accepted US codes found in the
stepper's 12-code menu (the automatic five when the menu has none). Variants:
  K        how many target entries each chosen code nominates (by breadcrumb vector)
  rank     source = max similarity to the chosen codes; fit = best chunk similarity
           to the description; mix = their mean
  fill     keep the top 3 mapped codes, fill to 5 from direct description matching
"""
import glob, json, sys
from pathlib import Path
import numpy as np
from tokenizers import Tokenizer
from sentence_transformers import SentenceTransformer
from chunker import chunk

HERE = Path(__file__).parent
OUT = Path(sys.argv[1])
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2"); model.max_seq_length = 256
unit = lambda V: V / np.linalg.norm(V, axis=1, keepdims=True)
tk = Tokenizer.from_file(glob.glob(str(HERE / "../../v4/.fastembed_cache/models--Qdrant--all-MiniLM-L6-v2-onnx/snapshots/*/tokenizer.json"))[0]); tk.no_truncation()
count = lambda s: len(tk.encode(s).ids)
C = {}
for k in ("us_sic", "isic_rev4", "nace_rev2"):
    d = json.loads((OUT / f"{k}.json").read_text())
    C[k] = dict(code=d["code"], V=unit(np.array(d["vec"], dtype=np.float32)), idx={c: i for i, c in enumerate(d["code"])})
cos = [c for c in json.loads((HERE / "companies.json").read_text())["companies"] if c.get("labels_status") == "reviewed"]

def nominate(E, key):
    S = E @ C[key]["V"].T
    per = max(2, min(5, -(-5 // len(E))))
    votes, best = {}, {}
    for row in S:
        o = np.argsort(-row)
        for j in o[:50]: best[j] = max(best.get(j, -1), float(row[j]))
        for j in o[:per]: votes[j] = votes.get(j, 0) + 1
    return sorted(best, key=lambda j: (-votes.get(j, 0), -best[j]))
prep = {}
for c in cos:
    E = model.encode(chunk(c["description"], count, 64, 200), normalize_embeddings=True, show_progress_bar=False)
    order = nominate(E, "us_sic")
    prep[c["name"]] = (E, [C["us_sic"]["code"][j] for j in order[:5]], [C["us_sic"]["code"][j] for j in order[:12]])

def picks(c):
    acc = set(c["acceptable"]["us_sic"]); _, auto, pool = prep[c["name"]]
    got = [u for u in pool if u in acc][:5]
    return (got, True) if got else (auto, False)

def mapped(us, E, dst, K, rank):
    Vd = C[dst]["V"]
    cand, srcsim = set(), np.full(len(Vd), -1.0)
    for u in us:
        s = Vd @ C["us_sic"]["V"][C["us_sic"]["idx"][u]]
        for j in np.argsort(-s)[:K]: cand.add(j)
        srcsim = np.maximum(srcsim, s)
    fit = (E @ Vd.T).max(0)
    score = {"source": srcsim, "fit": fit, "mix": (srcsim + fit) / 2}[rank]
    return sorted(cand, key=lambda j: -score[j]), score

def direct(E, dst): return nominate(E, dst)[:5]

def run(dst):
    rows = {}
    def add(name, fn):
        rows[name] = [(c, [C[dst]["code"][j] for j in fn(c)]) for c in cos]
    add("direct: description -> target", lambda c: direct(prep[c["name"]][0], dst))
    for K in (3, 5, 8):
        for rank in ("source", "fit", "mix"):
            add(f"mapped K={K}, rank by {rank}", lambda c, K=K, rank=rank: mapped(picks(c)[0], prep[c["name"]][0], dst, K, rank)[0][:5])
    def fill(c, K=5, rank="source"):
        m = mapped(picks(c)[0], prep[c["name"]][0], dst, K, rank)[0][:3]
        d = [j for j in direct(prep[c["name"]][0], dst) if j not in m]
        return (m + d)[:5]
    add("mapped top 3 (K=5, source) + direct fill", fill)
    add("mapped top 3 (K=5, mix) + direct fill", lambda c: fill(c, 5, "mix"))
    return rows

def score(rows, key, only=None):
    n = hit = pr = rc = 0
    for c, s in rows:
        if only is not None and picks(c)[1] != only: continue
        acc = set(c["acceptable"].get(key, []))
        if not acc or not s: continue
        n += 1; hit += bool(set(s) & acc); pr += len(set(s) & acc) / len(s); rc += len(set(s) & acc) / len(acc)
    return hit / n, pr / n, rc / n, n

for dst in ("isic_rev4", "nace_rev2"):
    rows = run(dst)
    print(f"\n{dst}   any / precision / recall   (all 37 | the 28 where the menu had a right US code)")
    for name, r in rows.items():
        a = score(r, dst); b = score(r, dst, True)
        print(f"  {name:44s}{a[0]:6.2f}{a[1]:7.2f}{a[2]:7.2f}   |{b[0]:6.2f}{b[1]:7.2f}{b[2]:7.2f}")
