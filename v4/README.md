# company_dns V4 (prototype)

The first real running server combining what
[`docs/plans/go-duckdb-rewrite.md`](../docs/plans/go-duckdb-rewrite.md),
[`docs/plans/edgar-backend.md`](../docs/plans/edgar-backend.md), and
[`experiments/`](../experiments/) validated individually — see
[`docs/plans/v4-server-prototype.md`](../docs/plans/v4-server-prototype.md)
for the full plan this implements. **Prototype**: US SIC + EDGAR +
Wikipedia (real, per §8.1), no UX — see that doc's §1 scope. Tracking
toward an initial development release:
[`docs/plans/v4-initial-release-roadmap.md`](../docs/plans/v4-initial-release-roadmap.md).

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

**Data directory.** Every data file lives in one directory, named by
`COMPANY_DNS_DATA_DIR`. For now, in development, point it at the repo's
top-level `tmp/` (the same place the SIC files are staged by hand):

```bash
export COMPANY_DNS_DATA_DIR=/path/to/company_dns/tmp
```

If it is unset the default is that same repo-root `tmp/`, found from the source
tree at build time, so it no longer depends on which directory you start the
server from. In the container image it is the directory the files are copied
into; a volume mounted there replaces them. Each file also still has its own
override variable (below).

**1. Ingest the EDGAR catalog** (writes `edgar_10x_catalog.feather` into the
data directory, not committed - `docs/plans/v4-server-prototype.md` §4,
`docs/plans/v4-deployment.md` §3.2). With no arguments it pulls the last two
years of completed quarters (8) from the SEC and rebuilds the catalog from
scratch:

```bash
cargo run --release --bin ingest-edgar                       # last 2 years
cargo run --release --bin ingest-edgar -- --years 1          # last year
cargo run --release --bin ingest-edgar -- --from 2024Q1 --to 2025Q4
cargo run --release --bin ingest-edgar -- 2025 2             # one quarter
```

It needs network access to sec.gov. If any quarter fails nothing is written
and the existing catalog is left untouched; an empty result is refused.

**2. Get the SIC data** - the Mediumroast-produced flat-and-embedded files,
staged by hand in the data directory for now (the delivery mechanism from
mediumroast.io is not confirmed): `us_flat_embedded.feather`,
`japan_rev13_flat_embedded.feather`, `nace_rev2_flat_embedded.feather`,
`isic_rev4_flat_embedded.feather`. Check a new file before use with
`python3 docs/plans/research/check_ic_feather.py <file>`. See
`experiments/df-spike/README.md` for background.

**3. Run the server:**

```bash
cd crates/server
cargo run --release
```

