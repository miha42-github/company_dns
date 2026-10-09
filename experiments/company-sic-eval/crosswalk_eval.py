#!/usr/bin/env python3
"""Can one system's codes find the matching codes in another system? (plan sec. 11)

    arch -x86_64 python3.11 crosswalk_eval.py <out_dir>      # after `eval.py dump`

E1  structural check, no labels needed: ISIC Rev.4 and NACE Rev.2 share many
    identical four-digit codes (ISIC 4791 == NACE 47.91). Given the ISIC class,
    does the matcher rank its identical NACE class near the top (and the other
    way)? Several matchers: semantic on the stored breadcrumb vectors, semantic
    on re-embedded class titles, keyword overlap, and rank-fusion of the two.
E2  the use case on the reviewed companies: take a company's US SIC codes
    (a) the reviewer-accepted ones = a perfect human narrowing, or (b) the
    automatic recommended five, map them into ISIC / NACE, and score against
    the reviewed target-system sets. Compared with matching the description to
    the target system directly.
"""
import glob, json, re, sys
from pathlib import Path
import numpy as np
from tokenizers import Tokenizer
from sentence_transformers import SentenceTransformer
from chunker import chunk

HERE = Path(__file__).parent
OUT = Path(sys.argv[1])
KEYS = ["us_sic", "isic_rev4", "nace_rev2", "japan_sic"]
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2"); model.max_seq_length = 256
unit = lambda V: V / np.linalg.norm(V, axis=1, keepdims=True)

C = {}
for k in KEYS:
    d = json.loads((OUT / f"{k}.json").read_text())
    title = [t.split(" > ")[-1] for t in d["text"]]
    C[k] = dict(code=d["code"], text=d["text"], title=title, V=unit(np.array(d["vec"], dtype=np.float32)),
                T=unit(model.encode(title, normalize_embeddings=True, show_progress_bar=False)),   # titles only, re-embedded
                idx={c: i for i, c in enumerate(d["code"])})
    print(f"{k}: {len(d['code'])} codes")

STOP = set("and or of the for to in other than not elsewhere classified n.e.c nec except including activities activity manufacture manufacturing services service products product related equipment".split())
def toks(s):
    return {w for w in re.findall(r"[a-z]+", s.lower()) if w not in STOP and len(w) > 2}
for k in KEYS:
    C[k]["tok"] = [toks(t) for t in C[k]["title"]]

def sem_breadcrumb(src, i, dst): return C[dst]["V"] @ C[src]["V"][i]
def sem_title(src, i, dst): return C[dst]["T"] @ C[src]["T"][i]
def kw(src, i, dst):
    a = C[src]["tok"][i]
    if not a: return np.zeros(len(C[dst]["code"]))
    return np.array([len(a & b) / len(a | b) if b else 0.0 for b in C[dst]["tok"]])
def rrf(*scores, k=60):
    out = np.zeros(len(scores[0]))
    for s in scores:
        order = np.argsort(-s); r = np.empty(len(s)); r[order] = np.arange(1, len(s) + 1)
        out += 1 / (k + r)
    return out
MATCHERS = {
    "semantic (breadcrumb)": sem_breadcrumb,
    "semantic (title only)": sem_title,
    "keyword overlap": kw,
    "semantic title + keyword (RRF)": lambda s, i, d: rrf(sem_title(s, i, d), kw(s, i, d)),
    "breadcrumb + title + keyword (RRF)": lambda s, i, d: rrf(sem_breadcrumb(s, i, d), sem_title(s, i, d), kw(s, i, d)),
}

# ---------------------------------------------------------------- E1
print("\nE1  ISIC Rev.4 <-> NACE Rev.2 where the four-digit code is identical (a structural, label-free check)")
nace_as_isic = {c.replace(".", ""): c for c in C["nace_rev2"]["code"]}
pairs = [(ic, nace_as_isic[ic]) for ic in C["isic_rev4"]["code"] if ic in nace_as_isic]
print(f"  {len(pairs)} identical-code pairs (ISIC has {len(C['isic_rev4']['code'])} classes, NACE {len(C['nace_rev2']['code'])})")
print(f"  {'matcher':36s}{'ISIC->NACE top1':>17s}{'top3':>7s}{'top5':>7s}{'NACE->ISIC top1':>17s}{'top3':>7s}{'top5':>7s}")
for name, fn in MATCHERS.items():
    row = []
    for src, dst, pr in (("isic_rev4", "nace_rev2", pairs), ("nace_rev2", "isic_rev4", [(b, a) for a, b in pairs])):
        hits = {1: 0, 3: 0, 5: 0}
        for a, b in pr:
            sc = fn(src, C[src]["idx"][a], dst)
            top = [C[dst]["code"][j] for j in np.argsort(-sc)[:5]]
            for n in hits:
                hits[n] += b in top[:n]
        row += [hits[1] / len(pr), hits[3] / len(pr), hits[5] / len(pr)]
    print(f"  {name:36s}" + "".join(f"{x:>{w}.2f}" for x, w in zip(row, (17, 7, 7, 17, 7, 7))))

