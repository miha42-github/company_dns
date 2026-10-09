#!/usr/bin/env python3
"""Company -> SIC match evaluation (docs/plans/company-sic-match.md sec. 3, 8).

    python3 eval.py dump <tmp_dir> <out_dir>     # needs pyarrow: US SIC corpus -> JSON
    python3 eval.py run  <out_dir> [--sizes 64,96,128,160,200] [--json results.json]
                                                 # needs numpy + sentence-transformers + tokenizers

Strategies compared on companies.json (description snapshot + filer SEC SIC):
  trunc256   today's behaviour: the model reads the first 256 tokens only
  max        chunk, embed each chunk, a code's score = its best chunk similarity
  vote       chunk, rank per chunk, fuse the per-chunk rankings with RRF (k=60)
  meanvec    chunk, average the chunk vectors, search once (expected to be no better)

Metrics are measured at division (2-digit), group (3-digit) and class (4-digit)
level against the code the company filed with the SEC. The filer code is a weak
label (one code per filer, chosen by primary revenue), so every difference is
reported with a paired-bootstrap 95% interval; "better" means the interval
excludes zero. Only the US SIC corpus has filer codes, so this run is US-only;
other systems join once `acceptable` sets are filled in (README.md).
"""
import json, random, sys, glob
from pathlib import Path

HERE = Path(__file__).parent
RRF_K = 60
# key in companies.json `acceptable`  ->  dumped feather
SYSTEM_FILES = {"us_sic": "us_flat_embedded.feather", "isic_rev4": "isic_rev4_flat_embedded.feather",
                "nace_rev2": "nace_rev2_flat_embedded.feather"}
# also dumped (no acceptable sets yet, used by crosswalk_eval.py)
EXTRA_FILES = {"japan_sic": "japan_rev13_flat_embedded.feather"}
TOKENIZER_GLOB = str(HERE / "../../v4/.fastembed_cache/models--Qdrant--all-MiniLM-L6-v2-onnx/snapshots/*/tokenizer.json")


def dump(tmp, out):
    import pyarrow.feather as f
    Path(out).mkdir(parents=True, exist_ok=True)
    for key, name in {**SYSTEM_FILES, **EXTRA_FILES}.items():
        t = f.read_table(Path(tmp) / name)
        (Path(out) / f"{key}.json").write_text(json.dumps({
            "vec": t.column("vector_all_minilm_l6_v2").to_pylist(),
            "code": t.column("class_id").to_pylist(),
            "text": t.column("embedding_text").to_pylist(),
        }))
        print(f"wrote {Path(out) / (key + '.json')} ({t.num_rows} rows)")


