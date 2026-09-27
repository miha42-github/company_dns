# Performance improvements: DB scan, concurrency, replicas, comparison tooling, connection reuse, Wikipedia round-trips

Status: **Items 1, 2, 3, 4, and 5 executed, merged, deployed, and validated
against the live service** (PRs #99-#103; see each item's section for the
measured before/after numbers — EDGAR sequential latency down 56-97%,
Wikipedia-bound concurrent throughput up to 81% faster at concurrency 8,
service now handles concurrency=16 cleanly on 4 replicas where it crashed
at that level on 2). **Item 6 was re-researched on 2026-09-27 and its
conclusion changed** — no longer "smallest lever, backlog only"; see its
section for a large, measured, previously-hidden bottleneck and a proposed
Tier A implementation. Not yet scheduled or implemented — awaiting a
decision on whether to pursue it as real work.
Owner: michael.hay@mediumroast.io
Scope: all five non-caching performance levers from the "increase
performance without caching" discussion — (1) the `companies` DB
full-table-scan fix, (2) moving blocking I/O off the event loop, (3)
replica/worker count, (5) reusing HTTP connections to SEC EDGAR, and (6)
reducing Wikipedia round-trips — plus (4) the before/after comparison
tooling needed to actually judge whether any of the others worked. Caching
is explicitly out of scope here. (Numbering keeps the order each item was
first raised in, not necessarily priority or execution order — see
"Suggested execution order" below for the latter.)
Measurement: [perf_tests/baseline.py](../../perf_tests/baseline.py) and the
committed baseline ([perf_tests/results/baseline-20260926.json](../../perf_tests/results/baseline-20260926.json))
are the before/after yardstick for items 1, 2, 3, and 5; item 4 is what
makes that comparison rigorous instead of eyeballing two printouts. Item 6
is a research/backlog item, not something with a measurable implementation
yet.

---

## 1. `companies` table full-table-scan fix

### The evidence

The perf baseline showed `edgar_ciks` — a SQLite-only endpoint with **no
external network call** — at a ~2.7s median latency, statistically the same
ballpark as endpoints that make a live SEC API call. That's not explained by
anything fixed so far; it's the local DB query itself.

Root cause, confirmed by reading the actual schema and ingestion code:

- `lib/prepare_db.py`'s `_create_companies_table` creates `companies` with
  **no index and no primary key**:
  `CREATE TABLE companies (cik int, name text, year int, month int, day int, accession text, form text)`.
- `lib/prepare_edgar_data.py`'s `extract_data()` ingests SEC's **full**
  filing index (`ALL_FORMS`/`form_all.tab`) for the last 2 years — every
  form type, not just the ones the app ever queries.
- `lib/edgar.py`'s two query methods (`get_all_ciks`, `get_all_details`)
  both run `WHERE name LIKE '%...%' AND form LIKE '10-%'` — a **leading
  wildcard on `name`**, which defeats any plain B-tree index even if one
  existed. `self.form_type = '10-'` is a fixed constant; nothing in the
  codebase ever queries any other form prefix.

To size the actual table, I pulled one real quarter of SEC's public
full-index (`https://www.sec.gov/Archives/edgar/full-index/2025/QTR3/form.idx`)
and measured it directly (not estimated):

| Metric (one quarter) | Value |
|---|---|
| Total filing rows (all form types) | 287,877 |
| Distinct CIKs | 64,618 |
| Rows matching `form LIKE '10-%'` | 8,784 (**3.1%** of the quarter) |

`extract_data()` ingests 8 quarters (`start_year = now - 2`), so
`companies` almost certainly holds on the order of **~2 million rows**, of
which only ~3% (roughly 60–70K, accounting for quarter-over-quarter overlap
among the same recurring filers) is the `10-K`/`10-Q` family the app
actually ever filters to at query time. **97% of the table is dead weight
for every single query this app makes.**

### Recommended fix — Step 1 (do this first, near-zero risk)

Filter at **ingest time**, not query time: in
`lib/prepare_edgar_data.py`'s `extract_data()`, skip any row whose form
doesn't start with `10-` before appending it to `idx`. This is a one-line
change to the loop, backed by the fact that `EdgarQueries.form_type = '10-'`
is the only value ever used anywhere in the codebase (confirmed by grep —
no other prefix is referenced).

Why this is safe and low-risk:

- `companies.db` is **entirely rebuilt from scratch** on every image build
  (`makedb.py` runs in the `Dockerfile`, and the monthly/dispatch CI job +
  `build-and-deploy.sh` both trigger fresh builds) — there is no existing
  production data to migrate or risk corrupting. The change takes effect on
  the next image build, full stop.
