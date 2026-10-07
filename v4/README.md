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

**Build profiles.** `cargo build --release` is the quick development build. For a shipped binary there are
two named profiles, both with fat LTO, one codegen unit and stripped symbols (the DataFusion feature trim, no Parquet and no
compression codecs, applies to every build):

```bash
cargo build --profile release-lean    # about 89 MiB stripped; no slower than the plain release build
cargo build --profile release-small   # about 62 MiB; same speed except scan-heavy SQL (about 28% slower)
```

Each takes several minutes to build. The sizes were measured on macOS arm64 and the choice between them is confirmed after
testing on Linux (`docs/plans/v4-release-to-staging.md`, step 5). The binary lands in `target/release-lean/` or `target/release-small/`.

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
"## Observability" below).

## API docs

`GET /openapi.json` (raw spec), `GET /docs` (Swagger UI), `GET /redoc`
(ReDoc) — matching V3's FastAPI `docs_url`/`redoc_url`/`openapi_url`
exactly. Built via `utoipa`/`utoipa-axum` —
[`docs/plans/v4-openapi-docs.md`](../docs/plans/v4-openapi-docs.md).

Both pages stay in a light theme and load **nothing from a third party**: Swagger UI is embedded by
`utoipa-swagger-ui`, and ReDoc is a vendored, pinned copy (2.5.4, MIT; `crates/server/assets/redoc/`) embedded in the
binary and served at `/redoc/redoc.standalone.js`, with the system font stack (no CDN, no Google Fonts), so
both work on an isolated network. Licences and notices: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

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

## Profiles: authenticated access

Callers can authenticate with HTTP Basic Auth: the profile id as the user name and a
generated token as the password. Profiles live in **two files**, split by what they hold,
both read once at startup (changing them means a restart; an invalid file stops the server;
unknown keys are an error). With no credentials file everyone is anonymous.

**1. Credentials** (`COMPANY_DNS_CREDENTIALS_FILE`), like `/etc/passwd`: one
`profile:sha256-of-token` per line, `#` comments allowed
([`credentials.example`](credentials.example)). This is the only secret file, and it holds
only hashes, so a leaked copy is not a working credential. Keep it out of the repository and
the image (a mounted Kubernetes or Docker secret in a deployment, a gitignored file locally).

```sh
TOKEN=$(openssl rand -hex 32)                           # give this to the client, once
printf '%s' "$TOKEN" | shasum -a 256 | cut -d' ' -f1    # put this after "profile:" in the file
```

**2. Rules** (`COMPANY_DNS_RULES_FILE`, optional), JSON with no secrets in it, so it can live
in a ConfigMap or in git ([`rules.example.json`](rules.example.json)): a `defaults` section and
per-profile overrides. A profile starts from the defaults and an override changes only the
settings it names:

```json
{
  "defaults": {"rate_limit": {"requests_per_minute": 300, "burst": 30}},
  "profiles": {
    "mediumroast.io": {"rate_limit": {"bypass": true},
                       "sql": {"datasets": ["sic", "edgar"], "limits": {"max_rows": 500}}},
    "partner":        {"rate_limit": {"requests_per_minute": 600}}
  }
}
```

How inheritance works: objects merge key by key (so `partner` above keeps the default `burst`),
a value or a list replaces (a `datasets` list is replaced, not appended to), and `null` removes
an inherited setting (`"sql": null` takes SQL away, `"max_rows": null` drops one limit).
`bypass` and a quota are alternatives, so naming one in an override replaces an inherited other.
A profile with no entry just gets the defaults; an entry for a profile with no credential is an
error (it catches typos).

The settings, all optional:

| Setting | Meaning |
|---|---|
| `rate_limit: {"bypass": true}` | No rate limit on the lookup routes. |
| `rate_limit: {"requests_per_minute": N, "burst": M}` | A quota of the profile's own instead of the `User-Agent` tiers (burst defaults to N). Fleet-wide numbers, divided across replicas like the tier quotas (`rate_limit.rs`). |
| no `rate_limit` | An identified caller gets the normal tier, whatever its `User-Agent`. |
| `sql: {"datasets": [...], "limits": {...}}` | May use the experimental SQL endpoint, on those datasets, with optional limits of its own (below). No `sql` means no SQL. |

