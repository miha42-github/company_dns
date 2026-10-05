# V4 SQL endpoint: accepting SQL over HTTP, and which Rust crate to build on

Status: **Phase 1 built (2026-10-05), under test.** The endpoint, profiles file,
Basic Auth, per-dataset contexts, global limits, tests and a local test script
exist (`v4/crates/server/src/sql_endpoint.rs`, `v4/scripts/sql-try.sh`); phase 2
(per-profile limits and the rest) is not started. Earlier status follows.
**Decided (2026-10-05).** The
section 7 decisions are made (HTTP only, per-dataset, vectors hidden, off by
default behind a config flag, caps configurable). Added the same day:
**credentialed access only, strict for mediumroast.io, and the feature is
declared experimental** (section 5a). Section 5 is rewritten to match.
Owner: michael.hay@mediumroast.io
Scope: add a V4 endpoint that takes a SQL statement as input and returns rows
from the data V4 already holds (the SIC-family feather tables and the EDGAR
catalog). Preference stated up front: **reuse an existing Rust crate rather
than write our own**. This document says what exists, what is actually
reusable, and what is left for us to build whichever way we go.

---

## 1. What V4 has today

- Query engine: **Apache DataFusion 55.1.0** (`v4/Cargo.lock`), already the
  engine behind every V4 query. There is no database server; each catalog is
  an in-process `SessionContext` over `.feather` (Arrow IPC) files.
- Two separate contexts today, one per crate:
  - `SicCatalog` (`crates/sic/src/lib.rs`): tables `sic_data` (US SIC) plus
    one table per extra system registered with `register_system` (Japan SIC,
    NACE Rev. 2, ISIC Rev. 4). Includes the `vector_all_minilm_l6_v2`
    columns, so `array_distance` queries work.
  - `EdgarCatalog` (`crates/edgar/src/catalog.rs`): table `edgar_catalog`.
- Every existing query is built by our code as a string and run with
  `ctx.sql(..)`. User text reaches SQL only through escaping/validation in
  those builders. **No endpoint accepts SQL from a caller.**
- Server: axum 0.8 + utoipa, V3 envelope, tiered rate limiter that sits in
  front of all data routes, request-body limit layer, static UI from disk.
  Data is read-only and replaced wholesale by the quarterly data workflow.

So the engine, the data and the HTTP layer exist. What is missing is a
controlled way to let a caller's SQL reach the engine.

## 2. What "an endpoint that takes SQL" could mean

Three different shapes. They need different crates and I would not conflate
them:

| Shape | Caller | Transport | Typical use |
|---|---|---|---|
| A. **HTTP JSON**: `POST /V4.0/sql` with `{"sql": "..."}`, rows back as JSON (envelope) | curl, notebooks, the web UI, anything | HTTP/JSON | ad-hoc exploration, scripts, the Explorer UI |
| B. **Arrow Flight SQL** (gRPC) | ADBC / JDBC / ODBC Flight drivers, DuckDB/Polars/pandas via ADBC | gRPC, Arrow batches | bulk, typed, fast |
| C. **Postgres wire protocol** | `psql`, DBeaver, Tableau, Metabase, any Postgres driver | TCP :5432 style | BI tools and SQL clients people already own |

A fits "an endpoint" in the sense the rest of V4 uses the word (a route in the
OpenAPI doc, behind the same rate limiter and envelope). B and C are separate
listeners, not routes.

## 3. Candidate crates (researched 2026-10-05)

Versions and dates are from docs.rs / lib.rs on 2026-10-05; I did not build any
of them.

### 3.1 datafusion-postgres (shape C)
- v0.18.0 (released 2026-09-29), Apache-2.0, `datafusion-contrib`, built on
  `pgwire` ^0.40. Serves a `SessionContext` directly: `serve()`,
  `serve_with_handlers()`, and `serve_with_hooks()` with a `QueryHook` trait
  for custom query processing; has pluggable authentication and permission
  control, and a `pg_catalog` companion crate so BI tools can introspect.