- It doesn't touch `lib/edgar.py`'s query logic, the `companies` table's
  columns, or any downstream consumer's expectations about row shape — it
  just means far fewer rows exist to scan. The `form LIKE '10-%'` filter
  stays in the SQL as a defensive/documentation measure even though it'll
  now always be true.
- Expected impact: cutting the table from ~2,000,000 rows to
  ~60,000–70,000 rows (roughly a **30x reduction**) should cut a linear
  `LIKE` scan's cost by roughly the same factor — plausibly taking the
  ~2.7s median down to the 50–150ms range, without adding any indexing
  complexity at all.

### Step 2 — measure, using the tool we already have

Rebuild `companies.db` with the ingest filter, redeploy, then:
```bash
python3 perf_tests/baseline.py --skip-concurrency
```
and compare `edgar_ciks` / `edgar_detail` medians against the committed
baseline (`perf_tests/results/baseline-20260926.json`). This is exactly what
the suite was built for.

### Step 3 — conditional follow-up (only if Step 2 isn't good enough)

If a ~60–70K-row table is still too slow for a leading-wildcard `LIKE` scan,
the next lever is indexing the name search itself. Two options, **not**
proposed for immediate execution — only as a documented fallback:

- **SQLite FTS5 with the `trigram` tokenizer** (available SQLite 3.34+,
  confirmed supported locally on 3.40.1 — verify the actual container's
  SQLite version before relying on this). This is the SQLite-native feature
  specifically designed to accelerate arbitrary substring matching (i.e.
  `LIKE '%x%'`-style queries), unlike default FTS5 tokenizers which split on
  word boundaries and wouldn't preserve today's substring-anywhere
  semantics. Would need the two query sites rewritten from `LIKE` to
  `MATCH` against a companion FTS5 virtual table, and — since I haven't
  validated the exact `MATCH` query syntax against real, punctuation-heavy
  company names (commas, periods, "Inc.", multi-word names) — a small
  standalone validation script comparing FTS5 `MATCH` results against the
  current `LIKE` results for the same queries, run before touching
  `lib/edgar.py`, to make sure result sets actually match before swapping.
- **Normalize the schema**: split into a small deduplicated
  `company_names(cik, name)` table (searched) and a separate
  `filings(cik, year, month, day, accession, form)` table (only queried
  once a CIK is already known). This is architecturally the cleanest
  long-term shape — it also mirrors the fix already made to
  `get_all_details()` (fetch firmographics once per unique company, not
  once per filing row) — but it's a bigger change touching ingestion,
  schema, and both query methods. Worth doing eventually; not worth doing
  before measuring whether Step 1 alone is sufficient.

**My recommendation: do Step 1, measure, and only decide on Step 3 with real
numbers in hand.** Given the 30x row reduction, I'd be surprised if Step 3
turns out to be necessary at all.

---

## 2. Move blocking I/O off the event loop (concurrency, per-pod)

### The evidence

`company_dns.py` runs a single uvicorn worker (`uvicorn.run(app, host=host,
port=8000, ...)` — no `workers=` argument), and `_handle_request` calls
query methods directly:
```python
if asyncio.iscoroutinefunction(func):
    data = await func(*args, **kwargs)
else:
    data = func(*args, **kwargs)   # <-- runs inline on the event loop
```
None of the query classes are `async`, so every blocking call (SEC EDGAR,
Wikipedia/Wikidata via `wptools`, the ArcGIS geocoder) executes directly on
the one event loop thread this process has. The perf baseline's concurrency
numbers are consistent with this: speedup at concurrency 8 topped out
around ~2x for `edgar_ciks`/`health` — which lines up with there being **2
pod replicas** to spread load across, not with any real intra-pod
parallelism.

### Why this is more than a one-line fix — a prerequisite that must come first

The obvious fix — wrap the sync call in
`starlette.concurrency.run_in_threadpool` inside `_handle_request` — is
**not safe to do on its own**, because of how the query "handler" objects
are constructed today. In `company_dns.py`:
```python
sq = SICQueries()
eq = EdgarQueries()
wq = WikipediaQueries()
gq = GeneralQueries()
uksq = UKSICQueries()
isicsq = InternationalSICQueries()
eusicsq = EuSICQueries()
japansicsq = JapanSICQueries()
unified_sic_q = UnifiedSICQueries()
```
These 9 objects are **module-level singletons, constructed once at process
startup and shared across every request** (30 call sites across
`company_dns.py` reference them via `_handle_request(sq, sq.get_...)` etc.).
`_handle_request` mutates shared state on them before every call:
```python
def _handle_request(handler, func, query_value, *args, **kwargs):
    handler.query = query_value
    ...
```
Today this is silently safe only because **nothing actually runs
concurrently** — the single event loop thread executes each request's
handler to completion before starting the next one, so the shared
`handler.query` write-then-read never actually races. The moment real
concurrency is introduced (via `run_in_threadpool` or anything else), this
becomes a live, silent data-corruption bug: two concurrent requests to the
same endpoint (e.g. two different SIC lookups both hitting the shared `sq`
object) could read each other's `.query` value and **return the wrong
company's/code's data to the wrong caller** — a worse failure mode than a
crash.

