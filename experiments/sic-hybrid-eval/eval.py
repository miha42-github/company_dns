#!/usr/bin/env python3
"""Regression harness for hybrid (keyword + semantic, RRF) SIC search.

    python3 eval.py dump     <tmp_dir> <out_dir>    # needs pyarrow
    python3 eval.py simulate <out_dir>              # needs numpy + sentence-transformers
    python3 eval.py server   <out_dir> <base_url>   # stdlib only

The two Python environments are separate on purpose: on the machine this was
written on, pyarrow and numpy/sentence-transformers live in different
installs, so `dump` turns the four feather files into plain JSON plus raw
float32 vectors that the other two commands read. See README.md and
docs/plans/sic-hybrid-search.md section 3 (method) and section 5 (gate).

`simulate` reproduces the offline method the plan was validated with.
`server` scores the live endpoints (similarity vs hybrid) the same way and is
the acceptance check that the SQL does what the simulation did. Both exit 1
when a threshold fails.

Metrics, over one merged list: any@k = a correct row from ANY of the four
systems is in the top k; MRR = mean 1/(rank of the first correct row);
pair@10 = share of (concept x system) pairs whose correct row is in the top 10.
"""
import json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
SYSTEMS = [  # key, label, feather file
    ("us", "US SIC", "us_flat_embedded.feather"),
    ("japan", "Japan SIC", "japan_rev13_flat_embedded.feather"),
    ("nace", "EU NACE", "nace_rev2_flat_embedded.feather"),
    ("isic", "ISIC", "isic_rev4_flat_embedded.feather"),
]
FORMS = ["short", "long", "term"]
RRF_K = 60
POOL = 50
UA = "sic-hybrid-eval/1.0 (michael.hay@mediumroast.io)"
# Thresholds (plan section 5). Margins leave room for sampling noise on 37 concepts.
MIN_TERM_HYBRID_ANY10 = 0.95
MIN_TERM_MRR_VS_SEMANTIC = 0.0     # hybrid MRR must be >= semantic MRR on single terms
MAX_SHORT_MRR_LOSS = 0.08          # hybrid may trail semantic by at most this on phrases


def concepts():
    return json.loads((HERE / "concepts.json").read_text())["concepts"]


# --------------------------------------------------------------------- dump
def cmd_dump(tmp_dir, out_dir):
    import array
    import pyarrow.feather as feather
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    for key, label, fname in SYSTEMS:
        t = feather.read_table(Path(tmp_dir) / fname)
        cols = {c: t.column(c).to_pylist() for c in ("unique_key", "class_id", "class_desc")}
        cols["label"] = label
        (out / f"{key}.json").write_text(json.dumps(cols))
        vecs = t.column("vector_all_minilm_l6_v2").to_pylist()
        (out / f"{key}.f32").write_bytes(array.array("f", [x for v in vecs for x in v]).tobytes())
        print(f"{key}: {t.num_rows} rows")


def load_dump(out_dir):
    out = Path(out_dir)
    return {k: json.loads((out / f"{k}.json").read_text()) for k, _, _ in SYSTEMS}


def answer_key(D):
    """concept index -> {system: set(unique_key)}; fails loudly on an unknown class id."""
    by_class = {k: {c: u for c, u in zip(D[k]["class_id"], D[k]["unique_key"])} for k in D}
    key = []
    for c in concepts():
        per = {}
        for k, ids in c["classes"].items():
            for cid in ids:
                if cid not in by_class[k]:
                    sys.exit(f"concept {c['concept']!r}: class id {cid} not in system {k}")
            per[k] = {by_class[k][cid] for cid in ids}
        key.append(per)
    return key


# ------------------------------------------------------------------ metrics
def score(lists, key):
    """lists[i] = ordered unique_keys (or (unique_key, position) pairs) for concept i."""
    n = len(key); any1 = any3 = any10 = 0; mrr = 0.0; p10 = pairs = 0
    for order, per in zip(lists, key):
        pos = {}
        for i, item in enumerate(order, 1):
            uk, p = item if isinstance(item, tuple) else (item, i)
            pos.setdefault(uk, p)
        allc = set().union(*per.values())
        hit = [pos[u] for u in allc if u in pos]
        first = min(hit) if hit else None
        if first is not None:
            any1 += first <= 1; any3 += first <= 3; any10 += first <= 10; mrr += 1 / first
        for k, ids in per.items():
            pairs += 1
            g = [pos[u] for u in ids if u in pos]
            p10 += bool(g) and min(g) <= 10
    return dict(any1=any1 / n, any3=any3 / n, any10=any10 / n, mrr=mrr / n, pair10=p10 / pairs)


def table(title, rows):
    print(f"\n=== {title} ===")
    print(f"{'method':22}{'any@1':>7}{'any@3':>7}{'any@10':>8}{'MRR':>7}{'pair@10':>9}")
    for name, r in rows.items():
        print(f"{name:22}{r['any1']:7.2f}{r['any3']:7.2f}{r['any10']:8.2f}{r['mrr']:7.2f}{r['pair10']:9.2f}")


