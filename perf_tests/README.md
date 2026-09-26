# company_dns performance baseline suite

A small script that hits a curated set of `company_dns` endpoints - derived
from the live deployment's own OpenAPI spec, not hardcoded guesses - across
ten well-known companies, both sequentially (clean per-call latency) and at
increasing concurrency levels (does the server actually serve requests in
parallel, or serialize them?).

## Why this exists

While investigating why EDGAR/Wikipedia lookups were slow, we fixed two
concrete bugs (see `lib/edgar.py`/`lib/wikipedia.py` git history and
`docs/plans/onprem-k8s-migration.md`). This suite exists to measure what's
left, and specifically to test the hypothesis that concurrency - not
per-call latency - is the more tractable lever now. See
`docs/plans/performance-improvements.md` for the full plan, including item
2 (`company_dns.py` now constructs a fresh handler per request and runs
blocking query methods via `run_in_threadpool`, instead of the old shared-
singleton pattern that ran everything inline on the event loop).

The concurrency experiment's per-company batches (see
`CONCURRENCY_ENDPOINT_KEYS`) don't just measure latency - they also assert
correctness: each concurrent response is checked to make sure it actually
belongs to the company that was queried, not a neighbor's. This checks
against the company's **CIK**, not the raw query string - EDGAR-touching
endpoints (`merged_firmographics` especially) legitimately replace the
query with the resolved formal filer name once matched (querying `IBM`
correctly returns `INTERNATIONAL BUSINESS MACHINES CORP`), so a literal
query-string match would false-positive on entirely correct responses. CIK
is the one identifier that's actually stable across every endpoint's
response format (`edgar_ciks` returns it unpadded, `wikipedia_firmographics`/
`merged_firmographics` return it zero-padded, but the unpadded digits are
always a substring of the padded form). This is a direct regression guard
against the specific bug item 2 fixed (a shared mutable `.query` attribute
on module-level singletons, which could previously have let two concurrent
requests to the same endpoint race and swap results). A failed check raises
immediately with the offending endpoint, concurrency level, and response
body, rather than silently reporting a fast but wrong
answer as a latency win.

## Usage

```bash
# Full run against the live deployment (default)
python3 perf_tests/baseline.py

# Against a local/port-forwarded instance instead
python3 perf_tests/baseline.py --base-url http://localhost:8000

# Just see the call matrix, make no requests
python3 perf_tests/baseline.py --list

# Sequential baseline only, skip the concurrency experiment (faster, gentler on prod)
python3 perf_tests/baseline.py --skip-concurrency

# Widen/narrow the concurrency experiment
python3 perf_tests/baseline.py --concurrency 1 2 4 8 16 --repeat 3
```

Full results (every call: endpoint, company, URL, status, latency) are
written as JSON to `perf_tests/results/<timestamp>.json` by default, or
wherever `--out` points. Console output is a human-readable summary. Each
report also stamps `git_commit` (best-effort, from whatever checkout the
script is run from) and `deployed_image` (best-effort, shelled out to
`kubectl -n company-dns get deployment company-dns -o jsonpath=...` when
`kubectl` is available) — so a report can be matched back to exactly what
code was live when it was taken, without relying on memory or reconstructing
it from PR merge times later.

## Comparing two runs

```bash
python3 perf_tests/compare.py perf_tests/results/before.json perf_tests/results/after.json

# Write the diff out as JSON too, and/or tune the flagging thresholds
python3 perf_tests/compare.py before.json after.json --out diff.json
python3 perf_tests/compare.py before.json after.json --regression-pct 15 --improvement-pct 25
```

Prints both reports' provenance, then a per-endpoint sequential latency
delta (median/p95, before vs. after) and a per-`(endpoint, concurrency
level)` concurrency delta (wall time, speedup-vs-serial, before vs. after),
flagging anything that got meaningfully worse as **REGRESSION** and
meaningfully better as **IMPROVED** (thresholds configurable, default 10%
worse / 20% better) so the interesting rows don't require reading every
line.

**Caveat, worth internalizing before trusting a flag**: `edgar_ciks`,
`edgar_detail`, `edgar_firmographics_by_cik`, `health`, and `sic_lookup` are
either local-only or a single direct SEC call — clean signal for whatever
code change you're testing. `wikipedia_firmographics` and
`merged_firmographics` carry real variance from Wikipedia/Wikidata's own
response times and upstream caching that has nothing to do with
`company_dns` code — a flag on those two when your change didn't touch the
Wikipedia path at all is noise, not signal. `compare.py`'s docstring repeats
this; it's easy to forget mid-investigation.

Requires only `requests` (already a `company_dns` dependency) - no new
project dependencies.

## What it hits