There's a second, compounding issue specific to the six SQLite-backed
classes (`sic.py`, `uk_sic.py`, `international_sic.py`, `eu_sic.py`,
`japan_sic.py`, `edgar.py`): each opens **one `sqlite3.connect()` connection
and one cursor at construction time**, stored as `self.e_conn`/`self.ec`,
and reuses that same cursor object for every call
(`self.ec.execute(...)` inside every query method). SQLite connections
default to `check_same_thread=True`, so simply running these methods inside
a threadpool worker thread (different from the thread that constructed the
singleton at startup) would raise
`sqlite3.ProgrammingError: SQLite objects created in a thread can only be
used in that same thread` immediately — a hard crash, not a subtle bug.

### Recommended fix, in order

1. **Stop sharing singleton handler instances across requests.** Construct
   a fresh instance of the relevant query class per request instead of
   reusing the module-level singleton. This eliminates *both* problems at
   once — no shared `.query` attribute to race on, and no shared
   `sqlite3.Connection`/`Cursor` to violate thread-affinity on, since each
   request's object (and its own fresh SQLite connection) is now only ever
   touched by the one request that created it. Concretely, this likely
   means changing `_handle_request`'s signature from taking a pre-built
   `handler` instance to taking a handler **class** (or a small zero-arg
   factory), and updating all 30 call sites — mechanical, but touches every
   endpoint. Cost: one extra `sqlite3.connect()` (a fast, local, file-based
   operation) per request for the six DB-backed classes — negligible next
   to multi-second external calls, and not a meaningful regression even for
   the ~50ms `health`/`sic_lookup` endpoints.
2. **Then** wrap the (now safely request-scoped) call in
   `run_in_threadpool` inside `_handle_request`, for every non-async
   handler. This lets FastAPI's thread pool (via `anyio`, default capacity
   40) actually run multiple in-flight blocking calls concurrently within
   one pod, rather than serializing them on the single event loop thread.
3. Apply this uniformly (all handlers through `_handle_request`, not just
   the "slow" ones) rather than special-casing which endpoints get
   threadpool treatment — simpler, and the overhead of `run_in_threadpool`
   for an already-fast local call is negligible.

### Measurement

