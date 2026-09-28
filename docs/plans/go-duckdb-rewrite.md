# company_dns rewrite: Rust + DataFusion, parquet data products, cache-with-fallback

Status: **Language/engine decided: Rust + DataFusion (§6.5).** Most of
what follows is still a working draft to iterate on together — where a
decision has actually been made, it's marked `**Decided:**` explicitly;
everything else is still up for discussion. Title/scope below updated
from the original "Go, DuckDB" framing now that §6.5 has resolved that
question — earlier sections that still discuss Go or DuckDB as live
options are kept as-is (not rewritten after the fact) since the
reasoning that led to the decision is worth keeping visible.
Owner: michael.hay@mediumroast.io
Scope: a from-scratch rewrite of `company_dns` in Rust with DataFusion as
the query/data-access engine, backed by Mediumroast parquet/feather data
packages for SIC/NACE classification data (US legacy SIC, Japanese SIC,
UK SIC, EU NACE), plus a "cache a limited number of rows, fall back to
the live service" pattern for both EDGAR and Wikipedia data. Explicitly
**not** an incremental migration of the current Python/FastAPI/SQLite
codebase — the current implementation is preserved at tag
[`V3.3.0`](https://github.com/miha42-github/company_dns/releases/tag/V3.3.0)
and branch `archive/python-v3.3.0` for reference and rollback, and stays
in production until the rewrite is ready to replace it. **Purpose
reframed (§6.5): this is now explicitly a reference/example OSS project**
demonstrating how to use the IC-classification and enriched-company data
Mediumroast is giving away as free samples — not a bulk-processing
service; see §1's use-case list.

---

## 1. Motivation and goals

As stated, five things are driving this:

1. **Parquet data products for classification parity.** Mediumroast
   parquet packages covering legacy US SIC, legacy Japanese SIC, UK SIC,
   and EU NACE — bringing the new service to feature parity with what
   `company_dns` already does today (see `lib/sic.py`, `lib/uk_sic.py`,
   `lib/japan_sic.py`, `lib/eu_sic.py`, `lib/international_sic.py` and
   their `prepare_*_data.py` counterparts for the current, per-country
   implementations).
2. **EDGAR: cache a limited number of rows, fall back to the live SEC
   EDGAR service** when a lookup misses the cache.
3. **Wikipedia: same pattern** — cache a limited number of rows, fall
   back to the live Wikipedia/Wikidata service on a cache miss.
4. **Rust**, replacing Python/FastAPI (§6.5 — decided; originally
   framed as Go, changed after direct comparison against Rust).
5. **DataFusion**, replacing SQLite (§6.5 — decided; originally framed
   as "DuckDB replacing SQLite," resolved differently — DataFusion alone
   covers what both SQLite and DuckDB were being considered for, see
   §6.5's "resolves §4" note).

**"Why these five together" — resolved (2026-09-27), was an open
question here**: `company_dns`'s purpose has been reframed. Mediumroast
is giving away several IC classification systems (legacy Japanese SIC,
US SIC, an older NACE vintage) and a sample of enriched Wikipedia/EDGAR
company data — including precomputed-embeddings versions — as free
"taste" packages, expecting most recipients won't immediately know what
to do with them. **`company_dns` is the example OSS project answering
that** — a reference implementation demonstrating real use cases against
real Mediumroast data, not a production bulk-processing service (bulk
operations explicitly out of scope). Concretely, the use cases this
needs to demonstrate:

- Search for SIC/industry codes and get results back across the
  various IC systems (parity with today's multi-system search).
- **Match a company description to one or more IC systems** — given a
  company's descriptive text (which may be long), resolve it to its
  best-fit classification code(s) with the full hierarchical structure.
  This is a single-company-at-a-time capability (not a batch/bulk
  operation — corrected after an earlier draft of this doc
  mischaracterized it as "batch/API-oriented"), and a company can
  legitimately resolve to more than one code (real companies span
  multiple classifications). Design thinking (chunking long input,
  confidence/triage, multi-code output) is in
  [`docs/plans/ic-similarity-search-poc.md`](ic-similarity-search-poc.md)
  §10.2 — flagged there as likely deserving its own plan document.
- **Find companies based on a search.**
- **Find companies similar to a given company** (company-to-company
  similarity, using the enriched/embedded company data samples).
- **Issue a SQL query directly against the included cached data** —
  DataFusion's own SQL interface, already proven in
  `experiments/ic-similarity-service`, covers this directly (§6.5).

Not every use case works identically across every data source: some
searches can spill over to the live EDGAR/Wikipedia services on a cache
miss (per items 2/3 above), some genuinely can't (the IC/classification
data is a static, self-contained sample with no live-service
equivalent to fall back to). Same asymmetry for direct SQL access — it
works against whatever's cached/local, not against anything requiring a
live API call. Worth keeping this distinction explicit in the UX rather
than presenting every feature as uniformly available — see the new UX
planning doc.

## 2. What stays true from the current implementation

Not being thrown out, just carried forward as requirements:

- The response envelope shape (`code`, `message`, `module`, `data`,
  `dependencies`) — or a deliberate, documented replacement for it.
- CIK as the durable EDGAR identifier (not company name) — the current
  codebase has a known bug here (issue #33, see below) worth *not*
  repeating in the rewrite.
- The existing endpoint surface (EDGAR CIK/detail lookups, Wikipedia
  firmographics, merged firmographics, SIC/NACE description search) as
  the floor, not the ceiling.
- Whatever's actually landed on in the SQLite-vs-DuckDB vector search
  discussion below, since it bears directly on issue #53.

## 3. Open issues triage

Only four open issues in the tracker right now. Going through each with
an eye toward: does this get picked up *as part of* the rewrite, does it
stay a Python-only fix (if the current service needs to keep running for
a while), or is it WONTFIX because the rewrite makes it moot?

| # | Title | Recommended disposition | Rationale |
|---|---|---|---|
| [#53](https://github.com/miha42-github/company_dns/issues/53) | Augment SIC description data with similarity/semantic search using SQLite's vector function | **Pick up in the rewrite — but the backend choice below changes what "SQLite's vector function" even means.** | Filed assuming SQLite. If DuckDB replaces SQLite, this issue's premise needs revisiting, not just its implementation — see §4. Good anchor for that discussion regardless of outcome. |
| [#54](https://github.com/miha42-github/company_dns/issues/54) | Move client-side pagination to server-side pagination (API-breaking) | **Pick up in the rewrite.** | Already flagged as API-breaking in the issue itself — a new major version/implementation is the natural place to land a breaking API change, rather than breaking existing Python-service callers separately. |
| [#78](https://github.com/miha42-github/company_dns/issues/78) | Extract SIC data management functions into a separate module | **WONTFIX (on the Python codebase) — superseded by the rewrite.** | The motivation (share SIC logic more broadly, clean separation) is better served by the rewrite's data-product/parquet design from the start than by refactoring Python code that's being replaced. Worth confirming you agree before closing. |
| [#33](https://github.com/miha42-github/company_dns/issues/33) | `edgar.get_all_details()` keys a dict by company name instead of CIK | **WONTFIX (as filed) — but carry the underlying fix forward.** | The specific proposed diff is Python-specific and the file it targets won't exist post-rewrite. But the lesson (CIK is durable, name isn't) is exactly the kind of bug worth not re-introducing in Go — captured in §2 above. Recommend closing #33 with a comment pointing here, not silently. |

*No open issues about adding vector search were closed as WONTFIX in the
past — #53 is still open, hasn't been superseded by anything already
shipped. Worth a second pass once this doc is further along, in case
something changes the calculus for #54 or #78 (e.g., if pagination or SIC
module boundaries turn out to be harder to decide than expected, might
be worth doing in Python first as a testbed).*

## 4. Backend: SQLite vs. DuckDB, specifically for vector/semantic search

> **Superseded by §6.5** — kept as-is below since the reasoning is still
> useful context, but the actual resolution ended up being neither
> option: DataFusion alone (Rust, §6) handles parquet reads, vector
> search, and ad-hoc SQL access, already proven in
> `experiments/ic-similarity-service`, making this SQLite-vs-DuckDB
> framing moot rather than answered.

This is the concrete question issue #53 turns on, and the one place
where "which backend" isn't just a taste call — it's worth grounding in
actual data before deciding. Research below, current as of 2026-09-27.

### 4.1 Why this matters for *this* project specifically

The candidate dataset for #53 (SIC/NACE descriptions) is small:

| Source | Rows |
|---|---|
| `source_data/sic_data/sic-codes.csv` | 1,006 |
| `source_data/sic_data/industry-groups.csv` | 417 |
| `source_data/sic_data/major-groups.csv` | 84 |
| `source_data/sic_data/divisions.csv` | 11 |
| `source_data/eu_sic_data/NACE_Rev2.1_Heading_All_Languages.tsv` | 1,048 |
| **Total (US SIC + EU NACE only; UK/Japan not yet in-repo)** | **~2,566** |

Even generously assuming UK and Japanese SIC roughly double or triple
this, we're talking low-to-mid thousands of rows, not millions. That
number matters a lot: it's squarely in the range where **brute-force
vector search (linear scan) is fast enough that approximate nearest-
neighbor (ANN) indexing like HNSW is a nice-to-have, not a requirement.**
That reframes the comparison — it's not "which one has better ANN
performance at scale," it's "which one is more reliable and simpler for
a workload this size."

**Update, per discussion:** vectors for both the industry-classification
(SIC/NACE) data and company data will be **precomputed by Mediumroast
upstream**, using multiple algorithms, some specifically SIMD-oriented —
not generated at query time or ingest time by `company_dns` itself. This
pushes the reframing above even further: the runtime cost in question is
purely *similarity computation over already-computed vectors*, not
embedding generation. That's exactly the workload both candidates handle
well at this scale — `sqlite-vec`'s brute-force scan is explicitly SIMD-
accelerated (AVX/NEON), and DuckDB's entire execution engine is
vectorized/SIMD-oriented by design, so a brute-force `list_cosine_
similarity`-style scan in DuckDB isn't just "acceptable because the
dataset is small," it's arguably a natural fit for how DuckDB executes
queries generally. Either way, real ANN indexing (HNSW) looks even less
necessary than §4.1's row-count argument alone suggested — worth
confirming with an actual benchmark once we're at that point, but it
further weakens the case for taking on DuckDB VSS's production-readiness
risk (§4.3) to get ANN we probably don't need.

### 4.2 SQLite's vector search story

- **`sqlite-vec`** (Alex Garcia) is the actively maintained, current
  answer — pure C, no dependencies, runs anywhere SQLite runs (including
  WASM/browser). Stores vectors in `vec0` virtual tables; K-nearest-
  neighbor search via brute-force (linear) scan, SIMD-accelerated
  (AVX/NEON), multiple distance metrics and vector types (float, int8,
  binary). A community fork (`photostructure/sqlite-vec`) adds distance
  constraints, pagination, and space-reclaiming `optimize` on top, with
  releases as recent as February 2026.
- Independent assessment (Marco Bambini, "The State of Vector Search in
  SQLite"): calls `sqlite-vec` **production-ready**, with the caveat
  that vectors live in separate virtual tables, so queries need explicit
  joins back to the source data — a real but manageable ergonomic cost,
  not a reliability risk.
- **`sqlite-vector`** (sqlite.ai) is newer and more aggressive on
  performance (claims 50% faster inserts, ~17x faster queries with
  quantization vs. brute-force baselines) and allows vectors in ordinary
  tables, not just virtual ones — worth a look, but less battle-tested
  than `sqlite-vec`.
- **`sqlite-vss`** (the older Faiss-based extension) is **abandoned** —
  its own creator discontinued it over integration issues. Not a live
  option; mentioning only so we don't accidentally reach for it.
- **`libsql`/Turso** offers DiskAnn-based indexing, but indexing can take
  *hours* for typical datasets — a mismatch for a dataset that's a few
  thousand rows and changes rarely (SIC/NACE codes don't churn daily).

### 4.3 DuckDB's vector search story

- DuckDB's **VSS extension** adds HNSW-indexed vector similarity search
  (`l2sq`, `cosine`, `ip` distance metrics) on its fixed-size `ARRAY`
  type, built on the `usearch` library — real ANN, not brute-force.
- It is explicitly labeled **experimental** by DuckDB itself.
- The serious issue for a production service: **HNSW indexes only work
  on in-memory databases by default.** Persisting the index to disk at
  all requires opting into an experimental flag
  (`hnsw_enable_experimental_persistence`), and DuckDB's own
  documentation states plainly: *"we still recommend that you do not use
  this feature in production environments,"* because **WAL (write-ahead
  log) recovery for custom extension indexes isn't fully implemented** —
  a crash or unexpected shutdown with uncommitted changes can **corrupt
  the index or lose data**, requiring manual recovery.
- Deletions are marked, not pruned, so index quality can degrade over
  time without periodic maintenance — a real but secondary concern next
  to the persistence issue.

### 4.4 "Have our cake and eat it too": can DuckDB read SQLite directly?

Yes, and it changes the shape of the split-decision option below. DuckDB
ships a **core `sqlite` extension** (`ATTACH 'file.db' (TYPE sqlite);`,
autoloaded on first use) that reads *and writes* SQLite database files
directly via standard SQL — no ETL step, no copying data between
engines. Unlike the VSS extension, this one is **not** flagged
experimental in DuckDB's own docs; it reads as a stable, production-
oriented core extension.

Caveats worth knowing before leaning on this:

- **Unconfirmed: does it see `sqlite-vec`'s `vec0` virtual tables?**
  DuckDB's sqlite extension documentation only discusses standard
  SQLite b-tree tables — it doesn't mention virtual tables or loading
  third-party SQLite runtime extensions (like `sqlite-vec` itself) at
  all. Silence isn't a "no," but it's not a "yes" either — DuckDB embeds
  its own SQLite reader, and interpreting a `vec0` virtual table
  requires the `sqlite-vec` module to be registered with *that* SQLite
  instance, which may or may not happen automatically. **This needs a
  small spike/prototype to confirm one way or the other before
  designing around it** — don't assume it works without testing it.
- **Type enforcement**: DuckDB is strictly typed, SQLite is weakly
  typed; the extension converts via type-affinity rules, with an
  `sqlite_all_varchar` escape hatch if needed (must be set before
  attaching).
- **Single writer at a time** across the attached SQLite file (multiple
  concurrent readers are fine) — a non-issue for SIC/NACE data that
  changes on Mediumroast's release cadence, not continuously.
- Don't link multiple copies of the SQLite library into the same
  process — DuckDB's own docs flag this as a real footgun, worth keeping
  in mind if the Go binary *also* links a separate SQLite driver
  directly (likely, if we want `sqlite-vec` support at all — see below).

**What this actually buys us**, assuming the virtual-table question
above resolves favorably (or even if it doesn't): the plain relational
data sitting alongside the vectors — SIC/NACE codes, descriptions,
metadata, whatever else lives in ordinary tables in that SQLite file —
becomes queryable from DuckDB with zero duplication, joinable directly
against parquet-backed company/EDGAR data in the same DuckDB query. The
vector *similarity search* step itself may still need to go through
SQLite directly (via a Go SQLite driver with `sqlite-vec` loaded) rather
than through DuckDB's attachment, if the virtual-table question above
comes back "no" — in which case the likely shape is: SQLite computes the
nearest-neighbor SIC/NACE codes, hands back a small set of IDs, and
DuckDB does everything else (joins, parquet reads, aggregation) using
those IDs. Not as seamless as one unified query, but still a real "both,
each doing what it's good at" architecture rather than a forced either/or.

### 4.5 Comparison table

| | SQLite (`sqlite-vec`) | DuckDB (VSS extension) |
|---|---|---|
| Index type | Brute-force / linear scan (SIMD-accelerated) | HNSW (true ANN) |
| Maturity | Actively maintained, called production-ready by independent review | Explicitly experimental per DuckDB's own docs |
| Disk persistence | Standard SQLite durability — no caveats | Requires an experimental flag; off by default |
| Crash safety | Standard SQLite WAL | **DuckDB's own docs warn of data loss/index corruption on crash** — WAL recovery incomplete for this extension |
| Fit for ~2.5-10k row SIC/NACE dataset | Good — brute-force is plenty fast at this scale | Overkill on the index side, and the extra ANN sophistication isn't worth the persistence risk here |
| Query ergonomics | Extra join (vectors in a separate virtual table) | Native `ARRAY` column, no join needed |
| Ecosystem trajectory | Multiple independent, competing implementations (`sqlite-vec`, `sqlite-vector`) actively improving | Single official extension, DuckDB-maintained, but stuck at "experimental" for a while |

### 4.6 Where this leaves us

The data supports your instinct: **for this project's actual workload
(a few thousand rows of classification-code text, read far more often
than written, where "good enough" similarity ranking beats sub-
millisecond ANN), SQLite's vector story is the safer choice** —
specifically because DuckDB's own documentation disqualifies its VSS
extension from production use today, not because of any performance
gap. If DuckDB's stance on WAL recovery/persistence changes later,
that calculus could change too — worth a "recheck before committing"
note rather than treating this as permanently settled.

§4.4 makes the "split the decision" option below meaningfully more
attractive than it would otherwise be: it's not just "run two separate
embedded databases and stitch results together in application code," it
could be "SQLite owns the vector index, DuckDB transparently reads
everything else out of that same file plus parquet, in one query
language." That's a materially nicer architecture *if* the virtual-table
question resolves favorably — worth prototyping early, since it's cheap
to test and the answer changes how much of the "split" option's cost is
real.

**This is a real tension with goal #5 above** (DuckDB replacing SQLite
generally, for its analytical/parquet-native strengths — which matter a
lot for reading the Mediumroast parquet data products directly). Options
to think through together, not decided here:

- **Split the decision**: DuckDB for the parquet-backed classification
  data (its actual strength — querying parquet directly, no ETL step),
  SQLite (with `sqlite-vec`) specifically for the semantic-search index
  over SIC/NACE descriptions. Two embedded stores instead of one, but
  each doing what it's better at.
- **DuckDB only, brute-force vector search via plain SQL** (a
  `list_cosine_similarity`-style scan, no HNSW index at all) — sidesteps
  the experimental-index risk entirely, and at ~2.5-10k rows, a full
  scan without an index may simply be fast enough that the HNSW question
  is moot either way. Worth benchmarking before assuming this isn't
  viable.
- **SQLite only**, and read the parquet data products into SQLite at
  ingest time rather than querying parquet natively — gives up DuckDB's
  parquet-native convenience, keeps one storage engine.
- **Revisit DuckDB's VSS extension status closer to implementation
  time** — it's explicitly evolving (see the 2026 development activity
  in the research above); "experimental today" isn't necessarily
  "experimental when we actually build this."
- **DataFusion-native (if §6 lands on Rust)**: skip the SQLite/DuckDB
  question for vector search entirely. DataFusion already has a
  SIMD-kernel `cosine_distance` function over Arrow arrays, and with
  vectors arriving precomputed (§4.1) and both SIC/NACE *and* company
  data arriving as Arrow-native `.feather` (§6.3), the same query engine
  that reads the parquet/feather data could do the similarity search
  too — no second embedded store at all. See §6.3 for the full
  DataFusion-vs-DuckDB writeup this option depends on.

## 5. Data architecture: cache-with-fallback (EDGAR, Wikipedia)

Both EDGAR and Wikipedia move from "always call the live service" (or
"rebuild an unbounded local cache from scratch on every image build," as
today's `companies.db` does) to: **keep a limited number of rows cached
locally, fall back to the live service on a miss.**

**Update, per discussion:** the cached rows themselves are also a
Mediumroast-supplied parquet data product, same delivery mechanism as
the SIC/NACE classification data in §1 — not something `company_dns`
builds up on its own from scratch. Several open questions from the first
draft are now settled:

- **Decided: no write-back to the persistent store, ever.** A live
  EDGAR/Wikipedia fallback answer is served to the caller and not
  written into the parquet-backed cache. The cached set changes only
  when Mediumroast ships a new parquet package — one source of truth,
  no risk of a locally-written row disagreeing with what Mediumroast
  ships later for the same company.
- **Decided: company-to-company semantic search is in scope.** Since
  company data gets the same precomputed-vectors treatment as SIC/NACE
  data, "find companies similar to X" is a real feature this rewrite
  should support, not just SIC/NACE description search. Worth reflecting
  in whatever endpoint surface gets designed later, and worth keeping in
  mind for §4's backend decision too — the vector-search question isn't
  only about a ~2.5k-row SIC/NACE dataset anymore, it's also about
  however many companies Mediumroast's package includes (likely larger,
  though still probably not "needs real ANN" territory — worth getting
  an actual row-count estimate before assuming).
- **Decided: the row cap is set by Mediumroast**, not independently
  tunable by `company_dns`. The same capped package is also planned to
  be available as a **downloadable sample package** in its own right,
  separate from what ships inside `company_dns` — worth keeping the
  ingest path generic enough that both consumption modes (embedded in
  the service, standalone download) can share it rather than diverging.

**Still open: does a cache miss get *any* ephemeral, non-persistent
caching**, given there's no write-back to the real store? A few distinct
options, not mutually exclusive:

1. **No caching at all beyond the parquet-seeded set.** Simplest — every
   miss re-fetches live, every time, no matter how recently the same
   company was looked up. Correct by construction (nothing to go stale),
   but repeat lookups for anything outside the seeded set always pay
   full live-service latency.
2. **Process-local, in-memory cache with TTL + LRU eviction**, scoped to
   raw fallback responses only — never promoted to the vector-backed
   store, never appears in semantic search, purely a fast-path for
   *direct* repeat lookups within a process's lifetime. Lost on restart/
   redeploy, and not shared across replicas (each pod warms its own).
   This is the option flagged as interesting, especially for Wikipedia,
   where live latency is the highest (per V3.3.0's numbers, even the
   v2 backend is ~700-1000ms median vs. a local lookup's sub-100ms).
3. **Shared in-memory cache across replicas** (e.g., Redis, or similar)
   — same idea as #2 but pooled, so a miss on one pod warms it for every
   pod. Removes the "N replicas, N cold caches" downside of #2, at the
   cost of a new external dependency this service doesn't have today.
4. **Rely on standard HTTP caching semantics** (respect Wikipedia/SEC's
   own `Cache-Control`/`ETag` headers via a local HTTP cache like Go's
   `httpcache`) instead of inventing a bespoke cache — piggybacks on
   protocol-level caching, works uniformly for both EDGAR and Wikipedia,
   less code to own.

No vectors get computed for anything cached this way, by design —
matches "we don't want to compute the vectors" — so none of these
options interact with §4's vector-search backend decision at all; they
only affect *direct*-lookup latency on a cache miss, not similarity
search.

- Does the EDGAR fallback path inherit anything from the current Python
  service's item-5 connection-reuse work, or is a Go-native equivalent
  (e.g., a shared `http.Client` with keep-alive) the right call instead?
  **Keeping all options on the table** — evaluate for best fit in Go
  rather than assuming a straight port.
- Same question for the Wikipedia fallback path and item 6's direct-
  HTTP approach (`lib/wikipedia_v2.py`) — the *idea* (narrow the
  MediaWiki/Wikidata requests to only the fields actually used, real
  identifying User-Agent, respect `maxlag`/429/503) carries over
  conceptually, but the Go implementation should be evaluated on its own
  merits rather than assumed to mirror the Python approach.

## 6. Language choice: Go vs. Rust

Raised by evaluating [tikv/tikv](https://github.com/tikv/tikv) and
[whispem/minikv](https://github.com/whispem/minikv) for the §5 caching
question — both Rust, which raised the question of whether Rust would
be a better overall fit than Go "for compatibility with these emerging
distributed KVS systems." Research below, current as of 2026-09-27.

### 6.1 The two KV stores themselves

**TiKV**: a serious, heavyweight, genuinely proven system — CNCF
*graduated* project (not just "hosted"), originally built by PingCAP to
back TiDB, in wide production use, handles 100+TB-scale deployments via
Raft-sharded regions and a Placement Driver. Written in Rust, yes — but
it's a full distributed database, not a caching library: running it
means operating a Placement Driver cluster plus RocksDB-backed storage
nodes, with Raft consensus and 2PC transactions. That's a lot of
operational surface for what §5 actually needs (an ephemeral cache for
EDGAR/Wikipedia fallback misses) — the same "overkill relative to actual
need" pattern as DuckDB's HNSW index in §4.3, just one level up in
infrastructure weight.

**minikv**: describes itself as "production-ready," with Raft consensus,
2PC, 256 virtual shards, an S3-compatible API, and even built-in vector
search — on paper, a lot of overlap with what this rewrite needs
generally. Worth the same skepticism applied to DuckDB VSS's self-
description earlier in this doc, though: it reads as a new, likely
solo/small-team project (recent "Show HN" post, a `v1.0.0` "GA line"),
with no independent production track record found comparable to TiKV's.
"Production-ready" is the author's own claim, not (yet) an outside
assessment. **One detail that undercuts the "need Rust for
compatibility" premise directly**: the same author also publishes
[`whispem/mini-kvstore-go`](https://github.com/whispem/mini-kvstore-go),
a Go implementation of essentially the same segmented-log/compaction/
bloom-filter design. If minikv-style compatibility is genuinely the
goal, a Go-native peer already exists from the same source — this isn't
a Rust-exclusive ecosystem.

**Lighter-weight Rust options exist too**, worth knowing about even
though they're a different category (embedded, single-node, no
clustering — closer to BoltDB/sled than to TiKV): `redb` (pure Rust,
copy-on-write B+trees, LMDB-like) and `fjall` (LSM-based, built for
higher write throughput). Neither is a distributed KVS; both are
reasonable if the actual need turns out to be "an embedded on-disk KV
store," which isn't what §5 described.

**Bottom line on the KVS question specifically**: none of these are
actually sized to §5's stated need. An ephemeral, process-local or
shared TTL+LRU cache for fallback-miss responses doesn't need Raft
consensus, sharding, or S3-compatible object storage — it needs
something closer to an in-process LRU cache (Go: `ristretto`; Rust:
`moka`) or, if cross-replica sharing matters, plain Redis (mature,
battle-tested, first-class clients in both languages, not something
either candidate here improves on for this use case). **Recommend not
letting the caching-layer choice drive the language choice** — the
caching decision (§5's four options) and the language decision are
close to independent, and treating them as linked risks a much bigger
decision (the whole rewrite's language) being anchored on a much smaller
one (how to cache Wikipedia lookups).

### 6.2 Go vs. Rust, on the dimensions that actually matter for this project

Skipping generic "which language is faster" framing in favor of what
this specific rewrite needs — parquet/Arrow-heavy data access, embedded
DuckDB + SQLite(+ `sqlite-vec`), moderate-concurrency HTTP fallback
calls, a multi-arch Docker/k8s deploy story, and (unstated but real) a
small/solo maintainer team.

| Dimension | Go | Rust |
|---|---|---|
| Parquet/Arrow ecosystem | `apache/arrow-go` is the official Apache implementation, but young and comparatively lightly adopted; `segmentio/parquet-go` is a solid community alternative, though its repo recently moved maintainership to `parquet-go/parquet-go`. Historically the weaker side of this comparison — Go "lacked an official and performant Parquet library" until arrow-go. | `apache/arrow-rs` + `datafusion` are the **official, first-party Apache implementations**, heavily used and actively developed (DataFusion's recent release cycle: ~740 commits from 139 contributors in ~11 weeks). This is Rust's strongest, most directly relevant advantage for *this* project specifically, given how central parquet + precomputed vectors are to the whole design. |
| DuckDB driver | `marcboeker/go-duckdb` — community-maintained Go bindings around DuckDB's C/C++ core. | `duckdb-rs` — community-maintained Rust bindings, similar shape. Roughly comparable maturity to the Go side; neither is DuckDB's own first-party client library. Worth a real evaluation pass on both, not assumed. |
| SQLite + `sqlite-vec` | `modernc.org/sqlite` (pure Go, no cgo) is a genuine, well-regarded advantage for plain SQLite — but it's a from-scratch reimplementation, not the real SQLite C library, so it's unclear it can load an arbitrary C extension like `sqlite-vec` at all. Loading `sqlite-vec` for real likely means falling back to a cgo-based driver (`mattn/go-sqlite3`), which gives up the pure-Go cross-compilation advantage. **Needs a spike**, same caveat as §4.4's DuckDB question. | `rusqlite` wraps the real libsqlite3 via FFI (optionally bundling the C source) and has a documented `load_extension` path — more directly compatible with loading `sqlite-vec` as-is, but it's still an FFI boundary either way, not a pure-Rust reimplementation. **Also needs a spike** to confirm in practice, not assumed to "just work." |
| Concurrency model | Goroutines + `net/http`: simple, well-proven for I/O-bound, moderate-concurrency services — which matches this project's actual profile (a REST API doing outbound HTTP calls and local DB lookups, not millions of concurrent connections). | `async`/Tokio is more powerful and can go further (production Tokio deployments handle far higher connection counts than this service will ever see), but that power comes with real complexity (`async fn` coloring, `Send`/`Sync` bounds, pinning) that this project's actual load doesn't obviously need. |
| Deployment / cross-compilation | Single static binary, trivially cross-compiled, well-matched to the existing `linux/amd64,linux/arm64` multi-arch Docker build (`.github/workflows/main.yml`) — an established Go strength. | Also produces static-ish binaries and cross-compiles reasonably well, but any cgo/FFI dependency (DuckDB's C++ core, `sqlite-vec`, potentially `rusqlite`) adds real cross-compilation friction on **both** languages here — this isn't a clean Go-wins point once those dependencies are in the picture either way. |
| Team fit | *Unstated — worth asking directly.* Do you (or anyone else likely to touch this code) have existing Rust experience, or would this be a first production Rust project alongside a first-ever rewrite? That's a bigger practical factor than most of the above rows for a small/solo-maintained OSS project. | *Same question, mirrored.* |

A few 2026 "Go vs. Rust" comparison posts turned up in research (blog
posts, not benchmarks run against this workload) claim things like
"Rust is 15-30% faster for CPU-bound work" and "50-80MB vs 100-320MB RAM
at runtime" — included for completeness, but **treated as directional
SEO-blog claims, not verified data**, the same posture this doc took
toward self-described "production-ready" claims elsewhere. `company_dns`
is not a CPU-bound workload (it's dominated by outbound network calls to
EDGAR/Wikipedia and small local DB lookups), so generic CPU-bound
benchmarks are unlikely to be the deciding factor regardless.

### 6.3 DataFusion vs. DuckDB, expanded

Worth digging into deeper, per request — two reasons: it's genuinely the
more interesting question than Go-vs-Rust in the abstract, and it
changes shape now that **Mediumroast will distribute data in `.feather`
format specifically, for Arrow compatibility** (in addition to the
parquet packages in §1). Feather V2 *is* the Arrow IPC file format —
they're not "compatible," they're the same bytes on disk — so this is
squarely an Arrow-ecosystem question, not a generic "which database is
faster" one.

**Architecturally, these two aren't really peers.** DataFusion is a
query *framework/library* — Arrow RecordBatches are its native, only
in-memory representation, and it's built with 16+ extension points
(`TableProvider` for custom data sources, `CatalogProvider`, physical
planners, and so on) explicitly for embedding inside a larger
application. DuckDB is a self-contained *embedded database* — its own
storage format, transactions, and catalog, packaged for "point it at
data and query it" use (a notebook, an ad-hoc analysis, a CLI). Spice
AI's comparison puts it plainly: DuckDB is the direct starting point
for ad-hoc/notebook analysis; **for a service with custom storage and
planning requirements, DataFusion offers the explicit integration
points** — and `company_dns` is unambiguously the second case, not the
first. A real-world data point in the same direction:
[Bauplan](https://bauplanlabs.com/post/duck-hunt-moving-bauplan-from-duckdb-to-datafusion)
(a data-platform company, not a hobby project) publicly moved *from*
DuckDB *to* DataFusion specifically because they were building a
product on top and needed the extensibility — the same shape of
decision this rewrite is facing.

**On `.feather`/Arrow IPC specifically, the gap is real and currently
in DuckDB's disfavor:**

- For DataFusion, reading a `.feather` file isn't an import/conversion
  step at all — Arrow IPC reads are inherently zero-copy when the
  source supports it (a memory-mapped file, a buffer reader), meaning a
  Mediumroast-shipped `.feather` file can be mmap'd straight into Arrow
  `RecordBatch`es with no deserialization. This is about as close to
  "native format" as it gets, because it *is* DataFusion's native
  format.
- For DuckDB, Arrow IPC/Feather support exists, but as a **community
  extension** (`arrow`, aliased to `nanoarrow`) — not core, not built
  in by default, and **not zero-copy**: it goes through
  nanoarrow-based encode/decode. DuckDB's own extension roadmap
  currently lists real gaps: no ZSTD/LZ4 compression support on writes,
  no LZ4 support on reads, no file-footer support yet. This is a
  younger, still-actively-developing piece of DuckDB, in clear contrast
  to DuckDB's native (and excellent) direct Parquet support — the
  Feather/Arrow-IPC story specifically is the weaker side of DuckDB
  right now, not the strong side.
- One unverified but relevant performance claim, worth flagging rather
  than either dismissing or leaning on: DataFusion has recently been
  reported as **the fastest single-node engine for querying Parquet,
  ahead of both DuckDB and ClickHouse**. Treated the same way as the
  Go-vs-Rust blog claims above — plausible, comes from a specific
  benchmark not independently re-verified here, shouldn't be
  load-bearing on its own, but consistent with the architectural story
  (Arrow-native, zero-copy-oriented design) rather than contradicting it.

**A genuine bonus, tying back to §4's vector-search question**:
DataFusion already ships a SIMD-kernel `cosine_distance` scalar function
operating directly over Arrow array columns — evaluated in DataFusion
itself even when the underlying data is scanned from elsewhere (e.g., a
federated DuckDB table). Combined with §4.1's finding that this
project's vectors are precomputed upstream by Mediumroast (so the
runtime cost really is just similarity computation over Arrow arrays,
nothing more), **a DataFusion-based Rust service could plausibly do the
SIC/NACE and company similarity search natively** — same engine that's
already reading the parquet/feather data, no `sqlite-vec` or DuckDB VSS
needed at all, and no split-architecture (§4.6) required either. This is
a new, real option worth adding to §4.6's list: *DataFusion-native
vector search via its built-in Arrow-array distance functions,
bypassing the SQLite-vs-DuckDB question entirely for the vector-search
piece.*

**The honest tradeoff, not glossed over**: DataFusion being a framework
rather than a database cuts both ways. `company_dns` would own more —
its own persistence/catalog wiring, its own decisions about how data
gets loaded and refreshed — where DuckDB would hand more of that to you
"batteries included." That's more upfront engineering work, in exchange
for a architecture that fits this project's actual shape (a service
embedding a query engine, reading Mediumroast's Arrow-native data
products) more precisely than DuckDB's ad-hoc-analytics-first design
does.

### 6.4 Where this leaves us

The specific reason Rust came up — "compatibility with TiKV/minikv" —
doesn't hold up well under examination (§6.1): TiKV is oversized for the
actual need, and minikv has a Go-native sibling project from the same
author, so neither actually requires choosing Rust. **If Rust gets
chosen, the real argument for it is the parquet/Arrow/DataFusion
ecosystem** (§6.2's first row, expanded in §6.3) — which, now that
`.feather` is confirmed as a second Mediumroast delivery format and
DataFusion's vector-search angle is on the table too, is a noticeably
stronger argument than it looked at first pass. **§7.3/§7.4 moved this
from theory to a verified result**: DuckDB's Arrow extension could not
open the real `tmp/us_flat.feather` file at all — root-caused in §7.4 to
a `pandas` `RangeIndex` metadata quirk, not compression as first
suspected — while DataFusion read the same file, and a second, much
larger vectors-included file, unmodified, with no such issue either
time. That's not a marginal edge in DataFusion's favor on this specific
point — it's the difference between "works" and "doesn't," twice now,
on files this project will actually receive. This bears
directly on this project's core workload in a way the KVS question
doesn't. Worth deciding on that basis — and on team fit — rather than the
caching-library premise that raised the question.

### 6.5 Decided: Rust + DataFusion

**Settled.** Rust, with DataFusion as the query/data-access engine, is
the architecture going forward. Two things resolved this, together:

**1. It's proven, not theoretical, at this point.** §6.4 was written
when this was still a documentation-grounded lean. Since then, four
things got actually built and run against real Mediumroast data, all in
Rust, all working: `df-spike` (reads `.feather` files, including the
zstd-compressed ones, after finding and fixing the real `arrow-ipc`
feature gap `df-spike`'s own earlier test had missed), `embed-bench`
and `quality-eval` (benchmark and validate embedding models against
real IC data), and `ic-similarity-service` (a working REST service +
UI doing real vector similarity search, chunking design, and a
live-typed truncation check). The language decision isn't picking a
horse anymore; it's confirming the horse that's already run the race.

**2. The business context settles the remaining "why" question §1
flagged as open.** `company_dns`'s purpose has been reframed (direct
context, 2026-09-27): Mediumroast is giving away several IC
classification systems (legacy Japanese SIC, US SIC, an older NACE
vintage) and a sample of enriched Wikipedia/EDGAR company data —
including the precomputed-embeddings versions — as free "taste"
packages. Most people who download those packages won't know what to
do with them. **`company_dns` becomes the example OSS project showing
how to actually use this data** — reference use cases (SIC/IC search
across systems, company-to-classification matching, company search,
company-to-company similarity, ad-hoc SQL against the cached data), not
a production bulk-processing service (bulk operations explicitly not a
goal). That purpose is a direct, strong argument for DataFusion
specifically: it's the tool that reads Mediumroast's Arrow-native
parquet/feather output with zero translation, and demonstrating "here's
how to work with this data" is easiest to do faithfully in the engine
built for that data's own format. This is what item 1's "why these five
together" open question was actually missing — the goal was never just
a faster service, it's a reference implementation for data Mediumroast
is about to publish.

**Resolves §4's SQLite-vs-DuckDB question too, by making it moot.**
`ic-similarity-service` already demonstrated DataFusion alone —
no SQLite, no DuckDB — handling parquet/feather reads, vector
similarity search (`array_distance` via DataFusion's own SQL interface,
§7.3-onward), *and* ad-hoc SQL queries against the same in-memory
table, all through one engine. That directly satisfies the newly-named
"issue a SQL query against the included cached data" use case (item 5
of the use-case list above) for free — it's the same code path already
built for search. §4's careful SQLite-vs-DuckDB vector-search analysis
isn't wrong, it's just answering a question that no longer needs
answering: DataFusion was never one of the two options being compared
there, and it turned out to be the one that didn't need the tradeoff at
all.

## 7. Spike plan: DataFusion against a real Mediumroast `.feather` file

Everything in §6.3 is grounded in DuckDB's and DataFusion's own
documentation, not in anything actually tested against real Mediumroast
data. Before that section's conclusions carry any real weight in a
language decision, worth validating directly — cheaply, with a single
real file, not a full prototype of the rewrite.

**Scope, deliberately narrow**: pull in **one** `.feather` file from
Mediumroast — US SIC industry-classification data is the natural first
choice, both because it's the smallest/simplest of the four
classification systems in §1 and because it's the one this repo already
has a directly comparable baseline for
(`source_data/sic_data/sic-codes.csv` et al., §4.1's row counts). **This
file does not include vector data yet** — confirmed — so this spike is
scoped purely to *ingestion and query mechanics*, not §4's vector-search
question at all. Keep those two questions separate; a follow-up spike
once a vectors-included `.feather` file exists is the right place to
actually test DataFusion's `cosine_distance` (§6.3) or `sqlite-vec`
(§4.4) against real vector data.

### 7.1 What this spike should actually answer

1. Does DataFusion read the file with zero transformation — i.e., does
   `SessionContext::read_ipc` (or equivalent) load it directly into
   queryable `RecordBatch`es, no conversion step, the way §6.3's
   "zero-copy" claim implies?
2. Does the schema match what's expected for US SIC data — division,
   major group, industry group, SIC code, description — and does it map
   cleanly onto the fields `source_data/sic_data/*.csv` (and
   `lib/sic.py`) currently expose? This is also a real check on
   Mediumroast/`company_dns` schema compatibility generally, not just a
   DataFusion mechanics test.
3. Can a basic SQL query run against it through DataFusion's SQL
   frontend (e.g., `SELECT * FROM sic WHERE division = '...'`), not just
   raw schema/row inspection — confirming end-to-end usability, not only
   "the file loads."
4. Sanity-check load time (not a rigorous benchmark — just "is this
   instant, as expected for ~1-2k rows," matching §4.1's data-scale
   argument).
5. **Worth doing side-by-side, not DataFusion-only**: load the same
   file into DuckDB via its `arrow`/`nanoarrow` community extension
   (§6.3) and run the equivalent query. This repo's own habit in this
   document has been "verify documentation claims empirically before
   leaning on them for a decision" (applied to DuckDB VSS, minikv,
   sqlite-vec — same standard should apply to our own DataFusion
   research, not just the other candidates'). Cheap to do since DuckDB's
   CLI makes this a few commands, no Rust project needed for that half.

### 7.2 First look: `tmp/us_flat.feather` (via `pyarrow`, not yet DataFusion/DuckDB)

A real sample landed at `tmp/us_flat.feather` (93KB). Inspected with
`pyarrow.feather` (Arrow's own reference implementation) — deliberately
not DataFusion or DuckDB yet, since this step is just "is the file
well-formed and what does it actually look like," before spending effort
on either candidate. Reads cleanly, no errors, effectively instant for a
file this size.

**Schema** (flat, one row per subclass — 13 columns, all string except
none):

```
section_id, section_desc, division_id, division_desc,
group_id, group_desc, class_id, class_desc,
subclass_id, subclass_desc, countries, ic_module, unique_key
```

**1,005 rows** — matches almost exactly the 1,006-row
`source_data/sic_data/sic-codes.csv` this repo already has (§4.1's row
count table), a good sign for schema/data parity between what
`company_dns` has today and what Mediumroast ships.

**Two findings worth calling out explicitly:**

1. **This is a flat, fully denormalized table** — every hierarchy level
   (section → division → group → class → subclass) is repeated on every
   row, rather than the current codebase's approach of separate
   normalized tables per level (`major-groups.csv`, `industry-
   groups.csv`, `divisions.csv`, `sic-codes.csv`, joined at query time —
   see `lib/sic.py`, `lib/prepare_sic_data.py`). Simpler to query
   (no joins needed), more storage/redundancy per row — a reasonable
   tradeoff for a dataset this small, and it means the rewrite's
   ingestion code doesn't need to reconstruct a normalized schema from
   Mediumroast's data, just read it as-is.
2. **The schema looks designed to be shared across all four
   classification systems in §1**, not US-SIC-specific: `ic_module`
   (`"us"` here) and `countries` (`"United States"` here) are both
   plain data columns, not baked into the schema shape — implying UK
   SIC, Japanese SIC, and EU NACE likely arrive as the *same* 13-column
   schema with different `ic_module`/`countries` values, not four
   different shapes to handle separately. Worth confirming this
   explicitly with Mediumroast rather than assuming from one file, but
   if true, it meaningfully simplifies the ingestion code either
   language ends up writing — one schema, one code path, four data
   sources.
3. `unique_key` (e.g. `us-A-01-011-0111`) looks like a natural
   module-prefixed composite key — a reasonable join target for
   whenever the vectors-included version of this file arrives (§4's
   vector-search question), though that's still ahead of this file, not
   confirmed by it.

### 7.3 Results: DuckDB vs. DataFusion, both run against the real file

Both halves of §7.1 actually run now — `duckdb` (1.5.5) and a disposable
Rust/`datafusion` (42.2.0) spike, both installed via Homebrew/cargo for
this test, both run directly against `tmp/us_flat.feather` (the real,
ZSTD-compressed file as shipped, not a modified copy). This is the
single most concrete finding in this document so far — not documentation
research, actual behavior on real Mediumroast data.

**DuckDB: fails on the file as shipped.**

```
INSTALL arrow FROM community; LOAD arrow;
SELECT * FROM read_arrow('tmp/us_flat.feather') LIMIT 5;
```
```
Invalid Input Error: arrow_scan: get_next failed(): InternalException:
"...Compression type with value 1 not supported by this build of
nanoarrow..."
```

> **Correction (§7.4)**: the paragraph originally here concluded this was
> a ZSTD compression-support gap, based on the error message and on
> decompressing the file making it work. §7.4 found that conclusion was
> **wrong** — a follow-up test isolated the actual trigger to a `pandas`
> `RangeIndex` entry in the file's schema metadata, not the compression
> codec at all. DuckDB's `arrow` extension still has a real bug here,
> just a different one than first diagnosed; the "no ZSTD/LZ4 for
> reads" line from DuckDB's own roadmap (§6.3) is still accurate as
> *documentation*, it just isn't what actually caused *this* failure.
> Left the original (wrong) reasoning below struck through rather than
> deleted, so the correction in §7.4 has something concrete to point at.

~~Confirmed this is a compression-support gap, not a corrupt file or a
one-off bug: decompressing the file to an uncompressed copy first
(`pyarrow.feather.write_feather(..., compression='uncompressed')`) makes
DuckDB's `arrow` extension read it and query it correctly. Also
confirmed the extension is already at its latest version
(`UPDATE EXTENSIONS` → `NO_UPDATE_AVAILABLE` for both `arrow` and
`nanoarrow`) — this isn't "go update and it's fixed," it's the current
state of DuckDB's community Arrow extension. This is exactly the gap
§6.3 flagged from DuckDB's own documented roadmap ("no ZSTD/LZ4
compression... for reads") — now verified directly against a real
Mediumroast file, not just read about.~~ **See §7.4 for what was
actually going on.**

**DataFusion: reads the file as shipped, no workaround needed.** The
only friction was mechanical, not architectural: `read_arrow`'s default
file-extension filter expects `.arrow`, not `.feather`, so it initially
refused the file — a one-line fix (`ArrowReadOptions { file_extension:
".feather", ..Default::default() }`), not a real limitation. Once past
that, it read the original ZSTD-compressed file directly:

> **Second correction (from building `experiments/ic-similarity-
> service/`, see its README):** "read the original ZSTD-compressed file
> directly" needs a caveat. DataFusion 42.2.0's own `Cargo.toml` only
> requests `arrow-ipc`'s `"lz4"` feature by default, not `"zstd"` —
> confirmed by reading the manifest directly. `us_flat.feather` (this
> section's file) is tiny with short string buffers that may simply
> have been too small to actually get zstd-compressed despite carrying
> the codec tag, meaning this test may never have exercised real zstd
> *decompression* at all. `tmp/us_flat_embedded.feather`'s much larger
> float-vector buffers definitely do, and reading *that* file failed
> with `zstd IPC decompression requires the zstd feature` until
> `arrow-ipc = { features = ["zstd"] }` was added explicitly. Net effect
> on the DataFusion-vs-DuckDB conclusion: unchanged (DataFusion still
> works, just needs one extra Cargo.toml line; DuckDB's `arrow`
> extension has no equivalent fix available at all for its own,
> different failure). But "no workaround needed" specifically wasn't
> accurate — flagging rather than leaving it uncorrected, same policy as
> §7.4's first correction.

```
Reading tmp/us_flat.feather via read_arrow (Feather V2 == Arrow IPC file format)...

=== Schema ===
[13 fields, all LargeUtf8/large_string — matches pyarrow's schema exactly]

=== Row count === 1005

+------------+------------------------------------+----+
| section_id | section_desc                       | n  |
+------------+------------------------------------+----+
| A          | Agriculture, Forestry, And Fishing | 20 |
+------------+------------------------------------+----+
```
That query result (companies in the "Agricultural Production Crops"
division, grouped by section) **matches DuckDB's result on the
uncompressed copy exactly** — same 20-row count, same values — a real
cross-validation that both engines agree on the data itself; the only
difference is which one can open the file Mediumroast actually shipped.

**What this settles, concretely (see §7.4 for a correction to the first
point below):**

- ~~§6.3's DuckDB-Arrow-maturity-gap claim... it's specifically that
  DuckDB's Arrow extension can't open a compressed file, and
  Mediumroast's real output is compressed by default.~~ **Wrong — see
  §7.4.** DataFusion still reads the file with no workaround needed,
  and DuckDB still fails on it, but the *reason* DuckDB fails isn't
  compression.
- This doesn't mean DuckDB is unusable here — §7.4 also found a
  workaround (dropping one schema-metadata field). But it's still an
  extra step DataFusion doesn't need, and still the kind of
  small-but-real friction that adds up when picking the tool that's the
  *worse* fit for a format you'll use constantly — the underlying
  pattern from the original (wrong) conclusion holds even though the
  specific mechanism doesn't.
- The "does writing spike code count as code" question from the
  original draft got resolved in practice by just doing it — a ~30-line
  disposable Rust binary in the session's scratchpad directory, not
  committed to the repo, not part of the rewrite. Worth naming
  explicitly as the pattern going forward: small, throwaway validation
  spikes are a different thing from "writing the rewrite," and don't
  need to wait on the language decision being final.

**Not tested at the time**: vector search (§4) — this file had no
vector column. §7.4 covers a follow-up once one existed.

### 7.4 Follow-up: a real vectors-included file, and a correction

A vectors-included version landed: `tmp/us_flat_embedded.feather` — the
same US SIC data plus a new `embedding_text` column and four
`FixedSizeList<Float32>` vector columns (one per embedding model —
`all-MiniLM-L6-v2`, `all-mpnet-base-v2`, `BAAI/bge-small-en-v1.5`,
`intfloat/e5-base-v2`), generated per the instructions worked out in
chat (per-model prefix conventions applied correctly, model identity
recorded as Arrow field-level metadata, normalized vectors). This
answers §7's original scoping note ("a follow-up spike once a
vectors-included `.feather` file exists") and adds two real findings.

**Data validation, all clean**: 1,005 rows in, 1,005 out; all 13
original columns byte-identical to the source file (checked directly,
not assumed); all four vector columns have the correct dimension
(384/768/384/768), zero nulls, zero NaN/Inf, and every vector's L2 norm
≈ 1.0 (correctly normalized, as the metadata claims). A relatedness
sanity check (cosine similarity between "Wheat" and "Corn," both under
"Cash Grains," vs. "Wheat" against an unrelated section like
Finance/Insurance) passed for all four models — related pairs scored
meaningfully higher in every case, though `e5-base-v2`'s margin was
noticeably smaller than the other three's (0.975 vs. 0.833, a gap of
~0.14) compared to, e.g., MiniLM's much wider gap (0.971 vs. 0.278) —
not a failure, but worth keeping in mind if `e5-base-v2` is ever a
finalist for the "pick one" decision.

**Storage cost, measured**: `us_flat.feather` (13 string columns) is
93,482 bytes for 1,005 rows (~93 bytes/row). The embedded version is
8,646,570 bytes for the same 1,005 rows (~8,604 bytes/row) — **~93x
larger**, almost entirely the vectors: raw uncompressed vector payload
alone is `(384+768+384+768) floats × 4 bytes = 9,216 bytes/row`, and
ZSTD only gets that down to ~8,600 (confirmed directly: ZSTD saves
~11% here, LZ4 barely helps) — expected, since dense embedding floats
are high-entropy and don't compress well by nature, not a tuning
problem. **This matters directly for the company-data embeddings
mentioned as "coming later" (§5)**: at SIC's ~1,000-row scale, 93x is
academic; at real company-data row counts, shipping all four models
costs ~8.6KB/row where shipping only the "best support" pick (BGE-small,
384-dim, per the earlier decision) would cost ~1.5KB/row — roughly **6x
smaller**. Worth deciding *per dataset* whether to ship all four
(reasonable for SIC/NACE, small enough not to matter) or just the
chosen production model (worth strongly considering for company data,
where the multiplier is the difference between fitting Mediumroast's
row cap comfortably and not).

**Correction to §7.3's DuckDB finding**: testing this larger file
surfaced that DuckDB's `arrow` extension actually reads it
successfully — despite it also being ZSTD-compressed (confirmed:
re-writing it at `compression='zstd'` reproduces it byte-for-byte).
That directly contradicted §7.3's "ZSTD isn't supported" conclusion, so
it got isolated properly this time instead of accepting the first
plausible explanation: the original `us_flat.feather`'s schema metadata
contains a `pandas` `RangeIndex` entry (`index_columns: [{"kind":
"range", "start": 0, "stop": 1005, "step": 1}]`), left over from however
it was originally written from a pandas DataFrame; the embedded file
doesn't have this (written with `preserve_index=False`). Stripping
*only* that one metadata field from a copy of the original file — same
data, same ZSTD compression, nothing else touched — made DuckDB read it
without error. **The actual bug is DuckDB's `arrow` extension mishandling
a `pandas` RangeIndex metadata entry**, not a compression-codec gap; the
"Compression type... not supported" error was a misleading message for
an unrelated fault. DataFusion was never bothered by the RangeIndex
metadata either way.

This doesn't reverse §6.4's overall lean toward DataFusion — DuckDB's
`arrow` extension still failed on real, unmodified Mediumroast output
while DataFusion didn't, on two separate files now, for two different
reasons — but it does mean **the specific mechanism cited in this doc's
own earlier conclusion was wrong**, and it's a useful reminder of why
§7's whole premise (verify empirically, don't stop at the first
plausible-looking error) exists in the first place. A workaround exists
for DuckDB here too (drop the RangeIndex metadata field, same shape of
fix as decompressing was for the wrong diagnosis) — still an extra
ingestion-side step DataFusion doesn't need.

### 7.5 Model performance: which of the 4 embedding models to actually support at query time

§4's runtime constraint (a query must be embedded with a model
compatible with whichever model produced the corpus vectors it's
compared against — see the "query-time embedding" discussion in chat)
means the Rust runtime needs to pick which model(s) it actually runs
inference with, even though all four ship in the data. Benchmarked the
three models `fastembed-rs` supports natively (`intfloat/e5-base-v2`
excluded — confirmed earlier not to be in its catalog) with a disposable
Rust spike (`fastembed` crate v7.1.0), against all 1,005 real
`embedding_text` values from `us_flat_embedded.feather`:

| Model | Dim | On-disk size | Load time (warm) | Single-query latency (median / p95) | Batch (1,005 rows) |
|---|---|---|---|---|---|
| `all-MiniLM-L6-v2` | 384 | 87MB | 72ms | 2.49ms / 2.69ms | 966ms (0.96ms/row) |
| `BAAI/bge-small-en-v1.5` | 384 | 128MB | 70ms | 4.69ms / 5.29ms | 1,788ms (1.78ms/row) |
| `all-mpnet-base-v2` | 768 | 418MB | 149ms | 7.17ms / 7.59ms | 4,335ms (4.31ms/row) |

("Load time" measured warm, i.e. models already downloaded/cached — the
first-ever run includes a one-time model download that isn't
representative of steady-state service startup.)

**Recommendation, for the "keep one low-dim and one high-dim" framing**:

- **High-dim: `all-mpnet-base-v2`.** No real alternative within native
  `fastembed-rs` support anyway (the only 768-dim option), and the
  numbers confirm it's fine for the runtime use case regardless — 7.17ms
  median per query is negligible next to this service's actual dominant
  latency (Wikipedia/EDGAR calls run 700-1000ms+, per the V3.3.0
  baseline in §7's earlier context). The 418MB on-disk footprint (3-5x
  the 384-dim options) is the real cost, and it's a Docker-image-size
  line item, not a performance concern.
- **Low-dim: `BAAI/bge-small-en-v1.5`, not `all-MiniLM-L6-v2`.** MiniLM
  is measurably faster (~1.9x) and smaller (87MB vs 128MB), but the
  absolute gap (2.49ms vs 4.69ms) is noise against this service's real
  request-path costs — while BGE-small's retrieval-quality edge (the
  reason it was recommended in the first place, back when picking "the
  one with best support") is the kind of difference that actually shows
  up in results. Speed was never the real constraint at the 384-dim
  tier.

**Net effect**: of the four models in the shipped data, two
(`bge-small-en-v1.5`, `all-mpnet-base-v2`) would get a runtime
query-embedding path; the other two (`all-MiniLM-L6-v2`,
`intfloat/e5-base-v2`) stay in the data for comparison/future use
without needing one right now. Worth revisiting if `e5-base-v2` (or a
different model entirely) ever becomes a serious contender — it would
need a manual ONNX export + `ort` (§6.2), not the zero-effort
`fastembed-rs` path the two recommended models get.

**Update — §7.6 below complicates this.** §7.5 only measured speed. A
follow-up quality evaluation found `all-MiniLM-L6-v2` actually
outperforms `bge-small-en-v1.5` on *this specific dataset* — the "pick
BGE-small for quality" reasoning above was based on general retrieval
benchmarks (MTEB), which don't necessarily transfer to short,
controlled-vocabulary classification text. Read §7.6 before treating
the low-dim pick above as settled.

### 7.6 Model quality: does the "best support" pick actually retrieve well?

§7.5 measured speed only — never actually tested whether the models
retrieve *correctly*. No labeled benchmark exists for this dataset, so
this uses the SIC hierarchy itself as a weak-label proxy: two rows
sharing a `group_id` are, by construction, more semantically related
than two rows in different groups. A better embedding model should
reflect that structure more strongly in its vector space. All four
models' precomputed vectors already exist in `us_flat_embedded.feather`
(including `e5-base-v2`, which §7.5 couldn't benchmark for speed since
it isn't in `fastembed-rs`'s catalog — but its vectors are still real
data, testable without running any Rust code).

**Caveat that shaped the methodology**: 416 groups across 1,005 rows,
median group size **2**, and 201 rows (20%) are the *only* member of
their group — meaning a naive precision@k metric is capped at 0 for a
fifth of the dataset regardless of model quality, and capped well below
1.0 for most of the rest (a 2-member group's row can score at most 1/5
at k=5). Reported both a precision@k view (all 1,005 rows, useful for
comparing against a random baseline) and a ceiling-corrected recall@k /
hit@1 view (the 804 rows that actually have a same-group peer to find,
each row's own true-peer count as the denominator) — the second is the
more trustworthy number, the first is included for transparency about
what was tried first.

**Separation margin** (mean same-group cosine similarity − mean
different-group cosine similarity, all 1,005 rows):

| Model | Same-group sim | Different-group sim | Margin |
|---|---|---|---|
| `all-MiniLM-L6-v2` | 0.8463 | 0.3629 | **0.4834** |
| `all-mpnet-base-v2` | 0.8427 | 0.4009 | 0.4418 |
| `BAAI/bge-small-en-v1.5` | 0.8528 | 0.5661 | 0.2867 |
| `intfloat/e5-base-v2` | 0.9433 | 0.8104 | 0.1329 |

**Recall@k / hit@1** (804 rows with ≥1 true same-group peer):

| Model | Recall@5 | Recall@10 | Hit@1 |
|---|---|---|---|
| `all-MiniLM-L6-v2` | **0.814** | **0.915** | **0.868** |
| `intfloat/e5-base-v2` | 0.803 | 0.914 | 0.851 |
| `all-mpnet-base-v2` | 0.769 | 0.879 | 0.832 |
| `BAAI/bge-small-en-v1.5` | 0.768 | 0.893 | 0.801 |

**The uncomfortable result**: `all-MiniLM-L6-v2` — the model §7.5
*deprioritized* for the low-dim slot in favor of `bge-small-en-v1.5` on
quality grounds — wins on every metric tested here, by a real margin.
`e5-base-v2` is a strong second on the ranking-quality metrics
(recall@k, hit@1) despite having by far the smallest separation margin
(0.133) — its absolute similarity scores are compressed into a narrow
high band (consistent with the small margin already seen in the
Wheat/Corn sanity check in §7.4), so its *relative ranking* is still
good even though a fixed similarity-score threshold would work poorly
for it. `bge-small-en-v1.5` and `all-mpnet-base-v2` are essentially tied
for worst on the ranking metrics here.

**Why this doesn't simply overturn §7.5's recommendation**:
`bge-small-en-v1.5`'s reputation comes from general-purpose retrieval
benchmarks (MTEB), dominated by natural-language passages — not short,
controlled-vocabulary classification codes like `"Wheat"` or `"Cash
Grains"`. This dataset may just not be BGE-small's or mpnet's strong
suit. The company-description embeddings ("coming later," per the
original chat discussion) are actual free-text natural language —
plausibly much closer to what MTEB actually measures, and where
BGE-small's general reputation is more likely to hold. **The honest
conclusion: this result is conclusive for SIC/NACE-style short
classification text, not for company data.** The exact same
recall@k/margin methodology needs re-running once company-data vectors
exist, rather than assuming this SIC result transfers.

**Practical effect, scoped correctly**:

- For SIC/NACE specifically: worth reconsidering `all-MiniLM-L6-v2`
  over `bge-small-en-v1.5` for the low-dim slot, given it wins cleanly
  on real, in-domain data rather than a general external benchmark.
- For company data: no change yet — `bge-small-en-v1.5` remains the
  tentative low-dim pick until this same evaluation runs against real
  company vectors.
- `e5-base-v2`'s strong ranking performance here is a real data point in
  favor of doing the manual ONNX export work (§6.2/§7.5) to give it a
  `fastembed-rs`-equivalent runtime path, if company-data results
  confirm it's competitive there too — it was excluded from §7.5 purely
  on "not zero-effort," not on any quality concern, and this result
  weakens the case for leaving it out by default.
- The two low-dim options (`MiniLM`, `bge-small`) may simply be
  measuring different things well — worth keeping both in mind as
  "best for short/controlled-vocabulary text" vs. "best for natural-
  language passages" rather than assuming one strictly dominates the
  other once company data is in the picture.

### 7.7 Decision: `all-MiniLM-L6-v2` + `all-mpnet-base-v2` for IC data, confirmed in place

**Decided (2026-09-27), scoped to IC/SIC-NACE data only**: ship exactly
two embedding models — `all-MiniLM-L6-v2` (384-dim, low) and
`all-mpnet-base-v2` (768-dim, high) — driven by §7.6's quality results
plus a hard storage constraint (export size was too high with all four
models present). Explicitly *not* a decision about company-data
embeddings, which remain untested (company data files are "genuinely
large" compared to IC data, per discussion — not yet in a position to
run the same evaluation there) and may land on a different pair once
they are.

Reasoning recap:
- **Low-dim (`all-MiniLM-L6-v2`)**: no tradeoff — wins on every quality
  metric in §7.6 *and* is faster/smaller than `bge-small-en-v1.5` per
  §7.5. Clean pick.
- **High-dim (`all-mpnet-base-v2`)**: a real tradeoff against
  `intfloat/e5-base-v2`, which ranks ~4% higher on recall@5/hit@1 (see
  §7.6's table) — but `e5-base-v2` needs a manual ONNX export (not in
  `fastembed-rs`'s catalog, §7.5) and a correctness-sensitive prefix
  convention (§4.2, the earlier `"query: "`/`"passage: "` discussion)
  replicated exactly between corpus and runtime. `mpnet-base-v2` is
  zero-effort in `fastembed-rs`, has a healthy separation margin (0.442,
  vs. e5's compressed 0.133), and was judged the pragmatic choice for a
  storage-constrained IC export. Worth revisiting `e5-base-v2` later if
  its quality edge holds up on company data too — the export effort is
  a known, bounded cost, not a reason to rule it out permanently.

**Confirmed in place**: a regenerated `tmp/us_flat_embedded.feather`
with only these two vector columns landed and was validated the same
way as the four-model version — schema correct (`vector_all_minilm_l6_v2`
`FixedSizeList<Float32>[384]`, `vector_all_mpnet_base_v2`
`FixedSizeList<Float32>[768]`, field metadata intact), 1,005 rows, all
13 original columns byte-identical to `us_flat.feather`, zero
nulls/NaN/Inf, all vectors normalized (norm ≈ 1.0). `quality-eval`
re-run against this exact file reproduced §7.6's numbers for these two
models exactly (as expected — same vectors, two fewer columns).

**Storage, confirmed**: 4,361,778 bytes (1,005 rows, ~4,340 bytes/row) —
almost exactly half the four-model version's ~8,600 bytes/row, matching
the halved total dimensionality (1,152 vs. 2,304 floats/row). Growth
over the plain `us_flat.feather` baseline is now **~47x instead of
~93x**.

### 7.8 Revised decision: one model, not two — `all-MiniLM-L6-v2` only

**Superseding §7.7.** Building `experiments/ic-similarity-service`
(§9) and actually using it surfaced something the tables in §7.6 hadn't
made obvious: `all-mpnet-base-v2` reports systematically higher raw
similarity scores than `all-MiniLM-L6-v2` on the *same* queries (e.g.
"growing wheat" → 60.2% top match on mpnet vs. 48.6% on MiniLM, held
across every query tried). Confirmed this isn't mpnet being "more
confident" about correct matches — it's a generally higher baseline
across *both* related and unrelated pairs (§7.6's own diff-group-
similarity numbers already showed this: 0.401 for mpnet vs. 0.363 for
MiniLM), the same phenomenon seen taken to an extreme with
`e5-base-v2`'s compressed score range. Cross-model raw-percentage
comparisons aren't meaningful — each model has its own score
distribution.

That observation prompted revisiting whether keeping mpnet in the IC
export was earning its keep at all. It wasn't:

| | `all-MiniLM-L6-v2` | `all-mpnet-base-v2` |
|---|---|---|
| Recall@5 / Recall@10 / Hit@1 | **0.814 / 0.915 / 0.868** | 0.769 / 0.879 / 0.832 |
| Separation margin | **0.483** | 0.442 |
| Query latency (median) | **2.49ms** | 7.17ms |
| On-disk model size | **87MB** | 418MB |
| **Service RSS with both models loaded** | | **~687MB** |
| **Service RSS with only this model loaded** | **~203MB** (measured directly) | |

MiniLM doesn't win a tradeoff here — it wins on quality, latency, disk
size, *and* memory, simultaneously, with nothing pulling the other way.
The original "one low-dim, one high-dim" framing (§7.7) was a reasonable
starting heuristic before any of this data existed; it doesn't survive
contact with it. **Decided: ship `all-MiniLM-L6-v2` only for IC data.**

Confirmed in place: a regenerated `tmp/us_flat_embedded.feather` with
only `vector_all_minilm_l6_v2` validates cleanly (1,005 rows, all 13
original columns byte-identical, zero nulls/NaN, normalized vectors),
`quality-eval` reproduces §7.6's MiniLM numbers exactly, and
`ic-similarity-service` (updated to load only this model by default,
`IC_MODELS=all_mpnet_base_v2` or `IC_MODELS=both` still available for
comparison) runs at ~203MB RSS with unchanged, correct search results.
File size: **1,496,162 bytes, ~1,488 bytes/row** — growth over the plain
`us_flat.feather` baseline is now **~16x**, down from §7.7's ~47x and
the original four-model version's ~93x.

**Same scope caveat as §7.7, repeated because it matters**: this is IC
data only. Company-description embeddings are a different text domain,
untested, and may not land on a single model — the "one model" framing
is not itself the finding; the finding is "MiniLM beats mpnet on *this*
dataset by every measure we have." That could look completely different
once company vectors exist to test against.

## 8. Go-specific open questions (assuming Go — revisit if §6 lands on Rust)

- Web framework: stdlib `net/http` (Go 1.22+'s routing is now solid
  enough that a framework may not be needed at all) vs. something like
  `chi` or `echo`. FastAPI's automatic OpenAPI/Swagger docs were a real
  feature of the current service (V3.2.0) — whatever's chosen needs an
  equivalent story, not a silent regression.
- DuckDB Go driver maturity (`marcboeker/go-duckdb` or similar) vs.
  SQLite Go driver maturity (`mattn/go-sqlite3` (cgo) vs.
  `modernc.org/sqlite` (pure Go, no cgo)) — worth its own short
  investigation, since "pure Go, no cgo" affects cross-compilation and
  the multi-arch Docker build story that today's service already
  depends on (`linux/amd64,linux/arm64` in `.github/workflows/main.yml`).
  See also §6.2's row on this same tradeoff.
- Deployment target: does this still run on the same on-prem MicroK8s
  cluster (`k8s/prod/`) via the same `scripts/build-and-deploy.sh`
  pattern, or does a compiled Go binary change that story (e.g., a much
  smaller/simpler container image, no `pip install`/`makedb.py` build
  step)?
- Migration/cutover strategy: does this follow the same shadow-endpoint-
  then-cutover pattern V3.3.0 used for the Wikipedia backend (run both
  implementations side by side, validate, then switch), scaled up to an
  entire-service rewrite? Given the scope, a side-by-side period seems
  likely to be worth it, but at what granularity (whole-service, or
  endpoint-by-endpoint)?

## 9. Explicitly out of scope for this document

- No code, no repo scaffolding, no dependency choices locked in yet —
  **with one explicit exception to resolve**: §7.2 flags that the
  DataFusion/DuckDB spike likely needs some throwaway validation code to
  actually run. Whether that counts as "code" under this line, or is a
  separate disposable-prototype category, needs an explicit yes/no
  before it gets written, not an assumption either way.
- No decision yet on whether this is a new repo or a directory/branch
  within the existing one.
- No versioning/naming decided (is this "V4.0.0"? A different product
  name entirely, given how far it diverges from the current
  implementation?).
- No language decision yet either (§6) — this document's own title still
  says "Go, DuckDB" from the original framing; revisit the title once §6
  actually resolves.

## 10. Next steps

1. Talk through §1's "why now, why all five together" framing and
   capture the real answer here.
2. Settle §4 (SQLite vs. DuckDB for vector search) enough to know what
   to tell issue #53 — doesn't need to be final, just enough to update
   the issue with a direction. Concretely: spike whether DuckDB's
   `sqlite` extension can see `sqlite-vec`'s `vec0` virtual tables
   (§4.4) — cheap to test, and the answer meaningfully changes how
   attractive the "split" architecture option is. Note this now depends
   partly on §6/§6.3: if Rust+DataFusion is chosen, the DataFusion-native
   vector-search option (§4.6's last bullet) may make the whole
   SQLite-vs-DuckDB question moot for the vector-search piece — worth
   settling the language question first, or at least in parallel, rather
   than strictly before it.
3. §5's cache-with-fallback questions are now mostly settled (no
   write-back, company semantic search in scope, Mediumroast sets the
   cap) — remaining: pick one of the four ephemeral-cache options for
   direct-lookup misses (or confirm "none," option 1), and get an actual
   row-count estimate for the company parquet package so §4's backend
   decision accounts for that dataset too, not just SIC/NACE.
4. Settle §6 (Go vs. Rust) — specifically, answer the team-fit question
   §6.2 flagged (any existing Rust experience?), and decide whether the
   parquet/Arrow ecosystem advantage is enough to outweigh Go's simpler
   deployment story, independent of the KVS-compatibility premise that
   turned out not to hold up.
5. ~~**Immediate/concrete**: run §7's spike...~~ **Done (§7.3)** —
   DuckDB's `arrow` extension failed to open the real, ZSTD-compressed
   `tmp/us_flat.feather`; DataFusion read it directly with one line of
   config. Concrete, not theoretical, evidence for §6.3/§6.4's leaning.
6. **New, follow-on**: get a vectors-included `.feather` file (once
   Mediumroast has one to share) and repeat something like §7's spike
   scoped to the vector-search question specifically — test DataFusion's
   `cosine_distance` UDF (§6.3) against real precomputed vectors, and/or
   `sqlite-vec` loaded via `rusqlite`/`mattn`-style drivers (§4.2/§4.4),
   to give §4's decision the same kind of real-file evidence §7.3 just
   gave §6.
7. Work through §8's Go-specific questions (or their Rust equivalents,
   if §6 lands elsewhere) — §7.3's result is a real point in Rust's
   favor now, worth weighing alongside the team-fit question from §6.2.
8. Decide issue dispositions from §3 and act on them (comment/close/
   relabel as agreed).
