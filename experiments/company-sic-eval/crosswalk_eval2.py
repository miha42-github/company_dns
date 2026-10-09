#!/usr/bin/env python3
"""The semantic mapper against the OFFICIAL crosswalks (plan sec. 11).

    arch -x86_64 python3.11 crosswalk_eval2.py <out_dir>

E3  every source code vs the official table: does the matcher's top-k contain a
    code the official crosswalk lists? (US SIC -> ISIC Rev.4 / NACE Rev.2 via the
    UN chain; ISIC Rev.4 <-> NACE Rev.2 direct.)
E4  the reviewed companies: take the US codes a person would pick, then
      (a) the official crosswalk alone (unranked set), (b) the semantic mapper,
      (c) official candidates re-ranked by how well each fits the description
    scored against the reviewed ISIC / NACE sets.
"""
import glob, json, re, sys
from pathlib import Path
import numpy as np
from tokenizers import Tokenizer
from sentence_transformers import SentenceTransformer
from chunker import chunk
import official_crosswalks as oc

HERE = Path(__file__).parent
OUT = Path(sys.argv[1])
KEYS = ["us_sic", "isic_rev4", "nace_rev2", "japan_sic"]
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2"); model.max_seq_length = 256
unit = lambda V: V / np.linalg.norm(V, axis=1, keepdims=True)
STOP = set("and or of the for to in other than not elsewhere classified n.e.c nec except including activities activity manufacture manufacturing services service products product related equipment".split())
toks = lambda s: {w for w in re.findall(r"[a-z]+", s.lower()) if w not in STOP and len(w) > 2}

C = {}
for k in KEYS:
    d = json.loads((OUT / f"{k}.json").read_text())
    title = [t.split(" > ")[-1] for t in d["text"]]
    C[k] = dict(code=d["code"], title=title, V=unit(np.array(d["vec"], dtype=np.float32)),
                T=unit(model.encode(title, normalize_embeddings=True, show_progress_bar=False)),
                idx={c: i for i, c in enumerate(d["code"])}, tok=[toks(t) for t in title])

def sem_bc(s, i, d): return C[d]["V"] @ C[s]["V"][i]
def sem_ti(s, i, d): return C[d]["T"] @ C[s]["T"][i]
def kw(s, i, d):
    a = C[s]["tok"][i]
    return np.array([len(a & b) / len(a | b) if (a and b) else 0.0 for b in C[d]["tok"]])
def rrf(*sc, k=60):
    out = np.zeros(len(sc[0]))
    for x in sc:
        o = np.argsort(-x); r = np.empty(len(x)); r[o] = np.arange(1, len(x) + 1); out += 1 / (k + r)
    return out
MATCHERS = {"semantic breadcrumb": sem_bc, "semantic title": sem_ti, "keyword": kw,
            "title + keyword (RRF)": lambda s, i, d: rrf(sem_ti(s, i, d), kw(s, i, d)),
            "breadcrumb + title + keyword (RRF)": lambda s, i, d: rrf(sem_bc(s, i, d), sem_ti(s, i, d), kw(s, i, d))}

# ------------------------------------------------------------------ E3
i4n2, n2i4 = oc.isic4_nace2()
j2i, i2j = oc.jsic13_isic4()
OFFICIAL = {("us_sic", "isic_rev4"): oc.us_to_isic4(), ("us_sic", "nace_rev2"): oc.us_to_nace2(),
            ("isic_rev4", "nace_rev2"): i4n2, ("nace_rev2", "isic_rev4"): n2i4,
            ("isic_rev4", "japan_sic"): i2j, ("japan_sic", "isic_rev4"): j2i, ("us_sic", "japan_sic"): oc.us_to_jsic13()}
print("E3  semantic mapper vs the official crosswalk (any official counterpart in the top k)\n")
for (src, dst), tab in OFFICIAL.items():
    codes = [c for c in C[src]["code"] if c in tab and any(g in C[dst]["idx"] for g in tab[c])]
    print(f"{src} -> {dst}: {len(codes)} of {len(C[src]['code'])} source codes have an official counterpart present in our corpus; mean {np.mean([len([g for g in tab[c] if g in C[dst]['idx']]) for c in codes]):.1f} counterparts each")
    print(f"  {'matcher':36s}{'top1':>7s}{'top3':>7s}{'top5':>7s}{'top10':>7s}")
    for name, fn in MATCHERS.items():
        h = {1: 0, 3: 0, 5: 0, 10: 0}
        for c in codes:
            G = {g for g in tab[c] if g in C[dst]["idx"]}
            top = [C[dst]["code"][j] for j in np.argsort(-fn(src, C[src]["idx"][c], dst))[:10]]
            for n in h: h[n] += bool(G & set(top[:n]))
        print(f"  {name:36s}" + "".join(f"{h[n] / len(codes):7.2f}" for n in h))
    print()

