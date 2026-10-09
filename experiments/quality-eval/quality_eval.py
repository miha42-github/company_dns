"""
Quality evaluation for embedding models, against real US SIC data.

No labeled benchmark exists for this dataset, so this uses the SIC
hierarchy itself as a weak-label proxy for "should be semantically
related": two rows sharing a group_id are, by construction, more
related than two rows in different groups. A better embedding model
should reflect that structure more strongly in its vector space.

See docs/plans/go-duckdb-rewrite.md sec7.6 for results and interpretation
(the recall@k numbers are the trustworthy ones - precision@k is capped
low by this dataset's many small/singleton groups, included only for
transparency about what was tried first).

Usage:
    python3 quality_eval.py /path/to/some_embedded.feather

Requires numpy + pyarrow (not part of company_dns's own dependencies -
this is analysis tooling, not application code). A venv is recommended:
    python3 -m venv venv && venv/bin/pip install numpy pyarrow
    venv/bin/python quality_eval.py /path/to/file.feather
"""
import sys

import numpy as np
import pyarrow.feather as feather

# Maps a friendly label to the vector column name. Adjust this if
# evaluating a differently-named file (e.g. company data instead of
# SIC/NACE) - these names match us_flat_embedded.feather specifically.
MODELS = {
    "all_minilm_l6_v2": "vector_all_minilm_l6_v2",
    "bge_small_en_v15": "vector_bge_small_en_v15",
    "all_mpnet_base_v2": "vector_all_mpnet_base_v2",
    "e5_base_v2": "vector_e5_base_v2",
}

# Column used as the ground-truth grouping label. group_id is the level
# used in the docs/plans/go-duckdb-rewrite.md sec7.6 writeup - division_id
# or class_id would give a coarser/finer grouping if re-running this.
LABEL_COLUMN = "group_id"


def main(path: str) -> None:
    table = feather.read_table(path)
    labels = np.array(table.column(LABEL_COLUMN).to_pylist())
    n = len(labels)

    same_group = labels[:, None] == labels[None, :]
    np.fill_diagonal(same_group, False)
    has_peer = same_group.any(axis=1)
    n_same_pairs = same_group.sum()

    print(f"n={n} rows, label column={LABEL_COLUMN!r}")
    print(f"{n_same_pairs} same-group pairs, {has_peer.sum()} rows have >=1 same-group peer")
    print(f"({n - has_peer.sum()} singleton-group rows excluded from recall@k/hit@1 below)\n")

    print("--- Separation margin (all rows) ---")
    print(f"{'model':22s} {'same-grp sim':>13s} {'diff-grp sim':>13s} {'margin':>8s}")
    margins = {}
    sims_by_model = {}
    for label, col in MODELS.items():
        if col not in table.column_names:
            print(f"{label:22s} (column {col!r} not present, skipping)")
            continue
        arr = np.stack(table.column(col).to_pylist()).astype(np.float32)
        sims = arr @ arr.T  # cosine similarity, assumes normalized vectors
        sims_by_model[label] = sims

        same_sim = sims[same_group].mean()
        diff_mask = ~same_group & ~np.eye(n, dtype=bool)
        diff_sim = sims[diff_mask].mean()
        margin = same_sim - diff_sim
        margins[label] = margin
        print(f"{label:22s} {same_sim:13.4f} {diff_sim:13.4f} {margin:8.4f}")

    print("\n--- Precision@k (all rows - capped low by small/singleton groups, see docstring) ---")
    print(f"{'model':22s} {'p@5':>7s} {'p@10':>7s}")
    for label, sims in sims_by_model.items():
        sims_no_self = sims.copy()
        np.fill_diagonal(sims_no_self, -np.inf)
        order = np.argsort(-sims_no_self, axis=1)
        p5 = same_group[np.arange(n)[:, None], order[:, :5]].mean()
        p10 = same_group[np.arange(n)[:, None], order[:, :10]].mean()
        print(f"{label:22s} {p5:7.3f} {p10:7.3f}")

    print("\n--- Recall@k / hit@1 (rows with >=1 true peer only - the trustworthy numbers) ---")
    print(f"{'model':22s} {'recall@5':>10s} {'recall@10':>10s} {'hit@1':>7s}")
    for label, sims in sims_by_model.items():
        sims_no_self = sims.copy()
        np.fill_diagonal(sims_no_self, -np.inf)
        order = np.argsort(-sims_no_self, axis=1)

        recalls5, recalls10, hit1 = [], [], []
        for i in np.where(has_peer)[0]:
            true_peers = set(np.where(same_group[i])[0])
            top5 = set(order[i, :5].tolist())
            top10 = set(order[i, :10].tolist())
            top1 = order[i, 0]
            recalls5.append(len(true_peers & top5) / len(true_peers))
            recalls10.append(len(true_peers & top10) / len(true_peers))
            hit1.append(1.0 if top1 in true_peers else 0.0)

        print(
            f"{label:22s} {np.mean(recalls5):10.3f} {np.mean(recalls10):10.3f} {np.mean(hit1):7.3f}"
        )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} /path/to/some_embedded.feather", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
