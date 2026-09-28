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
differences worth noting, not yet resolved:

- No separate accession-number field — `lib/edgar.py` needs the
  accession number specifically (to build filing index URLs, e.g.
  `EDGARARCHIVES/{cik}/{accession}/`), not just the full `url`. It's
  very likely extractable from `IndexEntry.url`'s path (the URL is a
  direct link to the filing text), but this spike didn't verify that
  parsing — worth doing before relying on it.
- `date_filed` is a single string (`"2025-06-30"`), not pre-split into
  year/month/day the way `pyedgar`'s output and `lib/edgar.py`'s
  `YEAR`/`MONTH`/`DAY` fields are — a trivial parse, not a real gap.

**Not tested here**: rate-limiting behavior under real load (this spike
made only two requests total, well under the default 10 req/s limit —
nothing here demonstrates the adaptive limiter actually engaging or
recovering correctly under sustained/concurrent use).

## Bottom line for edgar-backend.md §2.1/§3

This is a real, positive data point for Option 2 (native Rust module) —
`edgarkit` handled both halves of §1's split cleanly against live SEC
data, not just in its own README examples. It doesn't settle the
Option 1 vs. Option 2 choice on its own (that's still open, per
edgar-backend.md §5), but the crate's biggest risk flagged in §2.1
(new, solo-maintained, low-adoption) is now paired with a real, passing
empirical test, not just a maturity concern taken on faith either way.