- **Version problem: it depends on DataFusion ^54, we are on 55.1.0.** Cargo
  would pull two DataFusion versions and a `SessionContext` from ours cannot be
  passed to theirs (different crate types). We would have to pin V4 back to 54
  or wait for a 55 release. Documentation coverage is about 40%.
- Strong for shape C; irrelevant for A.

### 3.2 arrow-flight with the `flight-sql` feature (shape B)
- Official Apache `arrow-flight` crate. The `flight-sql` feature gives a
  `FlightSqlService` trait to implement; DataFusion ships an example Flight
  server that runs SQL. We would still write the service glue, auth and limits
  ourselves, but it is mostly glue. Brings tonic/gRPC into the build and a
  second port. Third-party wrappers exist (`sagitta`, `rhei-flight`) but are
  small and young; I would not depend on them.
- Version coupling with DataFusion is via arrow versions, so lower risk than
  3.1, but needs checking.

### 3.3 datafusion-dft (shapes A and B, as a product)
- v0.3.0 (2026-02-16), Apache-2.0, on DataFusion 51. Provides an HTTP server
  (REST for SQL and catalog exploration) and a FlightSQL server.
- **Binary only, not an embeddable library**, and four DataFusion versions
  behind. Useful as a reference for how others shape the REST API, not as a
  dependency.

### 3.4 datafusion-server (shape A)
- v0.21.0 (2026-04-04), MIT, DataFusion 53 (flagged obsolete). Session-based
  query server with REST, Python plugin hooks, Flight scaling.
- It is a standalone server with its own session model, data-source
  registration and Python plugins; we would be adopting a second server rather
  than adding a route to ours. Not a fit.

### 3.5 ROAPI (shape A)
- Exposes CSV/JSON/Parquet over REST/SQL using DataFusion and actix. Different
  web stack (we are axum) and standalone. I did not verify its current
  version or DataFusion pin; listed for completeness only.

### 3.6 DataFusion itself
- `SessionContext::sql_with_options(sql, SQLOptions)` with
  `with_allow_ddl(false)`, `with_allow_dml(false)`,
  `with_allow_statements(false)`; `SQLOptions::verify_plan` checks an existing
  logical plan the same way. This is the supported mechanism for read-only
  SQL and is exactly the guard a public endpoint needs. Disallowed statements
  include INSERT/UPDATE/DELETE, CREATE/DROP, COPY, CREATE EXTERNAL TABLE and
  SET. (A known historic concern is that CREATE EXTERNAL TABLE can reach the
  filesystem, which is why it must be off.)
- Runtime limits exist through `RuntimeEnvBuilder` (memory pool, e.g.
  `FairSpillPool`) and `SessionConfig`. I did not confirm the exact 55 builder
  method names; that is a first-day check in the build phase.
- `enable_url_table` is opt-in, so `SELECT * FROM 'file.csv'` is not available
  unless we turn it on. We will not.

## 4. Conclusion on reuse

There is **no crate that gives us shape A as a library**. The two HTTP-SQL
projects are standalone servers on old DataFusion versions. But shape A does
not need one: DataFusion already does the hard parts (parsing, planning,
execution, the read-only guard). What we write is a thin axum handler of
roughly 100 to 200 lines plus safety limits. That is the "use the existing
module" answer for A: **the module is DataFusion's `sql_with_options`; we do
not need another crate.**

For B and C real crates exist and are worth using, but each is its own
listener, its own auth story and its own deployment surface, and C is blocked on
the DataFusion version mismatch today.

## 5. Design (shape A, HTTP/HTTPS only)

`POST /V4.0/sql`, body `{"dataset": "sic" | "edgar", "sql": "SELECT ...", "limit": 1000}`.

1. **Per-dataset, no cross-dataset joins.** `dataset` is required and selects
   one query context:
   - `sic`: the US SIC table plus the other registered systems (Japan SIC,
     NACE, ISIC). They share one context today, so joins across systems
     work inside this dataset.
   - `edgar`: `edgar_catalog`.
   Each dataset gets its **own dedicated read-only query context**, separate
   from the one the existing endpoints use, so exposure rules cannot affect
   them.
