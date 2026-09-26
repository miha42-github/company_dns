# Performance improvements: EDGAR DB scan, request concurrency, replica count

Status: **Draft — for review, not yet executed**
Owner: michael.hay@mediumroast.io
Scope: items 1–3 from the "increase performance without caching" discussion
(company DB full-table-scan fix, moving blocking I/O off the event loop,
replica/worker count). Caching is explicitly out of scope here.
Measurement: [perf_tests/baseline.py](../../perf_tests/baseline.py) and the
committed baseline ([perf_tests/results/baseline-20260926.json](../../perf_tests/results/baseline-20260926.json))
are the before/after yardstick for all three items.

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

### Two independent levers here

1. **More pod replicas** (`kubectl`/`deployment.yaml` change only, no code
   change): bump `replicas` from 2 to, say, 4. Zero-risk, purely additive —
   but by itself this just means "more independent single-threaded
   processes," each still subject to item 2's serialization problem until
   that's fixed. **This is a multiplier on item 2, not a substitute for
   it** — the perf baseline already showed the current 2-pod setup topping
   out around ~2x speedup, exactly what you'd expect from 2 independent
   serialized processes; 4 replicas without item 2 would plausibly get to
   ~4x, still far short of what proper in-process concurrency would give.
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
every pod/worker equally), then treat replica count as a cheap,
low-risk multiplier on top — bump `replicas` to match available cluster
headroom. I'd hold off on uvicorn multi-worker-per-pod for now: once item 2
is in place, one worker process per pod, with `run_in_threadpool` handling
I/O-bound concurrency, likely gets most of the benefit without adding
another layer of process management (worker-per-pod is more useful for
CPU-bound workloads, which this app mostly isn't — its slow paths are
network-wait, not computation).

### Pre-flight check before bumping replicas

I don't have cluster metrics access in this session. Before increasing
`replicas`, check actual headroom on `cafe-1`/`espresso-1`:
```bash
kubectl top nodes
kubectl top pods -A
```
The cluster also runs `mediumroast-website` (2 replicas), the `vault-*`
Postgres/API pods, and a full observability stack (Prometheus/Grafana/
Loki/Tempo) on these same two worker nodes — worth confirming there's
actual spare capacity rather than assuming it.

---

## Suggested execution order

1. **Item 1, Step 1**: ingest-time form filtering in
   `lib/prepare_edgar_data.py`. Smallest, safest, highest-confidence win —
   do this first and measure before anything else, since it might change
   how urgent items 2–3 even are.
2. **Item 2**: singleton-to-per-request refactor + `run_in_threadpool`,
   together (the first isn't optional once the second is on the table).
   This is the largest and riskiest piece of the three — touches
   `company_dns.py`'s 30 call sites and all 9 handler classes' construction
   pattern — and should get real concurrent-correctness testing, not just
   latency measurement, before merging.
3. **Item 3**: bump `replicas` (cheap, do any time, ideally after item 2 so
   the perf data reflects the real per-pod concurrency ceiling rather than
   just "more copies of a serialized process"). Uvicorn multi-worker
   deferred unless item 2 + more replicas still isn't enough.

Each item re-runs `perf_tests/baseline.py` and compares against
`perf_tests/results/baseline-20260926.json` before moving to the next, so
we know which change actually caused which improvement rather than
attributing a combined effect to the wrong lever.

## Open questions for the user

1. Item 1: comfortable with a single ingest-time filter first, deferring
   FTS5/schema normalization unless measurement shows it's still needed?
2. Item 2: this is a bigger refactor than originally described (30 call
   sites, a real pre-existing race condition to fix as a prerequisite) —
   comfortable with that scope, or want it split into its own smaller
   PR/review cycle separate from items 1 and 3?
3. Item 3: any known constraints on how many replicas `cafe-1`/`espresso-1`
   can actually absorb, or should I/you just check `kubectl top nodes`
   first?