```bash
python3 perf_tests/baseline.py --concurrency 1 4 8 --repeat 3
```
Compare per-endpoint speedup-vs-serial numbers against the baseline. Expect
per-pod concurrency to improve meaningfully (ideally approaching the
threadpool's effective capacity for I/O-bound work), independent of however
many pod replicas exist — this is the number that should move as a direct
result of this item, as distinct from item 3 below.

### Risk / correctness verification before merging

Given the shared-state race described above is real but currently masked,
this needs actual concurrent-load correctness testing, not just latency
timing — e.g. firing concurrent requests for **different queries against
the same endpoint** (which `perf_tests/baseline.py`'s concurrency mode
already does, cycling through different companies) and asserting each
response actually contains the company it asked for, not a neighbor's data.
Worth adding this as an explicit assertion in the perf suite's concurrency
runner before relying on it to validate this change, rather than trusting
latency numbers alone to prove correctness.

---

## 3. Replica count / uvicorn workers

### Current state

`k8s/prod/deployment.yaml`: `replicas: 2`, resources `requests: 100m
CPU/256Mi`, `limits: 500m CPU/1Gi`, spread across `cafe-1`/`espresso-1` via
pod anti-affinity. `company_dns.py` calls `uvicorn.run(app, ...)` with no
`workers` argument (single process per pod).

### Decision: bump to 4 replicas, and no more than 4

Per the user: `company_dns` is additive to what's already running on
`cafe-1`/`espresso-1` and there's plenty of headroom, but capped at **4
replicas** as a deliberate ceiling (not "as many as fit") — this isn't
scaled by measured need, it's a fixed target agreed up front.

### Two independent levers here

1. **More pod replicas** (`kubectl`/`deployment.yaml` change only, no code
   change): bump `replicas` from 2 to 4. Zero-risk, purely additive — but by
   itself this just means "more independent single-threaded processes,"
   each still subject to item 2's serialization problem until that's fixed.
   **This is a multiplier on item 2, not a substitute for it** — the perf
   baseline already showed the current 2-pod setup topping out around ~2x
   speedup, exactly what you'd expect from 2 independent serialized
   processes; 4 replicas without item 2 would plausibly get to ~4x, still
   far short of what proper in-process concurrency would give.
2. **Multiple uvicorn worker processes per pod** (`workers=N` in
   `uvicorn.run(...)`): a real implementation detail worth flagging now —
   uvicorn's multi-worker mode requires the app be passed as an **import
   string** (e.g. `"company_dns:app"`), not the app object directly, because
   each worker subprocess re-imports it independently. The current call
   (`uvicorn.run(app, ...)`) passes the object, so this would need to
   become `uvicorn.run("company_dns:app", ..., workers=N)` — a small but
   necessary change, not just adding a parameter.

### Recommended approach

Do item 2 first (fixes the actual bottleneck architecturally, benefits
every pod/worker equally), then bump `replicas` to 4 as a cheap, low-risk
multiplier on top. I'd hold off on uvicorn multi-worker-per-pod for now:
once item 2 is in place, one worker process per pod, with
`run_in_threadpool` handling I/O-bound concurrency, likely gets most of the
benefit without adding another layer of process management (worker-per-pod
is more useful for CPU-bound workloads, which this app mostly isn't — its
slow paths are network-wait, not computation).

### Pre-flight check before bumping replicas

Per the user, not treated as a blocker: `company_dns` is additive and
there's plenty of room on `cafe-1`/`espresso-1` for a 4-replica footprint at
its current per-pod resource sizing (100m/256Mi requests). Still worth a
quick sanity check at the time of the actual change, since the cluster's
other workloads (`mediumroast-website`, `vault-*`, the observability stack)
aren't static:
```bash
kubectl top nodes
kubectl top pods -A
```

---

## 4. Performance comparison tooling

### Why this is its own item, not an afterthought

`perf_tests/baseline.py` can run and persist a JSON report, but as it
stands today, comparing two runs (before item 1, after item 1; before item
2, after item 2; etc.) means opening two JSON files or two console
printouts and eyeballing the difference. For a plan whose entire premise is
"measure each change with the perf suite before moving to the next," that's
not good enough — we need an actual diff, and we need to know with
confidence which code was running when each measurement was taken.

Two concrete gaps:

1. **No comparison report.** Nothing turns two result files into a delta —
   "`edgar_ciks` median went from 2738ms to 96ms, a 96.5% improvement" isn't
   something the tool currently says; you'd have to compute it by hand from
   two summary tables.
2. **No provenance.** The JSON report records `base_url` and
   `generated_at`, but not *what code was actually deployed* when the run
   happened. A run from next month has no built-in way to prove which of
   the other items in this plan were live at the time — you'd have to
   remember or reconstruct it from PR merge times, which is exactly the
   kind of thing that gets forgotten under real operational pressure.

### Proposed fix

**In `perf_tests/baseline.py`**: record provenance in the report at run
time, best-effort:
- `git_commit`: `git rev-parse HEAD` (short SHA) of whatever checkout the
  script is run from, wrapped in a `try`/`except` so it degrades gracefully
  (`null`) if run somewhere without git available. This is a reasonable
  proxy for "what was deployed," accurate as long as the perf run happens
  from the same checkout that was just built/deployed via
  `scripts/build-and-deploy.sh` — which is exactly the intended workflow:
  merge a fix, pull, deploy, immediately run the perf suite from that same
  checkout.
- Also worth capturing the deployed image tag directly, when available,
  rather than relying solely on the git-commit proxy: if `kubectl` is on
  the `PATH` (it will be when run from `cafe-1`, where deploys actually
  happen), best-effort shell out to
  `kubectl -n company-dns get deployment company-dns -o jsonpath='{.spec.template.spec.containers[0].image}'`
  and record the result as `deployed_image`. Also wrapped in `try`/`except`
  — the suite should never fail a real measurement run just because
  provenance capture didn't work (e.g. it's being run against `--base-url
  http://localhost:8000` with no cluster access).

**New file `perf_tests/compare.py`**:
```bash
python3 perf_tests/compare.py perf_tests/results/before.json perf_tests/results/after.json
```
- Loads both reports' `sequential_results`, groups by `endpoint_key` same as
  `print_sequential_summary` already does, and prints a delta table: median
  and p95 for both runs, absolute and percentage change, per endpoint.
- Does the same for `concurrency_results`, grouped by `(endpoint_key,
  concurrency_level)` — comparing wall-time-per-batch and the
  speedup-vs-serial factor between the two runs, which is the number that
  actually matters for judging item 2/3's effect.
- Flags results plainly rather than just printing numbers and leaving
  interpretation to the reader: mark any endpoint whose median got
  meaningfully worse (e.g. >10% slower) as a visible **REGRESSION**, and
  anything that improved by some threshold (e.g. >20% faster) as
  **IMPROVED** — a quick scan should surface the interesting rows without
  reading every line.