def run(out, sizes, json_out):
    import numpy as np
    from tokenizers import Tokenizer
    from sentence_transformers import SentenceTransformer
    from chunker import chunk

    corpus = json.loads((Path(out) / "us_sic.json").read_text())
    V = np.array(corpus["vec"], dtype=np.float32)
    V /= np.linalg.norm(V, axis=1, keepdims=True)
    codes = corpus["code"]
    code_set = set(codes)
    companies = json.loads((HERE / "companies.json").read_text())["companies"]

    tk = Tokenizer.from_file(glob.glob(TOKENIZER_GLOB)[0])
    tk.no_truncation()
    count = lambda s: len(tk.encode(s).ids)
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    model.max_seq_length = 256
    cache = {}

    def enc(texts):
        miss = [t for t in texts if t not in cache]
        if miss:
            for t, e in zip(miss, model.encode(miss, normalize_embeddings=True, show_progress_bar=False)):
                cache[t] = np.asarray(e, dtype=np.float32)
        return np.stack([cache[t] for t in texts])

    def ranked(scores):  # distinct codes, best first
        seen, order = set(), []
        for i in np.argsort(-scores):
            if codes[i] not in seen:
                seen.add(codes[i])
                order.append(codes[i])
        return order

    def vote(S):  # S: chunks x rows
        fused = np.zeros(S.shape[1])
        for row in S:
            ranks = np.empty(S.shape[1])
            ranks[np.argsort(-row)] = np.arange(1, S.shape[1] + 1)
            fused += 1.0 / (RRF_K + ranks)
        return fused

    strategies = ["trunc256"] + [f"{m}{s}" for s in sizes for m in ("max", "vote", "meanvec")]
    results = {s: [] for s in strategies}
    meta = []
    for c in companies:
        d, truth = c["description"], c["filer_sic"]
        meta.append({"name": c["name"], "tokens": count(d), "truth": truth, "in_corpus": truth in code_set})
        results["trunc256"].append(ranked(V @ enc([d])[0]))
        for s in sizes:
            cs = chunk(d, count, target=s, hard_cap=max(200, s))
            E = enc(cs)
            S = E @ V.T
            results[f"max{s}"].append(ranked(S.max(0)))
            results[f"vote{s}"].append(ranked(vote(S)))
            mv = E.mean(0)
            results[f"meanvec{s}"].append(ranked(V @ (mv / np.linalg.norm(mv))))
            meta[-1][f"chunks{s}"] = len(cs)

    def hits(strategy, digits, k):
        """1/0 per company: truth's first `digits` characters appear among the top-k codes' prefixes."""
        res = []
        for r, m in zip(results[strategy], meta):
            if digits == 4 and not m["in_corpus"]:
                res.append(None)  # filer code is not a leaf in this corpus: cannot score at 4 digits
                continue
            top = []
            for code in r:
                p = code[:digits]
                if p not in top:
                    top.append(p)
                if len(top) == k:
                    break
            res.append(1 if m["truth"][:digits] in top else 0)
        return res

    def mean(xs):
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else float("nan")

    rng = random.Random(7)
    boots = [[rng.randrange(len(meta)) for _ in meta] for _ in range(2000)]

    def delta_ci(a, b):
        pairs = [(x, y) for x, y in zip(a, b)]
        diffs = []
        for idx in boots:
            sel = [pairs[i] for i in idx if pairs[i][0] is not None]
            if sel:
                diffs.append(sum(x - y for x, y in sel) / len(sel))
        diffs.sort()
        return diffs[int(.025 * len(diffs))], diffs[int(.975 * len(diffs))]

    n4 = sum(m["in_corpus"] for m in meta)
    print(f"companies: {len(meta)}   filer code is a 4-digit leaf in the US corpus: {n4}")
    long_ = sum(m["tokens"] > 256 for m in meta)
    print(f"descriptions > 256 tokens: {long_}   median tokens: {sorted(m['tokens'] for m in meta)[len(meta)//2]}\n")
    cols = [("4d@10", 4, 10), ("3d@5", 3, 5), ("3d@10", 3, 10), ("2d@3", 2, 3)]
    print(f"{'strategy':14s}" + "".join(f"{c[0]:>8s}" for c in cols) + "    delta vs trunc256 (95% CI)   3d@5 / 4d@10")
    summary = {}
    for s in strategies:
        row = {c[0]: mean(hits(s, c[1], c[2])) for c in cols}
        summary[s] = row
        line = f"{s:14s}" + "".join(f"{row[c[0]]:8.2f}" for c in cols)
        if s != "trunc256":
            lo3, hi3 = delta_ci(hits(s, 3, 5), hits("trunc256", 3, 5))
            lo4, hi4 = delta_ci(hits(s, 4, 10), hits("trunc256", 4, 10))
            line += f"    [{lo3:+.2f},{hi3:+.2f}]  [{lo4:+.2f},{hi4:+.2f}]"
        print(line)

    print("\nby description length, 3d@5  (trunc256 vs the best-looking max strategy)")
    best = max((s for s in strategies if s.startswith("max")), key=lambda s: summary[s]["3d@5"])
    for label, lo, hi in (("<=128 tok", 0, 128), ("129-256", 129, 256), (">256", 257, 10**6)):
        idx = [i for i, m in enumerate(meta) if lo <= m["tokens"] <= hi]
        a = [hits("trunc256", 3, 5)[i] for i in idx]
        b = [hits(best, 3, 5)[i] for i in idx]
        print(f"  {label:10s} n={len(idx):2d}  trunc256 {mean(a):.2f}   {best} {mean(b):.2f}")
    # ---- hand-judged acceptable sets (draft), every system ----------------------------------
    labelled = [i for i, c in enumerate(companies) if c.get("acceptable")]
    if labelled:
        print(f"\nacceptable-set metrics on {len(labelled)} hand-drafted companies "
              f"(any@k = a plausible code is in the top k; recall@10 = share of plausible codes in the top 10)")
        picks = ["trunc256"] + [f"{m}{s}" for s in (128, 200) for m in ("max", "vote", "meanvec") if s in sizes]
        picks = [p for p in picks if p in strategies]
        # re-rank per system from the cached chunk embeddings
        for key in SYSTEM_FILES:
            cp = json.loads((Path(out) / f"{key}.json").read_text())
            Vs = np.array(cp["vec"], dtype=np.float32)
            Vs /= np.linalg.norm(Vs, axis=1, keepdims=True)
            cds = cp["code"]
            def rank_sys(scores):
                seen, order = set(), []
                for i in np.argsort(-scores):
                    if cds[i] not in seen:
                        seen.add(cds[i]); order.append(cds[i])
                return order
            print(f"\n  {key}")
            print(f"  {'strategy':14s}{'any@3':>8s}{'any@10':>8s}{'recall@10':>11s}   delta any@10 vs trunc256 (95% CI)")
            base_any = None
            for p in picks:
                a3, a10, rc = [], [], []
                for i in labelled:
                    d = companies[i]["description"]
                    acc = set(companies[i]["acceptable"].get(key, []))
                    if not acc:
                        continue
                    if p == "trunc256":
                        r = rank_sys(Vs @ enc([d])[0])
                    else:
                        size = int("".join(ch for ch in p if ch.isdigit()))
                        cs = chunk(d, count, target=size, hard_cap=max(200, size))
                        E = enc(cs); S_ = E @ Vs.T
                        if p.startswith("max"): r = rank_sys(S_.max(0))
                        elif p.startswith("vote"): r = rank_sys(vote(S_))
                        else:
                            mv = E.mean(0); r = rank_sys(Vs @ (mv / np.linalg.norm(mv)))
                    a3.append(1 if acc & set(r[:3]) else 0)
                    a10.append(1 if acc & set(r[:10]) else 0)
                    rc.append(len(acc & set(r[:10])) / len(acc))
                line = f"  {p:14s}{mean(a3):8.2f}{mean(a10):8.2f}{mean(rc):11.2f}"
                if base_any is None:
                    base_any = a10
                else:
                    ds = []
                    for _ in range(2000):
                        idx = [rng.randrange(len(a10)) for _ in a10]
                        ds.append(sum(a10[j] - base_any[j] for j in idx) / len(idx))
                    ds.sort()
                    line += f"   [{ds[50]:+.2f},{ds[1949]:+.2f}]"
                print(line)
    if json_out:
        Path(json_out).write_text(json.dumps({"meta": meta, "summary": summary}, indent=1))
        print(f"\nwrote {json_out}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 3 and a[0] == "dump":
        dump(a[1], a[2])
    elif len(a) >= 2 and a[0] == "run":
        sizes = [int(x) for x in (a[a.index("--sizes") + 1] if "--sizes" in a else "64,96,128,160,200").split(",")]
        run(a[1], sizes, a[a.index("--json") + 1] if "--json" in a else None)
    else:
        print(__doc__)
        sys.exit(2)