Env vars (all optional): `COMPANY_DNS_DATA_DIR` (above), and per-file overrides
`SIC_DATA_PATH`, `JAPAN_SIC_DATA_PATH`, `EU_NACE_DATA_PATH`, `ISIC_DATA_PATH`,
`EDGAR_CATALOG_PATH`, plus `SIC_MODELS`
(`all_minilm_l6_v2` default, per `go-duckdb-rewrite.md` §7.8), `PORT`
(default `4000`), `RUST_LOG`/`LOG_LEVEL_CONFIG_PATH` (see
"## Profiles: authenticated access

Set `COMPANY_DNS_PROFILES_FILE` to a JSON file with a section per profile
(see [`profiles.example.json`](profiles.example.json)) and callers can authenticate
with HTTP Basic Auth: the profile id as the user name, a generated token as the
password. The file holds only a SHA-256 of each token, so a leaked file is not a
working credential; keep it out of the repository and the image (a mounted
Kubernetes or Docker secret in a deployment, a gitignored file locally). It is
read once at startup, so changing it means a restart, and an invalid file stops
the server. No file means everyone is anonymous. Unknown keys are an error.

```json
{"profiles": {
  "my-app": {
    "secret_sha256": "<sha256 of the token>",
    "rate_limit": {"requests_per_minute": 600, "burst": 60},
    "sql": {"datasets": ["sic", "edgar"]}
  }
}}
```

```sh
TOKEN=$(openssl rand -hex 32)                           # give this to the client, once
printf '%s' "$TOKEN" | shasum -a 256 | cut -d' ' -f1    # put this in the file
```

What a profile may be granted (everything is optional; no grant means none):

| Grant | Meaning |
|---|---|
| `rate_limit: {"bypass": true}` | No rate limit on the lookup routes. |
| `rate_limit: {"requests_per_minute": N, "burst": M}` | A quota of the profile's own instead of the `User-Agent` tiers (burst defaults to N). Fleet-wide numbers, divided across replicas like the tier quotas (`rate_limit.rs`). |
| no `rate_limit` | An identified caller gets the normal tier, whatever its `User-Agent`. |
| `sql: {"datasets": [...]}` | May use the experimental SQL endpoint, on those datasets (below). |

No credential is anonymous (the `User-Agent` tiers apply). A **wrong** credential
is a `401`, never silently anonymous, and failed logins are throttled per source
IP. `Origin` and `Referer` are ignored for identity. Use TLS: the token travels
with every request.

## Experimental: SQL endpoint

> **Experimental.** `POST /V4.0/sql` may change or be removed without notice.
> It is **off by default**, takes arbitrary SQL, and can use real CPU and memory,
> so it is closed to everyone who does not hold a credential you issued. Design
> and decisions: [`docs/plans/v4-sql-endpoint.md`](../docs/plans/v4-sql-endpoint.md).

One read-only statement per request, against one dataset: `sic` (US SIC plus
Japan SIC, EU NACE and ISIC when loaded) or `edgar` (the filings catalog), in
DataFusion's SQL dialect. The embedding (`vector_*`) columns are not exposed.
`select * from information_schema.columns` lists tables and columns.

**Turn it on** (nothing below is set by default):

| Variable | Default | Meaning |
|---|---|---|
| `COMPANY_DNS_SQL_ENABLED` | off | `true` registers the route. Without it the route does not exist (404) and is absent from `/docs`. |
| `COMPANY_DNS_PROFILES_FILE` | none, required when enabled | Path to the profiles file ("Profiles" above). The server refuses to start without a valid one; it never starts open. |
| `COMPANY_DNS_SQL_DEFAULT_ROWS` / `_MAX_ROWS` | 1000 / 10000 | Rows returned by default / the ceiling a request's `limit` is clamped to. |
| `COMPANY_DNS_SQL_TIMEOUT_SECS` | 10 | Statement timeout; the query is cancelled. |
| `COMPANY_DNS_SQL_MEMORY_MB` | 256 | Memory pool per dataset's query context; no spilling to disk. |
| `COMPANY_DNS_SQL_MAX_CONCURRENT` | 4 | Queries running at once on this process; more get a 429, not a queue. |
| `COMPANY_DNS_SQL_PARALLELISM` | 2 | DataFusion partitions per query, so one query cannot take every core. |

These are one global set of limits for every profile (per-profile limits are the
next phase). Invalid values stop startup.

**Credentials.** The route needs a profile granted `sql` (see "Profiles" above): no
credential is a `401`, a profile without `sql` or without that dataset is a `403`.
**Two layers of limits.** SQL goes through the same rate limiter as the lookups, so the
`User-Agent` tiers and a profile's `rate_limit` grant apply to it, sharing the same buckets,
**except that a trusted `Origin`/`Referer` is never a bypass here** (client-set headers). On
top of that a profile can carry its own SQL limits, each clamped by the server-wide values
above (a mistake in the file can restrict a profile, never exceed what the host allows):

```json
"sql": {"datasets": ["sic"],
        "limits": {"max_rows": 500, "timeout_secs": 5, "concurrency": 2,
                   "requests_per_minute": 30, "burst": 3}}
```

All five are optional. `requests_per_minute` and `burst` are fleet-wide numbers, divided
across replicas like the other quotas; a profile's `concurrency` is its own gate on top of
the server-wide one.

```sh
curl -u my-app:$TOKEN -H 'Content-Type: application/json' http://localhost:4000/V4.0/sql \
  -d '{"dataset": "sic", "sql": "select count(*) as n from sic_data"}'
```

**Try and test it locally:** [`scripts/sql-try.sh`](scripts/sql-try.sh) creates
throwaway profiles under `.local/sql/` (gitignored), starts the server with SQL on
and small limits, and runs a battery of checks (access, read-only, hidden vectors,
limits, throttling) against it:

```sh
scripts/sql-try.sh start          # in one terminal
scripts/sql-try.sh check          # in another
scripts/sql-try.sh q sic "select * from sic_data limit 3"
```

## Observability" below).

## API docs

`GET /openapi.json` (raw spec), `GET /docs` (Swagger UI), `GET /redoc`
(ReDoc) — matching V3's FastAPI `docs_url`/`redoc_url`/`openapi_url`
exactly. Built via `utoipa`/`utoipa-axum` —
[`docs/plans/v4-openapi-docs.md`](../docs/plans/v4-openapi-docs.md).

## Security

Per-client rate limiting, an inbound `User-Agent` gate, and request
hygiene (timeout, body-size limit, tracing) — real, live, and
past V3's actual (undocumented) posture, not just matching it. Full
design and live-verification record:
[`docs/plans/v4-security-hardening.md`](../docs/plans/v4-security-hardening.md).

- Every request to a data endpoint needs a `User-Agent` that looks
  self-identifying (has an `@` or a `http(s)://` in it, isn't a bare
  default like `curl/8.x`) to get the normal rate-limit tier (200/min
  fleet-wide, split across replicas); anything else lands in a much
  tighter draconian tier (5/min fleet-wide) — not a hard block, but
  harsh enough that a real integration notices and sets one.
- `/health`, `/docs`, `/redoc`, and `/openapi.json` are exempt from
  the gate entirely — it protects the firmographics/SIC data
  endpoints, not Kubernetes' own liveness/readiness probes or a human
  reading documentation.
- The local dev site and mediumroast.io skip the limiter via a
  trusted-`Origin` check. That header is set by the client, so it is a
  convenience for browsers, not proof of identity, and it is never
  honoured by the SQL endpoint. The earlier hourly-HMAC `User-Agent`
  secret (`MEDIUMROAST_SHARED_SECRET`) was removed; authenticated access
  is the profiles mechanism (HTTP Basic Auth, see "Profiles" below).
  Access is a ladder: no or generic `User-Agent` gets the draconian tier,
  a self-identifying one (`YourApp/1.0 (contact@example.com)`) the normal
  tier, and a Basic-Auth profile whatever its grants allow: no rate limit,
  a quota of its own, and/or SQL.
- Client IP for rate-limit keying is read from `X-Forwarded-For`
  (rightmost entry — the one Traefik itself appended, not anything a
  client could pre-populate to spoof an earlier entry), since this
  deployment sits behind Traefik as its sole external edge
  (`k8s/prod/ingress.yaml`) and the Service is `ClusterIP`-only.

## Observability

Real structured logging (`tracing`, replacing raw `println!`), with a
level that can be raised or lowered on a live, already-running process
— no restart, no rollout. Full design and live-verification record:
[`docs/plans/v4-dynamic-log-level.md`](../docs/plans/v4-dynamic-log-level.md).

- `RUST_LOG` sets the starting level (default `warn`) — standard
  `tracing`/`EnvFilter` directive syntax, e.g. `warn`, `debug`, or a
  targeted directive like `company_dns_server=debug,tower_http=debug`
  (recommended over a bare `debug` for incident response — a blanket
  `debug` also floods the log with every dependency's own internal
  output, e.g. DataFusion logging one line per partition on every SIC
  query; the targeted form gives just this crate's and `tower_http`'s
  detail).
- After startup, the level can be changed on a live process by editing
  the file at `LOG_LEVEL_CONFIG_PATH` (default
  `/etc/company-dns-log-level/log-level`, meant to be a K8s ConfigMap
  mounted as a **directory**, not via `subPath` — `subPath` bind-mounts
  the file once at container start and never updates it, silently
  defeating this feature). Polled every 5 seconds; a missing or
  unreadable path just means the startup level stays in effect,
  nothing fails or blocks waiting for it — safe to leave unset for
  local `cargo run`.

## Endpoints

V3-parity (same envelope, same URL shape, `/V3.0/` → `/V4.0/` — see
`v4-server-prototype.md` §5.2/§5.3/§10). Every resource here is also
served at its original `/V3.0/` path for backward compatibility
(`v4-openapi-docs.md` §8) — both documented separately in `/docs`:

```
GET /V4.0/na/sic/{description,code,division,industry,major}/{query}   (+ /V3.0/na/sic/...)
GET /V4.0/na/companies/edgar/{ciks,detail,summary}/{company_name}     (+ /V3.0/na/companies/edgar/...)
GET /V4.0/na/company/edgar/firmographics/{cik_no}                     (+ /V3.0/na/company/edgar/firmographics/...)
```

New, V4-only (§5.1), no `/V3.0/` equivalent:

```
GET /V4.0/na/sic/similarity/{query}?model=all_minilm_l6_v2&k=10
POST /V4.0/global/sic/match          {"text": "..."} or {"chunks": [...]}   (default: US SIC only; "systems" to add more)
POST /V4.0/global/sic/map            {"from": "US SIC", "codes": ["3571"], "to": [...], "description": "..."}
```

`POST /V4.0/global/sic/match` is the first POST route: a company description in, a
recommended set of 2-5 industry codes per classification system out, each with
its hierarchy and the text segment that supports it
(`docs/plans/company-sic-match.md`; the Company Explorer's Industry Match tab).
`POST /V4.0/global/sic/map` carries a chosen set of codes into the other systems by
embedding similarity (no crosswalk tables are used).

Real, built 2026-09-28 (§8.1/§8.2 — near-exact company/page title, same
as V3; V3's corporate-suffix hint restored and actually executed as a
REST call, not just suggested). Also served at `/V3.0/`:

```
GET /V4.0/global/company/wikipedia/firmographics/{company_name}   (+ /V3.0/global/company/wikipedia/firmographics/...)
GET /V4.0/global/company/merged/firmographics/{company_name}      (+ /V3.0/global/company/merged/firmographics/...)
```

Not aliased at `/V3.0/` (`v4-openapi-docs.md` §8.1): the non-US SIC
systems (UK/EU/ISIC/Japan — not implemented in V4 at all) and V3's
legacy wptools-backed `/v1/` Wikipedia/merged variants (V4's client is
a port of V3's `v2` backend specifically, no wptools equivalent
exists).

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