# ------------------------------------------------------------------ E4
tk = Tokenizer.from_file(glob.glob(str(HERE / "../../v4/.fastembed_cache/models--Qdrant--all-MiniLM-L6-v2-onnx/snapshots/*/tokenizer.json"))[0]); tk.no_truncation()
count = lambda s: len(tk.encode(s).ids)
cos = [c for c in json.loads((HERE / "companies.json").read_text())["companies"] if c.get("labels_status") == "reviewed"]

def nominate(E, key, per_cap=5):
    S = E @ C[key]["V"].T
    per = max(2, min(5, -(-per_cap // len(E))))
    votes, best = {}, {}
    for row in S:
        o = np.argsort(-row)
        for j in o[:50]: best[j] = max(best.get(j, -1), float(row[j]))
        for j in o[:per]: votes[j] = votes.get(j, 0) + 1
    return sorted(best, key=lambda j: (-votes.get(j, 0), -best[j]))
def prep(c):
    cs = chunk(c["description"], count, 64, 200)
    E = model.encode(cs, normalize_embeddings=True, show_progress_bar=False)
    order = nominate(E, "us_sic")
    return E, [C["us_sic"]["code"][j] for j in order[:5]], [C["us_sic"]["code"][j] for j in order[:12]]
prepared = {c["name"]: prep(c) for c in cos}

def score(rows, key):
    n = hit = pr = rc = size = 0
    for c, s in rows:
        acc = set(c["acceptable"].get(key, []))
        if not acc or not s: continue
        n += 1; hit += bool(set(s) & acc); pr += len(set(s) & acc) / len(s); rc += len(set(s) & acc) / len(acc); size += len(s)
    return hit / n, pr / n, rc / n, size / n

def pivot_semantic(us, dst, fn, per=3, cap=5):
    votes, best = {}, {}
    for u in us:
        sc = fn("us_sic", C["us_sic"]["idx"][u], dst)
        for j in np.argsort(-sc)[:per]:
            votes[j] = votes.get(j, 0) + 1; best[j] = max(best.get(j, -9), float(sc[j]))
    return [C[dst]["code"][j] for j in sorted(votes, key=lambda j: (-votes[j], -best[j]))[:cap]]

def official_set(us, dst):
    tab = OFFICIAL[("us_sic", dst)]
    out = []
    for u in us:
        for g in sorted(tab.get(u, ())):
            if g in C[dst]["idx"] and g not in out: out.append(g)
    return out

def official_rerank(us, dst, E, cap=5):
    cand = official_set(us, dst)
    if not cand: return []
    S = (E @ C[dst]["V"].T).max(0)
    return sorted(cand, key=lambda g: -S[C[dst]["idx"][g]])[:cap]

def direct(E, dst): 
    return [C[dst]["code"][j] for j in nominate(E, dst)[:5]]

def picks(c, mode):
    acc = set(c["acceptable"]["us_sic"]); E, auto, pool = prepared[c["name"]]
    if mode == "oracle": return list(acc)[:5]
    if mode == "menu": 
        got = [u for u in pool if u in acc][:5]
        return got if got else auto
    return auto

print("E4  reviewed companies, US codes -> ISIC / NACE.  any plausible / precision / recall / mean set size\n")
for dst in ("isic_rev4", "nace_rev2"):
    print(f"  target {dst} (n={len(cos)})")
    print(f"    {'method':64s}{'any':>6s}{'prec':>7s}{'rec':>7s}{'size':>6s}")
    rows = {"direct: description -> target (no US step)": [(c, direct(prepared[c['name']][0], dst)) for c in cos]}
    for mode, label in (("oracle", "perfect US set"), ("menu", "person picks from the 12-code menu"), ("auto", "automatic US five")):
        rows[f"[{label}] official crosswalk alone (unranked set)"] = [(c, official_set(picks(c, mode), dst)) for c in cos]
        rows[f"[{label}] official candidates re-ranked by the description"] = [(c, official_rerank(picks(c, mode), dst, prepared[c['name']][0])) for c in cos]
        rows[f"[{label}] semantic mapper (titles)"] = [(c, pivot_semantic(picks(c, mode), dst, sem_ti)) for c in cos]
    for name, r in rows.items():
        h, p, rc, sz = score(r, dst)
        print(f"    {name:64s}{h:6.2f}{p:7.2f}{rc:7.2f}{sz:6.1f}")
    print()
