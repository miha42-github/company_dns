# quality-eval

Measures embedding-model *retrieval quality*, not speed — complements
`../embed-bench/` (which only measured latency/size). See
[`docs/plans/go-duckdb-rewrite.md`](../../docs/plans/go-duckdb-rewrite.md)
§7.6 for the full writeup and results.

No labeled benchmark exists for this dataset, so the SIC hierarchy
itself is used as a weak-label proxy: two rows sharing a `group_id` are,
by construction, more semantically related than two rows in different
groups. A better embedding model should reflect that structure more
strongly in its vector space. Reports precision@k, a ceiling-corrected
recall@k / hit@1 (the trustworthy numbers — this dataset has many
small/singleton groups that cap naive precision@k low regardless of
model quality), and a same-group-vs-different-group separation margin.

Works directly against a `*_embedded.feather` file's vector columns —
no Rust/`fastembed-rs` involved, since the vectors are already
precomputed in the data (including `intfloat/e5-base-v2`, which
`embed-bench` can't benchmark for speed since it isn't in
`fastembed-rs`'s catalog, but whose *quality* is testable here like any
other model).

## Running it

```bash
python3 -m venv venv && venv/bin/pip install numpy pyarrow
venv/bin/python quality_eval.py /path/to/us_flat_embedded.feather
```

## Key result (2026-09-27, US SIC data)

`all-MiniLM-L6-v2` won on every metric — recall@5, recall@10, hit@1, and
separation margin — against `bge-small-en-v1.5`, `all-mpnet-base-v2`,
and `e5-base-v2`. This is the opposite of what general retrieval
benchmarks (MTEB) would suggest, likely because this dataset is short,
controlled-vocabulary classification text, not the natural-language
passages MTEB measures. **Re-run this against company-data vectors once
they exist** — this result is specific to SIC/NACE-style data, not
assumed to transfer to company descriptions. See §7.6 for the full
reasoning and what this does/doesn't change about the model
recommendation.
