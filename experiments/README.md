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
  configuration.
- **`embed-bench/`** — benchmarks the three embedding models
  `fastembed-rs` supports natively (`all-MiniLM-L6-v2`,
  `BAAI/bge-small-en-v1.5`, `all-mpnet-base-v2`) against real US SIC
  data, to pick which model(s) the rewrite's query-time embedding path
  should run. See §7.5 of the same doc for results and the
  low-dim/high-dim recommendation.

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