# ---------------------------------------------------------------- E2
print("\nE2  reviewed companies: US SIC codes -> ISIC / NACE, vs the reviewed target sets")
tk = Tokenizer.from_file(glob.glob(str(HERE / "../../v4/.fastembed_cache/models--Qdrant--all-MiniLM-L6-v2-onnx/snapshots/*/tokenizer.json"))[0]); tk.no_truncation()
count = lambda s: len(tk.encode(s).ids)
cos = [c for c in json.loads((HERE / "companies.json").read_text())["companies"] if c.get("labels_status") == "reviewed"]

def auto_us_set(desc):
    """the server's rule: chunks (64) each nominate their best codes (more when few chunks), top 5 by votes then similarity."""
    cs = chunk(desc, count, 64, 200)
    E = model.encode(cs, normalize_embeddings=True, show_progress_bar=False)
    S = E @ C["us_sic"]["V"].T
    per = max(2, min(5, -(-5 // len(cs))))
    votes, best = {}, {}
    for row in S:
        for j in np.argsort(-row)[:per]:
            votes[j] = votes.get(j, 0) + 1
        for j in np.argsort(-row)[:50]:
            best[j] = max(best.get(j, -1), float(row[j]))
    ranked = sorted(votes, key=lambda j: (-votes[j], -best[j]))[:5]
    for j in sorted(best, key=lambda j: -best[j]):
        if len(ranked) >= 2: break
        if j not in ranked: ranked.append(j)
    return [C["us_sic"]["code"][j] for j in ranked], E

def us_pool(E, size=12):
    S = E @ C["us_sic"]["V"].T
    per = max(2, min(5, -(-5 // len(E))))
    votes, best = {}, {}
    for row in S:
        order = np.argsort(-row)
        for j in order[:50]:
            best[j] = max(best.get(j, -1), float(row[j]))
        for j in order[:per]:
            votes[j] = votes.get(j, 0) + 1
    ranked = sorted(best, key=lambda j: (-votes.get(j, 0), -best[j]))[:size]
    return [C["us_sic"]["code"][j] for j in ranked]

def direct_set(E, dst):
    S = E @ C[dst]["V"].T
    per = max(2, min(5, -(-5 // len(E))))
    votes, best = {}, {}
    for row in S:
        for j in np.argsort(-row)[:per]:
            votes[j] = votes.get(j, 0) + 1
        for j in np.argsort(-row)[:50]:
            best[j] = max(best.get(j, -1), float(row[j]))
    ranked = sorted(votes, key=lambda j: (-votes[j], -best[j]))[:5]
    return [C[dst]["code"][j] for j in ranked]

def pivot_set(us_codes, dst, fn, per_code=3, cap=5):
    """each selected US code nominates its best `per_code` target codes; rank by (nominations, best score); top `cap`."""
    votes, best = {}, {}
    for u in us_codes:
        sc = fn("us_sic", C["us_sic"]["idx"][u], dst)
        for r, j in enumerate(np.argsort(-sc)[:per_code]):
            votes[j] = votes.get(j, 0) + 1
            best[j] = max(best.get(j, -9), float(sc[j]))
    ranked = sorted(votes, key=lambda j: (-votes[j], -best[j]))[:cap]
    return [C[dst]["code"][j] for j in ranked]

def combined_query(us_codes, dst):
    """one query from the selected codes' titles together ('combination search')."""
    q = model.encode(["; ".join(C["us_sic"]["title"][C["us_sic"]["idx"][u]] for u in us_codes)], normalize_embeddings=True, show_progress_bar=False)[0]
    sc = C[dst]["T"] @ q
    return [C[dst]["code"][j] for j in np.argsort(-sc)[:5]]

def score(sets, key):
    hit = prec = rec = n = 0
    for c, s in sets:
        acc = set(c["acceptable"].get(key, []))
        if not acc or not s: continue
        n += 1; hit += bool(set(s) & acc); prec += len(set(s) & acc) / len(s); rec += len(set(s) & acc) / len(acc)
    return hit / n, prec / n, rec / n

rows = {}
auto = {c["name"]: auto_us_set(c["description"]) for c in cos}
for dst in ("isic_rev4", "nace_rev2"):
    res = {}
    res["direct: description -> target"] = [(c, direct_set(auto[c["name"]][1], dst)) for c in cos]
    for src_name, src in (("oracle US set", lambda c: c["acceptable"]["us_sic"]), ("auto US set", lambda c: auto[c["name"]][0])):
        for name in ("semantic (title only)", "semantic title + keyword (RRF)", "breadcrumb + title + keyword (RRF)"):
            res[f"pivot[{src_name}]: {name}"] = [(c, pivot_set(src(c), dst, MATCHERS[name])) for c in cos]
        res[f"pivot[{src_name}]: combined query"] = [(c, combined_query(src(c), dst)) for c in cos]
    print(f"\n  target: {dst}   (any plausible / precision / recall, n={len(cos)})")
    for name, sets in res.items():
        h, p, r = score(sets, dst)
        print(f"    {name:62s}{h:6.2f}{p:7.2f}{r:7.2f}")

# ---------------------------------------------------------------- E2b
print("\nE2b  a person picks plausible US codes from the stepper's 12-code menu (simulated), then we map")
def human_from_pool(c, E):
    acc = set(c["acceptable"]["us_sic"])
    chosen = [u for u in us_pool(E) if u in acc][:5]
    return chosen, (len(chosen) > 0)
sim = {c["name"]: human_from_pool(c, auto[c["name"]][1]) for c in cos}
found = sum(1 for v in sim.values() if v[1])
print(f"  the menu contains at least one accepted US code for {found}/{len(cos)} companies; where it does not, the person has nothing right to pick (falls back to the automatic five)")
for dst in ("isic_rev4", "nace_rev2"):
    res = {}
    res["direct: description -> target"] = [(c, direct_set(auto[c["name"]][1], dst)) for c in cos]
    pick = lambda c: sim[c["name"]][0] if sim[c["name"]][1] else auto[c["name"]][0]
    res["pivot[person picks from menu]: semantic (title only)"] = [(c, pivot_set(pick(c), dst, MATCHERS["semantic (title only)"])) for c in cos]
    res["pivot[person picks from menu]: breadcrumb + title + keyword"] = [(c, pivot_set(pick(c), dst, MATCHERS["breadcrumb + title + keyword (RRF)"])) for c in cos]
    res["pivot[person picks from menu]: combined query"] = [(c, combined_query(pick(c), dst)) for c in cos]
    # pivot results first, then fill from the direct set (fusion by union, pivot first)
    def fuse(c):
        p = pivot_set(pick(c), dst, MATCHERS["semantic (title only)"], cap=3)
        d = [x for x in direct_set(auto[c["name"]][1], dst) if x not in p]
        return (p + d)[:5]
    res["pivot (3) + direct (fill to 5)"] = [(c, fuse(c)) for c in cos]
    only = [c for c in cos if sim[c["name"]][1]]
    print(f"\n  target: {dst}   any plausible / precision / recall  (all {len(cos)}; and only the {len(only)} where the menu had a right code)")
    for name, sets in res.items():
        h, p, r = score(sets, dst)
        sub = [(c, s) for c, s in sets if sim[c["name"]][1]]
        h2, p2, r2 = score(sub, dst)
        print(f"    {name:58s}{h:6.2f}{p:7.2f}{r:7.2f}   |{h2:6.2f}{p2:7.2f}{r2:7.2f}")

# Japan has no reviewed sets: eyeball a few mappings
print("\nJapan SIC (no reviewed sets yet): top 3 for some US SIC codes, title+keyword RRF")
for u in ("3571", "2834", "5812", "4812", "3711", "7372"):
    if u not in C["us_sic"]["idx"]: continue
    sc = MATCHERS["semantic title + keyword (RRF)"]("us_sic", C["us_sic"]["idx"][u], "japan_sic")
    print(f"  US {u} {C['us_sic']['title'][C['us_sic']['idx'][u]][:38]:38s} -> " + " | ".join(f"{C['japan_sic']['code'][j]} {C['japan_sic']['title'][j][:30]}" for j in np.argsort(-sc)[:3]))
