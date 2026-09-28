# experiments/

Disposable spikes and validation prototypes — not the rewrite itself, not
production code, not covered by any stability/compatibility guarantee.
Each subdirectory here exists to answer a specific question raised in a
`docs/plans/` document, empirically, rather than leaving the answer as
documentation research or assumption.

Committed at the top level (not per-worktree, not in a scratchpad) so the
result is available in every worktree and durable across sessions —
these findings get cited from the planning docs they support and are
worth keeping around for that reason, even though the code itself is
throwaway.

## Contents

- **`df-spike/`** — tests whether Apache DataFusion (Rust) and DuckDB's
  `arrow` community extension can actually read a real Mediumroast
  `.feather` file, as opposed to what their documentation claims. See
  [`docs/plans/go-duckdb-rewrite.md`](../docs/plans/go-duckdb-rewrite.md)
  §7.3/§7.4 for the full writeup and results (§7.4 includes a correction
  to an initial misdiagnosis — worth reading both, not just §7.3).
  Short version: DuckDB's `arrow` extension failed on the file as
  shipped; DataFusion read it directly, unmodified, with one line of
  configuration. **Caveat found later by `ic-similarity-service/`**:
  that file's buffers may have been too small to actually exercise real
  zstd decompression — see that experiment's README before assuming
  DataFusion's zstd support needs zero configuration in general.
- **`embed-bench/`** — benchmarks the three embedding models
  `fastembed-rs` supports natively (`all-MiniLM-L6-v2`,
  `BAAI/bge-small-en-v1.5`, `all-mpnet-base-v2`) against real US SIC
  data, to pick which model(s) the rewrite's query-time embedding path
  should run. See §7.5 of the same doc for results and the
  low-dim/high-dim recommendation — **speed only, see `quality-eval/`
  for retrieval quality**, which complicates the pick made here.
- **`quality-eval/`** — measures retrieval *quality* (not speed) for all
  four embedding models, including `intfloat/e5-base-v2` (not covered by
  `embed-bench/`, but its precomputed vectors are testable without any
  Rust code), using the SIC hierarchy as a weak-label proxy for semantic
  relatedness. See §7.6 of the same doc. Notable result: `all-MiniLM-
  L6-v2` outperformed `bge-small-en-v1.5` on this specific dataset,
  contrary to general retrieval-benchmark expectations — flagged as
  SIC/NACE-specific, not assumed to transfer to company data.
- **`ic-similarity-service/`** — the first thing in `experiments/` that
  isn't a benchmark script: a small local REST service + minimal web UI
  wiring together DataFusion (data access), `fastembed-rs` (query-time
  embedding with the two §7.7-decided models), and Axum (HTTP), so
  similarity search can actually be typed into and looked at rather than
  read off a results table. Planned in
  [`docs/plans/ic-similarity-search-poc.md`](../docs/plans/ic-similarity-search-poc.md).
  Surfaced two real bugs while building it — a DataFusion
  `arrow-ipc`/zstd feature gap (see the `df-spike/` caveat above) and a
  mismatched Rust-vs-SQL API on DataFusion's `array_distance` function —
  both documented with fixes in this experiment's own README.
- **`edgar-spike/`** — tests whether the `edgarkit` crate can replace
  the current Python EDGAR implementation (`pyedgar`'s `IndexMaker` for
  quarterly index-building, plus `lib/edgar.py`'s hand-rolled JSON REST
  firmographics fetch), against real, live SEC EDGAR data. See
  [`docs/plans/edgar-backend.md`](../docs/plans/edgar-backend.md) §2.1/§5.
  Both halves passed cleanly: `get_firmographics()`'s exact output
  shape was rebuilt from a real IBM lookup using only `edgarkit`, no
  `pyedgar` or hand-rolled JSON parsing (and surfaced a real bug in the
  current Python code's ticker-list handling along the way); a real
  quarterly index download+parse took ~1.65s and reproduced almost
  exactly the ~3% `10-%`-form-type ratio already documented in
  `lib/prepare_edgar_data.py`'s own comment — a genuine cross-validation,
  not just a passing test.
- **`edgar-index-query/`** — the other half of `edgar-spike/`'s
  index-building test: loads the `.feather` file that spike writes with
  DataFusion and runs real SQL against it, same `read_arrow` pattern as
  `df-spike/`. Had to be a **separate crate**, not just another function
  in `edgar-spike/` — a real, unavoidable `chrono`-version conflict
  between `edgarkit` (needs `>=0.4.45`) and `arrow-arith`/DataFusion
  (no 53.x version works with that `chrono`), confirmed by trying to pin
  around it three different ways. All 9,241 rows round-tripped cleanly;
  a real query for IBM found its actual Q1 2025 10-Q. Also surfaced an
  unexpected finding: the `'10-%'` form-type filter both codebases use
  catches more than its own comment describes (`10-D`, `10-12G/B`,
  `10-KT` too, not just `10-K`/`10-K/A`/`10-Q`) — see this experiment's
  README for the full breakdown.
- **`edgar-cache-spike/`** — builds
  [`go-duckdb-rewrite.md`](../docs/plans/go-duckdb-rewrite.md) §5.1's
  general caching mechanism (`moka`, TTL+LRU, process-local) and wires
  it to `edgarkit`'s real live-fallback fetch — the piece that actually
  answers whether the whole EDGAR path works end to end, not just
  fetch-and-shape (`edgar-spike/`) or write-and-query
  (`edgar-index-query/`). Checked `edgarkit` for any built-in caching
  first (none — confirmed by a docs.rs search, zero hits). Five tests
  against real SEC data: a cache hit was **~46,000x faster** than a miss
  (11.75µs vs. 544ms); 5 concurrent requests for the same uncached CIK
  produced only **1** real network fetch (`moka`'s single-flight
  de-duplication, not something a hand-rolled cache gets for free); TTL
  expiry and LRU eviction (under a capacity-2 cache) both confirmed with
  real re-fetches, not just cache statistics; and the same `Cache<K, V>`
  type was reused with a completely different key/value shape as a
  stand-in for a future Wikipedia instance, proving "one mechanism, not
  two" holds in code.

## Conventions for adding a new experiment

- One subdirectory per question being tested, named for what it tests
  (not `test1`, `scratch`, etc.).
- A comment at the top of the entry point (or a short local `README.md`
  if the setup needs more explanation) linking back to the planning doc
  section that motivated it.
- Don't commit large or sensitive sample data files here — reference
  where to get them instead (see `df-spike/README` notes on
  `tmp/us_flat.feather`, which is gitignored, not committed).
- `target/`, `node_modules/`, and other build artifacts are gitignored
  at the repo root — don't need per-experiment `.gitignore` entries for
  those.