2. **Vector columns hidden.** The query contexts register views of the tables
   with every `vector_*` column removed (for example by dropping columns on the
   `DataFrame` before `into_view`; the exact call is a build-time check). The
   existing contexts keep the vectors for the similarity endpoints. A
   consequence: SQL callers cannot run `array_distance`; semantic search stays
   on the dedicated endpoints.
3. **Read-only guard**: `sql_with_options` with DDL, DML and statements all
   off, one statement per request (reject `;`-separated batches). URL/file
   tables stay disabled (`enable_url_table` is never called).
4. **Off by default behind a config flag.** `COMPANY_DNS_SQL_ENABLED`
   (default `false`). When off, the route is not registered, so it returns
   404 and does not appear in the OpenAPI document; when on, startup logs the
   effective limits. Matches how the other settings are read
   (`COMPANY_DNS_DATA_DIR` etc.).
5. **Configurable limits**, defaults as agreed, env var names proposed:
   | Setting | Env var | Default |
   |---|---|---|
   | Default rows returned | `COMPANY_DNS_SQL_DEFAULT_ROWS` | 1,000 |
   | Hard row ceiling (per-request `limit` is clamped to it) | `COMPANY_DNS_SQL_MAX_ROWS` | 10,000 |
   | Statement timeout | `COMPANY_DNS_SQL_TIMEOUT_SECS` | 10 |
   | Query memory pool | `COMPANY_DNS_SQL_MEMORY_MB` | 256 |
   | Concurrent SQL requests | `COMPANY_DNS_SQL_MAX_CONCURRENT` | 4 (my addition; say if unwanted) |
   These are the server-wide defaults and ceilings (section 5a); a profile may
   be given lower values, or higher up to the ceilings. Invalid values fail
   startup with a clear message rather than silently falling back. Row cap is enforced server-side (stop reading the stream at
   the cap) and truncation is reported as a limitation entry, as the match
   endpoint does. Timeout wraps collection with `tokio::time::timeout`. The
   memory pool is set on the query context's runtime. Max SQL text length
   comes from the existing request-body limit layer.
6. **Rate limiting**: SQL does **not** use the tiered limiter's bypasses and
   has its own, stricter, per-profile limits. See section 5a.
7. **Response**: V3 envelope with `columns` (name and Arrow type), `rows`,
   `row_count`, `truncated`, and a limitation naming the DataFusion SQL
   dialect/version.
8. **Tests**: guard tests (INSERT, CREATE, COPY, SET, multi-statement,
   `SELECT * FROM 'file'` all rejected); vector columns absent from both
   datasets; row cap and clamp; timeout; flag off gives 404; env parsing
   (defaults, overrides, invalid).
9. **UI**: none. Curl and the Swagger/Redoc pages are enough.

## 5a. Access control, limits, and experimental status

Principle: this endpoint can consume real CPU and memory, so unlike the
lookup routes it is **closed by default and credential-only**. Nobody gets in
because of who they appear to be; they get in because they hold a credential
the operator issued.

### It is the existing secret mechanism, generalised (correction)

An earlier draft of this section read as if it introduced a new secret
store. It does not. V4 already has the pattern: a runtime secret
(`MEDIUMROAST_SHARED_SECRET`) sourced from each environment's own sealed K8s
Secret, never baked into the image, never in the repo, distinct per tier
(`v4-deployment.md` sections 2 and 3.4; `v4-security-hardening.md` 3.5).
What is new is that more than one party needs credentials, each with its own
limits and permissions. Decided 2026-10-05: **this is a general access
mechanism for V4, not an SQL-specific one.** SQL is its first new consumer;
mediumroast.io's existing rate-limit trust is expressed in the same mechanism.

| Today | General mechanism |
|---|---|
| one secret, one identity (mediumroast.io), trust = skip the limiter | **one file** with a section per profile: secret plus what that profile may do |
| env var from a sealed K8s Secret | the same secret store, delivered as a mounted file; any secret env var may also be given as `<NAME>_FILE` |
| a bypass only | per-feature grants: rate-limit treatment, SQL access, and whatever comes later |

