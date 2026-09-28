# EDGAR backend for the Rust + DataFusion rewrite

Status: **Draft — research only, no code written yet.** This doc exists
to work out what the current Python EDGAR implementation actually does,
survey what exists in the Rust ecosystem for the same job, and lay out
the real options — not to commit to one yet.
Owner: michael.hay@mediumroast.io
Scope: how the new `company_dns` (V4.0.0, Rust + DataFusion — see
[`go-duckdb-rewrite.md`](go-duckdb-rewrite.md) §6.5/§9) gets its EDGAR
data, both the cached/seeded set and the live-fallback path (§5/§5.3 of
that doc). Not in scope here: Wikipedia's backend (gets its own doc per
§5.4), the UX/API surface for EDGAR lookups (that's
[`company-dns-ux.md`](company-dns-ux.md)), or any of the IC/classification
data work (`ic-similarity-search-poc.md`).

---

## 1. What the current Python implementation actually does

It's worth being precise here, because "EDGAR uses pyedgar" undersells
it — the current code is really **two separate capabilities**, only one
of which touches `pyedgar` at all:

### 1.1 Index-building: `lib/prepare_edgar_data.py`, via `pyedgar`

`ExtractEdgarData._initialize()` calls `pyedgar.utilities.indices.
IndexMaker().extract_indexes(start_date=start_year)`, which downloads
SEC's quarterly full-text filing index (a large, gzipped, tab-delimited
file listing every filing by every company for that period) and unpacks
it locally. `extract_data()` then reads that file directly (not through
any further `pyedgar` API — plain `csv`/`gzip` stdlib) and filters it
down to rows whose form type starts with `10-` (10-K, 10-K/A, 10-Q —
`FORM_TYPE_FILTER`), which is the only form family `lib/edgar.py` ever
queries against. This filtered set becomes the `companies` SQLite table
that `EdgarQueries.get_all_ciks()` and `get_all_details()` query with
plain `LIKE`/`=` SQL — this table *is* the "cached/seeded set" described
in `go-duckdb-rewrite.md` §5, just built by a bespoke Python/SQLite
pipeline today instead of arriving as a Mediumroast `.feather` package.

**`pyedgar`'s actual job here is narrow**: it knows how to find, fetch,
and decompress SEC's quarterly index files. Nothing about SIC/company
enrichment, nothing about individual filing content — just "here's the
index of what was filed, by whom, when."

### 1.2 Live firmographics fetch: `lib/edgar.py`'s `get_firmographics`

This is the fallback path `go-duckdb-rewrite.md` §5 already describes
(cache a limited set, fall back to live EDGAR on a miss) — and it
**does not use `pyedgar` at all**. `get_firmographics(cik)` builds a
`CIK##########.json` filename, makes a plain `requests.get()` against
`https://data.sec.gov/submissions/{cik_file}` (a public, stable JSON
REST API), and reshapes the response (fills blanks with `"Unknown"`,
extracts address fields, cross-references SIC via `lib/sic.py`). A
shared, module-level `requests.Session()` handles connection reuse
(see the comment at `lib/edgar.py:20-28`, referenced from
`go-duckdb-rewrite.md` §5.3).

**This split matters for the rewrite**: item 1.1 (index-building) is
where `pyedgar`'s real value is — parsing SEC's index file format
correctly, handling quarterly boundaries, etc. Item 1.2 (live
firmographics) is a generic JSON-over-HTTP call that doesn't need
`pyedgar`, or any specialized library at all, in either language.

### 1.3 What's *not* being replicated

The current codebase does not use `pyedgar` for filing content
retrieval, XBRL parsing, or anything beyond the index. Whatever the
rewrite does, it only needs to match §1.1 and §1.2 above — not the
larger surface `pyedgar` (or Rust equivalents like `edgarkit`, §2 below)
expose for actually parsing filing documents themselves.

## 2. What exists in the Rust ecosystem

Research below, current as of 2026-09-27 (crates.io), following this
document's own project-wide habit of checking real numbers rather than
taking a README's framing at face value (`go-duckdb-rewrite.md` §7's
whole premise, applied here too).

### 2.1 `edgarkit` (crates.io, `r007/edgarkit`)

