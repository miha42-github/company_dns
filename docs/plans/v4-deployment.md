# V4 deployment: image, secrets, environments, and the on-prem cluster

Status: **Planned (2026-09-30); sequencing and data decisions added
(2026-10-04).** Consolidates and supersedes
`v4-container-packaging.md` and the forward-looking parts of
`onprem-k8s-migration.md` (that doc's own Azure→K8s migration history
for V3 stays in place, unchanged — see §0). Grounded in real
measurements (binary size, data size) and a real, audited live-cluster
survey, not assumed capacity or a clean-slate design.
Owner: michael.hay@mediumroast.io
Scope: everything about getting a V4 change from source to a running,
correctly-sized, correctly-secured, environment-appropriate deployment
on the existing on-prem `microk8s` cluster — the container image
itself (size, secrets, data bundling), and the dev → staging → prod
environment pipeline that verifies a build before it reaches
production, including the specific platform-parity gap that motivated
adding real environments in the first place.

---

## 0. Why this doc, and why it supersedes two others

Three pieces of related work happened separately in this session and
are being merged here, on request, into one canonical source:

1. **Container packaging** — raised while designing
   `v4-security-hardening.md` §3.5's rolling shared secret: *"we can
   look at something like docker secrets to keep the secret sealed...
   the rust binary appears to be almost 200MB in size... we should
   consider how we bundle in the feather files."* Audited into two
   independent problems (§1.1/§1.2), a secret-injection design that
   deliberately does *not* do what was initially suggested (§2), and a
   binary-size reduction plan (§3.3).
2. **Deployment environments** — raised immediately after
   `v4-dynamic-log-level.md`'s spike flagged an open gap: its reload
   design was proven on macOS, not on the real Linux/`microk8s` target,
   and *"this is a point we need to add to the deployment plan as a
   deliberate step for verification... flesh out the dev → staging →
   prod deployment methodology... add tests that account for that...
   an intermediate step will be to simply run the image in plain docker
   on Ubuntu which suggests our image builds must be multiplatform."*
3. **A process correction**: a first pass at item 2 was written as a
   *third* new doc (`v4-deployment-environments.md`) without checking
   whether it belonged in one of the two existing related docs instead.
   Caught directly — *"Wait don't we already have a plan for
   build/deployment?"* — and the explicit resolution: consume both
   existing docs plus the new content into **one** file, and mark the
   originals as superseded rather than deleting them.

**What "superseded" means here, precisely**: `v4-container-packaging.md`
is fully absorbed — nothing forward-looking is left there that isn't
also here. `onprem-k8s-migration.md` is *partially* absorbed — its
reusable facts (live cluster survey: nodes, namespaces, ingress, TLS,
storage, SealedSecrets — §1.3 below) and its proven manifest pattern
(§3.8) are carried forward here, but its actual migration narrative
(the Azure Container App decommissioning: DNS cutover steps, the two
real bugs hit during that migration, the teardown plan, the rollback
plan) is V3-specific history that already concluded — *"Migration
complete"* — and stays exactly where it is, untouched, as the
historical record of how that migration actually happened. Nothing in
this doc asks anyone to go re-read that narrative to understand V4's
deployment; both older docs get a status-line pointer here instead.

## 0.1 Where this is in the sequence (decided 2026-10-04)

The goal before any deployment is to get the major functions operable. The
order of work:

1. **Make the major functions operable** — in progress. The data side was
   settled on 2026-10-04 (§3.2): one data-directory variable, a rebuilt EDGAR
   catalog, the SIC files staged by hand.
2. **Thin the binary** (§3.3, spike §4.1–4.3).
3. **Package — phase 1: a single Docker image, delivered multi-platform**
   (`linux/amd64` and `linux/arm64`), run first with plain `docker run`
   (§3.5 step 2).
4. **Phase 2: stage it at `staging-company-dns.mediumroast.io`** on the
   `microk8s` cluster, to check stability and functionality *before* anything
   is promoted to production (§3.4–3.6).

Running alongside all of it: a **robust API test suite**, built by extending
the existing Python performance suite (`perf_tests/`, §3.9). It is the check
that runs against the image in phase 1 and at the staging gate in phase 2.

The dev tier (`company-dns-dev`, §3.4) is **not part of phases 1–2**. It stays
in the design as written and is scheduled only if it is wanted later.

## 1. Current state (audited)

### 1.1 Binary size — measured, not assumed

- `v4/target/release/company-dns-server`: **172MB unstripped, 128MB
  stripped** (measured directly: `strip` on a copy of the release
  binary, macOS arm64 build). ~44MB (26%) is symbol table; the
  remaining ~128MB is linked code and data.
- `v4/Cargo.toml` has **no `[profile.release]` section at all** —
  every release build uses Cargo's plain defaults (`opt-level = 3`,
  `lto = false`, `codegen-units = 16`, `panic = "unwind"`,
  `strip = "none"`). None of the standard binary-size levers are on
  yet.
