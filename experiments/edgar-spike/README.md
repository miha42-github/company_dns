# edgar-spike

Tests whether the `edgarkit` crate (crates.io, `r007/edgarkit`) can
replace what the current Python EDGAR implementation does — see
[`docs/plans/edgar-backend.md`](../../docs/plans/edgar-backend.md) §2.1
for the crate research and §5 for why this spike exists. Two things
tested, matching that doc's §1 split:

1. **Company/firmographics fetch** (`lib/edgar.py`'s `get_firmographics`,
   a live JSON REST call — no `pyedgar` involved in the current code).
2. **Quarterly index-building** (`lib/prepare_edgar_data.py`, currently
   `pyedgar`'s `IndexMaker`).

## Running it

```bash
cargo run
```

Hits real `data.sec.gov`/`www.sec.gov` endpoints — no local data needed,
no flags. Uses a Mediumroast-identifying User-Agent
(`Mediumroast, Inc. edgar-spike hello@mediumroast.io`), per SEC.gov's
fair-access requirements and matching `lib/edgar.py`'s existing pattern.

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

## Bottom line for edgar-backend.md §2.1/§3

This is a real, positive data point for Option 2 (native Rust module) —
`edgarkit` handled both halves of §1's split cleanly against live SEC
data, not just in its own README examples, and the two output-shape
gaps found (accession number, date parts) are both cheap, verified
derivations from what `IndexEntry` already returns — not missing
functionality. It doesn't settle the Option 1 vs. Option 2 choice on
its own (that's still open, per edgar-backend.md §5), but the crate's
biggest risk flagged in §2.1 (new, solo-maintained, low-adoption) is
now paired with a real, passing empirical test against this project's
actual data shape, not just a maturity concern taken on faith either
way.