The closest match found to what §1 actually needs. Feature-flagged:
`search`, `filings`, `company`, `feeds`, `index` (all on by default).
The **`index` feature specifically** — "Download and parse daily and
quarterly filing indices" — appears to cover the same ground as
`pyedgar`'s `IndexMaker` (§1.1), and the **`company` feature** covers
company facts/submissions retrieval (`edgar.submissions(cik)` in its own
README example) — the same data `get_firmographics` fetches today
(§1.2). Built on `reqwest` + `tokio` + `governor` (rate limiting) +
`quick-xml`, async-first. Ships its own adaptive rate limiter for SEC's
fair-access rules, which the current Python code doesn't have (today's
`headers` dict sets a `User-Agent` but has no rate-limiting logic at
all) — a potential improvement, not just parity.

**Maturity, stated plainly rather than glossed over**: v0.4.0, released
~2 months ago, 638 downloads all-time, 6 versions published, single
author (Sergey Monin), explicitly labeled "unofficial." This is a new,
low-adoption, solo-maintained crate — real functionality on paper, no
independent track record yet. Worth the same posture this project has
taken toward other self-described "production-ready" or promising-
looking dependencies elsewhere (`go-duckdb-rewrite.md` Annex C's minikv,
Annex A's DuckDB VSS): plausible, not yet verified against this
project's actual data, needs a real spike before being trusted.

### 2.2 `sec_edgar` (crates.io, `tieje/rs_sec_edgar`)

v1.0.5, released ~3 years ago, 9,918 downloads all-time (more adoption
than `edgarkit`, but stale — no updates in 3 years). Narrower scope than
`edgarkit`: CIK lookup (`CIKQuery`) plus Atom-feed-based filing search
(`EdgarQueryBuilder` → `get_feed_entries`) built around EDGAR's older
Atom feed interface, not the modern `data.sec.gov` JSON APIs
`get_firmographics` actually calls, and no index-file parsing
equivalent to `pyedgar`'s `IndexMaker` found in its README. Doesn't
cover §1.1 or §1.2 as directly as `edgarkit` does.

### 2.3 Nothing else found

No other actively-relevant crate turned up in this search. (A crate
literally named `sec` exists but is unrelated — it's a secret-redaction
helper for `Debug`/`Display`, not EDGAR-related; noting only so it isn't
mistaken for a hit later.)

### 2.4 Bottom line

`edgarkit` is the one real candidate for a native-Rust path, and it's
promising specifically because its feature boundaries (`index`,
`company`) line up with this project's actual two-part need (§1.1,
§1.2) — but it's new enough that "promising on paper" and "actually
works against real SEC data the way this project needs" are still two
different claims. Nothing here rules out option 2 below; nothing here
proves it either.

## 3. Two options, not yet decided between

### Option 1: `pyedgar` as a CLI, feeding a conversion-to-`.feather` pipeline

Keep `pyedgar` doing what it already does well (§1.1's index-building),
run it as an external step (script or small CLI wrapper) outside the
Rust service itself, and convert its output to `.feather` as part of a
data pipeline that feeds the new service — the same shape as how
Mediumroast's own IC-classification and company data packages already
arrive (`go-duckdb-rewrite.md` §0/§1).

- **Pro**: zero risk on the index-parsing logic itself — `pyedgar`
  already does this correctly today, in production. No need to
  re-validate SEC's index file format edge cases from scratch.
- **Pro**: keeps the Rust service itself free of a Python dependency at
  *runtime* — Python only runs as a build/ingest-time step, not inside
  the service.
- **Con**: still a Python dependency *somewhere* in the pipeline,
  which cuts against the "pure Rust, single static binary" story
  `go-duckdb-rewrite.md` §6.5 point 2 makes for the rest of the
  architecture. Worth asking whether that's actually a problem for a
  build-time-only step, or just an aesthetic inconsistency.
- **Con**: item 1.2 (live firmographics fallback) still needs a Rust
  answer regardless of what happens here — this option only addresses
  index-building, not the live-fallback path.
- **Open**: does `company_dns` even own index-building going forward,
  or does Mediumroast's own pipeline produce the EDGAR `.feather`
  package the same way it does for IC/classification data (§5's
  "Mediumroast-supplied `.feather` data product" framing)? If so, this
  option may be moot — not `company_dns`'s decision to make at all.

### Option 2: A small Rust module replicating what `pyedgar` does

Either build directly against `data.sec.gov`'s index files (the same
raw format `pyedgar` parses, §1.1) using plain `reqwest` + a tab-
delimited/gzip parser, or adopt `edgarkit`'s `index` feature (§2.1) to
avoid re-implementing that parsing from scratch.

