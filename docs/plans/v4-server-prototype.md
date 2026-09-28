# V4 prototype server: US SIC (feather) + EDGAR (edgarkit + cache), V3-parity endpoints

Status: **Built (2026-09-28) — `v4/` is a real, running server.**
Implements §3's crate layout, §4's ingest binary (real run: 9,241 rows
written to `./tmp/edgar_10x_catalog.feather` via `edgarkit` + DataFusion
55 in one process), §5's endpoints (all tested against real SIC/EDGAR
data — `sic/description`, `sic/code`, `sic/similarity`, `edgar/ciks`,
`edgar/firmographics/{cik}` all returned correct results, including a
live cached `edgarkit` fetch for IBM), §7's `--profile v4` harness
extension (ran cleanly against the live server, 31/31 requests OK), and
§8's Wikipedia + merged firmographics — originally staged stubs,
**promoted to real, tested, live-verified implementations the same day
(§8.1/§8.2)** after `experiments/wikipedia-spike/` validated the full
approach (crate evaluation, wptools infobox/claims parsing port,
side-by-side diff against V3's live output across 10 companies, a
corporate-suffix hint restoration that goes further than V3's own
swallowed-by-a-404-bug version, an infobox-presence gate, and a
Wikidata canonical-title fix). See `v4/README.md` for how to run it.
**`detail`/`summary` are at real parity with V3** (§5.4) — an initial
pass deferred `detail`'s per-match live firmographics enrichment as a
speculative-design concern; corrected the same day, since for a *port*
specifically, matching V3's actual data is the point, not a
nice-to-have. **Not done**: a real V3-vs-V4 `compare.py` run (needs a
V3 target to run the harness against, not attempted here), CI/release
packaging, and everything §1 already scoped out (UX, non-US SIC
systems, and bare-name-to-page-title resolution beyond V3's own
suffix-hint heuristic — see §8.1).
Owner: michael.hay@mediumroast.io
Scope: a prototype `company_dns` V4 server (Rust + DataFusion, per
[`go-duckdb-rewrite.md`](go-duckdb-rewrite.md) §6.5/§9) covering US SIC
similarity/lookup and EDGAR (initial catalog + live spillover, per
[`edgar-backend.md`](edgar-backend.md)), implementing the subset of V3
endpoints needed for a real side-by-side performance comparison, plus
new SIC-similarity endpoints V3 has no equivalent for, plus a real
Wikipedia client and merged-firmographics implementation (§8, promoted
the same day this status line was last updated — no longer just staged
module boundaries). Explicitly **not** in this prototype: a UX/UI
(stays with [`company-dns-ux.md`](company-dns-ux.md), deferred until we
work on it together — §9), and the other four SIC systems
(UK/ISIC/EU-NACE/Japan) — US SIC only, matching what's actually been
spiked.

---

## 0. Why this doc, and what "prototype" actually means here

Four things now exist as working, individually-verified spikes:

- **`experiments/df-spike/` + `experiments/ic-similarity-service/`** —
  DataFusion reads a real Mediumroast `.feather` file and serves vector
  similarity search over it (`go-duckdb-rewrite.md` §7.3/§7.4, §7.8's
  `all-MiniLM-L6-v2`-only decision).
- **`experiments/edgar-spike/` + `experiments/edgar-index-query/`** —
  `edgarkit` fetches real EDGAR firmographics and quarterly-index data;
  the index round-trips through `.feather` and back through DataFusion
  (`edgar-backend.md` §2.1).
- **`experiments/edgar-cache-spike/`** — a general `moka`-backed TTL+LRU
  cache, proven against real `edgarkit` calls including concurrent
  single-flight de-duplication (`go-duckdb-rewrite.md` §5.1).

Each of these answers one question in isolation. **None of them has run
together, in one process, serving real HTTP requests shaped like V3's
actual API.** That's what "prototype" means here: not new research,
integration — and the first point where this project can honestly say
"V4 does X" instead of "a spike proved X is possible."

## 1. Scope, mapped to what was asked

1. **Implement the relevant V3 APIs for EDGAR and US SIC** — §5/§6
   below, the exact endpoint list and what backs each one.
2. **New V4 endpoints for SIC similarity** — §5.1, following the same
   URL-shape convention V3 already uses.
3. **Source/repo structure** — §3.
4. **EDGAR staging data written to `./tmp`** — §4.
5. **Extend the Python perf harness for V3-vs-V4 comparison** — §7.
6. **Defer the UX, focus on the server** — §9.
7. **Stage Wikipedia searching, V3-shaped** — §8.1.
8. **Stage merged firmographics (EDGAR + Wikipedia)** — §8.2.

## 2. What's genuinely new here, versus what's just being reused

Worth being explicit, since it's easy to undercount how much of this is
already de-risked:

- **Not new**: reading a real `.feather` file with DataFusion; vector
  similarity search over SIC data; `edgarkit` firmographics fetch;
  `edgarkit` quarterly-index fetch; writing/reading a `.feather` file
  round-trip; the general TTL+LRU cache; `edgarkit` + DataFusion sharing
  a process (blocked on DataFusion 42, resolved on 55.x — §3 below).
  All of this is `experiments/`-proven already.