mediumroast.io is one profile. Open-source users define their own.

### What the existing gates do and why SQL cannot reuse them

The data routes are gated by a self-identifying `User-Agent`, a tiered per-IP
limiter, and two bypasses that skip the limiter (`rate_limit.rs`,
`trusted_origin.rs`, `secret_ua.rs`):
- **Trusted `Origin`/`Referer`** (`localhost`, `*.mediumroast.io`). The client
  sets these headers; `curl -H "Origin: https://mediumroast.io"` is accepted
  as readily as a browser. Fine for skipping a limit on cheap lookups, **not
  acceptable as proof of identity for SQL**. (Worth a note in
  `v4-security-hardening.md` 3.4: today it means any caller willing to send
  that header is unlimited on every data route.)
- **Rolling HMAC `User-Agent`**. A real credential, but being replaced by the
  profiles mechanism below (nothing is implemented against it on the
  mediumroast.io side yet).

For SQL: Origin/Referer are ignored entirely, and the route sits behind its
own gate, not the tiered limiter's bypasses.

### The profiles file (one file, a section per profile)

- **Where it lives**: one file, path in `COMPANY_DNS_PROFILES_FILE`, one per
  tier. It holds only token hashes, but it also carries each profile's grants
  and limits, so it is still delivered as a secret and never committed:
  - Kubernetes: a SealedSecret (controller already installed) mounted as a
    file, one per tier, so staging and dev never hold prod's.
  - Plain Docker / Compose / Swarm: a Docker secret (a file under
    `/run/secrets/`).
  - Local development: a gitignored file (pattern added to `.gitignore`).
  - Never in the image, never in the repo. The repo ships only
    `profiles.example.json` with obviously fake hashes.
- **One section per profile.** A profile has an `id`, a `secret_sha256`, and optional
  per-feature grants. Features not mentioned are not granted:
  ```json
  {"profiles": {
    "mediumroast.io": {
      "secret_sha256": "<hash of the token given to mediumroast.io>",
      "rate_limit": {"bypass": true},
      "sql": {"datasets": ["sic", "edgar"],
              "limits": {"max_rows": 500, "timeout_secs": 5, "concurrency": 2, "requests_per_minute": 30}}},
    "partner-example": {
      "secret_sha256": "<...>",
      "sql": {"datasets": ["sic"]}}
  }}
  ```
  (Fake values, shape only. Real numbers are the operator's to set in the sealed
  file.)
- **Authentication: HTTP Basic Auth (decided 2026-10-05), general rather than
  SQL-specific.** `Authorization: Basic base64(<profile id>:<token>)`. The
  username is the profile id; the password is a high-entropy generated token
  (never a human password). The file stores only a **SHA-256 hash** of each
  token (`secret_sha256`), compared in constant time, so a leaked or dumped
  file does not hand out working credentials. A fast hash is right for random
  256-bit tokens; a slow password hash would add cost for no benefit. Operators
  generate a token and its hash with standard tools (for example `openssl rand
  -hex 32` and `shasum -a 256`), documented in the README; the token is given
  to the client once and never stored in plain text on the server.
  - Works with `curl -u id:token`, every HTTP client library and Swagger UI's
    "Authorize" button; the OpenAPI document declares it as an HTTP Basic
    security scheme.
  - It authenticates a *profile*; each feature then asks what that profile is
    granted. No header: the request is anonymous (lookups behave as today). A
    present but wrong credential: `401` with `WWW-Authenticate: Basic`,
    never silently treated as anonymous. SQL from an anonymous caller: `401`;
    a profile without SQL: `403`; dataset not granted: `403`; a limit hit:
    `429` with `Retry-After`.
  - **Costs, stated openly:** the token travels with every request, so TLS is
    required (enforced at the ingress; the hop inside the cluster is plain HTTP
    as it is today), and a captured token stays valid until rotated rather than
    expiring in hours. Failed attempts are throttled per source IP, so guessing
    is not practical, and the audit log records them.
  - Not chosen: a rolling hourly HMAC (needs custom client code, needs the raw
    secret on the server, and mainly mattered when the value sat in
    `User-Agent`), and HTTP Digest (same raw-secret problem, weak tooling).
