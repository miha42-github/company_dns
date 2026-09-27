# df-spike

Tests whether Apache DataFusion (Rust) can read a real Mediumroast
`.feather` file directly — see
[`docs/plans/go-duckdb-rewrite.md`](../../docs/plans/go-duckdb-rewrite.md)
§7 for the full context and §7.3 for results. The DuckDB half of that
same comparison was run via the `duckdb` CLI directly against the file,
no project needed for that side.

## Running it

```bash
cargo run --release -- /path/to/some.feather
```

Defaults to `../../tmp/us_flat.feather` (relative to this directory,
i.e. `tmp/us_flat.feather` at the repo root) if no path is given.

**The sample file itself is not committed to this repo** — it's real
Mediumroast output (US SIC industry-classification data), and `tmp/` is
gitignored. Get a copy from wherever Mediumroast's data products are
currently shared/staged, or point this at any other `.feather`
(Arrow IPC) file — you'll need to adjust the query at the bottom of
`src/main.rs` if the schema differs from US SIC's 13-column shape
(`section_id`, `section_desc`, `division_id`, `division_desc`,
`group_id`, `group_desc`, `class_id`, `class_desc`, `subclass_id`,
`subclass_desc`, `countries`, `ic_module`, `unique_key`).

## What it found

DataFusion's `read_arrow` read the file directly — compressed (ZSTD),
unmodified, exactly as Mediumroast shipped it — after one line of
configuration to accept a `.feather` extension (it defaults to expecting
`.arrow`). DuckDB's `arrow` community extension, tested the same way via
its CLI, failed outright on the same file with `Compression type with
value 1 not supported by this build of nanoarrow` — confirmed as a real
gap (not a corrupt file) by decompressing a copy, which DuckDB then read
fine.
