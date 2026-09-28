# V4 prototype server: US SIC (feather) + EDGAR (edgarkit + cache), V3-parity endpoints

Status: **Draft — plan only, no code written yet.** This doc lays out
what a first running V4 server looks like, combining what's already
been individually proven in `experiments/` into one real process for
the first time — not a new round of research, but the point where the
separately-validated pieces get wired together and measured against the
current V3 Python service on a consistent set of endpoints.
Owner: michael.hay@mediumroast.io
Scope: a prototype `company_dns` V4 server (Rust + DataFusion, per
[`go-duckdb-rewrite.md`](go-duckdb-rewrite.md) §6.5/§9) covering US SIC
similarity/lookup and EDGAR (initial catalog + live spillover, per
[`edgar-backend.md`](edgar-backend.md)), implementing the subset of V3
endpoints needed for a real side-by-side performance comparison, plus
new SIC-similarity endpoints V3 has no equivalent for. Explicitly
**not** in this prototype: a UX/UI (stays with
[`company-dns-ux.md`](company-dns-ux.md), deferred until we work on it
together — §9), a real Wikipedia client or merged-firmographics
implementation (§8 stages the module boundaries only), and the other
four SIC systems (UK/ISIC/EU-NACE/Japan) — US SIC only, matching what's
actually been spiked.

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
2. **New V4 endpoints for SIC similarity** — §5.3, following the same
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
    wikipedia/                (stub only — §8.1, trait/module boundary,
                               no real HTTP client yet)
    firmographics/             (stub only — §8.2, the merge shape, no
                               real merge logic yet)
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

### 5.3 EDGAR (V3 parity)

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

## 8. Staged, not built: Wikipedia and merged firmographics

Per item 7/8 — these get their module boundaries defined now, so the
crate structure (§3) doesn't need reshaping later, but no real
implementation in this prototype.

### 8.1 Wikipedia searching, V3-shaped

`v4/crates/wikipedia/` — a trait (working name `WikipediaClient`) with
the same method shape `lib/wikipedia_v2.py`'s `get_firmographics`
already validated conceptually (narrowed field requests, real
identifying User-Agent, `maxlag`/429/503 handling —
`go-duckdb-rewrite.md` §5.4), wired into §3's `cache` crate the same
way `edgar`'s client is (own instance, own keyspace, title/QID-keyed —
exactly what `edgar-cache-spike`'s Test 5 already demonstrated is
possible with the same generic cache type). **The implementation
returns "not yet implemented"** (a clear, typed stub response, not a
silent 404) — this section is about the shape being right when real
work starts, not about shipping a working Wikipedia client in this
prototype.

### 8.2 Merged firmographics

`v4/crates/firmographics/` — mirrors `lib/firmographics.py`'s
`GeneralQueriesV2` shape (combine EDGAR + Wikipedia results for one
company), depending on both the `edgar` crate (real, per §5.3) and the
`wikipedia` crate (stub, per §8.1). The merge endpoint itself
(`GET /V4.0/global/company/merged/firmographics/{company_name}`, V3's
own shape) can exist and route correctly in this prototype, but its
response necessarily reflects §8.1's stub until that's real —
documented as such in the response, not silently incomplete.

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
  replacement** (§5.2/§5.3) — anything downstream still expecting that
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
7. Stub `v4/crates/wikipedia/` and `v4/crates/firmographics/` (§8).
8. Scope a V4-appropriate `ENDPOINTS` subset for `baseline.py` (§7),
   run it against both V3 and V4, and feed both reports into the
   already-existing `perf_tests/compare.py` for the first real
   V3-vs-V4 comparison.
9. Bring the results back to `company-dns-ux.md` §7 — real endpoints
   and real performance data change what's worth designing a UX around.
