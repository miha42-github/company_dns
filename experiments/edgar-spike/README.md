# edgar-spike

Tests whether the `edgarkit` crate (crates.io, `r007/edgarkit`) can
replace what the current Python EDGAR implementation does — see
[`docs/plans/edgar-backend.md`](../../docs/plans/edgar-backend.md) §2.1
for the crate research and §5 for why this spike exists. Two things
tested, matching that doc's §1 split:

1. **Company/firmographics fetch** (`lib/edgar.py`'s `get_firmographics`,
   a live JSON REST call — no `pyedgar` involved in the current code).
2. **Quarterly index-building** (`lib/prepare_edgar_data.py`, currently
   `pyedgar`'s `IndexMaker`) — including whether the result can actually
   be loaded into and queried by DataFusion, not just fetched; see
   [`../edgar-index-query/`](../edgar-index-query/) for that half.

## Running it

```bash
cargo run
```

Hits real `data.sec.gov`/`www.sec.gov` endpoints — no local data needed,
no flags. Uses a Mediumroast-identifying User-Agent
(`Mediumroast, Inc. edgar-spike hello@mediumroast.io`), per SEC.gov's
fair-access requirements and matching `lib/edgar.py`'s existing pattern.
Writes a `.feather` file as its last step — run
[`../edgar-index-query/`](../edgar-index-query/) afterward to load and
query it.

## What it found (2026-09-28)

**Company test — a clean match.** `edgar.submissions("0000051143")`
(IBM) returned every field `get_firmographics` currently builds by hand
from the same underlying `data.sec.gov/submissions/` JSON: `name`,
`cik`, `sic`, `sic_description`, `tickers`, `exchanges`, `ein`,
`description`, `website`, `category`, `fiscal_year_end`,
`state_of_incorporation`, `phone`, and a structured `addresses` (mailing
+ business, each with `street1`/`street2`/`city`/`state_or_country`/
`zip_code`) — already split out, not a single blob needing the manual
flattening `lib/edgar.py` does today. `company_facts(51143)` (XBRL
facts, not currently used by `company_dns` but available) also
succeeded. No missing fields, no surprises.

**Firmographics-shape test — the full `get_firmographics()` output,
rebuilt from `edgarkit` alone.** Beyond just checking the raw fields
are present (above), built the actual output shape
`get_firmographics()` returns — URL construction
(`companyFactsURL`/`firmographicsURL`/`filingsURL`/
`transactionsByIssuer`/`transactionsByOwner`, same paths as
`lib/edgar.py`'s `EDGARDATA`/`EDGARFACTS`/`EDGARURI`+`EDGARSERVER`
constants), `"Unknown"`-filling for blank optional fields, and address
flattening (`city`/`stateProvince`/`zipPostal`/`address` from the
mailing address, matching `lib/edgar.py`'s exact logic including the
street1+street2 concatenation) — entirely from the `Submission` struct,
no `pyedgar`, no hand-rolled `reqwest`+JSON call. Real IBM output, side
by side with the current Python shape's key names, matched field for
field. **One real discrepancy found in the process, not introduced by
this spike**: `lib/edgar.py`'s current "cleanup stock information" step
(`firmographics['tickers'] = [firmographics['exchanges'][0],
firmographics['tickers'][0]]`) overwrites `tickers` with
`[exchange, ticker]` instead of the actual ticker list — looks like a
real bug in the existing Python code, not something worth replicating.
The scope here is deliberately EDGAR-only: `get_firmographics`'s SIC
cross-reference (`division`/`majorGroup`/`industryGroup`, via
`lib/sic.py` against local SIC data) is a separate system — the
IC/classification work already covered elsewhere
(`go-duckdb-rewrite.md`, `ic-similarity-search-poc.md`) — not something
`edgarkit` provides or this spike tests.

**Index test — also a clean match, with a real cross-validation.**
`edgar.get_period_filings(EdgarPeriod::new(2025, Quarter::Q2), None)`
downloaded and parsed the real Q2 2025 quarterly full-text index in
**~1.65 seconds**: 331,786 total entries, of which 9,241 (**2.79%**)
start with `10-` (`10-K`, `10-K/A`, `10-Q`) — the same form-type filter
`lib/prepare_edgar_data.py`'s `FORM_TYPE_FILTER` applies. That 2.79%
lines up closely with the ~3% figure already documented in that file's
own comment (measured against a different quarter), a real, independent
cross-check that both pipelines are filtering the same underlying data
the same way. Each `IndexEntry` carries `company_name`, `form_type`,
`cik`, `date_filed`, `url` — covers `pyedgar`'s output except for two
gaps, **both closed by a follow-up check**:

- **Accession number**: not a separate field, but `IndexEntry.url`'s
  filename *is* the accession number with dashes
  (`https://www.sec.gov/Archives/edgar/data/{cik}/{accession}.txt`).
  Extracted it for a sample of 5 real `10-%` entries, used it to build
  the exact URL `lib/edgar.py`'s `filing_idx_url` constructs
  (`.../{cik}/{accession_no_dashes}/{accession}-index.html`), and
  fetched each one for real — **5/5 returned HTTP 200**. Not a
  theoretical derivation; verified against live `sec.gov`.
- **`date_filed`**: a single `"YYYY-MM-DD"` string, not pre-split into
  year/month/day the way `pyedgar`'s output and `lib/edgar.py`'s
  `YEAR`/`MONTH`/`DAY` fields are. A one-line `splitn('-')` handled it
  correctly for all 5 sample entries — confirmed a trivial parse, not a
  real gap, as suspected.

**Not tested here**: rate-limiting behavior under real load (this spike
made a handful of requests total, well under the default 10 req/s
limit — nothing here demonstrates the adaptive limiter actually
engaging or recovering correctly under sustained/concurrent use).

**Feather write — produces a real, loadable dataset.** All 9,241
filtered `10-%` entries get written to a real `.feather` (Arrow IPC)
file (uncompressed, ~1.47MB) using the same schema shape as
`lib/edgar.py`'s `companies` SQLite table (CIK/company/year/month/day/
accession/form). **This had to move to a separate crate,
[`../edgar-index-query/`](../edgar-index-query/), to actually load and
query it** — see that crate's README for why (a real `chrono`-version
conflict between `edgarkit` and `arrow-arith`/DataFusion, not a design
choice) and for the query results, including an unexpected finding
about what the `'10-%'` form-type filter actually catches.

## Bottom line for edgar-backend.md §2.1/§3

This is a real, positive data point for Option 2 (native Rust module) —
`edgarkit` handled both halves of §1's split cleanly against live SEC
data, not just in its own README examples, and the two output-shape
gaps found (accession number, date parts) are both cheap, verified
derivations from what `IndexEntry` already returns — not missing
functionality. **For §1.2 (live firmographics) specifically, `edgarkit`
is now a stronger contender than a hand-rolled `reqwest` client**: it
already returns the raw fields as structured Rust types (no manual JSON
poking), and rebuilding `get_firmographics()`'s exact output shape from
it required no `pyedgar` and surfaced one real bug in the current
implementation as a side effect. This doesn't settle the Option 1 vs.
Option 2 choice on its own (that's still open, per edgar-backend.md
§5), but the crate's biggest risk flagged in §2.1 (new, solo-maintained,
low-adoption) is now paired with a real, passing empirical test against
this project's actual data shape, not just a maturity concern taken on
faith either way.
