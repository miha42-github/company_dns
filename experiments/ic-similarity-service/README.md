# ic-similarity-service

A small local REST service + minimal web UI for manually testing
semantic similarity search over IC (SIC/NACE) data, using the two
embedding models decided in
[`docs/plans/go-duckdb-rewrite.md`](../../docs/plans/go-duckdb-rewrite.md)
§7.7 (`all-MiniLM-L6-v2` low-dim, `all-mpnet-base-v2` high-dim). Planned
in [`docs/plans/ic-similarity-search-poc.md`](../../docs/plans/ic-similarity-search-poc.md)
— read that first for the reasoning behind the stack/design choices
below.

**Not part of `company_dns`** — disposable, exploratory, localhost-only,
same posture as every other `experiments/` subdirectory.

## Stack

Rust + [DataFusion](https://datafusion.apache.org/) (data access) +
[`fastembed-rs`](https://github.com/Anush008/fastembed-rs) (query-time
embedding) + [Axum](https://github.com/tokio-rs/axum) (HTTP) + a static
HTML/vanilla-JS page (no build step, no framework). Continues directly
from `experiments/df-spike` and `experiments/embed-bench` rather than
being a fresh evaluation.

## Running it

Needs `tmp/us_flat_embedded.feather` at the repo root (not committed —
gitignored, real Mediumroast output; see the main repo's other
`experiments/*/README.md` files for how to get a copy).

```bash
cargo run --release
# or point it at a different file:
IC_DATA_PATH=/path/to/other_embedded.feather cargo run --release
```

Then open <http://127.0.0.1:8080>. First run downloads both embedding
models (~500MB combined, cached under `.fastembed_cache/` — gitignored,
not committed) and takes longer; subsequent runs load from cache in
under 200ms.

## API

```
GET /health                                          -> "ok"
GET /api/models                                       -> [{id, label, dim}, ...]
GET /api/similar?q={text}&model={id}&k={1-50, default 10}
                                                        -> [{rank, similarity, unique_key,
                                                            section_desc, division_desc,
                                                            group_desc, class_desc,
                                                            subclass_desc}, ...]
```

## A real bug this surfaced, worth knowing if reusing this pattern elsewhere

DataFusion 42.2.0's own `Cargo.toml` requests only the `"lz4"` feature
for its `arrow-ipc` dependency, **not** `"zstd"`
(`default-features = false`) — confirmed by reading the crate's own
manifest, not assumed. `tmp/us_flat_embedded.feather` is genuinely
zstd-compressed (its float-vector buffers are large enough for real
compression to kick in, unlike the tiny `us_flat.feather` used in
`df-spike`, whose buffers may be too small to have been compressed at
all despite carrying the same codec tag). Without an explicit fix, every
`/api/similar` call failed with:

```
External error: Arrow error: Invalid argument error: zstd IPC decompression requires the zstd feature
```

Fixed by adding `arrow-ipc = { version = "53", features = ["zstd"] }`
directly to this crate's `Cargo.toml` — Cargo's feature unification adds
it to the build even though `datafusion` itself doesn't request it.
**This means `df-spike`'s "DataFusion reads the file directly, no
workaround needed" finding (`go-duckdb-rewrite.md` §7.3/§7.4) likely
never actually exercised real zstd decompression** — worth a note back
on that section rather than treating it as fully settled.

## Also worth knowing: `array_distance`'s Rust API vs. its SQL API

`datafusion-functions-nested` 42.2.0's macro-generated
`array_distance(expr) -> Expr` convenience function only accepts **one**
argument, which doesn't match the underlying UDF's actual 2-argument
signature (an upstream inconsistency, not a mistake in how it's called
here). Went through DataFusion's SQL string interface instead
(`ctx.sql("... array_distance(col, arrow_cast([...], 'FixedSizeList(...)')) ...")`),
which resolves the same function correctly by name at runtime (its
signature is `user_defined`, checked at call time). See `search.rs` for
the full query construction and the cosine-similarity-from-Euclidean-
distance identity used for normalized vectors.