- **New**: a real EDGAR "10-x initial catalog" ingest pipeline (not a
  single ad hoc quarter fetched once for a test, but something with a
  defined scope and a real place to land — §4); actual versioned REST
  endpoints with the same URL shape and response envelope V3 uses, not
  internal test binaries; a workspace that holds more than one crate
  talking to each other in one server process; and a real, repeatable
  comparison against V3 on shared ground, not prose claims about what
  "should" be faster.

## 3. Architecture: source/repo structure

Proposed, not yet created — this section describes the layout, it
doesn't build it.

A new top-level directory, **`v4/`**, sibling to `experiments/` and the
existing V3 Python tree (`lib/`, `company_dns.py`) — not a new
repository, matching `go-duckdb-rewrite.md` §9's decision that this is
a branch within the current repo. A Cargo workspace, promoting each
already-spiked piece into a real library crate rather than a one-off
binary, plus one server binary that wires them together:

```
v4/
  Cargo.toml                 (workspace)
  crates/
    cache/                   (promoted from edgar-cache-spike — the
                               general moka-backed TTL+LRU type, generic
                               over K/V, no EDGAR-specific knowledge)
    edgar/                   (promoted from edgar-spike + edgar-index-
                               query — edgarkit wrapper: firmographics
                               fetch, catalog ingest, feather read/write)
    sic/                     (promoted from df-spike/ic-similarity-
                               service — DataFusion data access +
                               fastembed-rs query-time embedding for
                               US SIC)
    wikipedia/                (promoted from experiments/wikipedia-spike/
                               — real HTTP client, §8.1, built 2026-09-28)
    firmographics/             (real merge logic, §8.2, built 2026-09-28)
    server/                  (binary — Axum, wires the above crates to
                               real HTTP routes, §5/§6)
```