- Prints the two runs' `git_commit`/`deployed_image` (if captured) at the
  top of the report, so the comparison is self-documenting about what was
  actually being compared.
- Optional `--out` to also write the diff as JSON, for keeping a record
  alongside the raw baseline files.

### What this does *not* try to solve

Statistical rigor beyond what's reasonable for a small internal tool: no
confidence intervals, no accounting for time-of-day/external-API variance
across runs taken days apart. The known confound already documented above
(warm upstream caching affecting `merged_firmographics` at low concurrency)
still applies — `compare.py` will happily report a "regression" or
"improvement" on a noisy external-API endpoint that has nothing to do with
the actual code change. The comparison tool makes the *arithmetic*
trustworthy; it doesn't make Wikipedia's own response-time variance go
away. Endpoints in the `external-io` category with no local-code changes
behind them (e.g. `wikipedia_firmographics` when only item 1 or item 3
changed) should be read as noise, not signal — same caveat as in the
baseline README, just now something a diff tool could mislead someone
about if they don't already know that.

### Sequencing relative to the other items

Build this **before** starting item 1's implementation, not after — the
whole point is to have a trustworthy comparison mechanism in place before
there's anything to compare. It's also the smallest, lowest-risk item of
the six (pure tooling, no application code touched), so there's no reason
to defer it.

---

## 5. Reuse HTTP connections to SEC EDGAR

### The evidence

