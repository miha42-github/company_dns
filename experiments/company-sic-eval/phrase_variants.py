#!/usr/bin/env python3
"""Better key-phrase extraction (plan sec. 12). Same scoring as stopword_eval.py.

    arch -x86_64 python3.11 phrase_variants.py <out_dir>

E0  current extractor (chunker.phrases)
E1  + clean: drop fragments with digits or '&' or other non-word junk, strip relative
    lead-ins ("which includes", "that", "who", "the company ...")
E2  E1 + drop mostly-proper-noun fragments (names, brands: "James Gamble", "Head Shoulders")
E3  E2 + NLTK stop words decide the content words and are trimmed from both ends
E4  E3 + 2-5 word fragments only (shorter phrases match short labels better)
Scored on the 37 reviewed companies (2-5 set per system) and on the 200 filer-SIC
companies (is the filer's 3-digit group / exact class inside the recommended five).
"""
import glob, json, re, sys
from pathlib import Path
import numpy as np
from tokenizers import Tokenizer
from sentence_transformers import SentenceTransformer
from nltk.corpus import stopwords as nltk_sw
from chunker import chunk, phrases as phrases_e0, split_sentences, _SPLIT, _FILLER, _NONBIZ, _STOP

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
allc = json.loads((HERE / "companies.json").read_text())["companies"]
cos = [c for c in allc if c.get("labels_status") == "reviewed"]
NLTK = set(nltk_sw.words("english"))
LEAD = re.compile(r"^(?:which|that|who|whose|where|the company|the group|it|its|they|their|also|currently|primarily|mainly)\s+(?:(?:includes?|including|offers?|provides?|makes?|manufactures?|sells?|operates?|owns?|has|have|is|are)\s+)?", re.I)

def extract(text, mode):
    if mode == "E0": return phrases_e0(text)
    if mode == "E0fix":
        # the current extractor with only the two bug fixes: "&" means "and"; tokens containing digits
        # ("60th", "2030", "290,000") become break points instead of leaving fragments like "th on the ..."
        t = re.sub(r"\s*&\s*", " and ", text)
        t = re.sub(r"\b\S*\d\S*\b", ",", t)
        return phrases_e0(t)
    if mode == "E5":
        # E5: '&' is "and" (so "Fabric & Home Care" splits into "Fabric" and "Home Care"), tokens with digits
        # ("60th", "2030") become break points instead of deleting the fragment, relative lead-ins and stop
        # words are trimmed from the ends, no capitalisation filter (Title Case headings are real categories)
        t = re.sub(r"\s*&\s*", " and ", text)
        t = re.sub(r"\b\S*\d\S*\b", ",", t)
        out, seen = [], set()
        for s_ in split_sentences(re.sub(r"\s+", " ", t).strip()):
            for frag in _SPLIT.split(s_):
                frag = LEAD.sub("", _FILLER.sub("", frag.strip()).strip())
                w = re.findall(r"[A-Za-z][A-Za-z'\-]*", frag)
                if any(x.lower() in _NONBIZ for x in w): continue
                while w and w[0].lower() in NLTK: w = w[1:]
                while w and w[-1].lower() in NLTK: w = w[:-1]
                content = [x for x in w if x.lower() not in NLTK]
                if 1 <= len(w) <= 6 and len(content) >= 1 and len(" ".join(w)) >= 4:
                    f = " ".join(w).lower()
                    if f not in seen: seen.add(f); out.append(" ".join(w))
        return out
    out, seen = [], set()
    for s in split_sentences(re.sub(r"\s+", " ", text).strip()):
        for frag in _SPLIT.split(s):
            frag = _FILLER.sub("", frag.strip())
            frag = LEAD.sub("", frag.strip())
            if re.search(r"[\d&%$@#/*]", frag): continue            # digits, ampersands, symbols
            w = re.findall(r"[A-Za-z][A-Za-z'\-]*", frag)
            if any(x.lower() in _NONBIZ for x in w): continue
            if mode in ("E2", "E3", "E4") and len(w) >= 1:
                caps = sum(1 for i, x in enumerate(w) if x[0].isupper() and i > 0 or (i == 0 and x[0].isupper() and len(w) > 1 and w[1][0].isupper()))
                if caps / len(w) >= 0.5: continue                    # mostly names / brands
            if mode in ("E3", "E4"):
                while w and w[0].lower() in NLTK: w = w[1:]
                while w and w[-1].lower() in NLTK: w = w[:-1]
                content = [x for x in w if x.lower() not in NLTK]
            else:
                content = [x for x in w if x.lower() not in _STOP]
            hi = 5 if mode == "E4" else 7
            if 2 <= len(w) <= hi and len(content) >= 2:
                f = " ".join(w).lower()
                if f not in seen:
                    seen.add(f); out.append(" ".join(w))
    return out