**Decided (2026-09-28): DataFusion 55.x, and `edgarkit` for EDGAR** —
both confirmed explicitly (`go-duckdb-rewrite.md` and
`edgar-backend.md`'s status lines), not just implied by this
prototype's own requirements. The two decisions are linked: items 1 and
2 together mean SIC (DataFusion) and EDGAR (`edgarkit`) live in the
*same server process* — that's the whole point of combining them into
one prototype — and `edgar-backend.md` §2.1 already found that
`edgarkit` and DataFusion 42 cannot share a `Cargo.toml` at all (a real
`chrono`-version conflict, not a workaround-able one). `go-duckdb-
rewrite.md` §7.9 re-validated that DataFusion 55.1.0 changes nothing
about the already-proven SIC results, before either decision was made —
so this prototype starts from a settled architecture, not an open
question.

## 4. Data staging: the EDGAR catalog, written to `./tmp`

The "EDGAR 10-x initial catalog" (item 2) is `edgar-index-query`'s
pattern, generalized from a one-off test into a real ingest step:

- A small binary (working name: `v4-ingest-edgar`, under
  `v4/crates/edgar/` or its own `v4/bin/`) that calls `edgarkit`'s
  `get_period_filings` for a given year/quarter, filters to the
  `'10-%'` form family (kept broad, per `edgar-backend.md`'s decision
  not to narrow it), and writes the result to a `.feather` file —
  exactly `edgar-spike`'s `write_feather` function, promoted rather than
  rewritten.
- **Output path: `./tmp/edgar_10x_catalog.feather`**, at the repo root
  — not under `v4/` — matching where `tmp/us_flat.feather` and
  `tmp/us_flat_embedded.feather` already live, and covered by the same
  existing `.gitignore` entry (`tmp/`). This keeps one staging
  convention across both the SIC and EDGAR data, rather than inventing
  a second location.
- **Scope for the prototype**: one recent, fully-published quarter
  (the same choice `edgar-spike` already made) — not a historical
  backfill. `pyedgar`'s `IndexMaker` can pull multiple quarters;
  whether/how V4 eventually does the same is a real question but not
  this prototype's — it needs *a* real catalog to serve V3-parity
  endpoints against, not the complete one.
- **Decided (2026-09-28): catalog freshness is a build-time concern,
  not a runtime one.** The real service's refresh story is a GitHub
  Actions workflow that rebuilds the image monthly with a freshly
  ingested catalog baked in — the same shape this ingest step already
  is (§4's ingest binary, run once at build time, `.feather` written to
  `./tmp` and packaged into the image), just on a schedule rather than
  invoked manually for this prototype. **This means the server itself
  never needs to know about refreshing** — no cron, no background
  re-ingest job, no "is the catalog stale" logic inside the running
  process. Out of scope for this prototype specifically (no CI workflow
  being built here, just the ingest step the workflow would eventually
  call), but no longer an open question about *how* it would work.
- **EDGAR spillover** (live firmographics for CIKs not in the catalog,
  or a catalog entry that's gone stale) is `edgar-cache-spike`'s
  cache-on-top-of-`edgarkit` pattern, wired directly into the `edgar`
  crate's client — no new design needed here, just assembly.

## 5. New V4 endpoints

### 5.1 SIC similarity search

Mirrors `ic-similarity-service`'s `/api/similar`, but as a real
versioned V4 endpoint using V3's own URL-shape convention
(`/V{version}/{region}/{resource}/...`):

```
GET /V4.0/na/sic/similarity/{query}
```

Backed by the same DataFusion + `array_distance` + `fastembed-rs`
(`all-MiniLM-L6-v2`, per `go-duckdb-rewrite.md` §7.8) pipeline
`ic-similarity-service` already validated, reading
`tmp/us_flat_embedded.feather` (or whatever the real V4 data path ends
up being once it's not a spike). The Simple/Detailed input distinction
`ic-similarity-search-poc.md` §4 validated is a UX concern (query length
handling can stay a simple query-string length check at the API level
for now); the calibrated-label response shaping from that same doc is
worth carrying into the JSON response body's field *names* even before
there's a UI to render them, so the API doesn't need a breaking change
once §9's UX work resumes. **Envelope**: since the breaking-change
question for V4-only endpoints is explicitly deferred (§10), this
starts out wrapped in V3's `{code, message, module, data, dependencies}`
envelope too — the simplest default, not a decision that this endpoint
is locked into that shape long-term.

### 5.2 US SIC lookup (V3 parity)

Same five V3 endpoints, same URL shape, `/V3.0/` → `/V4.0/`:

| V3 | V4 |
|---|---|
| `GET /V3.0/na/sic/description/{sic_desc}` | `GET /V4.0/na/sic/description/{sic_desc}` |
| `GET /V3.0/na/sic/code/{sic_code}` | `GET /V4.0/na/sic/code/{sic_code}` |
| `GET /V3.0/na/sic/division/{division_code}` | `GET /V4.0/na/sic/division/{division_code}` |
| `GET /V3.0/na/sic/industry/{industry_code}` | `GET /V4.0/na/sic/industry/{industry_code}` |
| `GET /V3.0/na/sic/major/{major_code}` | `GET /V4.0/na/sic/major/{major_code}` |

Backed by a DataFusion SQL query against the `us_flat.feather`-shaped
table (`section_id`/`division_id`/etc. — `go-duckdb-rewrite.md` §7.2's
already-confirmed schema) instead of `lib/sic.py`'s SQLite queries. See
§6 for the one real semantic question this raises (exact-match vs. V3's
`LIKE`-based fuzzy match).

### 5.3 Health

```
GET /health
```

Not versioned (V3's own `/health` isn't either — `baseline.py`'s
`"category": "control"` liveness endpoint, no DB/network calls), and
not wrapped in V3's `{code, message, module, data, dependencies}`
envelope, since V3's `/health` isn't wrapped in it either
(`company_dns.py`'s `health_check`) — this is the one V3 endpoint that
was never inside that envelope to begin with, so "parity" here means
matching its actual bare-object shape, not V4's usual envelope.
**Real V3 parity, corrected**: an earlier pass had V4's handler return
a bare `"ok"` string instead of matching V3's response body — fixed.
Both now return the same three fields:

```json
{"status": "healthy", "version": "4.0.0", "timestamp": "2026-09-28T16:53:51Z"}
```

(`version` is expected to differ — V3 reports `"3.2.0"`, V4 reports
its own `"4.0.0"`; `status`/`timestamp` shape match exactly, ISO 8601
UTC with a trailing `Z`, via `chrono::Utc::now().to_rfc3339_opts(...,
true)` matching V3's `datetime.utcnow().isoformat() + "Z"`.) **Not yet
in the `--profile v4` harness catalog** (§7): `baseline.py`'s
`ENDPOINTS["health"]` entry has no `v4_path`, so `profile_endpoints("v4")`
excludes it today even though the route exists and now matches V3 —
a one-line gap (add `"v4_path": "/health"` to that entry), not a
missing implementation, worth fixing before the next comparison run
rather than in this doc pass.

### 5.4 EDGAR (V3 parity)

| V3 | V4 |
|---|---|
| `GET /V3.0/na/companies/edgar/ciks/{company_name}` | `GET /V4.0/na/companies/edgar/ciks/{company_name}` |
| `GET /V3.0/na/companies/edgar/detail/{company_name}` | `GET /V4.0/na/companies/edgar/detail/{company_name}` |
| `GET /V3.0/na/companies/edgar/summary/{company_name}` | `GET /V4.0/na/companies/edgar/summary/{company_name}` |
| `GET /V3.0/na/company/edgar/firmographics/{cik_no}` | `GET /V4.0/na/company/edgar/firmographics/{cik_no}` |

`ciks`/`detail`/`summary` query the `./tmp/edgar_10x_catalog.feather`
catalog from §4 (DataFusion, name search — see §6 for the fuzzy-match
question again); `firmographics/{cik_no}` is the cached live-fallback
path from §4's last bullet — `edgar-cache-spike`'s pattern, not a new
design.

**Built (2026-09-28), at parity with V3.** An earlier pass deferred
`detail`'s per-match live firmographics enrichment - **corrected
(2026-09-28): this was the wrong call for a port.** Consistency with
the data V3 actually returns matters more than the extra live calls
`detail` costs; deferring it would have made V3 and V4 answer different
questions for the same endpoint, undermining the whole point of the §7
comparison. `EdgarCatalog::find_grouped_by_name` now groups matching
filings by company exactly like `lib/edgar.py`'s `get_all_details` loop
does (same `company_name` normalization, same `forms` map, same
`accession_key`/`filingIndex` construction, unpadded month/day and
all), and `detail` merges in a real, cached `edgarkit` firmographics
fetch per matched company (`summary` doesn't) - the same
`firmographics=True`/`False` split V3's single method makes via a
parameter. Verified against real data: `detail` for IBM returns full
firmographics with a `forms` map attached; `summary` returns the bare
`{cik, companyName, forms}` V3's `firmographics=False` path produces.

## 6. V3 parity: real semantic differences to watch, not just latency

The perf comparison in §7 is only honest if V3 and V4 are actually
answering the same question. One real difference needs a decision
before the comparison means anything:

- **V3's name search is `LIKE '%name%'`-fuzzy** (both `lib/sic.py` and
  `lib/edgar.py`, `EdgarQueries.get_all_ciks`/`get_all_details`) against
  a SQLite table. **Decided (2026-09-28): V4 matches V3's `LIKE`
  behavior exactly** — DataFusion's own `LIKE` operator, a direct
  drop-in, applied consistently to both SIC-description and
  EDGAR-company-name search rather than each endpoint inventing its own
  answer. This keeps the §7 comparison honestly apples-to-apples for the
  prototype. Anything more sophisticated (prefix/substring tuning, or
  something closer to §5.1's similarity search applied to name lookup
  too) is explicitly **deferred to when V4 has additional company data
  to justify it** — not a prototype-scope concern, and not worth
  designing against speculatively before that data exists.
- **V4's EDGAR catalog (§4) is one recent quarter**, not V3's
  multi-year `companies` table (built from whatever `pyedgar`'s
  `IndexMaker` has accumulated in the current deployment). A
  V3-vs-V4 comparison needs to either accept that V4 will legitimately
  return fewer/different results for older filings (a real, disclosed
  scope difference, not a bug) or scope the comparison's test company
  list (`perf_tests/companies.py`) to companies with filings inside
  V4's catalog window. **Decided (2026-09-28): disclose the difference
  in the harness's report** rather than trying to hide it by
  cherry-picking test data — this is a prototype-scope limitation worth
  being visible about, not something to paper over.

## 7. Extending the Python perf harness for V3-vs-V4 comparison

**Less new than it first looks — `perf_tests/` already has most of
this.** `baseline.py` produces a JSON report against one `--base-url`;
`perf_tests/compare.py` already diffs *two* `baseline.py` reports
(`before.json`, `after.json`) — per-endpoint median/p95 delta,
REGRESSION/IMPROVED flags, and **already handles an endpoint present in
one report but not the other** (`"(new in after)"`/`"(missing in
after)"` — see `print_sequential_diff`). That's exactly the "V4 doesn't
implement everything V3 does yet" situation this prototype is in. The
comparison workflow this doc needs may just be:

```bash
python3 perf_tests/baseline.py --base-url http://v3-host:8000 --out v3.json
python3 perf_tests/baseline.py --base-url http://v4-host:PORT --out v4.json
python3 perf_tests/compare.py v3.json v4.json
```

`compare.py`'s "before"/"after" framing (written for regression-testing
one service over time) maps directly onto "V3"/"V4" without needing to
be taught a new concept — two reports, diffed. Real gaps, not
assumptions, worth confirming once both servers exist rather than
guessing now:

- **`verify_endpoints_exist` currently hard-fails if any path in
  `ENDPOINTS` is missing from the target's `openapi.json`.** Pointed at
  V4 (which won't implement UK/ISIC/EU/Japan/Wikipedia/merged in this
  prototype — §1 scope, §8/§9), `baseline.py` would refuse to run at
  all rather than just skipping what's missing. Needs either a V4-scoped
  subset of `ENDPOINTS` (a second catalog, or a `--profile` flag
  selecting SIC+EDGAR-only) or relaxing the hard-fail to a warn-and-skip
  when the *target* is explicitly flagged as partial — the former is
  probably cleaner, since it keeps `verify_endpoints_exist`'s existing
  "refuse to silently 404" guarantee intact for V3's full run.
- **§6's semantic-difference disclosure** (catalog-scope misses vs. real
  misses, `LIKE`-vs-exact-match differences) isn't something
  `compare.py` can infer from latency numbers alone — worth a short,
  explicit note in this prototype's own results write-up rather than a
  new field threaded through the JSON report format, at least for the
  first comparison run.
- **Response-body correctness checks** (`run_concurrency_experiment`'s
  CIK-based cross-contamination check, `perf_tests/README.md`) assume
  V3's exact response shape/field names — worth confirming V4's
  envelope (§10's open question) matches closely enough for this check
  to still mean something, before assuming it transfers unmodified.

**Nothing here requires `baseline.py` itself to change** to add a
second `--base-url` — running it twice, once per target, already
produces the two reports `compare.py` wants. The real work is the
`ENDPOINTS`-catalog scoping bullet above, plus using the two tools
together and writing up what the comparison actually shows.

## 8. Wikipedia and merged firmographics — built (2026-09-28)

Originally staged as module boundaries only (per item 7/8, so the
crate structure in §3 wouldn't need reshaping later); promoted to real,
tested, live-verified implementations the same day, after
`experiments/wikipedia-spike/` validated the full approach.

### 8.1 Wikipedia searching, V3-shaped

`v4/crates/wikipedia/` — a real `WikipediaClient` struct (not a trait —
no second implementation exists to justify one) with a
`get_firmographics(&self, company_name: &str)` method matching
`lib/wikipedia_v2.py`'s method of the same name, wired to its own
instance of §3's `cache` crate (`FallbackCache<String, Arc<Value>>`,
`DEFAULT_TTL` 1 hour, `DEFAULT_CACHE_CAPACITY` 10,000 — same type
`edgar`'s client uses, own keyspace, string-keyed by page title/QID
rather than `edgar`'s `u64` CIK, cache-aside via `try_get_with` exactly
like `EdgarClient`) — what `edgar-cache-spike`'s Test 5 already
demonstrated the generic cache type supports.

**What's real**: the full pipeline `experiments/wikipedia-spike/`
proved out - narrowed `action=parse`/`action=query`/`wbgetentities`
requests, `maxlag`/429/503/Retry-After backoff, a wptools-derived
infobox/claims parser (`infobox.rs`), V3's field-construction logic
(`firmographics.rs`), V3's corporate-suffix hint restored and actually
executed as REST calls rather than just suggested
(`client::resolve_candidate`/`lookup_firmographics`), gated on infobox
presence (not just page existence - the fix that made bare "Alphabet"/
"Meta" resolve correctly instead of returning a misleadingly
"successful" all-`"Unknown"` response), and Wikidata-canonical-title-
correct (so a resolved redirect's claims aren't silently lost). 5
passing tests (`cargo test -p company-dns-wikipedia`), diff-verified
against V3's live output across 10 companies in the spike, and
live-verified again after promotion: `GET /V4.0/global/company/
wikipedia/firmographics/Alphabet` (bare) returns full correct data
(real CIK `0001652044`, ISIN, tickers); a genuine miss returns a real
`404` with V3's exact hint message as the JSON `message` — the
improvement over V3's own swallowed-hint bug (`company_dns.py`'s
custom 404 handler discards `HTTPException.detail` for every 404,
confirmed live against the deployment), delivered for real since V4's
`not_found` responses are always JSON, never HTML.

**Deliberately not ported**: the spike's `resolve_title` (MediaWiki
full-text-search-based bare-name resolution, 60% success on its 5 test
cases) — it answers a different, narrower question (a name phrased
completely unlike its Wikipedia title) than V3 parity needs, and stays
available in the spike as a starting point if that becomes a real
V4-only feature request later, per that spike's own README.

The server's `wikipedia_firmographics` handler
(`v4/crates/server/src/main.rs`) maps `WikipediaError::NotFound` to a
V3-envelope `not_found` response (HTTP 404) carrying that error's own
message - V3's exact hint text, byte-identical - in the `message`
field, and `WikipediaError::Request` (a genuine network/parse failure,
not "this company doesn't exist") to a `server_error` response (HTTP
500) instead, so a caller can tell the two apart. Route:
`GET /V4.0/global/company/wikipedia/firmographics/{company_name}`,
same URL shape V3 uses.

**History: `experiments/wikipedia-spike/` (2026-09-28)** — settled the
two open questions this section originally raised, before promotion.
First, **no
existing crate is worth building on**: `mediawiki`, `wikibase_rest_api`,
`wikidata`, and `wikipedia` were all checked against crates.io's API
(maintenance activity, downloads, feature surface); none provide
wptools' actual infobox/claims parsing logic (`lib/wikipedia_v2.py`'s
verbatim port, the genuinely hard part) or first-class `maxlag`/
429-503-backoff/field-narrowing support — the three things that
module's own docstring credits for beating wptools. Hand-rolling on
`reqwest`, the way `lib/wikipedia_v2.py` hand-rolled on `requests`,
gives direct control over exactly those three things instead of
working around a generic client. Second, **the approach reproduces in
Rust against the real, live API**: ran against IBM, Apple Inc., and
Tesla, Inc. — real infobox parsing (33-39 fields per company), real
Wikidata claims resolved with correct labels (Apple's real CIK
`0000320193` came back attached to the right property), concurrent
fetch (`tokio::join!`, mirroring `lib/wikipedia_v2.py`'s
`ThreadPoolExecutor(3)`) completing in ~0.9-1.3s per company for all
three calls together, in the neighborhood of the Python version's own
measured numbers, not a regression. `maxlag` sent on every request.

**Extended the same day: the parsing itself is now real, tested Rust
code, not a stand-in.** `experiments/wikipedia-spike/src/infobox.rs`
ports wptools' `_template_to_dict`/`_template_to_dict_iter`/
`_template_to_text` (`lib/wikipedia_v2.py`'s own verbatim-port source),
including nested-template-in-value handling and per-element tail text,
not just flat top-level pairs — `_template_to_dict_find`/
`_text_with_children` (the `find=True` branch) deliberately left
unported, since `_get_infobox` never calls into that branch on the path
this project exercises. `experiments/wikipedia-spike/src/firmographics.rs`
ports `get_firmographics`'s field-construction logic (`_get_item`,
`_transform_isin`, `_transform_stock_ticker`, the Wikidata-vs-infobox
fallback chains, the `Private Company (Assumed)` default) — the spike
now prints V3's actual firmographics shape end to end. Real output for
IBM: correct ISIN (`US4592001014`), correct ticker/exchange split
(`["NYSE", "IBM"]`), correct CIK/city/country/industry — same for Apple
Inc. and Tesla, Inc. And **the 429/503/Retry-After backoff path is now
proven, not just implemented**: `cargo test` in that crate mocks a real
503 response with `Retry-After: 1` and asserts the retry both happens
and is timed correctly (plus a second test confirming a persistent 503
exhausts retries and errors rather than hanging), closing the one gap
the original spike run flagged (Wikimedia didn't lag live during
testing, so the path was unexercised until now).

**Diffed against live V3 output the same day, field by field** —
fetched V3's real `/V3.0/global/company/wikipedia/firmographics/{name}`
response for IBM, Apple Inc., and Tesla, Inc. (that route already uses
the `WikipediaQueriesV2` v2 backend by default,
`company_dns.py` line 508) and compared every field programmatically
against the spike's output. Found and fixed two real V3-parity bugs
that the "extended" pass above had actually gotten wrong, not just
left undone: (1) `description` still had raw HTML tags — V3's Python
runs the extract through `html2text` before returning it, a step this
spike's `fetch_query` was missing entirely, now fixed with the Rust
`html2text` crate; (2) `cik`/`country` were always forced into a
1-element list, but V3 returns them as bare strings for a single value
— the earlier pass's claim that this was "an intentional simplification,
not a fidelity gap" was wrong, since wptools' own single-vs-list
collapse rule is part of the real output shape, and
`get_firmographics` doesn't re-wrap `country`/`cik` the way it re-wraps
`industry`/`exchanges`/`website`. After both fixes, every field matches
V3 exactly for all three companies except `description`'s whitespace (a
benign difference between the two `html2text` implementations' handling
of stripped empty inline markup, not a data-fidelity gap).

