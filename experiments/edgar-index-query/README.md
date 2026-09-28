# edgar-index-query

Second half of the [`../edgar-spike/`](../edgar-spike/) test: loads the
`.feather` file that spike writes (a real SEC EDGAR quarterly index,
filtered to `10-%` forms) with DataFusion and runs real SQL against it —
the same `read_arrow` pattern [`../df-spike/`](../df-spike/) already
validated against a real Mediumroast file (see
[`docs/plans/go-duckdb-rewrite.md`](../../docs/plans/go-duckdb-rewrite.md)
§7).

## Why this is a separate crate, not just another function in `edgar-spike`

**A real, unavoidable dependency conflict**, not a design choice: `edgarkit`
requires `chrono >=0.4.45`, and `arrow-arith` (pulled in transitively by
`datafusion`, and by the `arrow` umbrella crate) has a genuine upstream
incompatibility with that chrono version — `arrow-arith` 53.4.0 fails to
compile against `chrono` 0.4.45 (`Datelike::quarter()`, added to `chrono`
in that range, collides with `arrow-arith`'s own `ChronoDateExt::quarter()`
for the same type), and `arrow-arith` 53.4.1 sidesteps that specific
collision only by hard-requiring `chrono <0.4.40` — which directly
contradicts `edgarkit`'s own requirement. No version of `arrow-arith` in
the 53.x line (the range DataFusion 42 needs) works with both
constraints at once. Confirmed by trying to pin around it three
different ways before concluding this is real, not a mistake in this
project's own `Cargo.toml`.

**Practical effect**: `edgarkit` and DataFusion **42** cannot share one
`Cargo.toml`. `edgar-spike` writes the `.feather` file using only the
narrow `arrow-array`/`arrow-schema`/`arrow-ipc` crates (no
`arrow-arith`, no `datafusion`); this crate reads it back with
`datafusion` (no `edgarkit`). Two processes, not one — a real
architectural constraint worth carrying into
[`docs/plans/edgar-backend.md`](../../docs/plans/edgar-backend.md)'s
Option 2 discussion, not just a spike inconvenience.

**This is specific to DataFusion 42, not permanent**: checked whether
a newer DataFusion release already fixed the upstream `arrow-arith`
bug, and it has — DataFusion 55.1.0 pulls `arrow-arith` 59.3.0, which
disambiguates the exact `quarter()` call that broke here and relaxes
the `chrono` bound to `^0.4.40` (satisfied by `edgarkit`'s `>=0.4.45`).
Verified with a real, throwaway test, not just reading version numbers:
built `edgarkit` + DataFusion 55 in one `Cargo.toml`, and both a live
`edgarkit` fetch and a real DataFusion SQL query ran correctly in the
same process. Not acted on here — this project's spikes are
deliberately pinned to DataFusion 42.2.0, matching
`go-duckdb-rewrite.md` §7's already-validated results — but see that
doc's `edgar-backend.md` §2.1/§4 for the tradeoff of upgrading
project-wide versus keeping this two-crate split.

## Running it

```bash
# 1. Produce the .feather file first:
(cd ../edgar-spike && cargo run)
# 2. Then read it back:
cargo run
```

Defaults to `../../tmp/edgar_10series_2025q2.feather` (relative to this
directory) if no path is given. Not committed — `tmp/` is gitignored,
same as `../df-spike`'s sample file.

## What it found (2026-09-28)

**Round-trip: clean.** All 9,241 rows `edgar-spike` wrote came back
exactly — schema matches (8 fields: `cik`, `company_name`, `form_type`,
`year`, `month`, `day`, `accession`, `url`), row count matches, no
DataFusion read errors (unlike `../df-spike`'s original DuckDB
comparison — no compression to fight here at all, since the file was
written uncompressed on purpose).

**A real query against it worked**: `SELECT ... FROM edgar_index WHERE
cik = 51143` (IBM) returned IBM's actual Q1 2025 10-Q, filed
2025-04-24, accession `0000051143-25-000032` — a real, correct answer
to the kind of lookup the EDGAR fallback-cache path (`go-duckdb-
rewrite.md` §5.3) would actually do.

**An unexpected, real finding**: grouping by `form_type` across all
9,241 rows shows the `'10-%'` filter (`lib/prepare_edgar_data.py`'s
`FORM_TYPE_FILTER`) catches more than its own comment describes. That
comment says it's "the only form prefix ever queried... 10-K, 10-K/A
and 10-Q" — accurate about *intent*, but the actual string-prefix match
also pulls in `10-D`/`10-D/A` (asset-backed-securities distribution
reports — 2,659 of the 9,241 rows, more than all 10-K/10-K/A combined),
`10-12G`/`10-12G/A`/`10-12B`/`10-12B/A` (registration forms), and
`10-KT`/`10-KT/A` (transition-period annual reports):

| form_type | count |
|---|---|
| 10-Q | 5,399 |
| 10-D | 2,630 |
| 10-K | 674 |
| 10-K/A | 405 |
| 10-Q/A | 49 |
| 10-D/A | 29 |
| 10-12G/A | 25 |
| 10-12G | 20 |
| 10-12B/A | 4 |
| 10-12B | 3 |
| 10-KT | 2 |
| 10-KT/A | 1 |

Not a bug — the current Python code is internally consistent about it
(`lib/edgar.py`'s own query also filters `form LIKE '10-%'`, the same
broad match) — but worth flagging before the rewrite's docs/comments
repeat "10-K, 10-K/A, 10-Q" as the literal, complete set. **Decided
(2026-09-28, see `docs/plans/edgar-backend.md` §2.1): keep the broader
`'10-%'` match** — the fix is to the description ("10-K, 10-K/A, 10-Q"
undersells what it actually catches), not the filter itself.

## Bottom line for edgar-backend.md

This closes the loop the earlier `edgar-spike` results opened: not just
"can `edgarkit` fetch and shape the right data," but "does that data,
written to `.feather`, actually load into and get queried by the same
engine (`DataFusion`) the rest of the rewrite already uses" — yes, real
9,241-row round trip, real query, real answer. The dependency-conflict
finding is the more consequential result, though: it means Option 2
(native Rust module, `edgar-backend.md` §3) isn't "one crate that does
everything" if it uses `edgarkit` — it's at least two, communicating via
files on disk (or some other boundary), the same shape as Option 1's
external-pipeline story, just with Rust on both sides instead of Python
feeding Rust.