def rule(E, P, key, phrase_min=0.40):
    V = C[key]["V"]; S = E @ V.T
    per = max(2, min(5, -(-5 // len(E))))
    w, best = {}, {}
    for row in S:
        o = np.argsort(-row)
        for j in o[:50]: best[j] = max(best.get(j, -1), float(row[j]))
        for j in o[:per]: w[j] = w.get(j, 0) + float(row[j])
    if P is not None and len(P):
        for row in P @ V.T:
            j = int(np.argmax(row))
            if row[j] >= phrase_min:
                w[j] = w.get(j, 0) + float(row[j]); best[j] = max(best.get(j, -1), float(row[j]))
    ranked = sorted(w, key=lambda j: (-w[j], -best[j]))[:5]
    for j in sorted(best, key=lambda j: -best[j]):
        if len(ranked) >= 2: break
        if j not in ranked: ranked.append(j)
    return ranked

cache = {}
def enc(texts):
    miss = [t for t in texts if t not in cache]
    if miss:
        for t, e in zip(miss, model.encode(miss, normalize_embeddings=True, show_progress_bar=False)): cache[t] = e
    return np.stack([cache[t] for t in texts]) if texts else None

leaf = set(C["us_sic"]["code"])
FRAMES = {"": "{p}", "industry": "{p} industry", "manufacture of": "manufacture of {p}", "business of": "business of {p}", "products": "{p} products"}
MODES = ["none (no phrases)", "E0", "E0fix", "E5"]
print(f"{'extractor':20s} {'phrases/co':>10s} | reviewed 37: US hit/prec/rec | ISIC | NACE | filer 200: group in set / class in set")
chunks_of = {c["name"]: enc(chunk(c["description"], count, 64, 200)) for c in allc}
for mode in MODES:
    res = {k: [0, 0, 0, 0] for k in KEYS}; nph = []
    for c in cos:
        ph = [] if mode.startswith("none") else extract(c["description"], mode.split(" | ")[0])
        frame = "{p}"
        nph.append(len(ph)); P = enc([frame.format(p=x) for x in ph]) if ph else None
        for k in KEYS:
            acc = set(c["acceptable"].get(k, []))
            if not acc: continue
            s = [C[k]["code"][j] for j in rule(chunks_of[c["name"]], P, k)]
            r = res[k]; r[0] += bool(set(s) & acc); r[1] += len(set(s) & acc) / len(s); r[2] += len(set(s) & acc) / len(acc); r[3] += 1
    g = cl = n4 = 0
    for c in allc:
        ph = [] if mode.startswith("none") else extract(c["description"], mode.split(" | ")[0])
        frame = "{p}"
        s = [C["us_sic"]["code"][j] for j in rule(chunks_of[c["name"]], enc([frame.format(p=x) for x in ph]) if ph else None, "us_sic")]
        t = c["filer_sic"]; g += t[:3] in [x[:3] for x in s]
        if t in leaf: n4 += 1; cl += t in s
    cells = " | ".join(f"{r[0] / r[3]:.2f} {r[1] / r[3]:.2f} {r[2] / r[3]:.2f}" for r in res.values())
    print(f"{mode:20s} {np.mean(nph):10.1f} | {cells} | {g / len(allc):.2f} / {cl / n4:.2f}")

print("\nExtracted phrases, P&G and Hitachi:")
HIT = Path("/private/tmp/claude-501/hitachi.txt").read_text().strip()
pg = next(c["description"] for c in allc if c["name"] == "Procter & Gamble")
pass
print("\nWhat the E0fix phrases match (US SIC, similarity >= 0.40):")
for label, text in (("P&G", pg), ("Hitachi", HIT)):
    ph = extract(text, "E0fix"); P = enc(ph); V = C["us_sic"]["V"]
    print(f"  {label} E0fix phrases: {ph}")
    for p, row in zip(ph, P @ V.T):
        j = int(np.argmax(row))
        if row[j] >= 0.40: print(f"  {label:8s} {p!r:40s} -> {C['us_sic']['code'][j]} {C['us_sic']['title'][j][:40]} ({row[j]:.2f})")
