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
  configuration. **Caveat found later by `ic-similarity-service/`**:
  that file's buffers may have been too small to actually exercise real
  zstd decompression — see that experiment's README before assuming
  DataFusion's zstd support needs zero configuration in general.
- **`embed-bench/`** — benchmarks the three embedding models
  `fastembed-rs` supports natively (`all-MiniLM-L6-v2`,
  `BAAI/bge-small-en-v1.5`, `all-mpnet-base-v2`) against real US SIC
  data, to pick which model(s) the rewrite's query-time embedding path
  should run. See §7.5 of the same doc for results and the
  low-dim/high-dim recommendation — **speed only, see `quality-eval/`
  for retrieval quality**, which complicates the pick made here.
- **`quality-eval/`** — measures retrieval *quality* (not speed) for all
  four embedding models, including `intfloat/e5-base-v2` (not covered by
  `embed-bench/`, but its precomputed vectors are testable without any
  Rust code), using the SIC hierarchy as a weak-label proxy for semantic
  relatedness. See §7.6 of the same doc. Notable result: `all-MiniLM-
  L6-v2` outperformed `bge-small-en-v1.5` on this specific dataset,
  contrary to general retrieval-benchmark expectations — flagged as
  SIC/NACE-specific, not assumed to transfer to company data.
- **`ic-similarity-service/`** — the first thing in `experiments/` that
  isn't a benchmark script: a small local REST service + minimal web UI
  wiring together DataFusion (data access), `fastembed-rs` (query-time
  embedding with the two §7.7-decided models), and Axum (HTTP), so
  similarity search can actually be typed into and looked at rather than
  read off a results table. Planned in
  [`docs/plans/ic-similarity-search-poc.md`](../docs/plans/ic-similarity-search-poc.md).
  Surfaced two real bugs while building it — a DataFusion
  `arrow-ipc`/zstd feature gap (see the `df-spike/` caveat above) and a
  mismatched Rust-vs-SQL API on DataFusion's `array_distance` function —
  both documented with fixes in this experiment's own README.
