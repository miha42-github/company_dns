#!/usr/bin/env python3
"""Does stripping stop words from the text we embed help or hurt? (plan sec. 12)

    arch -x86_64 python3.11 stopword_eval.py <out_dir>

Lists: NLTK English (179; what the Rust `stop-words` crate ships with its `nltk`
feature), scikit-learn English (318), and a LEARNED list: words in at least 10% of
the 200 descriptions that appear in none of the four code corpora's labels (so they
cannot help match a label). Stripping is applied to the segment text, to the key
phrases, or to both, before embedding. Scored two ways:
  * the reviewed sets (37 companies): hit / precision / recall of the 2-5 set, per system
  * the 200 filer-SIC companies: US group@5 and class@10 by best-segment ranking
"""
import glob, json, re, sys
from pathlib import Path
import numpy as np
from tokenizers import Tokenizer
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
from nltk.corpus import stopwords as nltk_sw
from chunker import chunk, phrases

HERE = Path(__file__).parent
OUT = Path(sys.argv[1])
KEYS = ["us_sic", "isic_rev4", "nace_rev2"]
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2"); model.max_seq_length = 256
unit = lambda V: V / np.linalg.norm(V, axis=1, keepdims=True)
tk = Tokenizer.from_file(glob.glob(str(HERE / "../../v4/.fastembed_cache/models--Qdrant--all-MiniLM-L6-v2-onnx/snapshots/*/tokenizer.json"))[0]); tk.no_truncation()
count = lambda s: len(tk.encode(s).ids)
C, vocab = {}, set()
for k in KEYS + ["japan_sic"]:
    d = json.loads((OUT / f"{k}.json").read_text())
    vocab |= set(re.findall(r"[a-z]+", " ".join(d["text"]).lower()))
    if k in KEYS:
        C[k] = dict(code=d["code"], V=unit(np.array(d["vec"], dtype=np.float32)))
allc = json.loads((HERE / "companies.json").read_text())["companies"]
cos = [c for c in allc if c.get("labels_status") == "reviewed"]

df = {}
for c in allc:
    for w in set(re.findall(r"[a-z]+", c["description"].lower())): df[w] = df.get(w, 0) + 1
LEARNED = {w for w, n in df.items() if n >= 0.10 * len(allc) and w not in vocab}
NLTK = set(nltk_sw.words("english")); SK = set(ENGLISH_STOP_WORDS)
print(f"lists: NLTK {len(NLTK)}, sklearn {len(SK)}, learned {len(LEARNED)} (e.g. {sorted(LEARNED)[:25]})")

def stripper(words):
    if not words: return lambda t: t
    rx = re.compile(r"\b(?:" + "|".join(sorted(map(re.escape, words), key=len, reverse=True)) + r")\b", re.I)
    return lambda t: re.sub(r"\s+", " ", rx.sub(" ", t)).strip() or t

VARIANTS = {  # name: (word list, apply to chunks, apply to phrases)
    "none (current)": (set(), False, False),
    "NLTK, segments only": (NLTK, True, False),
    "NLTK, phrases only": (NLTK, False, True),
    "NLTK, both": (NLTK, True, True),
    "sklearn 318, both": (SK, True, True),
    "learned list, both": (LEARNED, True, True),
    "learned list, segments only": (LEARNED, True, False),
    "NLTK + learned, both": (NLTK | LEARNED, True, True),
}

def prep(text, strip_c, strip_p):
    cs = chunk(text, count, 64, 200)
    ph = phrases(text)
    E = model.encode([strip_c(x) for x in cs], normalize_embeddings=True, show_progress_bar=False)
    P = model.encode([strip_p(x) for x in ph], normalize_embeddings=True, show_progress_bar=False) if ph else None
    return E, P

def rule(E, P, key, phrase_min=0.40):
    """the server's rule: chunks nominate (more when few), phrases nominate their best if >= 0.40, votes weighted by similarity"""
    V = C[key]["V"]; S = E @ V.T
    per = max(2, min(5, -(-5 // len(E))))
    w, best = {}, {}
    for row in S:
        o = np.argsort(-row)
        for j in o[:50]: best[j] = max(best.get(j, -1), float(row[j]))
        for j in o[:per]: w[j] = w.get(j, 0) + float(row[j])
    if P is not None:
        for row in P @ V.T:
            j = int(np.argmax(row))
            if row[j] >= phrase_min:
                w[j] = w.get(j, 0) + float(row[j]); best[j] = max(best.get(j, -1), float(row[j]))
    ranked = sorted(w, key=lambda j: (-w[j], -best[j]))[:5]
    for j in sorted(best, key=lambda j: -best[j]):
        if len(ranked) >= 2: break
        if j not in ranked: ranked.append(j)
    return [C[key]["code"][j] for j in ranked]

def filer_rank(E, key="us_sic"):
    S = E @ C[key]["V"].T
    sc = S.max(0); seen, out = set(), []
    for j in np.argsort(-sc):
        if C[key]["code"][j] not in seen:
            seen.add(C[key]["code"][j]); out.append(C[key]["code"][j])
    return out
leaf = set(C["us_sic"]["code"])

print(f"\n{'variant':30s} | reviewed 37: US hit/prec/rec | ISIC hit/prec/rec | NACE hit/prec/rec | filer 200: US group@5  class@10")
for name, (words, sc, sp) in VARIANTS.items():
    f = stripper(words)
    id_ = lambda t: t
    fc, fp = (f if sc else id_), (f if sp else id_)
    res = {k: [0, 0, 0, 0] for k in KEYS}
    for c in cos:
        E, P = prep(c["description"], fc, fp)
        for k in KEYS:
            acc = set(c["acceptable"].get(k, []))
            if not acc: continue
            s = rule(E, P, k); r = res[k]
            r[0] += bool(set(s) & acc); r[1] += len(set(s) & acc) / len(s); r[2] += len(set(s) & acc) / len(acc); r[3] += 1
    g5 = c10 = n10 = 0
    for c in allc:
        cs = chunk(c["description"], count, 64, 200)
        E = model.encode([fc(x) for x in cs], normalize_embeddings=True, show_progress_bar=False)
        top = filer_rank(E); t = c["filer_sic"]
        g5 += t[:3] in [x[:3] for x in top[:5]]
        if t in leaf:
            n10 += 1; c10 += t in top[:10]
    cells = " | ".join(f"{r[0] / r[3]:.2f} {r[1] / r[3]:.2f} {r[2] / r[3]:.2f}" for r in res.values())
    print(f"{name:30s} | {cells} | {g5 / len(allc):.2f}  {c10 / n10:.2f}")