**Both remaining gaps closed the same day.** Widened the diff to all
10 companies in `perf_tests/companies.py` (not a hand-picked easy
sample) — zero non-`description` field mismatches across all 10, same
benign whitespace-only gap on `description` (0-8 characters, one
company matched exactly), confirming the fixes above weren't a
3-company coincidence. And implemented company-name-to-page-title
resolution (`resolve_title` in `experiments/wikipedia-spike/src/
main.rs`, using MediaWiki's full-text search) - genuinely new work,
since V3 takes `wiki_name` as a near-exact page title already and
neither V3 nor `lib/wikipedia_v2.py` resolve bare names at all.
**Honest result: 3/5 (60%)** - "JPMorgan"→"JPMorgan Chase" and
"Exxon"→"ExxonMobil" resolved correctly, but "Alphabet" and "Meta"
resolved to their own generic-word Wikipedia articles instead of the
company (naive top-hit full-text search loses to an established
primary-topic page when a company's name collides with a common word).

**Then checked whether this is actually a V3-parity gap by testing the
same bare names against the live V3 deployment - it is not.** V3 has
the identical problem and doesn't even attempt to solve it:
`lib/wikipedia_v2.py` calls MediaWiki's `titles=`/`redirects=1`
directly, no search step. `IBM`/`Walmart` work as exact titles;
`JPMorgan`/`Exxon` work only because Wikipedia itself has literal
redirect pages under those exact strings (MediaWiki's own mechanism,
not V3 logic); `Alphabet`/`Meta` 404 outright on the live deployment
too; and `MetaX` returns **wrong company data silently** (a real,
unrelated Chinese chip company's page) with no error signal at all -
a sharper failure mode than anything this spike hit. **Conclusion:
company-name resolution is not a V3-parity gap** - V3's real behavior
already is "caller supplies the near-exact title, full stop," matching
`perf_tests/companies.py`'s documented assumption exactly. This
spike's `resolve_title` and its 60% result stay available as a
starting point for a genuine V4-only feature later, but nothing about
promoting into `v4/crates/wikipedia/` needs to wait on it.

**Tracing V3's "not found" path further turned up a real bug, and it's
now fixed here.** V3's Python does compute a hint message ("try
[{query} Inc./Corp./Corporation]" - `lib/wikipedia.py`/
`lib/wikipedia_v2.py`'s identical `lookup_error`), but
`company_dns.py`'s custom 404 handler (`company_dns.py:129-146`)
unconditionally serves a static themed HTML error page for any 404 and
discards that hint text (`HTTPException.detail`) - confirmed live
against the deployment, the hint never reaches a client at all, dead
code on the response path. Restored it in the spike (`hint_message`,
byte-identical wording to V3's), then went one step further per direct
instruction: `resolve_candidate`/`lookup_firmographics`
(`experiments/wikipedia-spike/src/main.rs`) actually issue the
suggested REST calls server-side - raw name first, then V3's exact
three suffix candidates in order - instead of just telling the caller
to retry manually, so a hit returns real, usable firmographics data
directly. Proved the mechanism deterministically with a mock-server test
(`cargo test`: a missing bare name resolved via its " Inc." suffix).

**Then a first live run exposed a real gap: page existence alone isn't
enough.** `resolve_candidate` originally accepted the *first* candidate
with any page at all - exactly how "Alphabet" and "Meta" defeated it,
since both exist as real, unrelated Wikipedia pages (confirmed:
running `lookup_firmographics` for bare "Alphabet" returned a
**200 with every field "Unknown"** except a real-sounding
`description` about the linguistic concept of an alphabet and
`type: "Private Company (Assumed)"` - a misleadingly "successful"
response, worse than a 404, since nothing signals anything's wrong).
Traced why: pulled the real page's parsetree, 98 templates, zero with
"box" in any title (same on "Meta": 6 templates, zero). **Fixed**:
`resolve_candidate` now requires both a page AND an infobox
(`fetch_infobox`) before accepting a candidate. Re-verified live -
bare "Alphabet" now correctly rejects the wrong page, retries with
" Inc.", and returns fully correct data (real CIK, ISIN, tickers,
identical to querying "Alphabet Inc." directly).

**Fixing that surfaced a second real bug, found by testing "Meta"**:
it resolved to "Meta Inc." (a real page), but `cik`/`industry`/
`exchanges` came back "Unknown" and `country` came back garbled.
Traced it: Wikipedia's own API correctly follows the "Meta Inc." →
"Meta Platforms" redirect, but Wikidata's separate sitelink API does
**not** follow Wikipedia-side redirects - it only indexes the
canonical title, so a claims lookup for the redirect alias silently
returns nothing. **Fixed**: `QueryData` now carries the canonical
title Wikipedia's own redirect resolution already provides, and the
Wikidata call uses that instead of the literal candidate string.
Re-verified live - "Meta" bare now matches "Meta Platforms" queried
directly, field for field.

Along the way: `Lear` → `Lear Corp.` became the mechanism's first
genuine non-synthetic real-world hit (not a mock), and `Timken` (whose
real title is "Timken Company") surfaced an honest, unfixed gap -
"Company" isn't one of V3's three suffix guesses, faithfully
reproduced rather than patched with a fourth guess V3's own hint text
doesn't include. V4's `not_found` responses are always JSON
(`envelope.rs`), never HTML, so there's no equivalent swallowing bug to
reproduce.

**Promoted into `v4/crates/wikipedia/` (2026-09-28) — real, tested,
running, not a stub.** `client.rs`/`infobox.rs`/`firmographics.rs` are
the spike's own modules of the same names, carried over rather than
rewritten — same infobox/claims parsing, same suffix-hint mechanism
(infobox-gated, canonical-title-correct), same 5 passing tests
(`cargo test -p company-dns-wikipedia`). `WikipediaClient` now wraps
the real HTTP client in the same cache-aside pattern
`company-dns-edgar`'s client uses (`try_get_with`, title-keyed, 1hr TTL
— `WikipediaError::NotFound` results aren't cached, matching V3's own
behavior of never caching a miss). Wired into the server with a real
User-Agent (`company_dns_wikipedia::USER_AGENT`, matching
`lib/wikipedia_v2.py`'s own real-identity convention), and the
`wikipedia_firmographics` handler now distinguishes `NotFound` (→ 404,
V3's exact hint message, byte-identical) from `Request` (→ 500, a
genuine network/parse failure) instead of treating every error the
same way. **Verified live against the real server**: `GET /V4.0/
global/company/wikipedia/firmographics/Alphabet` (bare, no suffix)
returns full correct Alphabet Inc. data (real CIK, ISIN, tickers);
`.../Meta` returns full correct Meta Platforms data; a genuine miss
(`.../Zzzznotarealcompany123`) returns a real `404` with V3's exact
hint text as the JSON `message` — the improvement over V3's own
swallowed-hint bug, delivered for real.

### 8.2 Merged firmographics

`v4/crates/firmographics/` — mirrors `lib/firmographics.py`'s
`GeneralQueriesV2` shape (combine EDGAR + Wikipedia results for one
company), depending on both the `edgar` crate (real, per §5.4) and the
`wikipedia` crate (now also real, per §8.1). The merge endpoint
(`GET /V4.0/global/company/merged/firmographics/{company_name}`, V3's
own shape) routes correctly.

**Fixed the same day, found while verifying the §8.1 promotion live**:
`merge()` previously took `wikipedia_error: Option<String>` only — no
parameter existed for successful Wikipedia data at all, a leftover
from when §8.1 was a stub that always errored. Once §8.1 started
actually succeeding, this became a real, visible bug: a successful
merge claimed `"source": "edgar+wikipedia"` while silently omitting
the Wikipedia data from the response entirely. `merge` now takes
`wikipedia: Result<Value, String>` and genuinely includes the data on
success — verified live: `.../merged/firmographics/International%20
Business%20Machines` returns `"source": "edgar+wikipedia"` with both
`edgar` and `wikipedia` keys actually populated; `.../merged/
firmographics/IBM` (a name EDGAR's fuzzy catalog match misses, a
pre-existing, separate, unrelated limitation) correctly falls back to
`"source": "wikipedia-only"` with real Wikipedia data still present.

## 9. UX: explicitly deferred

No `html/`, no web UI, for this prototype. JSON API only. An
OpenAPI-equivalent discovery endpoint is worth keeping (§7's harness
extension leans on `openapi.json` existing, the same way it already
does for V3) but that's API introspection, not a UX decision — nothing
here should be read as prejudging what
[`company-dns-ux.md`](company-dns-ux.md) eventually decides. That doc's
own §7 next-step ("react to this skeleton... before it grows further")
is still where UX work resumes, together, once this prototype gives us
something real to design a UX around rather than a hypothetical one.

## 10. Open questions

- ~~DataFusion 55.x: needs an explicit go-ahead before scaffolding...~~
  **Decided (2026-09-28)**: DataFusion 55.x and `edgarkit`, confirmed
  explicitly (§3, `go-duckdb-rewrite.md`/`edgar-backend.md` status
  lines) — no longer a precondition to confirm, a settled starting
  point.
- ~~§6's matching-semantics decision...~~ **Decided (2026-09-28, §6)**:
  V4 matches V3's `LIKE` behavior exactly; anything more sophisticated
  deferred until additional company data justifies it.
- ~~EDGAR catalog refresh policy...~~ **Decided (2026-09-28, §4)**: a
  monthly GitHub Actions workflow rebuilds the image with a freshly
  ingested catalog baked in — a build-time concern, not something the
  running server needs any logic for.
- **Response envelope shape — decided for V3 endpoints, deferred for
  V4-only ones (2026-09-28).** V3's `{code, message, module, data,
  dependencies}` envelope (`go-duckdb-rewrite.md` §2) **must stay
  identical, verbatim, for every V4 endpoint that's a V3-parity
  replacement** (§5.2/§5.4) — anything downstream still expecting that
  shape, and the §7 perf comparison itself, depend on it not changing.
  For genuinely new V4-only endpoints (§5.1's SIC similarity search,
  anything else V3 has no equivalent for), breaking changes to the
  envelope are explicitly on the table — but that discussion is
  deferred, not decided here. §5.1 should ship with *some* envelope
  (V3's, for now, being the simplest default) rather than block on this
  question; revisiting it isn't a breaking change to anything yet, since
  nothing downstream depends on a V4-only endpoint's shape before it
  exists.

## 11. Next steps

1. ~~Confirm §3's DataFusion 55.x requirement explicitly before
   scaffolding anything...~~ **Done (2026-09-28)** — DataFusion 55.x and
   `edgarkit` both confirmed explicitly (§3).
2. Scaffold the `v4/` workspace (§3) — crate skeletons, no logic yet.
3. Promote `edgar-cache-spike` into `v4/crates/cache/` — smallest,
   most self-contained piece, and everything else depends on it.
4. Promote `edgar-spike`/`edgar-index-query` into `v4/crates/edgar/`;
   build the real `./tmp/edgar_10x_catalog.feather` ingest step (§4).
5. Promote `df-spike`/`ic-similarity-service` into `v4/crates/sic/`.
6. Build `v4/crates/server/`: §5's endpoints, wired to §3's crates,
   settling §6's matching-semantics question as part of this work, not
   before it.
7. ~~Stub `v4/crates/wikipedia/` and `v4/crates/firmographics/` (§8).~~
   **Done (2026-09-28), and promoted to real implementations the same
   day** — `experiments/wikipedia-spike/` validated the approach, then
   both crates got the real code, not just stubs (§8.1/§8.2).
8. Scope a V4-appropriate `ENDPOINTS` subset for `baseline.py` (§7),
   run it against both V3 and V4, and feed both reports into the
   already-existing `perf_tests/compare.py` for the first real
   V3-vs-V4 comparison.
9. Bring the results back to `company-dns-ux.md` §7 — real endpoints
   and real performance data change what's worth designing a UX around.
