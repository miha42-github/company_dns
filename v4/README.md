# company_dns V4 (prototype)

The first real running server combining what
[`docs/plans/go-duckdb-rewrite.md`](../docs/plans/go-duckdb-rewrite.md),
[`docs/plans/edgar-backend.md`](../docs/plans/edgar-backend.md), and
[`experiments/`](../experiments/) validated individually — see
[`docs/plans/v4-server-prototype.md`](../docs/plans/v4-server-prototype.md)
for the full plan this implements. **Prototype**: US SIC + EDGAR +
Wikipedia (real, per §8.1), no UX — see that doc's §1 scope.

## Layout

```
crates/
  cache/          general moka TTL+LRU cache (promoted from experiments/edgar-cache-spike)
  edgar/          edgarkit wrapper: firmographics fetch + cache, catalog ingest/query
                  (promoted from experiments/edgar-spike, edgar-index-query, edgar-cache-spike)
  sic/            US SIC data access: V3-parity lookups + similarity search
                  (promoted from experiments/df-spike, ic-similarity-service)
  wikipedia/      real MediaWiki/Wikidata client - infobox/claims parsing, V3's
                  corporate-suffix hint (restored, actually executed as REST calls),
                  429/503 backoff (promoted from experiments/wikipedia-spike)
  firmographics/  real EDGAR+Wikipedia merge (both sides real now)
  server/         the Axum binary wiring it all to HTTP routes
```

Requires DataFusion 55.x and `edgarkit` sharing one process — decided in
`go-duckdb-rewrite.md`/`edgar-backend.md`'s status lines (2026-09-28),
resolving the `chrono`-version conflict that forced the EDGAR spikes
apart on DataFusion 42.

## Running it

**1. Ingest the EDGAR catalog** (writes to repo-root `./tmp/`, not
committed — `docs/plans/v4-server-prototype.md` §4):

```bash
cd crates/edgar
cargo run --release --bin ingest-edgar -- 2025 2
```

**2. Get the SIC data** — same real Mediumroast files
`experiments/df-spike`/`ic-similarity-service` use
(`tmp/us_flat.feather`/`tmp/us_flat_embedded.feather`), not committed
either. See `experiments/df-spike/README.md` for where to get a copy.

**3. Run the server:**

```bash
cd crates/server
cargo run --release
```

Env vars (all optional, default to the repo-root `./tmp/` files above):
`SIC_DATA_PATH`, `EDGAR_CATALOG_PATH`, `SIC_MODELS`
(`all_minilm_l6_v2` default, per `go-duckdb-rewrite.md` §7.8), `PORT`
(default `4000`).

## Endpoints

V3-parity (same envelope, same URL shape, `/V3.0/` → `/V4.0/` — see
`v4-server-prototype.md` §5.2/§5.3/§10):

```
GET /V4.0/na/sic/{description,code,division,industry,major}/{query}
GET /V4.0/na/companies/edgar/{ciks,detail,summary}/{company_name}
GET /V4.0/na/company/edgar/firmographics/{cik_no}
```

New, V4-only (§5.1):

```
GET /V4.0/na/sic/similarity/{query}?model=all_minilm_l6_v2&k=10
```

Real, built 2026-09-28 (§8.1/§8.2 — near-exact company/page title, same
as V3; V3's corporate-suffix hint restored and actually executed as a
REST call, not just suggested):

```
GET /V4.0/global/company/wikipedia/firmographics/{company_name}
GET /V4.0/global/company/merged/firmographics/{company_name}
```

## Comparing against V3

```bash
python3 ../perf_tests/baseline.py --base-url <v3-url> --profile v3 --out v3.json
python3 ../perf_tests/baseline.py --base-url http://127.0.0.1:4000 --profile v4 --out v4.json
python3 ../perf_tests/compare.py v3.json v4.json
```

`--profile v4` restricts the run to endpoints this server actually
implements (`perf_tests/baseline.py`'s `ENDPOINTS` catalog, `v4_path`
entries) — see `v4-server-prototype.md` §7 for why `compare.py` needed
no changes to do this, just the right two reports.