- **`edgar-spike/`** — tests whether the `edgarkit` crate can replace
  the current Python EDGAR implementation (`pyedgar`'s `IndexMaker` for
  quarterly index-building, plus `lib/edgar.py`'s hand-rolled JSON REST
  firmographics fetch), against real, live SEC EDGAR data. See
  [`docs/plans/edgar-backend.md`](../docs/plans/edgar-backend.md) §2.1/§5.
  Both halves passed cleanly: `get_firmographics()`'s exact output
  shape was rebuilt from a real IBM lookup using only `edgarkit`, no
  `pyedgar` or hand-rolled JSON parsing (and surfaced a real bug in the
  current Python code's ticker-list handling along the way); a real
  quarterly index download+parse took ~1.65s and reproduced almost
  exactly the ~3% `10-%`-form-type ratio already documented in
  `lib/prepare_edgar_data.py`'s own comment — a genuine cross-validation,
  not just a passing test.
- **`edgar-index-query/`** — the other half of `edgar-spike/`'s
  index-building test: loads the `.feather` file that spike writes with
  DataFusion and runs real SQL against it, same `read_arrow` pattern as
  `df-spike/`. Had to be a **separate crate**, not just another function
  in `edgar-spike/` — a real, unavoidable `chrono`-version conflict
  between `edgarkit` (needs `>=0.4.45`) and `arrow-arith`/DataFusion
  (no 53.x version works with that `chrono`), confirmed by trying to pin
  around it three different ways. All 9,241 rows round-tripped cleanly;
  a real query for IBM found its actual Q1 2025 10-Q. Also surfaced an
  unexpected finding: the `'10-%'` form-type filter both codebases use
  catches more than its own comment describes (`10-D`, `10-12G/B`,
  `10-KT` too, not just `10-K`/`10-K/A`/`10-Q`) — see this experiment's
  README for the full breakdown.
- **`edgar-cache-spike/`** — builds
  [`go-duckdb-rewrite.md`](../docs/plans/go-duckdb-rewrite.md) §5.1's
  general caching mechanism (`moka`, TTL+LRU, process-local) and wires
  it to `edgarkit`'s real live-fallback fetch — the piece that actually
  answers whether the whole EDGAR path works end to end, not just
  fetch-and-shape (`edgar-spike/`) or write-and-query
  (`edgar-index-query/`). Checked `edgarkit` for any built-in caching
  first (none — confirmed by a docs.rs search, zero hits). Five tests
  against real SEC data: a cache hit was **~46,000x faster** than a miss
  (11.75µs vs. 544ms); 5 concurrent requests for the same uncached CIK
  produced only **1** real network fetch (`moka`'s single-flight
  de-duplication, not something a hand-rolled cache gets for free); TTL
  expiry and LRU eviction (under a capacity-2 cache) both confirmed with
  real re-fetches, not just cache statistics; and the same `Cache<K, V>`
  type was reused with a completely different key/value shape as a
  stand-in for a future Wikipedia instance, proving "one mechanism, not
  two" holds in code.
- **`wikipedia-spike/`** — tests whether `lib/wikipedia_v2.py`'s
  approach (narrowed field requests, one targeted Wikidata labels call,
  a real User-Agent, `maxlag`/429/503/Retry-After handling — the fixes
  that module's docstring credits for beating wptools on speed and
  leanness) reproduces in Rust against the real, live MediaWiki/Wikidata
  API, and whether an existing crate (`mediawiki`, `wikibase_rest_api`,
  `wikidata`, `wikipedia`) is worth building on instead of hand-rolling,
  the way `edgarkit` was for EDGAR. See
  [`docs/plans/v4-server-prototype.md`](../docs/plans/v4-server-prototype.md)
  §8.1. Decided against adopting a crate — none of the candidates
  provide the actually-hard part (wptools' infobox/claims parsing logic,
  which `lib/wikipedia_v2.py` ports verbatim) or the `maxlag`/backoff/
  field-narrowing that module's own advantage over wptools rests on.
  Ran live against IBM, Apple Inc., and Tesla, Inc.: real infobox
  parsing (33–39 fields each), real Wikidata claims resolved with
  correct labels (e.g. Apple's real CIK `0000320193` came back attached
  to the right property), concurrent fetch completing in ~0.9–1.3s per
  company for all three calls together — in the neighborhood of the
  Python version's own measured numbers. **Extended (2026-09-28)**: the
  infobox/claims parsing (`src/infobox.rs`) and `get_firmographics`
  field-construction logic (`src/firmographics.rs`) are now real, ported
  Rust code — verbatim ports of wptools' `_template_to_dict`/
  `_template_to_dict_iter`/`_template_to_text` and
  `lib/wikipedia_v2.py`'s `_transform_isin`/`_transform_stock_ticker`/
  fallback-chain logic, not stand-ins. Real output for IBM: correct ISIN
  (`US4592001014`), correct ticker/exchange split (`["NYSE", "IBM"]`),
  correct CIK/city/country/industry, V3's actual field shape. The
  429/503/Retry-After backoff path is also now proven, not just
  implemented — `cargo test` mocks a real 503+`Retry-After` response and
  asserts the retry actually happens and is actually timed correctly.
  **Diffed against live V3 output (2026-09-28)**: fetched V3's real
  `/V3.0/global/company/wikipedia/firmographics/{name}` response for
  all three companies and compared field-by-field. Found and fixed two
  real V3-parity bugs — `description` still had raw HTML tags (V3's
  Python runs the extract through `html2text` first; this spike's fetch
  didn't, now fixed with the `html2text` crate), and `cik`/`country`
  were always wrapped in a 1-element list when V3 returns them as bare
  strings for a single value (wptools' own single-vs-list collapse rule
  wasn't actually a harmless simplification, as an earlier pass had
  assumed — it's part of the real output shape). After both fixes,
  every field matches V3 exactly across all three companies except
  `description`'s whitespace (a benign difference between the two
  `html2text` implementations, not a data-fidelity gap). **Widened and
  extended further (2026-09-28)**: the diff now covers all 10 companies
  from `perf_tests/companies.py` (not a hand-picked easy sample) — zero
  non-`description` field mismatches across all 10, with the same
  benign whitespace-only gap on `description` (0-8 characters, one
  company matched exactly). Also implemented and tested
  company-name-to-page-title resolution via MediaWiki's full-text
  search (`resolve_title`) — genuinely new work, not a port of
  existing V3/Python behavior, since V3 takes a near-exact page title
  as input already. **Honest result: 3/5 (60%)** — "JPMorgan"→"JPMorgan
  Chase" and "Exxon"→"ExxonMobil" resolved correctly, but "Alphabet"
  and "Meta" resolved to their own generic-word Wikipedia articles
  instead of the company. **Then checked the live V3 deployment with
  the same bare names (2026-09-28) and found it has the same problem,
  worse — it doesn't even attempt resolution.** `IBM`/`Walmart` work
  because they're exact titles; `JPMorgan`/`Exxon` work only because
  Wikipedia itself has literal redirect pages under those exact
  strings (MediaWiki's own `redirects=1`, not any V3 logic); `Alphabet`/
  `Meta` 404 outright; and `MetaX` returns **wrong company data
  silently** (a real, unrelated Chinese chip company's page) with no
  error at all. Conclusion: company-name resolution is not a
  V3-parity gap — V3's actual behavior already is "caller supplies the
  near-exact title," so this spike's 60% naive-search result is a
  real V4-only feature question worth its own design discussion later,
  not something blocking promotion into `v4/crates/wikipedia/`.
  **Found something more interesting while tracing the "not found"
  path, and fixed it (2026-09-28)**: V3's Python *does* compute a hint
  message ("try [{query} Inc./Corp./Corporation]" — `lib/wikipedia.py`
  and `lib/wikipedia_v2.py`'s identical `lookup_error`), but
  `company_dns.py`'s custom 404 handler unconditionally serves a static
  themed HTML error page for any 404 and discards that hint text —
  confirmed live, it never reaches the client at all. Restored the hint
  in this spike (`hint_message`, byte-identical wording), then went
  further per instruction: `resolve_candidate`/`lookup_firmographics`
  actually issue the suggested REST calls server-side instead of just
  suggesting them, so a hit returns usable data directly.
  **Then found and fixed two more real bugs the same day, both
  discovered by testing "Alphabet"/"Meta" directly against the new
  mechanism**: (1) `resolve_candidate` originally accepted the first
  candidate with *any* page, which is how "Alphabet"/"Meta" broke it in
  the first place (both exist as real, unrelated pages) — fixed by also
  requiring an infobox (`fetch_infobox`) before accepting a candidate,
  verified live: bare "Alphabet" now correctly rejects the
  writing-system-concept page and resolves via " Inc." to the real
  company, with fully correct data (real CIK, ISIN, tickers). (2) Fixing
  that exposed a second bug on "Meta": Wikidata's sitelink API doesn't
  follow Wikipedia's own redirects, so looking up claims for a resolved
  redirect alias ("Meta Inc.") silently returned nothing — fixed by
  capturing the canonical title MediaWiki's redirect resolution already
  provides and using that for the Wikidata call. Both fixes proven with
  new deterministic tests plus live re-verification. Along the way,
  found the mechanism's first genuine non-synthetic real-world hit
  ("Lear" → "Lear Corp.") and a genuine remaining gap (the real Timken
  company's title is "Timken Company" — outside V3's three-suffix list
  entirely, not fixed, since it's not part of the heuristic being
  restored). See this experiment's own README for the full breakdown.

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