`lib/edgar.py`'s `get_firmographics()` calls `requests.get(my_url,
headers=self.headers)` directly — a fresh `requests.get()` call, not a
method on a shared `requests.Session()`. Every call opens a brand new TCP
connection and does a fresh TLS handshake to `data.sec.gov`, even when the
same process calls it multiple times in short succession (e.g.
`edgar_detail`, which — after the item 1 fix — calls `get_firmographics()`
once per unique matched company, meaning a single incoming request can make
several outbound EDGAR calls in a row, each paying full connection setup
cost).

### Recommended fix

Use a shared `requests.Session()` instead of bare `requests.get()`, so
repeated calls to the same host reuse a pooled, keep-alive HTTP connection
(TCP + TLS handshake only once, not per call).

Placement, given item 2's plan to stop sharing `EdgarQueries` instances
across requests: the `Session` itself should still be **shared** (e.g. a
module-level `requests.Session()` in `lib/edgar.py`, or a class attribute),
**not** re-created per request alongside the rest of `EdgarQueries`'s
per-request state. This is safe: `requests.Session`'s connection pooling
(via `urllib3`) is designed to be reused across many sequential and
concurrent calls to the same host — sharing the `Session` while *not*
sharing the request-scoped `self.query`/cursor state (item 2's actual
correctness concern) are two independent things, and conflating them would
mean re-introducing per-call connection overhead for no reason. Only the
per-request identity/query state needs to stop being shared; the connection
pool is exactly the kind of resource that *should* stay shared.

Worth a quick look at `urllib3`'s default pool size
(`requests.adapters.HTTPAdapter`'s default `pool_maxsize`, 10) once item 2's
concurrency work is in and EDGAR calls can genuinely happen in parallel —
if concurrent EDGAR traffic ever exceeds 10 in-flight connections to
`data.sec.gov`, the pool would start queuing rather than opening more
connections. Not a concern at today's traffic level; worth revisiting after
item 2 lands and is measured.

### Measurement

`edgar_firmographics_by_cik` (single call, isolates the connection-setup
cost cleanly) and `edgar_detail` (multiple calls per request, where the win
compounds) are the two endpoints to watch in `perf_tests/baseline.py`
before/after.

---

## 6. Reduce Wikipedia round-trips

**Status update (2026-09-27): this was scoped as "the smallest lever of the
six, backlog research only." That was wrong.** Reading `wptools`' actual
source and measuring real requests against the live Wikipedia/Wikidata APIs
turned up a hidden, sequential, mostly-wasted request cascade that plausibly
accounts for the majority of `wikipedia_firmographics`/
`merged_firmographics`'s remaining latency. This is now one of the
higher-value remaining levers, not the smallest. Findings below; no code
changed yet.

### Confirmed field-to-source mapping

(Original mapping, now verified against `wptools`' actual source, not just
the extraction code that consumes it — see `lib/wikipedia.py`'s grep for
`parse_results.`/`query_results.`/`page_data.`)

- `query_results` (`get_query`): `description` (from `extract`), `url`
  (from `fullurl`) — **only these two fields are read**, nothing else from
  `action=query`'s response.
- `company_info` from `parse_results.data['infobox']` (`get_parse`):
  `type`, `name`, fallback `country`/`city`/`website`, `isin`, `tickers` —
  **only `infobox` (derived purely from `parsetree`) is read**, nothing
  else from `action=parse`'s response.
- `page_data.data['wikidata']` (`get_wikidata`): `industry (P452)`,
  `country (P17)`, `official website (P856)`,
  `Central Index Key (P5531)`, `stock exchange (P414)` — **only these 5
  Wikidata properties are read.**

### Finding 1 — the 3 calls are genuinely 3 separate MediaWiki API
modules, can't be merged via `wptools`

Confirmed by reading `wptools/query.py`'s query-string templates:
`action=parse` and `action=query` are different top-level MediaWiki API
actions (can't combine into one HTTP request even though both hit the same
host, `en.wikipedia.org`); `action=wbgetentities` is a third action against
a *different* host (`www.wikidata.org`). `get_wikidata()` also works
correctly even when called in parallel with the other two, before a
`wikibase` ID is resolved — it falls back to a `sites=enwiki&titles=<title>`
site-link lookup (still one request), confirmed in `query.py`'s
`wikidata()` method. **So the existing parallelization is architecturally
sound** — 3 calls is the right number for 3 genuinely independent data
sources, not itself a bug.

### Finding 2 — both `parse` and `query` fetch far more than we use, and
`parse` is the current bottleneck

Measured real response sizes and timings against the live API
(`en.wikipedia.org`/`www.wikidata.org`, `IBM`/`Apple Inc.`/`Microsoft`/
`Amazon (company)`/`Tesla, Inc.`):

| Call | Current payload | Payload if narrowed to only what we use | Reduction | Current median latency | Narrowed median latency |
|---|---|---|---|---|---|
| `parse` (IBM) | 936,809 bytes (`text` alone: 614,808 bytes, entirely unused) | 178,196 bytes (`parsetree` only) | **-81.0%** | 817ms | 393ms (**-45%**, measured across 5 companies) |
| `query` (IBM) | 25,168 bytes | 3,234 bytes (`extracts`+`info` only) | **-87.2%** | 235ms | not separately timed — already small, expect modest gain |
| `wikidata` claims (IBM) | 374,588 bytes | 367,348 bytes (`claims` only) | -1.9% (claims dominate regardless; no per-property filter exists in this API) | 461ms | ~unchanged |

Timing 5 companies' raw calls showed **`parse` is the actual bottleneck of
the 3 parallel calls today** (817ms median vs. `query`'s 235ms and
`wikidata`'s 461ms) — so narrowing `parse`'s fields alone should shift the
parallel group's floor from ~800-950ms down to whatever `wikidata` ends up
costing (see Finding 4 below, which is far larger).

### Finding 3 — `wptools`' request layer never reuses connections, even
within one lookup

Read `wptools/core.py`'s `_request()`: it constructs a **brand-new
`WPToolsRequest` (and thus a brand-new `pycurl.Curl()` handle) on every
single `_get()` call** — no connection pooling, no keep-alive reuse, not
even between the `parse` and `query` calls that both hit
`en.wikipedia.org` within the same lookup. This is the exact bug fixed in
`lib/edgar.py` for item 5, except here it's inside a third-party dependency
we don't control the request layer of. Every one of the 3 (really 4+, see
below) calls pays a full fresh TCP+TLS handshake.

### Finding 4 — the real dominant cost: `get_wikidata()` triggers a hidden,
sequential label-resolution cascade

This is the big one. `wptools/wikidata.py`'s `_set_data('wikidata')` calls
`self.get_labels()` automatically after every `get_wikidata()` call.
`get_labels()` resolves **every property and every Q-number value
referenced anywhere in the entity's claims** into human-readable text —
not just the 5 properties `company_dns` actually reads — fetching up to 50
entities per request and looping sequentially (`while 'entities' in
self.data and self.data['entities']: self._get('labels', ...)`) until all
are resolved.

Measured against IBM's real Wikidata entity (`Q37156`, 189 claim
properties):

| | Entities needing labels | Requests needed (50/request) | Measured time |
|---|---|---|---|
| **What `wptools` actually does today** | 308 (every property + every Q-value in all 189 claims) | 7, sequential | **2,808ms** |
| **What we actually need** (5 properties + their referenced Q-values) | 13 | 1 | **285ms** |

**That's an 89.8% reduction, ~2.5 seconds, entirely hidden inside what our
code treats as "one wikidata call."** This single mechanism plausibly
explains the gap between the raw single-request timings above (parse
817ms / query 235ms / wikidata-claims-only 461ms — none of which alone
approach the 4-8 second real-world `wikipedia_firmographics` latency) and
what's actually observed in production: add the ~2.8s hidden label cascade
on top of the ~461ms claims fetch and the numbers line up.

### What this means for the recommendation

Item 6 is **not** the smallest lever — Finding 4 alone is a larger,
better-evidenced opportunity than anything in items 1-3, 5 except item 1
itself. But capturing it means no longer being able to use `wptools`'
`get_wikidata()`/`get_labels()` as-is; the label cascade is baked into
`wptools`' internals with no public parameter to narrow it. Two tiers,
neither implemented yet:

**Tier A (moderate effort, high confidence)** — replace the wikidata leg
with a small, purpose-built direct client (mirroring item 5's
`requests.Session()` pattern):
1. Fetch claims directly: `action=wbgetentities&props=claims&sites=enwiki&titles=<title>` (already measured above, same cost as today).
2. From the claims response, collect only the ~13 entities needed for our
   5 properties (property IDs + their Q-number values) — same logic
   already prototyped in this research (see the entity-collection snippet
   used to produce the table above).
3. One targeted `action=wbgetentities&props=labels&ids=<13 ids>` request
   instead of `wptools`' 7-request cascade.
4. Reuse `wptools/utils.py`'s `get_infobox()` directly (it's a standalone
   function operating only on a `parsetree` string — not coupled to
   `wptools`' request layer, so it can be imported and reused as-is) for
   the `parse` leg, fetched via our own narrowed
   `action=parse&prop=parsetree` request instead of `wptools.get_parse()`.
5. For `query`, either keep `wptools.get_query()` as-is (its own waste is
   comparatively small — Finding 2 shows the narrowed version isn't even
   separately worth timing) or narrow it the same way for consistency.
6. All of the above through one shared `requests.Session()` (Finding 3),
   fixing the connection-reuse gap too.

This removes `wptools` from the hot path for `parse` and `wikidata`
(keeping it, if desired, only for `query`, or dropping it entirely for
consistency), replacing it with a few hundred lines of direct HTTP calls
plus reused utility functions — a real rewrite of `lib/wikipedia.py`'s
network layer, not a config tweak, but the payoff (roughly halving `parse`
and cutting ~2.5s off `wikidata` per lookup) is large and now backed by
measurements, not guesses.

**Tier B (bigger, not recommended without cause)** — drop `wptools`
entirely, including for `query`, and/or move to Wikidata's SPARQL endpoint
for even narrower claim-level filtering. Not justified by the evidence
gathered here; Tier A already captures the large, cheap wins.

### Still not proposing to implement this yet

This is research output for review, matching how item 6 was originally
scoped — but the conclusion has changed from "smallest lever, low
priority" to "large, well-evidenced lever, moderate implementation effort
(Tier A)." Worth a real decision from the user on whether to schedule Tier
A as an actual implementation item, given the strength of evidence, rather
than leaving it as an indefinite backlog note.

---

## Suggested execution order

Every code-touching item below follows the same cycle, made explicit here
because we've already been bitten twice in this repo by treating "redeploy"
as an assumed, un-worth-mentioning step (the non-root-UID
`CreateContainerConfigError` and the same-day image-tag collision, both
from the k8s migration work) — it's cheap to write out and expensive to
skip:

> **code change → build & push a new image → `kubectl apply` / rollout →
> confirm pods healthy → run `perf_tests/baseline.py` → diff with
> `perf_tests/compare.py` against the prior checkpoint → decide whether to
> proceed**

Concretely, on `cafe-1` (or wherever `build-and-deploy.sh` is run from):
```bash
git pull                              # after merging the item's PR
./scripts/build-and-deploy.sh         # build, push, apply, wait for rollout
kubectl -n company-dns get pods -o wide   # confirm 2/2 (or however many replicas) Running
python3 perf_tests/baseline.py --out perf_tests/results/after-item<N>-$(date +%Y%m%d).json
python3 perf_tests/compare.py perf_tests/results/<prior-checkpoint>.json perf_tests/results/after-item<N>-$(date +%Y%m%d).json
```

Checkpoints, in order:

0. **Item 4**: `compare.py` + provenance stamping in `baseline.py`. Do this
   first — smallest, lowest-risk, pure tooling (no deploy needed, it never
   touches `company_dns` itself). Re-run against the existing committed
   baseline once built, just to confirm it works, before touching any
   application code.
1. **Item 1, Step 1 + Item 5, bundled**: ingest-time form filtering
   (`lib/prepare_edgar_data.py`) and the EDGAR `requests.Session()` reuse
   (`lib/edgar.py`) both touch the EDGAR data path and are both small/safe
   — bundle them into one PR and one deploy cycle rather than two, to avoid
   doubling the build-and-redeploy overhead for two independently
   low-risk changes.
   - **Build & deploy**: `./scripts/build-and-deploy.sh` (this rebuilds
     `companies.db` from scratch via `makedb.py` during the Docker build,
     picking up the ingest filter automatically).
   - **Measure**: `perf_tests/baseline.py`, focus on `edgar_ciks`,
     `edgar_detail`, `edgar_firmographics_by_cik`.
   - **Compare**: `perf_tests/compare.py` against the item-0 checkpoint
     (i.e. the original `baseline-20260926.json`).
   - **Decide**: does this change how urgent item 2 even is? (If the DB fix
     alone gets `edgar_ciks`/`edgar_detail` down near
     `edgar_firmographics_by_cik`'s ~178ms, the case for item 2 shifts from
     "fixes a severe bottleneck" to "improves concurrent throughput on an
     already-fast path" — still worth doing, but worth knowing which one
     it is before deciding how much scrutiny item 2's bigger refactor
     needs.)
2. **Item 2, in its own PR — per decision, kept separate from item 1+5 and
   item 3, not bundled with anything**: singleton-to-per-request refactor +
   `run_in_threadpool`, together (the first isn't optional once the second
   is on the table). This is the largest and riskiest piece of the six —
   touches `company_dns.py`'s 30 call sites and all 9 handler classes'
   construction pattern — and should get real concurrent-correctness
   testing (see item 2's "Risk / correctness verification" section above),
   not just latency measurement, before merging. Its own review cycle, on
   its own timeline, independent of the other checkpoints.
   - **Build & deploy**: `./scripts/build-and-deploy.sh`.
   - **Measure**: `perf_tests/baseline.py --concurrency 1 4 8 --repeat 3`.
   - **Compare**: `perf_tests/compare.py` against the item-1 checkpoint —
     the number that should move here is per-pod concurrency/speedup, not
     sequential median latency (that's items 1/5's signal, not item 2's).
3. **Item 3**: bump `replicas` to **4** (the agreed ceiling — see item 3's
   "Decision" above). Sequenced last so the perf data reflects the real
   per-pod concurrency ceiling from item 2 rather than just "more copies of
   a serialized process" — doing this before item 2 would make the two
   effects hard to tell apart. Uvicorn multi-worker deferred unless item 2
   + 4 replicas still isn't enough.
   - **Deploy**: this one's a manifest-only change
     (`kubectl apply -f k8s/prod/deployment.yaml`), no image rebuild
     needed.
   - **Measure & compare**: same concurrency-focused comparison as item 2,
     against the item-2 checkpoint.

**Item 6** (reduce Wikipedia round-trips) has no deploy/measure cycle in
this plan — it's a backlog research item (see its section above), picked up
separately once someone's done the field-to-source mapping investigation.

## Decisions (previously open questions, now resolved)

1. ~~Item 4: any objection to the `git_commit`/`deployed_image`
   best-effort-`kubectl`-shellout approach for provenance...~~ **Resolved:
   approved as designed.** No change needed.
2. ~~Item 1: comfortable with a single ingest-time filter first, deferring
   FTS5/schema normalization...~~ **Resolved: approved as designed.**
   Ingest-time filter only; FTS5/normalization stays a conditional
   follow-up, not scheduled.
3. ~~Item 1 + 5 bundling: comfortable combining these into one PR/deploy
   cycle...~~ **Resolved: yes, bundle them.** One PR, one deploy cycle for
   items 1 and 5 together.
4. ~~Item 2: this is a bigger refactor than originally described...
   comfortable with that scope, or want it split into its own smaller
   PR/review cycle...~~ **Resolved: kept separate.** Item 2 gets its own
   PR and review cycle, independent of items 1+5 and item 3 — reflected in
   "Suggested execution order" above.
5. ~~Item 3: any known constraints on how many replicas
   `cafe-1`/`espresso-1` can actually absorb...~~ **Resolved: cap at 4
   replicas.** Per the user: `company_dns` is additive and there's plenty
   of room, but 4 is a deliberate ceiling, not "as many as fit" — updated
   throughout item 3's section and the execution order above. A quick
   `kubectl top nodes`/`top pods` check at execution time is still sensible
   (the cluster's other workloads aren't static) but isn't a blocker on the
   decision itself.
6. ~~Item 6: leave it purely as a written-down backlog item for now, or
   scope the field-to-source mapping investigation as actual follow-up
   work?~~ **Originally resolved as backlog-only — reopened 2026-09-27.**
   The requested follow-up research (see item 6's section) found a
   previously-hidden, large, measured bottleneck (a sequential
   label-resolution cascade costing ~2.8s per lookup, 89.8% of which is
   wasted resolving data never used) that changes the priority assessment.
   **New open question**: schedule Tier A (the proposed `wptools`
   replacement for the `parse`/`wikidata` legs) as a real implementation
   item, or keep it backlogged despite the new evidence?
