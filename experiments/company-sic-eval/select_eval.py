#!/usr/bin/env python3
"""Design check for the 2-5 code recommended set (plan decision 9).

    arch -x86_64 python3.11 select_eval.py <out_dir>      # after `eval.py dump`

For each reviewed company and system: chunk (128), embed, score every corpus
entry by its best chunk similarity, then apply a selection rule that returns
2-5 codes. Reports, over the reviewed companies: mean set size, precision
(share of recommended codes the reviewer accepted), recall (share of accepted
codes recovered), hit (at least one accepted code in the set) and set-size
spread. Rules differ in how they enforce the 2-5 bounds and whether they favour
variety (several lines of business) over near-duplicate siblings.
"""
import glob, json, sys
from pathlib import Path
import numpy as np
from tokenizers import Tokenizer
from sentence_transformers import SentenceTransformer
from chunker import chunk

HERE = Path(__file__).parent
OUT = Path(sys.argv[1])
TARGET = int(sys.argv[2]) if len(sys.argv) > 2 else 128
SYSTEMS = ["us_sic", "isic_rev4", "nace_rev2"]
tk = Tokenizer.from_file(glob.glob(str(HERE / "../../v4/.fastembed_cache/models--Qdrant--all-MiniLM-L6-v2-onnx/snapshots/*/tokenizer.json"))[0])
tk.no_truncation()
count = lambda s: len(tk.encode(s).ids)
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
model.max_seq_length = 256
companies = [c for c in json.loads((HERE / "companies.json").read_text())["companies"] if c.get("labels_status") == "reviewed"]
corp = {}
for k in SYSTEMS:
    d = json.loads((OUT / f"{k}.json").read_text())
    V = np.array(d["vec"], dtype=np.float32); V /= np.linalg.norm(V, axis=1, keepdims=True)
    corp[k] = (V, d["code"])
group = lambda k, code: code[:4] if k == "nace_rev2" else code[:3]
division = lambda code: code[:2]


def candidates(S, k, codes, top_m=3):
    """entries sorted by best-chunk similarity, with the chunk that drove each and how many chunks rank it in their top_m."""
    best, arg = S.max(0), S.argmax(0)
    support = np.zeros(S.shape[1], dtype=int)
    for row in S:
        support[np.argsort(-row)[:top_m]] += 1
    order = np.argsort(-best)
    return [(codes[i], float(best[i]), int(arg[i]), int(support[i])) for i in order]


def rule_top(n):
    return lambda cands, S, k: [c for c in cands[:n]]


def rule_relative(delta, lo=2, hi=5, per_group=None):
    def f(cands, S, k):
        top = cands[0][1]; out = []; gcount = {}
        for c in cands:
            if len(out) >= hi: break
            g = group(k, c[0])
            if per_group and gcount.get(g, 0) >= per_group: continue
            if c[1] >= top - delta or len(out) < lo:
                out.append(c); gcount[g] = gcount.get(g, 0) + 1
        return out
    return f


def rule_chunk_winners(per_chunk=1, lo=2, hi=5, delta=0.10):
    """each chunk nominates its own top entries; rank nominees by how many chunks nominate them, then similarity."""
    def f(cands, S, k):
        codes = [c[0] for c in cands]; info = {c[0]: c for c in cands}
        nominees = {}
        for row in S:
            for i in np.argsort(-row)[:per_chunk]:
                pass
        return None
    return f


def run_rules(rules):
    res = {name: {s: dict(size=[], prec=[], rec=[], hit=[]) for s in SYSTEMS} for name in rules}
    for c in companies:
        cs = chunk(c["description"], count, TARGET, max(200, TARGET))
        E = model.encode(cs, normalize_embeddings=True, show_progress_bar=False)
        for k in SYSTEMS:
            V, codes = corp[k]
            acc = set(c["acceptable"].get(k, []))
            if not acc: continue
            S = E @ V.T
            cands = candidates(S, k, codes)
            for name, rule in rules.items():
                rec = [x[0] for x in rule(cands, S, k)]
                r = res[name][k]
                r["size"].append(len(rec))
                r["prec"].append(len(set(rec) & acc) / len(rec))
                r["rec"].append(len(set(rec) & acc) / len(acc))
                r["hit"].append(1 if set(rec) & acc else 0)
    return res


def chunk_winner_rule(per_chunk=1, lo=2, hi=5):
    def f(cands, S, k):
        _, codes = corp[k]
        idx = {cd: i for i, cd in enumerate(codes)}
        votes = {}
        for row in S:
            for j in np.argsort(-row)[:per_chunk]:
                v = votes.setdefault(codes[j], [0, 0.0]); v[0] += 1; v[1] = max(v[1], float(row[j]))
        ranked = sorted(votes.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))
        out = [(cd, v[1], 0, v[0]) for cd, v in ranked][:hi]
        for c in cands:  # pad to the floor from the best-scoring entries
            if len(out) >= lo: break
            if c[0] not in {o[0] for o in out}: out.append(c)
        return out
    return f


rules = {
    "top5": rule_top(5), "rel .08 (2-5)": rule_relative(0.08),
    "chunk winners x1": chunk_winner_rule(1), "chunk winners x2": chunk_winner_rule(2), "chunk winners x3": chunk_winner_rule(3),
}
res = run_rules(rules)
print(f"{len(companies)} reviewed companies; chunk target {TARGET}\n")
mean = lambda xs: sum(xs) / len(xs) if xs else float("nan")
for k in SYSTEMS:
    print(k)
    print(f"  {'rule':22s}{'size':>6s}{'min-max':>9s}{'precision':>11s}{'recall':>8s}{'hit':>6s}")
    for name in rules:
        r = res[name][k]
        print(f"  {name:22s}{mean(r['size']):6.1f}{min(r['size']):>5d}-{max(r['size']):<3d}{mean(r['prec']):11.2f}{mean(r['rec']):8.2f}{mean(r['hit']):6.2f}")
    print()
