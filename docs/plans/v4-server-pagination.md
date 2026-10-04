# V4 server-side pagination (SIC search surfaces)

Status: **Scoped (2026-10-01), deferred to `V4.1.0`.** Raised while
reviewing V3's Swagger UI against V4's and realizing every "paginated"
list in V4 today is actually a full fetch with client-side `.slice()` -
a gap worth fixing deliberately before `sic-hybrid-search.md` and
`sic-global-search.md` both ship on top of the same pattern and have
to be retrofitted a second and third time. **Explicitly not part of**
`v4-initial-release-roadmap.md`'s initial dev/staging release or the
`V4.0.0` production-cutover milestone (§3a of that doc) - this doc's
design stays as a ready-to-build reference for whenever `V4.1.0` is
actually scheduled, not something blocking either nearer-term
milestone.
Owner: michael.hay@mediumroast.io
Scope: real server-side `LIMIT`/`OFFSET` pagination for SIC search
endpoints and the frontend changes needed to actually use it. Out of
scope: EDGAR/Wikipedia/firmographics (audit found these are
single-company lookups today, not paginated lists - see §2).

---

## 1. Why this matters now, not later

Today's "pagination" only feels instant because the entire result set
is already sitting in the browser's memory before the user ever clicks
"next page" - that's not representative of what real server-side
paging will feel like (network latency per page click, previously
absent). Worth deciding the backend contract and the UX tradeoffs
*before* `sic-hybrid-search.md`'s Hybrid endpoint and
`sic-global-search.md`'s multi-system endpoint get built on the same
fetch-everything assumption and need the same fix applied twice more.

## 2. Current state (audited 2026-10-01)

- **Keyword** (`GET /V4.0/na/sic/description/{query}`, `main.rs:339-344`)
  - No query params at all. `lookup.rs::find_by_description`
    (`lookup.rs:61-69`) runs an `ILIKE` query with **no `LIMIT`**,
    returns every match, full stop.
  - Same handler fn (`sic_description_impl`, `main.rs:315-330`) also
    backs `GET /V3.0/na/sic/description/{sic_desc}` - **this is the
    main constraint on this whole doc, see §3.**
- **Semantic** (`GET /V4.0/na/sic/similarity/{query}`, `main.rs:573-606`)
  - Takes `k` (default 10, clamped 1-50, `main.rs:547-560,585`) - a
    top-k cap, not a page size. No `offset`. `search_similar`
    (`similarity.rs:33-58`) issues one query with `LIMIT {k}`, no
    `OFFSET` - there's no way to fetch "ranks 11-20" today.
- **Frontend pagination is 100% client-side.** `global-search-alpine.js`
  fetches the full array once via `apiService.searchIndustryCodes`
  (`api-service.js:125-141`, no page/limit params sent), stores it in
  `this.allResults`, and `getCurrentPageResults()`
  (`global-search-alpine.js:255-267`) does
  `this.filteredResults.slice(start, end)` against `currentPage`/
  `resultsPerPage` (default 10). The server has already sent
  everything by the time "page 2" is clicked.
- Combine/Compare mode (`ic-explorer.js`) caps both columns at 10 via
  the same client-after-full-fetch pattern, with no "next page" UI at
  all today.
- grep across `crates/*/src` for `limit`/`offset`/`page`: only hits
  are `rate_limit.rs` (unrelated), `similarity.rs:55`'s `LIMIT {k}`,
  and Wikipedia API param names in test strings. No pagination param
  exists anywhere in the Rust code today.
- EDGAR (`edgar_ciks`, `edgar_detail`/`edgar_summary`,
  `edgar_firmographics`), Wikipedia, and merged firmographics
  (`main.rs:701-1001`) are all single-company path-param lookups, not
  paginated lists - out of scope per above, revisit only if that
  changes.

## 3. The real constraint: V3 byte-parity

`envelope.rs`'s own header comment is explicit: "every V4 endpoint
that's a V3-parity replacement keeps this envelope byte-for-byte
identical." `sic_description_impl` is that same function backing
**both** `/V3.0/na/sic/description/{sic_desc}` and
`/V4.0/na/sic/description/{sic_desc}` (`main.rs:315-344`). Adding
`limit`/`offset` query params or changing the `data` shape (from a
bare array to `{results, pagination}`) on that handler risks silently
changing the V3 alias's contract too, since it's the same code path.

**This doc's position: give the V4.0 route its own handler** (e.g.
`sic_description_paginated`), calling a new `lookup.rs` function,
rather than branching one shared handler on "is this the V3 route."
The V3.0 alias keeps calling the existing unpaginated
`find_by_description` untouched, forever. Cleaner than optional
params with "pagination only activates if present" logic living
inside a handler two different route contracts depend on.

## 4. Design