| endpoint key | category | what it measures |
|---|---|---|
| `health` | control | liveness endpoint, no DB/network calls |
| `sic_lookup` | control | SQLite-only SIC search, no external calls |
| `edgar_ciks` | control (see caveat below) | SQLite-only fuzzy CIK search by name |
| `edgar_detail` | external-io | fuzzy EDGAR search + one live SEC call per unique matched company |
| `edgar_firmographics_by_cik` | external-io | one direct live SEC call by CIK |
| `wikipedia_firmographics` | external-io | Wikipedia/Wikidata lookup via wptools |
| `merged_firmographics` | external-io | the heaviest real-world path: Wikipedia + conditionally EDGAR + ArcGIS geocoding |

The endpoint list is verified against `{base_url}/openapi.json` at startup;
the suite refuses to run if any of these paths have disappeared or been
renamed on the deployment, rather than silently reporting 404s as fast
responses.

## Baseline results (2026-09-26, `https://company-dns.mediumroast.io`)

Full raw data: `perf_tests/results/baseline-20260926.json`.

### Sequential (one call at a time)

| endpoint | n | ok% | median | p95 | max |
|---|---|---|---|---|---|
| `health` | 1 | 100% | 53ms | 53ms | 53ms |
| `sic_lookup` | 1 | 100% | 56ms | 56ms | 56ms |
| `edgar_ciks` | 10 | 100% | **2738ms** | 3301ms | 3469ms |
| `edgar_detail` | 10 | 100% | **2804ms** | 4181ms | 4676ms |
| `edgar_firmographics_by_cik` | 10 | 100% | 178ms | 369ms | 512ms |
| `wikipedia_firmographics` | 10 | 100% | 3851ms | 5652ms | 6120ms (one earlier run: a 30s timeout) |
| `merged_firmographics` | 10 | 100% | 6095ms | 7840ms | 8053ms |

### Findings, in order of how actionable they are

1. **New discovery, not previously known**: `edgar_ciks` - a SQLite-only
   endpoint with **no external network call at all** - has a ~2.7s median
   latency, in the same ballpark as `edgar_detail` (which does make a live
   SEC call). This means a meaningful chunk of "EDGAR is slow" isn't
   external-API latency at all - it's almost certainly the `companies`
   table's `WHERE name LIKE '%...%'` query doing a full table scan with no
   index (`lib/prepare_db.py`'s `CREATE TABLE companies (...)` has none).
   This is independent of, and likely a bigger lever than, the caching
   question we were already weighing - an index (or FTS) on `companies` is
   a small, local, no-architecture-change fix.
2. **`edgar_firmographics_by_cik` is fast** (178ms median) - confirms the
   earlier fix (calling `get_firmographics` once per unique company instead
   of once per filing row) is working as intended: a single direct EDGAR
   call really is quick.
3. **Wikipedia lookups remain the genuinely slow, hard-to-avoid-without-caching
   part** - 3.8s median even after removing the duplicate-fetch bug, because
   `wptools` still makes several real external calls per lookup (parse,
   query, wikidata) and Wikipedia/Wikidata's own response times dominate.
   This is the part that likely does need caching to improve further, as
   originally guessed.
4. **Concurrency**: real speedup was observed (not full serialization, but
   not linear either) - e.g. `edgar_ciks` at concurrency 8 showed ~2.1x
   speedup vs. fully-serial, `health` showed ~4.6x. Since the deployment
   currently runs 2 replica pods, this is consistent with each pod's single
   uvicorn process serializing its own in-flight blocking I/O calls (no
   `run_in_threadpool`), with the ~2x baseline coming from having 2 pods to
   spread load across. **This supports the original hypothesis directly**:
   increasing replica count (or running multiple uvicorn workers per pod)
   should increase real concurrent throughput roughly proportionally, since
   the ceiling is pod/worker count, not the network.
5. **Caveat - `merged_firmographics` concurrency numbers are confounded**:
   they came out suspiciously fast at concurrency 1 and 4 (140ms, 218ms),
   almost certainly because the concurrency experiment ran immediately
   after the sequential pass already fetched the exact same companies -
   likely a warm cache somewhere upstream (Wikipedia's own CDN, or the
   ArcGIS geocoder), not anything in company_dns. Concurrency 8 (which
   still hits mostly the same recently-fetched companies) jumped back up to
   8s, so this isn't a clean signal either way - **don't read anything into
   the low-N `merged_firmographics` numbers**. A follow-up run with
   `--repeat 3+` and enough of a gap between the sequential and concurrency
   passes (or a larger/rotating company set) would give a cleaner read.
6. Two isolated anomalies in the raw data, not investigated further: one
   30-second client-side timeout on a `wikipedia_firmographics` call
   (JPMorgan Chase, first run only - didn't recur), and one `502` on
   `merged_firmographics` (Meta Platforms, 13ms - a fast gateway-level
   failure, not an app timeout). Both are in the JSON for the record.