- **Pro**: single-language, single-binary story stays intact — no
  Python anywhere, matching the rest of the architecture.
- **Pro**: item 1.2 (live firmographics) is genuinely simple either way
  — a JSON GET request and some field reshaping, well within "write it
  ourselves" territory regardless of what happens with index-building.
  `edgarkit`'s `company` feature could also cover this, or a hand-rolled
  `reqwest` call — low risk either way, this piece doesn't need much
  external help.
- **Con**: index-building (§1.1) is the piece with real parsing
  complexity (quarterly file boundaries, format quirks `pyedgar` has
  presumably already hit and fixed) — hand-rolling it means re-earning
  correctness `pyedgar` already has. Using `edgarkit` for this instead
  means depending on a new, solo-maintained, 638-download crate for a
  meaningfully load-bearing piece of the pipeline — a real risk, not a
  hypothetical one, per §2.1's maturity note.
- **Open**: same question as Option 1's last bullet — if Mediumroast
  ends up owning EDGAR index-building upstream (the same way it now
  owns IC-classification and company data), this whole option may be
  solving a problem `company_dns` doesn't actually have anymore.

## 4. Open questions

- **Does `company_dns` still own EDGAR index-building at all**, or does
  that move upstream to Mediumroast's own data pipeline, consistent
  with how IC-classification and enriched-company data now arrive as
  `.feather` packages (`go-duckdb-rewrite.md` §0)? This changes the
  shape of both options above substantially and should probably be
  settled before spiking either one.
- **If `edgarkit` is seriously considered for Option 2**: a real spike
  against actual SEC data (not just reading its README) is needed
  before depending on it — consistent with this project's own standard
  for validating claims (`go-duckdb-rewrite.md` §7). Specifically worth
  testing: does its `index` feature correctly parse a real quarterly
  index file end to end, and does its rate limiter actually behave
  under SEC's fair-access rules in practice, not just in theory.
- **CIK-as-durable-identifier** (`go-duckdb-rewrite.md` §2, issue #33)
  needs to be preserved regardless of which option wins — whatever
  builds the cached/seeded EDGAR set must key by CIK, not company name.
- **Rate limiting**: today's Python implementation has none beyond a
  descriptive `User-Agent` — worth deciding whether the rewrite adds
  real rate-limiting (which `edgarkit` provides out of the box) as an
  improvement, independent of which option is chosen for the rest.
- Not yet addressed: how this interacts with `go-duckdb-rewrite.md`
  §5.2's no-shared-KVS caching decision — presumably EDGAR's
  live-fallback path (§1.2 above) just becomes another consumer of that
  same process-local TTL+LRU cache, but worth confirming once this
  doc's own questions are further along rather than assuming it.

## 5. Next steps

1. Settle the "does `company_dns` still own index-building" question
   (§4) — it changes which of §3's two options is even worth spiking.
2. If Option 2 stays live: a small, disposable spike (same spirit as
   `go-duckdb-rewrite.md` §7's `df-spike`) testing `edgarkit`'s `index`
   and `company` features against real SEC data, not committed to the
   repo.
3. If Option 1 stays live: confirm what a `pyedgar`-as-CLI step would
   actually look like — is it a thin wrapper around today's
   `lib/prepare_edgar_data.py` logic, or does it need rework to emit
   `.feather` instead of populating SQLite directly?
4. Either way, item 1.2 (live firmographics fallback) can likely move
   forward independently and sooner — it's the lower-risk half of this
   doc's scope, doesn't depend on §4's open question, and is small
   enough to just build directly in Rust once `go-duckdb-rewrite.md`
   §5.3's fallback-path questions are answered.
5. No code yet, per this doc's own status line — the above are spike
   proposals, not commitments.