def gate(results, identical_long, label):
    fails = []
    t = results["term"]
    if t["hybrid"]["any10"] < MIN_TERM_HYBRID_ANY10:
        fails.append(f"single-term hybrid any@10 {t['hybrid']['any10']:.2f} < {MIN_TERM_HYBRID_ANY10}")
    if t["hybrid"]["mrr"] < t["semantic"]["mrr"] + MIN_TERM_MRR_VS_SEMANTIC:
        fails.append(f"single-term hybrid MRR {t['hybrid']['mrr']:.2f} below semantic {t['semantic']['mrr']:.2f}")
    s = results["short"]
    if s["hybrid"]["mrr"] < s["semantic"]["mrr"] - MAX_SHORT_MRR_LOSS:
        fails.append(f"short-phrase hybrid MRR {s['hybrid']['mrr']:.2f} trails semantic {s['semantic']['mrr']:.2f} by more than {MAX_SHORT_MRR_LOSS}")
    if identical_long:
        fails.append(f"long sentences where hybrid scores differ from semantic (keyword found nothing): {identical_long}")
    print(f"\n[{label}] " + ("PASS" if not fails else "FAIL"))
    for f in fails:
        print("  -", f)
    return not fails


# ----------------------------------------------------------------- simulate
def cmd_simulate(out_dir):
    import numpy as np
    from sentence_transformers import SentenceTransformer
    D = load_dump(out_dir); key = answer_key(D)
    keys = [k for k, _, _ in SYSTEMS]
    rows = [(k, i) for k in keys for i in range(len(D[k]["unique_key"]))]
    uk = [D[k]["unique_key"][i] for k, i in rows]
    low = [D[k]["class_desc"][i].lower() for k, i in rows]
    V = np.vstack([np.fromfile(Path(out_dir) / f"{k}.f32", dtype=np.float32).reshape(len(D[k]["unique_key"]), 384) for k in keys])
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu")
    results = {}; long_diff = []
    for form in FORMS:
        qs = [c[form] for c in concepts()]
        Q = model.encode(qs, batch_size=64, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        sem_l, kw_l, hy_l = [], [], []
        for ci, q in enumerate(qs):
            s = V @ Q[ci]; sem = [int(g) for g in np.argsort(-s)]
            sem_l.append([uk[g] for g in sem[:200]])
            t = q.lower()
            kw = sorted((l.find(t), g) for g, l in enumerate(low) if t in l)
            # keyword-only: ties take the mid-rank of their group
            kl = []; i = 0
            while i < len(kw):
                j = i
                while j < len(kw) and kw[j][0] == kw[i][0]:
                    j += 1
                kl += [(uk[g], (i + 1 + j) / 2) for _, g in kw[i:j]]; i = j
            kw_l.append(kl)
            kr = {}; last = None; rank = 0
            for pos, (m, g) in enumerate(kw, 1):
                if m != last:
                    rank = pos; last = m
                kr[g] = rank
            sr = {g: i + 1 for i, g in enumerate(sem[:POOL])}
            sc = {g: (1 / (RRF_K + kr[g]) if g in kr else 0) + (1 / (RRF_K + sr[g]) if g in sr else 0) for g in set(kr) | set(sr)}
            fused = sorted(sc, key=lambda g: (-sc[g], sr.get(g, 10**6), uk[g]))
            hy_l.append([uk[g] for g in fused])
            if form == "long" and not kw and [uk[g] for g in fused[:10]] != [uk[g] for g in sem[:10]]:
                long_diff.append(concepts()[ci]["concept"])
        results[form] = {"semantic": score(sem_l, key), "keyword": score(kw_l, key), "hybrid": score(hy_l, key)}
        nkw = sum(1 for l in kw_l if l)
        table(f"simulate / {form} (keyword finds anything for {nkw} of {len(qs)})", results[form])
    return 0 if gate(results, long_diff, "simulate") else 1


# ------------------------------------------------------------------- server
def get(url):
    for attempt in range(6):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 * (attempt + 1)); continue
            if e.code == 404:
                return {"data": []}
            raise
    sys.exit("rate limited repeatedly; wait and retry")


def cmd_server(out_dir, base):
    D = load_dump(out_dir); key = answer_key(D)
    base = base.rstrip("/")
    results = {}; long_diff = []
    for form in FORMS:
        sem_l, hy_l = [], []
        for c in concepts():
            q = urllib.parse.quote(c[form], safe="")
            sem_h = get(f"{base}/V4.0/global/sic/similarity/{q}?k=50")["data"] or []
            hyb_h = get(f"{base}/V4.0/global/sic/hybrid/{q}?k=50")["data"] or []
            sem = [h["unique_key"] for h in sem_h]; hyb = [h["unique_key"] for h in hyb_h]
            sem_l.append(sem); hy_l.append(hyb)
            # When keyword finds nothing hybrid must equal semantic. Compare the
            # ordered similarity scores, not row identities: identical rows in two
            # systems (e.g. NACE 02.40 and ISIC 0240 share their text) tie exactly
            # and may swap places without the results being different.
            if form == "long" and not any(h["keyword_rank"] for h in hyb_h):
                if [round(h["similarity"], 4) for h in hyb_h[:10]] != [round(h["similarity"], 4) for h in sem_h[:10]]:
                    long_diff.append(c["concept"])
            time.sleep(0.05)
        results[form] = {"semantic": score(sem_l, key), "hybrid": score(hy_l, key)}
        table(f"server / {form}", results[form])
    return 0 if gate(results, long_diff, "server") else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == "dump":
        cmd_dump(a[1], a[2])
    elif len(a) == 2 and a[0] == "simulate":
        sys.exit(cmd_simulate(a[1]))
    elif len(a) == 3 and a[0] == "server":
        sys.exit(cmd_server(a[1], a[2]))
    else:
        sys.exit(__doc__)