### 4.1 Wire params: `limit` / `offset`

Chosen to match the SQL underneath directly (and `similarity`'s
existing `k` precedent) rather than `page`/`per_page`. Defaults and
max clamp not chosen yet (§6).

### 4.2 Total count

A paginated UI needs "N results" / "page X of Y," which means knowing
the total match count, not just the current page's rows. Two options:

1. A second `SELECT COUNT(DISTINCT class_id) ... WHERE ...` query,
   same `WHERE` clause - simple, correct, doubles query cost per page
   load.
2. A `COUNT(*) OVER()` window function inside the same query (`SELECT
   *, COUNT(*) OVER() AS total_count FROM (...) LIMIT n OFFSET m`) -
   one round trip. DataFusion's window-function support is already
   being relied on in `sic-hybrid-search.md`'s `RANK() OVER` design,
   so this is plausible, but **not yet verified working in this
   codebase** - confirm before committing to it over the simpler
   two-query approach.

### 4.3 Per-endpoint plan

- **Keyword**: new `sic_description_paginated` handler (§3) +
  `lookup.rs::find_by_description_paginated(query, limit, offset) ->
  (Vec<SicMatch>, total)`. Straightforward - `ILIKE` with a stable
  sort order, `LIMIT`/`OFFSET` added directly. First to ship (§5).
- **Semantic**: deliberately **not** touched by this doc's first pass -
  see §6's open question on whether OFFSET-paging nearest-neighbor
  results even makes sense. Keep `k` as today's hard cap until that's
  decided.
- **Hybrid** (`sic-hybrid-search.md`) and **Global**
  (`sic-global-search.md`): neither is built yet - both should design
  pagination in from day one using whatever pattern §4.1/§4.2 settle
  into, not retrofit it after the fact like this doc is doing for
  Keyword.

### 4.4 Frontend changes

- `global-search-alpine.js`: replace "fetch everything once, slice in
  memory" with a real fetch per page - `firstPage()`/`prevPage()`/
  `nextPage()`/`lastPage()`/`goToPage()` (currently instant,
  synchronous array slices) become async server calls. `totalResults`/
  `totalPages` come from the server's new pagination field instead of
  `filteredResults.length`.
- **Real UX change worth calling out, not just plumbing**: page
  navigation currently has zero latency because the full set is
  already local. Once real fetches are involved, next/prev needs a
  loading state it doesn't have today.
- **Filtering interacts with this too**: classification-system
  filtering (`toggleFilter`) currently runs client-side against the
  full in-memory set, no server round-trip. Once the server paginates,
  a filter change has to re-fetch page 1 of the *filtered* set from
  the server (filters become query params) - otherwise "10 results"
  becomes "3 after filtering this page" instead of "3 after filtering
  overall," which looks broken. This is a real behavior change the
  frontend work needs to account for, not a side effect to discover
  later.
- `ic-explorer.js` (Compare mode's columns): lower priority - no
  "next page" UI exists there today at all (hard-capped at 10), only
  relevant once Semantic/Hybrid/Global get real pagination too.

## 5. Rollout order (proposed)

1. **Keyword first.** Simplest case (substring match, no ranking
   ambiguity to resolve first), and it's the one place that already
   has a full pagination UI built and waiting - proves the
   `limit`/`offset` + total-count pattern and the Alpine real-fetch-
   per-page change together, in the lowest-risk spot.
2. Decide Semantic's paging semantics (§6) before touching it at all.
3. Build Global (`sic-global-search.md`) and Hybrid
   (`sic-hybrid-search.md`) with real pagination from the start, reusing
   whatever contract step 1 establishes.

## 6. Open questions

- **Does OFFSET-paging make sense for semantic/ANN search past the
  first page at all?** Relevance decays with rank in a way substring
  matching doesn't - "page 2 of nearest neighbors" is a fuzzier concept
  than "page 2 of keyword matches." Needs an explicit decision, not an
  assumption either way, before Semantic is touched.
- **`COUNT(*) OVER()` vs a second `COUNT(*)` query** (§4.2) - not
  verified against this codebase's DataFusion setup yet.
- **`limit`/`offset` vs `page`/`per_page`** as the wire param names -
  leaning `limit`/`offset`, not decided.
- **Should classification-system filtering move server-side at the
  same time pagination does**, or stay a client-side post-filter
  limited to just the current page? The latter is cheaper to build but
  produces the "looks broken" result-count problem in §4.4. Not
  decided.
- **Default and max page size** - not chosen yet.

## 7. Explicitly out of scope

- EDGAR/Wikipedia/firmographics pagination - none of these return
  paginated lists today (§2); revisit only if that changes.
- The Global and Hybrid endpoints' own design - covered by their own
  docs. This doc only commits that whichever ships later launches with
  real pagination already, not bolted on afterward.