### Set it up, step by step

Start from the two templates in this directory, [`credentials.example`](credentials.example) and
[`rules.example.json`](rules.example.json), and keep your real copies **outside the repository**
(or under a gitignored path):

```sh
mkdir -p ~/company_dns-access && cd ~/company_dns-access
cp /path/to/company_dns/v4/credentials.example credentials
cp /path/to/company_dns/v4/rules.example.json   rules.json
```

1. **Make a token per profile** and put its hash in `credentials` (replace the placeholder
   zeros on that profile's line; rename or delete the example profiles):

   ```sh
   TOKEN=$(openssl rand -hex 32)                         # give this to the client, once; never store it here
   printf '%s' "$TOKEN" | shasum -a 256 | cut -d' ' -f1   # paste this after "my-app:" in credentials
   ```

2. **Describe what each profile may do** in `rules.json`: put anything most profiles share under
   `defaults`, and only what differs under that profile in `profiles`. Profile names must match the
   credentials file. Skip the rules file entirely and every profile is an identified caller with no
   special grants.
3. **Start the server pointing at both files** (add the SQL flag only if you want the experimental
   SQL endpoint; it needs a profile with a `sql` setting):

   ```sh
   COMPANY_DNS_CREDENTIALS_FILE=$HOME/company_dns-access/credentials \
   COMPANY_DNS_RULES_FILE=$HOME/company_dns-access/rules.json \
   COMPANY_DNS_SQL_ENABLED=true \
   cargo run --release -p company-dns-server
   ```

   Add `RUST_LOG=info` to see the profile names it loaded (the default level is `warn`; with SQL on
   you always get one warning line saying the endpoint is experimental). A mistake in either file stops
   the server with a message naming the profile and the problem.
4. **Try it** with the token from step 1:

   ```sh
   curl -u my-app:$TOKEN http://localhost:4000/V4.0/na/sic/code/7372                   # a lookup, with the profile's rate limit
   curl -u my-app:$TOKEN -H 'Content-Type: application/json' http://localhost:4000/V4.0/sql \
     -d '{"dataset": "sic", "sql": "select count(*) as n from sic_data"}'              # SQL, if the profile has it
   ```

5. **Deploying**: mount `credentials` from a Kubernetes SealedSecret or a Docker secret, and `rules.json` from
   a ConfigMap or the image's config, one pair per environment, then set the two env vars to the mounted
   paths (see [`docs/plans/v4-deployment.md`](../docs/plans/v4-deployment.md)). To try everything locally with
   throwaway profiles instead, use [`scripts/sql-try.sh`](scripts/sql-try.sh) (below).

No credential is anonymous (the `User-Agent` tiers apply). A **wrong** credential is a `401`,
never silently anonymous, and failed logins are throttled per source IP. `Origin` and `Referer`
are ignored for identity. Whatever a profile ends up with is clamped by the server-wide limits,
so these files can restrict a profile but never exceed what the host allows. Use TLS: the token
travels with every request.

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
| `COMPANY_DNS_CREDENTIALS_FILE` | none, required when enabled | Path to the credentials file ("Profiles" above), plus optionally `COMPANY_DNS_RULES_FILE`. The server refuses to start without a valid credentials file; it never starts open. |
| `COMPANY_DNS_SQL_DEFAULT_ROWS` / `_MAX_ROWS` | 1000 / 10000 | Rows returned by default / the ceiling a request's `limit` is clamped to. |
| `COMPANY_DNS_SQL_TIMEOUT_SECS` | 10 | Statement timeout; the query is cancelled. |
| `COMPANY_DNS_SQL_MEMORY_MB` | 256 | Memory pool per dataset's query context; no spilling to disk. |
| `COMPANY_DNS_SQL_MAX_CONCURRENT` | 4 | Queries running at once on this process; more get a 429, not a queue. |
| `COMPANY_DNS_SQL_PARALLELISM` | 2 | DataFusion partitions per query, so one query cannot take every core. |

These are one global set of limits for every profile (per-profile limits are the
next phase). Invalid values stop startup.

**Credentials.** The route needs a profile with a `sql` setting (see "Profiles" above): no
credential is a `401`, a profile without `sql` or without that dataset is a `403`.
**Two layers of limits.** SQL goes through the same rate limiter as the lookups, so the
`User-Agent` tiers and a profile's `rate_limit` grant apply to it, sharing the same buckets,
**except that a trusted `Origin`/`Referer` is never a bypass here** (client-set headers). On
top of that a profile can carry its own SQL limits in the rules file, each clamped by the
server-wide values above (a mistake in the file can restrict a profile, never exceed what the
host allows):

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

V3-parity: same URL shape with `/V3.0/` changed to `/V4.0/` (`v4-server-prototype.md` §5.2/§5.3/§10).
Every one of them is also served at its original `/V3.0/` path, and those paths answer in **V3's exact
response shape** (a dictionary keyed by code with a `total`, V3's field names, messages and module strings), so an
existing V3 integration keeps working; the `/V4.0/` paths answer with V4's shape (a list of matches, each with its
parents). Both are documented separately in `/docs` (`v4-openapi-docs.md` §8):

```
GET /V4.0/na/sic/{description,code,division,industry,major}/{query}            (+ /V3.0/na/sic/...)
GET /V4.0/{eu,international}/sic/{section,division,group,class,description}/{query}   (+ /V3.0/...)
GET /V4.0/japan/sic/{division,major_group,group,industry_group,description}/{query}   (+ /V3.0/japan/sic/...)
GET /V4.0/na/companies/edgar/{ciks,detail,summary}/{company_name}              (+ /V3.0/na/companies/edgar/...)
GET /V4.0/na/company/edgar/firmographics/{cik_no}                              (+ /V3.0/na/company/edgar/firmographics/...)
```

EU NACE, ISIC and Japan SIC (the 15 per-system lookups) are matched against V3's real responses: 16 of the 19
captured V3 production responses are identical, and the rest differ only in data (V4's Japan and NACE files are the
corrected ones, and the US division narrative `full_description` is V3's text). A no-match is a JSON 404
envelope (V3 answered with an HTML page). Tests: `api_tests/` (`python3 api_tests/run.py`).

**V2.0, the limited legacy set** (V3's shorter paths with no regional prefix), answered exactly as the `/V3.0/` twin of each:

```
GET /V2.0/sic/{description,code,division,industry,major}/{query}
GET /V2.0/companies/edgar/{detail,summary,ciks}/{company_name}
GET /V2.0/company/edgar/firmographics/{cik_no}
GET /V2.0/company/wikipedia/firmographics/{company_name}
GET /V2.0/company/merged/firmographics/{company_name}
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

Real, built 2026-09-28 (§8.1/§8.2: near-exact company/page title, same
as V3; V3's corporate-suffix hint restored and actually executed as a
REST call, not just suggested). Also served at `/V3.0/` and `/V2.0/`, and at the explicit `/V3.0/.../v2/...`
URLs, which V3 documents as the same as the default:

```
GET /V4.0/global/company/wikipedia/firmographics/{company_name}   (+ /V3.0/..., /V2.0/company/wikipedia/..., /V3.0/.../v2/...)
GET /V4.0/global/company/merged/firmographics/{company_name}      (+ /V3.0/..., /V2.0/company/merged/..., /V3.0/.../v2/...)
```

Not carried forward: V3's UK SIC endpoints (`/V3.0/uk/...`) and its legacy wptools-backed `/v1/` Wikipedia and
merged variants (V4's client is a port of V3's `v2` backend specifically; no wptools equivalent exists).

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