- **No legacy path.** mediumroast.io has nothing implemented against the old
  hourly-HMAC `User-Agent` mechanism, so this replaces it outright: no
  compatibility mode, `secret_ua.rs` is removed when the profiles module is
  built, and `MEDIUMROAST_SHARED_SECRET` goes away in favour of the
  `mediumroast.io` profile. There is one credential mechanism.
- **Fails closed**: flag on for a feature that needs profiles (SQL) but the
  file is missing, empty or malformed means startup fails with a clear
  message. It never starts open.
- **Rotation and reload**: change the sealed secret and roll the pods. The file
  is read at startup only; there is no reload without a restart (decided).

### Two sets of limits

1. **Server-wide limits: protect the pod and the cluster.** Not secret, so
   they live in the environment's ConfigMap/env, one value per tier:
   total concurrent SQL queries per pod, total query memory pool per pod, a
   total SQL request budget, and the ceilings for rows and timeout. They are
   sized against the real pod: prod is 4 replicas, requests 256Mi / 100m, limits
   1Gi / 500m (`k8s/prod/deployment.yaml`), shared with every other route. So:
   - the query context's DataFusion parallelism is capped well below the CPU
     limit so one query cannot starve lookups on the same pod;
   - the memory pool plus the resident data and baseline must fit under the
     1Gi limit with headroom (the earlier 256 MB default is a starting point,
     not a promise; staging's capacity check decides);
   - request budgets are **per pod = aggregate divided by replicas**, the same
     convention as `rate_limit.rs` (`per_pod`, `REPLICA_COUNT`), including its
     known drift if the replica count changes without updating the constant.
2. **Per-profile limits: defaults plus per-profile override.** Defaults come
   from configuration; each profile's `sql.limits` may override: rows, timeout,
   concurrency, requests per minute, memory share. **A profile override is always
   clamped by the server-wide limits**, so a mistake in the profiles file can
   restrict a profile but can never exceed what the hosting system can take.

Enforcement order per request: authenticate the profile, check it is granted SQL and
the dataset, check its rate and concurrency, check the server-wide budget, then
run with the smaller of the profile and server-wide caps.

### Audit trail

One structured log line per request: profile id, dataset, hash and length of the
SQL (text only at debug), rows, duration, outcome. Failed authentication is
logged with source IP and counted. Secrets and tokens are never logged.

### Experimental declaration

- `v4/README.md` and this plan carry an **Experimental** notice: the SQL
  endpoint may change or be removed without a deprecation period; the dialect
  is whatever DataFusion version V4 uses; it is off by default; the security and
  resource assumptions here are the contract, not a compatibility promise.
- OpenAPI: operation tagged `experimental`, summary starting "Experimental:",
  description repeating the notice and the access rules.
- Every response carries a limitation entry `{"code": "experimental", ...}`.
- Startup log when enabled: "SQL endpoint is EXPERIMENTAL", the profile ids
  loaded (never secrets) and the effective server-wide limits.
- Outside `V4.0.0`'s stability promise until it has run in production for a
  period to be defined with the roadmap.

## 5b. Where the other plans change (the general solution)

- **`v4-deployment.md`**: section 2 (runtime secrets: one profiles file, may be
  mounted; Docker secrets named as the equivalent of the sealed K8s Secret;
  `<NAME>_FILE` convention); section 3.4 (per-tier profiles file and per-tier
  server-wide limits in the ConfigMap; staging capacity test); Step G;
  open questions. **Updated.**
- **`v4-security-hardening.md`**: 3.5 and 3.4 notes; the profiles mechanism
  replaces 3.5: HTTP Basic Auth against hashed profile tokens becomes the single
  credential mechanism, with no legacy User-Agent path. **Updated.**
- **Code, when built (not now)**: a small `access` module that loads the
  profiles file and answers "who is this request, and what are they granted";
  the tiered limiter and the SQL handler both ask it, replacing
  `secret_ua.rs`'s single-secret check. The origin-based trust in
  `trusted_origin.rs` stays for browser-driven lookups for now (browsers cannot
  hold a secret); tightening it is the hardening doc's open question.

## 5c. The capacity test that sets the server-wide limits

Yes, this is a test, not a guess. The limits protect the pod, so they should
come from measuring a real pod. On staging (2 replicas, same image):
1. Baseline: memory and latency of normal lookups with no SQL.
2. Run deliberately heavy SQL (large scans, sorts and self-joins on the EDGAR
   catalog, many concurrent queries) while a steady lookup load runs.
3. Raise concurrency, the memory pool and the parallelism cap until lookups
   degrade or memory approaches the pod limit; back off, and record the
   largest settings that keep lookup latency within an agreed margin of
   baseline.
4. Set the server-wide limits at a safe fraction of that, per tier; prod gets
   the same method on its own sizing (4 replicas).
**Pass criteria (decided 2026-10-05).** Measured on staging with the SQL
limits at their intended values, under steady lookup load plus the heaviest SQL
the limits allow:
1. Lookup p95 is no more than 25% above the no-SQL baseline, and p99 no more
   than 50% above.
2. Zero 5xx responses and zero timeouts on lookups during the run.
3. Peak pod memory stays under about 70% of the pod limit (1Gi in prod), with
   no out-of-memory kills or restarts.
4. SQL cannot hold the pod above its CPU limit long enough to throttle lookups
   (in practice covered by criterion 1).
5. A query that exceeds the row cap, timeout or memory pool fails cleanly with
   the intended error; it does not crash the pod or hang.
6. A soak of about 30 minutes shows no slow memory growth, and memory returns
   to baseline after the SQL load stops.
If any criterion fails, lower the server-wide limits (concurrency, memory pool,
parallelism cap) and repeat. The settings that pass become the staging values;
prod uses the same method on its 4-replica sizing.

## 6. Risks and open concerns

- **Credential handling is now part of the risk.** A leaked profile token is a
  resource-abuse vector (the file itself holds only hashes); the per-profile caps and the audit log bound and reveal
  it, and the secret lives in the operator's secret store, not in the repo.
- **Security surface is new.** V4 so far only runs SQL we construct. This is the
  first place a caller writes SQL; the allow-list approach (DataFusion's
  `SQLOptions`) is sound but we should add the tests above and review
  `v4-security-hardening.md` against it before enabling in production.
- **Cost-based abuse**: the SIC tables are small, but the EDGAR catalog is
  large; scans, sorts and self-joins there are the real cost. The timeout and
  memory cap are the protection, not the row cap. Hiding the vectors also
  removes the heaviest function (`array_distance`).
- **Data licensing**: raw SQL makes the full tables, including the labels and
  hierarchies of every classification system, trivially bulk-exportable. This
  is the same concern as the crosswalk licensing issue; confirm each source's
  terms allow redistribution of its full table before exposing it. At minimum
  the endpoint should stay behind the tiered limiter and the identifying
  User-Agent rule.
- **DataFusion upgrade coupling**: whichever SQL dialect we expose becomes an
  API surface; DataFusion changes functions between majors. Document it as
  "DataFusion SQL, version N" in the OpenAPI description and in the response.
- **Staleness**: crates above move fast (datafusion-postgres shipped a release
  a week ago); recheck versions when we start.

## 7. Decisions (2026-10-05)

1. Shape: HTTP/HTTPS only. No Flight SQL, no Postgres protocol for now.
2. Tables: per dataset (`sic`, `edgar`), no combined context.
3. Vector columns: hidden from SQL.
4. Access: off by default behind a config flag.
5. Caps: 1,000 default / 10,000 max rows, 10 s, 256 MB, all configurable.

6. Access (2026-10-05): credential-only; one general profiles file (a section
   per profile) delivered like the existing secret (sealed K8s Secret, Docker
   secret, or gitignored local file); mediumroast.io is one profile with strict
   limits set by the operator; open-source users create their own;
   experimental in all documentation (section 5a).
7. Limits (2026-10-05): two sets, **server-wide** (pod/cluster protection, per
   tier, split per replica) and **per-profile** (defaults plus overrides, always
   clamped by the server-wide set).
8. Credential (2026-10-05): **HTTP Basic Auth** (profile id and a generated
   token; only the token's SHA-256 is stored). Rolling HMAC and Digest were
   considered and not chosen.
9. General solution (2026-10-05): the `<NAME>_FILE` convention applies to any
   secret env var, one profiles file serves every feature, and mediumroast.io's
   rate-limit trust becomes a profile grant. No legacy `User-Agent` path,
   because nothing depends on it yet.

10. Concurrency cap (2026-10-05): kept; tried out in testing with
    mediumroast.io.
11. Reload (2026-10-05): profiles are read at startup only; changing them means
    a restart (rolling the pods). Simplicity, as this is an open-source example.
12. Capacity test pass criteria (2026-10-05): as listed in section 5c.

Still open: only the real server-wide limit values, which come from running the
capacity test on staging (section 5c).

## 8. Phases

Decided 2026-10-05: **the endpoint first, per-profile limits afterwards.**

**Phase 1: the SQL endpoint, with one global set of limits.**
- Off by default behind `COMPANY_DNS_SQL_ENABLED`; experimental labelling
  (section 5a) from day one.
- Profiles file (`COMPANY_DNS_PROFILES_FILE`) in its smallest form: a profile
  id, a `secret_sha256`, and the datasets it may query. HTTP Basic Auth,
  constant-time hash compare, failed-attempt throttling, audit log line. Flag on
  with no valid file fails startup. This is the minimum that keeps the endpoint
  closed; there is no anonymous SQL, even in phase 1.
- Per-dataset query contexts (`sic`, `edgar`) without vector columns,
  read-only guard (`sql_with_options`), one statement per request.
- **One global set of limits** (rows default and ceiling, timeout, memory pool,
  concurrency, parallelism cap) from env vars, applying to every profile. No
  per-profile numbers yet.
- Tests: guard (INSERT, CREATE, COPY, SET, multi-statement, file/URL tables all
  rejected), vectors absent, row cap and clamp, timeout, flag off gives 404,
  auth (missing, wrong, wrong dataset, forged `Origin` is accepted for
  nothing), env parsing; OpenAPI entry; README with the experimental notice and
  how to create a profile.
- Measure the extra memory of the two query contexts.

**Phase 2: profiles and limits (discussed after phase 1 exists).**
- Per-profile limit overrides, clamped by the global set (the two-set design in
  section 5a), and the `rate_limit` grant so mediumroast.io's trust moves into
  the profiles file (replacing `secret_ua.rs`).
- `<NAME>_FILE` convention for secret env vars.
- Deployment wiring (`v4-deployment.md` Step G): per-tier sealed profiles file
  and ConfigMap limits.
- The staging capacity test (section 5c) that sets the real global values.
- Hardening review and licensing check; the Origin finding in
  `v4-security-hardening.md`; define what "experimental" must prove before it
  is promoted. Default stays off.

**Not planned:** Flight SQL (3.2) and Postgres wire (3.1), kept for reference
if bulk or BI-tool users appear.

## 9. Sources

- [datafusion-postgres on docs.rs](https://docs.rs/datafusion-postgres)
- [datafusion-dft on lib.rs](https://lib.rs/crates/datafusion-dft)
- [datafusion-server on lib.rs](https://www.lib.rs/crates/datafusion-server)
- [DataFusion `SQLOptions`](https://docs.rs/datafusion/latest/datafusion/execution/context/struct.SQLOptions.html)
- [arrow-flight crate](https://docs.rs/crate/arrow-flight/59.3.0)
- [pgwire](https://docs.rs/crate/pgwire/latest)
- [DataFusion runtime configs](https://datafusion.apache.org/user-guide/runtime_configs.html)
- [DataFusion issue on read-only SQL and CREATE EXTERNAL TABLE](https://github.com/apache/datafusion/issues/1281)