- DataFusion 55.1.0's **default features pull in the entire SQL engine
  surface** (confirmed via crates.io's published feature list):
  `parquet`, avro-adjacent datasource support, compression codecs
  (`bzip2`/`flate2`/`zstd`/`liblzma`), the full expression-function
  libraries (`crypto_expressions`, `datetime_expressions`,
  `encoding_expressions`, `regex_expressions`, `string_expressions`,
  `unicode_expressions`), `nested_expressions`, and the full SQL
  frontend (`sql` + `sqlparser`). `v4/Cargo.toml`'s `datafusion = "55"`
  line doesn't customize this at all.
- Confirmed via grep against `crates/sic/src/{lib,lookup,similarity}.rs`:
  this project genuinely needs `sql` (`ctx.sql(&sql_string)` used
  throughout, `lookup.rs:91,115,140,157`, `similarity.rs:61`), but
  shows **no use of DataFusion's `parquet` API anywhere** — the SIC
  data source is `.feather` (Arrow IPC), loaded via `register_table`/
  `file_extension: ".feather"` (`crates/sic/src/lib.rs:29-33`).
- **Checked and resolved**: `edgarkit` (external dependency, sharing
  this same DataFusion instance per `go-duckdb-rewrite.md`/
  `edgar-backend.md`'s decision) has **zero dependency on DataFusion or
  Arrow at all** — confirmed by reading its published `Cargo.toml`
  directly. Trimming DataFusion's default features is entirely within
  company_dns's own control, not something edgarkit could re-widen via
  Cargo's feature unification.

### 1.2 Feather/data-file size — measured, and small

- Data in the repo-root `tmp/` as of 2026-10-04: four SIC systems
  (`us_flat_embedded` 1.5MB, `japan_rev13_flat_embedded` 2.2MB,
  `nace_rev2_flat_embedded` 0.9MB, `isic_rev4_flat_embedded` 0.6MB — 5.2MB
  together) plus the EDGAR 10-x catalog (**11.6MB**: 72,813 filings across 8
  quarters, including a URL column). **About 17MB in total** — roughly an
  eighth of the 128MB stripped binary. (The first version of this section
  measured ~4.4MB at dev scale, before Japan, NACE, ISIC and the two-year
  EDGAR window existed.) Bundling the data into the image still barely moves
  image size — binary size and data bundling remain two independent
  problems, not one, despite how the original request was framed. At this
  size §3.2's decision does not turn on bytes.

### 1.3 The live on-prem cluster (from `onprem-k8s-migration.md`'s survey, carried forward)

Run 2026-09-25/26 against the live cluster, re-confirmed live during
the rate-limiting incident investigation (`kubectl get pods -o wide`
showing the real node names below):

- **Nodes**: two worker nodes actually schedule pods — `host-1`/
  `host-2` in the migration doc's own text (the *real* live cluster
  names, confirmed since: `cafe-1`, `espresso-1`). A third node
  (`cortado-1`) is control-plane-only, ARM/Jetson hardware, and does
  **not** schedule application workloads. **This is a hard, small
  capacity constraint** — prod already reserves 4 replicas at
  100m–500m CPU / 256Mi–1Gi memory each (`k8s/prod/deployment.yaml`)
  across those same two nodes; anything new has to fit alongside that,
  not on separate hardware (§3.4).
- **Namespaces**: `mediumroast-web`, `mediumroast-staging`,
  `mediumroast-dev`, `vault-prod`, `vault-staging` already exist on
  this cluster — a real, live three-tier pattern for a sibling app,
  proving dev/staging/prod tiering already works here operationally.
  `cert-manager`, `cnpg-system`, `ingress`, `metallb-system`,
  `observability` (Prometheus/Grafana/Loki/Tempo) are also present;
  company_dns pods show up in `observability` automatically via
  node-exporter/kube-state-metrics, no extra work needed.
- **Ingress**: one Traefik `LoadBalancer` (`ingress` namespace,
  external IP `192.168.1.200`, ports `80`/`443`) serves every app on
  the cluster via per-namespace `Ingress`/`Middleware` resources,
  `ingressClassName: traefik` (three IngressClass names exist —
  `nginx`/`public`/`traefik` — but all point at the same controller;
  `traefik` is the one the live, working `mediumroast-website` Ingress
  actually uses, confirmed from its live YAML, and what `k8s/prod/`
  already uses too). Adding new hostnames for staging/dev needs no new
  ingress infrastructure — just new `Ingress`/`Middleware` resources
  per namespace (Traefik Middleware references are namespace-prefixed:
  `<namespace>-<name>@kubernetescrd`, confirmed from the live
  `mediumroast-web-redirect-https@kubernetescrd` reference — each new
  namespace needs its own `Middleware` copy, same reason
  `k8s/prod/middleware-redirect.yaml` exists).
- **TLS**: `letsencrypt-prod` `ClusterIssuer` exists and is `Ready`,
  proven working end-to-end today (`mediumroast-io-tls` Certificate is
  `Ready`) — reused as-is for any new hostname, no new issuer needed.
- **Storage**: `microk8s-hostpath` and two `nfs-nas*` storage classes
  exist (used by `vault-prod`'s Postgres/backups) — available if
  §3.2's data-bundling design ends up needing a real volume.
- **SealedSecrets**: controller (`sealedsecrets.bitnami.com` CRD)
  already running cluster-wide. Not used by V3 (its GHCR image is
  public, nothing to seal) — V4 changes that: `MEDIUMROAST_SHARED_SECRET`
  (`v4-security-hardening.md` §3.5) needs exactly this, and per-
  environment secret hygiene (§3.4 below) is now a real design point,
  not hypothetical.

### 1.4 Existing container/CI state

- `Dockerfile` (repo root) is V3's — `python:3.13-alpine`, unrelated to
  V4's Rust binary beyond being what V4 eventually replaces.
- `.github/workflows/main.yml`: V3's monthly scheduled build,
  `docker/build-push-action@v4` → GHCR, multi-platform
  (`linux/amd64,linux/arm64` via `docker/setup-buildx-action@v2`), GHA
  layer caching. No application secret used today, only
  `secrets.GITHUB_TOKEN` for registry auth — a real, already-working
  template for §3.1's build-secret approach, just not demonstrated with
  an application secret yet.
- No Rust Dockerfile exists anywhere in the repo yet.
- **V4 has no CI/CD, no built image, and no deployment path at all
  today** — confirmed by grep; `v4/README.md`'s only documented way to
  run it is `cargo run --release` by hand, on whatever machine a
  developer happens to be using.

### 1.5 The concrete gap that motivated adding real environments

`experiments/dynamic-log-level-spike/` proved its ConfigMap-mount
reload design (`notify` watching the parent directory, plus a polling
fallback) live — **on macOS**. The real target is amd64 Ubuntu 24.04
under `microk8s` (a different filesystem-event backend: inotify, not
FSEvents, with its own different edge cases around renames). Nothing
about that design is *assumed* broken on Linux — the parent-directory
watch technique is a generally-correct pattern chosen specifically to
sidestep most inotify rename gotchas too — but "sound design, proven on
a different platform" and "confirmed working on the actual target" are
different claims, and this doc exists so the second one always gets
checked before something like it reaches production, not just this one
case.

## 2. The secret-injection mismatch worth flagging

Two genuinely different things both get called "secret" across the
requests that opened the container-packaging half of this doc, and
treating them as one would undo a decision `v4-security-hardening.md`
§3.5 already made deliberately.

**Build-time secrets** (BuildKit `--secret` / "Docker secrets" in the
sense originally raised; `docker/build-push-action`'s `secrets:`
input): mounted into the build container's ephemeral filesystem only
for the `RUN` step that needs them, and — the actual property that
makes them worth using — **never written into any image layer or the
image's layer history**. Right tool for a secret genuinely needed only
*during* `docker build` — e.g. a private crate-registry auth token, or
credentials to fetch SIC feather data from an internal source as part
of the build if §3.2 lands on that option.

**Runtime secrets** — specifically `MEDIUMROAST_SHARED_SECRET`, which
`v4-security-hardening.md` §3.5 already designed: the *running server
process* reads it at startup and recomputes an hourly rolling HMAC
against it on every incoming request. Not a build-time need.
**Baking it into the image via a build-time secret mechanism would be
a regression from what §3.5 already decided**: (1) rotation would need
a rebuild+redeploy instead of just updating a K8s Secret and rolling
pods; (2) a built image is pulled by more environments and cached more
widely than a deploy-time secret store, so baking a secret into every
image pull widens exposure; (3) it conflates the build artifact
(should be identical across dev/staging/prod — §3.4) with
environment-specific config (the secret differs per environment) — the
same reasoning that already keeps `SIC_DATA_PATH`/`EDGAR_CATALOG_PATH`/
`PORT` as runtime env vars rather than baked in.

**Recommendation, unchanged**: keep `MEDIUMROAST_SHARED_SECRET` a
runtime env var sourced from each environment's own K8s Secret
(distinct per tier — §3.4), never touched by the image build. Reserve
BuildKit `--secret` for a genuine build-time need, if one turns out to
exist once §3.2 is decided.

**Addendum (2026-10-05, SQL endpoint, `v4-sql-endpoint.md` 5a/5b):** runtime
secrets are no longer a single value. The experimental SQL endpoint needs
several credentialed parties, so the single secret becomes **one profiles
files**: credentials (`COMPANY_DNS_CREDENTIALS_FILE`, `profile:sha256` lines like
`/etc/passwd`, the only secret) and optional rules (`COMPANY_DNS_RULES_FILE`, JSON, no
secrets: defaults plus per-profile overrides) for profiles (mediumroast.io,
partners, an open-source operator's own), each with a token hash and per-feature
grants (rate-limit treatment, SQL access and limits). It is a general
mechanism for V4, not an SQL-only one. It follows the same rule as above: a runtime
secret, never baked into the image, never in the repo, one per tier. It is
delivered as a **mounted file**, which fits a SealedSecret mounted as a volume
on the cluster and a Docker secret (`/run/secrets/...`) for plain-Docker runs,
and a gitignored file for local development. (A general `<NAME>_FILE`
convention for secret env vars was considered and dropped 2026-10-06: the only secret
is the credentials file, which is already a mounted file, and no secret env var remains.)
The credentials file holds token hashes, clients authenticate with HTTP Basic
Auth (`v4-sql-endpoint.md` 5a), and the old `MEDIUMROAST_SHARED_SECRET` is
**removed from the code (2026-10-05)**, replaced by the `mediumroast.io`
profile in phase 2 (nothing depended on it). The remaining mentions of that
secret in this document (§1.3, the §2 recommendation, §3.4, step 8) describe the
earlier design and are superseded: provision the credentials file (and the rules ConfigMap) instead.

## 3. Design

### 3.1 Build-time secrets, for whichever actual build-time need exists

Pattern, following the existing workflow's own shape
(`.github/workflows/main.yml:29-37`):

```yaml
- name: Build and push
  uses: docker/build-push-action@v4
  with:
    context: .
    push: true
    secrets: |
      SOME_BUILD_SECRET=${{ secrets.SOME_BUILD_SECRET }}
```

```dockerfile
RUN --mount=type=secret,id=SOME_BUILD_SECRET \
    SOME_BUILD_SECRET=$(cat /run/secrets/SOME_BUILD_SECRET) cargo build ...
```

No concrete build-time secret is identified yet — documented and ready
for whenever §3.2 lands on an option that needs one.

### 3.2 Data files: how they reach a running container — decided (2026-10-04)

**What the data is, and where each file comes from:**

| File (standard name in the data directory) | Produced by | Size |
|---|---|---|
| `us_flat_embedded.feather`, `japan_rev13_flat_embedded.feather`, `nace_rev2_flat_embedded.feather`, `isic_rev4_flat_embedded.feather` | Mediumroast's embedding export pipelines, **outside this repo**. Checked here with `docs/plans/research/check_ic_feather.py`. | 5.2MB together |
| `edgar_10x_catalog.feather` | `ingest-edgar`, **in this repo** (`v4/crates/edgar/src/bin/ingest_edgar.rs`), from the SEC's quarterly filing indexes | 11.6MB |

**Decisions:**

1. **One environment variable, `COMPANY_DNS_DATA_DIR`, names the directory
   holding every data file.** For now, in development, point it at the repo's
   top-level `tmp/`. A per-file variable (`SIC_DATA_PATH`,
   `JAPAN_SIC_DATA_PATH`, `EU_NACE_DATA_PATH`, `ISIC_DATA_PATH`,
   `EDGAR_CATALOG_PATH`) still overrides its one file. With neither set, the
   default is the repo-root `tmp/` found from the source tree at build time,
   so it no longer depends on the directory the server was started from (the
   old default was `../../tmp/...` relative to the working directory, and
   resolved to the wrong place from anywhere else — that is exactly how an
   EDGAR catalog went missing during testing). Implemented in
   `crates/edgar/src/data_dir.rs`, shared by the server and the ingest tool.
   **In the image:** the files are copied into the image's data directory
   (the Dockerfile sets `COMPANY_DNS_DATA_DIR`), so the image is
   self-contained and the plain-Docker smoke test (§3.5 step 2) can exercise
   real searches. A volume mounted at that same path replaces them without a
   rebuild.
2. **`ingest-edgar` takes years and quarters, defaulting to two years of
   quarters back from today. Built and run (2026-10-04).** With no arguments it
   pulls the **8 most recent completed quarters** (today is in 2026Q4, so
   2024Q4–2026Q3), merges them into one catalog and writes it to the data
   directory. `--years N` changes the window, `--from`/`--to` (e.g. `2024Q1`)
   set an explicit range, and the original `<year> <quarter>` form still works.
   It is a rolling window, rebuilt from scratch each run. Only *completed*
   quarters are in the default window — the running quarter's index keeps
   growing, so including it would change the catalog under the rebuild. Safety:
   any quarter that fails aborts the run and leaves the existing catalog
   untouched (written to a temporary name and renamed into place), an empty
   result is refused, and the file records `first_quarter`, `last_quarter`,
   `quarters`, `generated_at` and `rows` in its own metadata. Rows are
   de-duplicated by **(CIK, accession number)**, not accession alone —
   co-registrants such as Ameren Corp, Union Electric and Ameren Illinois file
   under one accession number and each is its own row (a first version
   de-duplicated by accession alone and would have silently dropped them; caught
   by comparing row counts, now covered by a test). Result of the first real
   run: 72,813 filings across the 8 quarters, 69,465 distinct accessions, 11.6MB;
   Apple went from 1 filing to 8 in the EDGAR Explorer. It needs network access
   to sec.gov and the project User-Agent; it cannot read the local V3 index
   files.
3. **The SIC data is staged by hand in `tmp/` for now**, because the delivery
   mechanism from mediumroast.io is not confirmed. **Consequence worth stating
   plainly:** `tmp/` is gitignored, so a CI runner cannot see it. Until that
   delivery mechanism exists, an image that contains the SIC data has to be built
   on a machine where `tmp/` is staged (a developer machine), and the scheduled
   workflow below can refresh the EDGAR catalog but cannot produce a complete
   image on its own. This is the main thing standing between phase 1 and a
   fully automated build (§6).
4. **The scheduled workflow is quarterly, not monthly.** It runs on the first
   day of January, April, July and October (`cron: '0 12 1 1,4,7,10 *'`), at
   which point the quarter that just ended is complete and becomes the newest in
   the window; each run therefore ships the last two years of completed
   quarters. Steps: ingest the catalog (no arguments) → check it (rows, quarter
   range from its metadata) → obtain the SIC files (mechanism open, point 3) →
   run `check_ic_feather.py` on each → build the multi-platform image → push.
   This **replaces the monthly cadence** planned in `v4-server-prototype.md` §4
   (updated the same day) and is distinct from V3's own monthly workflow
   (`.github/workflows/main.yml`), which this does not touch. Not built yet.

**Why bake-and-override rather than only a volume or a fetch** (the three
options the earlier version of this section weighed — borrowed back from
`v4-container-packaging.md` §3.2): *baking in* couples the code image to one
data snapshot, so every refresh needs a rebuild and redeploy, which worked
against the separate `ingest-edgar`/`server` design. That cost is now small:
refresh is already a scheduled quarterly *build*, the data is about 17MB, and
the volume override keeps an escape hatch for an out-of-cycle refresh without
rebuilding. A *volume populated by a separate process* gives the cleanest
decoupling but needs something to fill it before the server starts, a moving
part this size of data does not justify. *Fetching at startup* from object
storage adds a startup-time dependency and a new failure mode the local-file
model does not have.

**Known gap — a missing file is quiet.** Today a missing data file only logs a
warning and the server carries on (the EDGAR endpoints then return 500 "catalog
not loaded", and merged search degrades to Wikipedia-only with a note). That is
fine for development and wrong for a deployment, where a bad mount should stop
the pod. A strict startup mode (refuse to start, or fail readiness, when a
required file is absent) is recommended; not decided (§6).

### 3.3 Binary size reduction — independent levers, each needs its own spike number

1. **`[profile.release]` tuning.**
   - `strip = true` — **already confirmed** to save ~44MB (26%,
     §1.1). Free, no known downside for a shipped server binary.
   - `lto = "thin"`/`"fat"` — not yet measured; Arrow's generic-
     monomorphization-heavy code is exactly the shape that often
     benefits, but has to be measured on this dependency graph, not
     assumed.
   - `codegen-units = 1` — smaller/faster binary, slower build; worth
     measuring alongside LTO.
   - **`panic = "abort"` — explicitly NOT recommended without further
     study.** Tokio's per-task unwind isolation is what keeps one
     panicking request handler from taking down the whole server
     today; `panic = "abort"` would turn that into a full-process
     crash on a single bad request. An availability regression, not a
     free size win — flagged so it isn't reached for reflexively.
2. **DataFusion feature trimming — two very different risk
   categories, not one flat list.**
   - **File-format/codec support (`parquet`, avro-adjacent,
     `compression`) — safe to cut.** Orthogonal to SQL expressiveness;
     §1.1 already confirmed no Parquet API use anywhere, and the SIC
     source is Arrow IPC, not Parquet.
   - **Expression-function libraries (`crypto_expressions`,
     `datetime_expressions`, `encoding_expressions`,
     `regex_expressions`, `string_expressions`, `unicode_expressions`,
     `nested_expressions`) — deliberately kept on.** These gate what a
     `ctx.sql()` query can actually *express*; more expressive SQL may
     well be needed for future SIC/EDGAR lookups, and cutting these now
     risks silently blocking a future query. **Decided: keep the full
     set enabled in the first pass**, revisit only with an explicit
     tradeoff conversation if binary size is still a real problem after
     the format/codec cut and profile tuning are both applied.
   - `sql` itself stays on regardless (genuinely required).
3. **Multi-stage Docker build.** The Rust build stage (full toolchain,
   large) should never be the runtime image — final stage carries only
   the compiled binary plus whatever minimal base a stripped/trimmed
   binary needs (`debian:bookworm-slim`, or a `distroless`/`scratch`
   base if fully static via musl — needs checking `reqwest`'s
   `rustls-tls` against `*-unknown-linux-musl` targets).

### 3.4 Environment tiers: dev, staging, prod

All three run on the **same** `microk8s` cluster — no new hardware.
Namespaces `company-dns` (existing, unchanged shape), `company-dns-staging`,
`company-dns-dev`, mirroring `mediumroast-web`'s already-proven
three-namespace convention (§1.3) rather than inventing a new pattern.

- **dev** (*designed, not in phases 1–2 — see §0.1*): active iteration during
  build-out. **1 replica**, no
  anti-affinity needed, resource requests well under prod's
  256Mi/100m. Redeployed freely, expected to break sometimes. Answers
  "does it run on the real cluster at all" — cheap and fast, not the
  platform-parity gate.
- **staging** (*phase 2, `staging-company-dns.mediumroast.io`*): mirrors prod's *shape* as closely as the 2-node budget
  allows — real `microk8s`, real Ingress, real ConfigMap mounts,
  **2 replicas** (not 4 — enough to exercise multi-pod behavior, e.g.
  `rate_limit.rs`'s per-pod quota division at `v4-security-hardening.md`
  §5, at a *different* N than prod's hardcoded 4, without doubling the
  cost of all three tiers coexisting). **This is where §3.6's
  platform-parity suite actually runs**, gating promotion to prod.
- **prod**: `k8s/prod/`, unchanged shape. Gains a promotion *gate* —
  only an image that passed staging gets applied here.

**Distinct `MEDIUMROAST_SHARED_SECRET` per tier, not shared** — each
environment gets its own SealedSecret (already installed cluster-wide,
§1.3), so staging/dev testing never has access to, or could leak, the
real production secret mediumroast.io's live site trusts. Cheap to do;
the alternative gives a noisy dev environment the same trust as prod.

**SQL endpoint configuration per tier (added 2026-10-05, experimental,
off by default).** Each tier gets its own sealed credentials file and its own rules ConfigMap (same
reasoning as the distinct shared secret: staging and dev never hold prod's
credentials) and its own **server-wide SQL limits** in the tier's ConfigMap
(concurrency, query memory pool, request budget, row and timeout ceilings). The
limits are sized against the tier's real pod: prod is 4 replicas with requests
256Mi/100m and limits 1Gi/500m; staging 2 replicas. Request budgets are
aggregate divided by replicas, the `rate_limit.rs` convention, with its known
drift if the replica count and constant diverge. The SQL flag stays off until a
tier's credentials file exists; with the flag on and no valid file the server
refuses to start. Staging's capacity check (§4.7) must include the SQL capacity test
(`v4-sql-endpoint.md` §5c): deliberately heavy SQL under steady lookup load,
raising the caps until lookups degrade, to set the server-wide values.

### 3.5 The pipeline, with the plain-Docker-on-Ubuntu step explicit

Per what was asked directly — an intermediate step isolating "is it
the image/binary" from "is it something K8s-specific":

1. **Build.** Multi-platform image (`linux/amd64` and `linux/arm64` —
   §3.7; `linux/amd64` is the one that matters for this doc's purpose,
   since that's the real cluster's architecture).
2. **NEW: plain `docker run` on real Ubuntu amd64 — no K8s at all.**
   Smoke-test the built image directly: does it start, does `/health`
   respond, do real searches return results from the copied data files (the
   API test suite, §3.9), does the dynamic-log-level reload mechanism (once promoted
   per `v4-dynamic-log-level.md` §5) actually pick up a file change on
   real Linux. If this fails, it's the binary/image; if it passes but a
   later K8s step fails, the problem is specifically in the K8s
   ConfigMap-mount layer. **Cheapest real place to run this**: a GitHub
   Actions `ubuntu-latest` runner is genuinely native `linux/amd64`
   (not emulated) — a plain CI job, no new infrastructure needed.
3. **Deploy to `company-dns-dev`** *(not part of phases 1–2, §0.1 — skipped
   for now; the first real-`microk8s` test is staging)*. Real-`microk8s`,
   real-ConfigMap-mount test with fast iteration, not a hard gate.
4. **Promote to `company-dns-staging`** (`staging-company-dns.mediumroast.io`,
   phase 2). §3.6's full platform-parity
   suite runs here — the actual gate.
5. **Promote to `company-dns` (prod)** only after staging passes.
   Manual `kubectl apply`, matching how prod deploys today
   (`scripts/build-and-deploy.sh`) — no GitOps/ArgoCD reconciler exists
   on this cluster (checked directly: `helm list -A` showed no such
   release), so automatic promotion isn't free to add and isn't
   designed here.

### 3.6 The platform-parity test suite (what runs at the staging gate)

1. **The specific thing that started this**: confirm
   `v4-dynamic-log-level.md`'s promoted reload mechanism reacts to a
   real `kubectl edit configmap` on the real cluster — not just the
   hand-simulated symlink swap the spike used (a faithful reproduction
   of kubelet's real mechanism, precisely so this step has something
   solid to confirm against, but a real edit is still the final word).
2. Confirm `v4-security-hardening.md`'s `rate_limit.rs` behaves
   correctly with **staging's own replica count** (2, §3.4) — exercises
   the `REPLICA_COUNT`/per-pod-quota-division logic at a different N
   than prod's hardcoded 4, not just re-confirming prod's own
   assumption.
3. Once §6's static-musl-vs-glibc-slim question is decided: confirm the
   chosen base image actually runs correctly on the real target, not
   just that `cargo build` succeeded for that target triple.
4. General template for future platform-sensitive work: if a spike only
   proved something on a developer's Mac, it doesn't graduate to prod
   without a staging run first. Grows over time, doesn't stay frozen at
   today's items.

### 3.7 Multi-platform build — a hard requirement, and phase 1's delivery target

Previously an open question. Phase 1 (§0.1) is explicitly **one image delivered
for both `linux/amd64` and `linux/arm64`**, and `linux/amd64` is the one that
matters for the real cluster, whose workers are amd64 (§1.3). The *mechanism*
is still undecided (§6). The reasoning that makes it a real decision, borrowed
back from `v4-container-packaging.md` §6: V3's existing workflow builds both
platforms with `docker/setup-buildx-action` under **QEMU emulation**, which is
fine for an interpreted Python image but makes Rust compilation dramatically
slower than native, and this build compiles DataFusion. The options are
per-architecture native runners, a cross-compilation toolchain (`cross`), or
accepting a slow emulated build. §3.5's plain-Docker-on-Ubuntu step needs a real,
working `linux/amd64` image on every build, so the amd64 path cannot be the slow
or flaky one.

### 3.8 K8s manifests, mirroring the proven `k8s/prod/` shape

`k8s/prod/`'s existing pattern (`namespace.yaml`, `deployment.yaml`,
`service.yaml`, `ingress.yaml`, `middleware-redirect.yaml`,
`certificate.yaml` — authored during V3's migration, proven live) gets
a `dev/` and `staging/` sibling each, same shape, different sizing:

```
k8s/
  dev/      (designed, not scheduled - 1 replica, relaxed resources, hostname not chosen)
  staging/  (phase 2 - 2 replicas, staging-company-dns.mediumroast.io)
  prod/     (existing, unchanged)
```

Each environment's `Certificate`/TLS reuses the same `letsencrypt-prod`
`ClusterIssuer` prod already uses (§1.3) — no new issuer, just new
hostnames on the existing one. New `Ingress`/`Middleware` pairs per
namespace, same `ingressClassName: traefik` pattern, same
namespace-prefixed Middleware reference convention (§1.3).

### 3.9 The API test suite (extend `perf_tests/`)

What is missing is a robust test suite for the APIs. What exists is a
performance suite written in Python, `perf_tests/`, which is the right base
to extend rather than replace:

- **What it already does.** `baseline.py` keeps a curated `ENDPOINTS` catalog,
  verifies each path exists in the deployment's own OpenAPI spec before running
  (so it refuses to report "fast" results from 404s), runs every endpoint
  against ten well-known companies sequentially and then at rising concurrency,
  and — in the concurrency experiment — *asserts correctness*, checking each
  response belongs to the company asked for (by CIK) so a shared-state race
  cannot hide behind a good latency number. `--profile v3` / `--profile v4`
  (via each endpoint's `v4_path`) point it at either server; `compare.py` diffs
  two runs and flags regressions; `shadow_compare.py` compares V3 and V4
  responses. Results are JSON stamped with git commit and deployed image.
- **What it does not cover.** Only seven or so V3-parity endpoints have a
  `v4_path`. Nothing covers the V4-only surface — global SIC keyword
  (`/V4.0/global/sic/description`), semantic (`.../similarity`) and hybrid
  (`.../hybrid`), the four classification systems, the token and docs
  endpoints. Beyond the concurrency check it asserts almost nothing about
  *content*: not the response envelope, not error cases (404/429/500 shapes),
  not whether the data it needs was actually loaded. Several recent defects were
  exactly of that kind — an EDGAR catalog that was missing so every company came
  back Wikipedia-only, name matches that merged the wrong company, a UI showing
  "API Error" over a perfectly good 404 — and none would have failed a latency
  run.
- **Extension plan.** Add a functional layer beside the performance one, reusing
  its endpoint catalog, company list and `--base-url`/`--profile` plumbing:
  1. *Contract tests* for every V4 endpoint: status code, the
     `{code, message, module, data, dependencies}` envelope (verbatim for V3
     parity endpoints), documented error shapes, and a check that the live
     OpenAPI spec lists the endpoint.
  2. *Data-readiness tests*: each of the four classification systems returns
     results through the global endpoints, the EDGAR catalog is loaded and spans
     the expected quarters, merged firmographics finds EDGAR data for known
     companies (IBM, Apple Inc., Microsoft) — the checks that would have caught a
     missing catalog.
  3. *Search-quality regression*: fold in `experiments/sic-hybrid-eval/`
     (`eval.py server ...`), which already exits non-zero when hybrid search
     regresses against semantic.
  4. *V3 parity*: keep `shadow_compare.py` as the check that V3-parity
     endpoints still match V3.
  5. Keep the performance and concurrency runs, with `compare.py` thresholds,
     as the stability part of the staging gate.
- **Where it runs.** Against the image in phase 1 (plain `docker run`, §3.5 step
  2) and as the staging gate in phase 2 (§3.6). It must be runnable with nothing
  but `requests` and the standard library, like the existing suite, so a CI
  runner or a laptop can run it unchanged.

## 4. Research spike, before touching `v4/` for real

Following this project's established `experiments/`-first pattern:

1. `[profile.release]` tuning: `strip = true`, `lto = "thin"`/`"fat"`,
   `codegen-units = 1` in combination — measure real binary size and
   build-time cost, don't guess.
2. Trim DataFusion's `default-features` down to the format/codec-only
   cut (§3.3.2), confirm `cargo build`/`cargo test` still pass across
   `crates/sic`, `crates/edgar`, `crates/server` — measure the binary
   size delta. Don't widen the cut to expression-function features as
   part of this spike even if savings are small — that's a separate,
   deliberately-deferred tradeoff.
3. Prototype a real multi-stage Dockerfile with the smallest binary
   from 1/2, measure final image size end to end — including whether a
   static-musl build is realistic given `rustls-tls`, or glibc-slim is
   the practical floor.
4. Data bundling is decided (§3.2.1): copy the feather files into the image's
   data directory, with `COMPANY_DNS_DATA_DIR` set. Prototype it as part of 3 —
   confirm the image starts and serves real searches from the copied files, and
   that mounting a volume at the same path replaces them.
5. Confirm a GitHub Actions `ubuntu-latest` runner really is
   `linux/amd64` natively, and prove the plain-`docker run` smoke test
   as a real CI job, including a scripted version of the
   `configmap_sim.rs`-style update technique against a real file mount
   inside that container.
6. Stand up `company-dns-dev` for real on the cluster, confirm a
   `kubectl edit configmap` there actually triggers
   `v4-dynamic-log-level.md`'s reload mechanism on real `microk8s` — the
   actual thing §3.4–3.6 exist to make possible.
7. Confirm dev/staging's chosen resource requests (§3.4) don't starve
   prod or each other — a real `kubectl top nodes`/`describe node`
   check against the two real worker nodes' actual headroom, not an
   assumed-safe number.

## 5. Implementation steps, in the order decided (2026-10-04)

**Step A — make the major functions operable. Data side done 2026-10-04:**
`COMPANY_DNS_DATA_DIR` and the shared data-directory module, the server using
it, `ingest-edgar` taking years/quarters (default: the last two years of
completed quarters), the EDGAR catalog rebuilt (72,813 filings, 8 quarters), the
README updated. Remaining under this step is whatever the owner still finds
inoperable.

**Step B — thin the binary** (spike §4.1–4.2, then implement):

1. `v4/Cargo.toml`: add `[profile.release]` with whatever §4.1 confirms (at
   minimum `strip = true`, already confirmed).
2. `v4/Cargo.toml`: trim `datafusion`'s features per §4.2's confirmed safe list
   (format/codec support only; the expression-function libraries stay on).

**Step C — packaging, phase 1: one Docker image, multi-platform**

3. Add a real `v4/Dockerfile` (multi-stage, §3.3.3/§4.3) — the first Rust
   Dockerfile in the repo — built for `linux/amd64` and `linux/arm64` (§3.7),
   with the feather files copied into the data directory and
   `COMPANY_DNS_DATA_DIR` set (§3.2.1). Built where `tmp/` is staged until the
   SIC delivery mechanism exists (§3.2.3).
4. Prove the image with plain `docker run` on real Ubuntu amd64 (§3.5 step 2),
   running the API test suite (§3.9) against it.
5. Extend `perf_tests/` into the API test suite (§3.9).
6. Update `v4/README.md` with a "Building and running the container" section.

**Step D — the quarterly build**

7. Add the scheduled workflow (§3.2.4): quarterly, ingest → check → SIC files
   (once deliverable) → gate → multi-platform build → push. Decide whether it
   extends `.github/workflows/main.yml` or is its own V4 workflow, and whether
   it replaces V3's or runs alongside it during the transition
   (`v4-server-prototype.md` scope question, not decided here).

**Step E — phase 2: staging at `staging-company-dns.mediumroast.io`**

8. Add `k8s/staging/` (§3.8), sized by §4.7's real capacity check; its own
   `MEDIUMROAST_SHARED_SECRET` SealedSecret (§3.4); DNS and a `letsencrypt-prod`
   certificate for the hostname.
9. Deploy the image there, run the API test suite and the platform-parity suite
   (§3.6), and leave it up long enough to judge stability — this is the gate
   before anything is promoted.

**Step F — promotion to `company-dns` (prod)** only after staging passes
(§3.5 step 5). `k8s/dev/` (§3.8) is not part of any of the above.

**Step G — SQL endpoint wiring (after the feature exists, `v4-sql-endpoint.md`
section 8):** add `credentials.example`, `rules.example.json` and the `.gitignore` pattern; a
SealedSecret and ConfigMap entries per tier (`k8s/staging/`, `k8s/prod/`);
document the Docker-secret equivalent in the README; run the SQL capacity test
at staging (§3.4 addendum); flag stays off in prod until that passes.

If §3.1's build-time secret mechanism ends up needed (for example to fetch the
SIC files in CI, §3.2.3), wire it in following §3.1's pattern.

## 6. Open questions

**Resolved 2026-10-04** (kept visible, struck through):

- ~~Which data-bundling option (a/b/c, §3.2).~~ Decided: one data-directory
  variable, files copied into the image, a mounted volume can replace them.
- ~~Real production-scale SIC/embedding data size.~~ Measured: about 17MB with
  four systems and the two-year EDGAR window (§1.2); not a deciding factor.
- ~~Hostnames.~~ Staging is `staging-company-dns.mediumroast.io`; prod stays
  `company-dns.mediumroast.io`. (No dev hostname chosen — the dev tier is not
  scheduled.)
- ~~EDGAR catalog refresh cadence.~~ Quarterly, rolling two-year window (§3.2.4).

**Still open:**

- **SQL endpoint operations** (`v4-sql-endpoint.md`): real server-wide limit
  values per tier, from the staging capacity test (pass criteria decided in
  `v4-sql-endpoint.md` §5c). Profiles are read at startup only; changing them
  means a restart (decided).
- **How the SIC feather files reach CI.** They are staged by hand in `tmp/`
  (gitignored) because the mediumroast.io delivery mechanism is not confirmed
  (§3.2.3). Until it is, the scheduled build can refresh the EDGAR catalog but
  not assemble a complete image, and phase-1 images are built on a machine where
  `tmp/` is staged. Needs: where Mediumroast publishes the files (artifact,
  bucket, release) and how CI authenticates to it.
- **Strict startup mode.** Whether, and how, the server refuses to start (or
  fails readiness) when a required data file is missing or, for the catalog,
  older than the expected window (§3.2, "Known gap").
- **Multi-platform build mechanism** (native runners vs. `cross` vs. accepting
  slower QEMU-emulated builds) — a hard requirement for phase 1 (§3.7), mechanism
  still undecided.
- **Static musl vs. glibc-slim runtime base** — depends on whether `rustls-tls`
  builds cleanly against `*-unknown-linux-musl` targets; not yet checked.
- **Whether the expression-function features ever get cut.** §3.3.2 keeps them on
  in the first pass; revisiting needs its own explicit decision about which
  families are safe for *this* project's query patterns, not a blanket re-cut.
- **Whether V4's build replaces V3's `.github/workflows/main.yml` outright, runs
  alongside it, or gets its own workflow file** during the transition — a
  `v4-server-prototype.md`-scope decision.
- **Exact resource requests/limits for staging** — sized illustratively in §3.4,
  pending §4.7's real capacity check.
- **Does staging share prod's read-only data snapshot or get its own?** With the
  data baked into the image this mostly answers itself (staging runs the same
  image); only a volume override changes it.
- **CI trigger model** — assumed builds happen on push/PR and promotion between
  tiers is manual and deliberate.
- **Scope of the API test suite's first cut** (§3.9) — which of the five layers
  must exist for the phase-1 image test and which can wait for the staging gate.
- **Whether this pipeline structure eventually gets applied retroactively to V3**
  — not this doc's call; V3 is being replaced.

## 7. Explicitly out of scope for this doc

- **V3's Azure→K8s migration history** — stays in
  `onprem-k8s-migration.md`, unchanged; that migration already
  concluded and nothing here reopens it.
- **Any change to `v4-security-hardening.md` §3.5's rolling-secret
  design** — §2 above keeps that decision as-is, only addressing how
  its one input reaches each deployed environment.
- **GitOps/automatic reconciliation** (ArgoCD/Flux) — not present on
  this cluster today (confirmed), and introducing it is a much bigger
  infrastructure decision than this doc's scope.
