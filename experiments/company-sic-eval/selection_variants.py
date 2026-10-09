#!/usr/bin/env python3
"""Variants of the recommended-set rule, aimed at marketing-style descriptions
(docs/plans/company-sic-match.md sec. 12).

    arch -x86_64 python3.11 selection_variants.py <out_dir>

V0  current: chunks of 64 word pieces, each nominates its best codes, equal votes
V1  + relevance gate: a chunk only nominates if its best similarity is at least
    r x the best chunk's (drops headquarters/founding/headcount sentences)
V2  + phrase queries: list items and noun phrases ("data storage", "power grids")
    are queried on their own, because a short phrase matches a short label better
    than a paragraph does; a phrase nominates only above a similarity threshold
Scored on the reviewed companies against the reviewed sets (hit / precision /
recall of the 2-5 set), US SIC, ISIC and NACE, plus the Hitachi text.
"""
import glob, json, re, sys
from pathlib import Path
import numpy as np
from tokenizers import Tokenizer
from sentence_transformers import SentenceTransformer
from chunker import chunk, split_sentences

HERE = Path(__file__).parent
OUT = Path(sys.argv[1])
KEYS = ["us_sic", "isic_rev4", "nace_rev2"]
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2"); model.max_seq_length = 256
unit = lambda V: V / np.linalg.norm(V, axis=1, keepdims=True)
tk = Tokenizer.from_file(glob.glob(str(HERE / "../../v4/.fastembed_cache/models--Qdrant--all-MiniLM-L6-v2-onnx/snapshots/*/tokenizer.json"))[0]); tk.no_truncation()
count = lambda s: len(tk.encode(s).ids)
C = {}
for k in KEYS:
    d = json.loads((OUT / f"{k}.json").read_text())
    C[k] = dict(code=d["code"], title=[t.split(" > ")[-1] for t in d["text"]], V=unit(np.array(d["vec"], dtype=np.float32)))
cos = [c for c in json.loads((HERE / "companies.json").read_text())["companies"] if c.get("labels_status") == "reviewed"]
HITACHI = Path("/private/tmp/claude-501/hitachi.txt").read_text().strip()

SPLIT = re.compile(r"\s*(?:[;,:()—]|\band\b|\bincluding\b|\bsuch as\b|\bvia\b|\bwith\b|\bthrough\b|\bacross\b)\s*", re.I)
STOPW = set("the a an of in on to for by as is are was were has have its their our company companies group global major leading several key world worldwide".split())
FILLER = re.compile(r"^(specializing in|focused on|focus on|such as|including|operates across|operates in|offers|provides|provide|delivers|develops|manufactures|makes|sells|engaged in|active in|known for)\s+", re.I)
NONBIZ = set("founded headquartered headquarters employees workforce committed achieving neutrality evolved nearly globally innovation transformation operates".split())
def phrases(text):
    out, seen = [], set()
    for s in split_sentences(re.sub(r"\s+", " ", text).strip()):
        for frag in SPLIT.split(s):
            frag = FILLER.sub("", frag.strip())
            w = re.findall(r"[A-Za-z][A-Za-z\-]+", frag)
            if any(x.lower() in NONBIZ for x in w): continue
            content = [x for x in w if x.lower() not in STOPW]
            if 2 <= len(w) <= 7 and len(content) >= 2:
                f = " ".join(w).lower()
                if f not in seen:
                    seen.add(f); out.append(" ".join(w))
    return out

def nominate_set(E, P, key, gate=0.0, per_chunk=None, phrase_min=None, phrase_per=1, chunk_w=1.0, phrase_w=1.0, weighted=False, chunk_floor=0.0):
    V = C[key]["V"]
    S = E @ V.T
    n = len(E)
    per = per_chunk or max(2, min(5, -(-5 // n)))
    tops = S.max(1); best_chunk = tops.max()
    votes, best = {}, {}
    for row, top in zip(S, tops):
        o = np.argsort(-row)
        for j in o[:50]: best[j] = max(best.get(j, -1), float(row[j]))
        if top >= gate * best_chunk:
            for j in o[:per]:
                if row[j] >= chunk_floor: votes[j] = votes.get(j, 0) + (chunk_w * float(row[j]) if weighted else chunk_w)
    if phrase_min is not None and P is not None and len(P):
        SP = P @ V.T
        for row in SP:
            o = np.argsort(-row)
            for j in o[:phrase_per]:
                if row[j] >= phrase_min:
                    votes[j] = votes.get(j, 0) + (phrase_w * float(row[j]) if weighted else phrase_w); best[j] = max(best.get(j, -1), float(row[j]))
    ranked = sorted(votes, key=lambda j: (-votes[j], -best[j]))[:5]
    for j in sorted(best, key=lambda j: -best[j]):
        if len(ranked) >= 2: break
        if j not in ranked: ranked.append(j)
    return [C[key]["code"][j] for j in ranked]

VARIANTS = {
    "V0 current": dict(),
    "W: phrases>=.40, vote = similarity": dict(phrase_min=0.40, weighted=True),
    "F: phrases>=.40, chunk floor .30": dict(phrase_min=0.40, chunk_floor=0.30),
    "F: phrases>=.40, chunk floor .35": dict(phrase_min=0.40, chunk_floor=0.35),
    "WF: sim votes, chunk floor .30": dict(phrase_min=0.40, weighted=True, chunk_floor=0.30),
    "WF: sim votes, chunk floor .35": dict(phrase_min=0.40, weighted=True, chunk_floor=0.35),
    "V2 phrases >= .40 (equal)": dict(phrase_min=0.40),
}
def prep(text):
    cs = chunk(text, count, 64, 200)
    E = model.encode(cs, normalize_embeddings=True, show_progress_bar=False)
    ph = phrases(text)
    P = model.encode(ph, normalize_embeddings=True, show_progress_bar=False) if ph else None
    return E, P, ph

prepared = {c["name"]: prep(c["description"]) for c in cos}
print(f"{len(cos)} reviewed companies; set = 2-5 recommended\n")
mean = lambda x: sum(x) / len(x)
for key in KEYS:
    print(key); print(f"  {'variant':22s}{'hit':>6s}{'prec':>7s}{'recall':>8s}{'size':>6s}")
    for name, kw in VARIANTS.items():
        hit = pr = rc = sz = n = 0
        for c in cos:
            acc = set(c["acceptable"].get(key, []))
            if not acc: continue
            E, P, _ = prepared[c["name"]]
            s = nominate_set(E, P, key, **kw)
            n += 1; hit += bool(set(s) & acc); pr += len(set(s) & acc) / len(s); rc += len(set(s) & acc) / len(acc); sz += len(s)
        print(f"  {name:22s}{hit / n:6.2f}{pr / n:7.2f}{rc / n:8.2f}{sz / n:6.1f}")
    print()

E, P, ph = prepare = prep(HITACHI)
print("Hitachi phrases extracted:", ph)
for name in ("V0 current", "V2 phrases >= .40 (equal)", "W: phrases>=.40, vote = similarity", "WF: sim votes, chunk floor .30"):
    print(f"\n{name}")
    for key in ("us_sic", "isic_rev4"):
        s = nominate_set(E, P, key, **VARIANTS[name])
        print(f"  {key:10s} " + " | ".join(f"{c} {C[key]['title'][C[key]['code'].index(c)][:34]}" for c in s))
