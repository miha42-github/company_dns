# embed-bench

Benchmarks the three embedding models `fastembed-rs` supports natively
out of the box — `all-MiniLM-L6-v2`, `BAAI/bge-small-en-v1.5`,
`all-mpnet-base-v2` — against real US SIC `embedding_text` values, to
inform which model(s) the Go/Rust rewrite's query-time embedding path
should actually run. See
[`docs/plans/go-duckdb-rewrite.md`](../../docs/plans/go-duckdb-rewrite.md)
§7.5 for the full writeup and recommendation.

`intfloat/e5-base-v2` (the fourth model Mediumroast ships vectors for)
is excluded — confirmed separately that it isn't in `fastembed-rs`'s
built-in model catalog, so it isn't a zero-effort comparison the way the
other three are (would need a manual ONNX export + `ort` instead).

## Running it

```bash
# 1. Generate embedding_texts.txt from a real embedded .feather file
#    (not committed - derived data, regenerate as needed):
python3 -c "
import pyarrow.feather as feather
table = feather.read_table('/path/to/us_flat_embedded.feather')
texts = table.column('embedding_text').to_pylist()
with open('embedding_texts.txt', 'w') as f:
    for t in texts:
        f.write(t.replace(chr(10), ' ') + chr(10))
"

# 2. Run the benchmark (downloads all 3 models on first run, ~600MB total)
cargo run --release
# or point it at a different input file:
cargo run --release -- /path/to/other_embedding_texts.txt
```

Measures, per model: warm load/init time, single-query embed latency
(min/median/p95/max over 30 calls — the relevant number for the runtime
query-embedding use case, one call per incoming request) and batch
throughput across the full input file (a secondary number, relevant to
offline/bulk re-embedding cost, not the request path).

## Results (2026-09-27, this repo's `us_flat_embedded.feather`, 1,005 rows)

| Model | Dim | On-disk size | Load time (warm) | Single-query latency (median / p95) | Batch (1,005 rows) |
|---|---|---|---|---|---|
| `all-MiniLM-L6-v2` | 384 | 87MB | 72ms | 2.49ms / 2.69ms | 966ms (0.96ms/row) |
| `BAAI/bge-small-en-v1.5` | 384 | 128MB | 70ms | 4.69ms / 5.29ms | 1,788ms (1.78ms/row) |
| `all-mpnet-base-v2` | 768 | 418MB | 149ms | 7.17ms / 7.59ms | 4,335ms (4.31ms/row) |

On-disk sizes are from `~/.cache/huggingface/hub` after a normal
`fastembed-rs` download (includes tokenizer/config files alongside the
ONNX weights, not just the raw model file).

**Recommendation** (see §7.5 for full reasoning): `BAAI/bge-small-en-v1.5`
for the low-dim slot (retrieval quality over MiniLM's raw speed, which
doesn't matter much against this service's real request-path latencies)
and `all-mpnet-base-v2` for the high-dim slot (the only native 768-dim
option anyway; its latency is negligible in context).
