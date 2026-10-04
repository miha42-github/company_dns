# V4 container packaging: image size, data bundling, secret injection

Status: **Superseded (2026-09-30) by
[`v4-deployment.md`](v4-deployment.md).** This doc's content (image
size audit, the secret-injection mismatch, data-bundling options,
binary-size reduction plan) has been fully consumed into that doc's
§1–§3, alongside a new dev/staging/prod deployment-environments design
raised immediately afterward. Kept here, unchanged, as the original
research record — `v4-deployment.md` is the canonical, actively-updated
source for all of this going forward; don't edit this file for new
decisions.

---

Status (original, as of 2026-09-29): **Planned.** Audited against real measurements
(binary size, actual data-file size, existing Dockerfile/CI), not yet
spiked or implemented.
Owner: michael.hay@mediumroast.io
Scope: two problems raised together, kept as two problems rather than
conflated into one (§1 explains why): (1) how `MEDIUMROAST_SHARED_SECRET`
(`docs/plans/v4-security-hardening.md` §3.5) gets from a GitHub Actions
secret into a form the real deployment can use, without undoing that
doc's already-decided runtime-secret design; (2) why the V4 Rust
server's release binary is far larger than expected, and how SIC/EDGAR
`.feather` data should reach a running container. Referenced from
`v4-security-hardening.md`'s §3.5 (raised while designing that
section's rolling shared secret).

---

## 0. Why this doc

Raised directly, while working on `v4-security-hardening.md` §3.5's
rolling shared-secret mechanism: *"For managing this secret, we can
look at something like docker secrets to keep the secret sealed and
inject the secret into image when built and keep the secret as a
github secret referred to only by variable during the build."*
Additionally: *"I've noticed that the rust binary appears to be almost
200MB in size this is huge but we should consider how we bundle in the
feather files to a docker container so that the binary remains as
small as possible."* Both are real, but auditing the actual numbers
(§1) shows they're independent problems with independent fixes, not
one problem — worth saying up front since the second request's framing
("bundle feather files... binary remains small") implies the data
might be inflating the binary, and it isn't.

## 1. Current state (audited 2026-09-29)

### 1.1 Binary size — measured, not assumed

- `v4/target/release/company-dns-server`: **172MB unstripped, 128MB
  stripped** (measured directly: `strip` on a copy of the release
  binary, macOS arm64 build). ~44MB (26%) is symbol table; the
  remaining ~128MB is linked code and data.
- `v4/Cargo.toml` has **no `[profile.release]` section at all** —
  every release build uses Cargo's plain defaults: `opt-level = 3`,
  `lto = false`, `codegen-units = 16`, `panic = "unwind"`,
  `strip = "none"`. None of the standard binary-size levers are turned
  on yet.
- DataFusion 55.1.0's **default features pull in the entire SQL engine
  surface** (confirmed via crates.io's published feature list, not
  assumed): `parquet`, avro-adjacent datasource support, compression
  codecs (`bzip2`, `flate2`, `zstd`, `liblzma` via the `compression`
  feature), the full expression-function libraries
  (`crypto_expressions`, `datetime_expressions`, `encoding_expressions`,
  `regex_expressions`, `string_expressions`, `unicode_expressions`),
  `nested_expressions`, and the full SQL frontend (`sql` + `sqlparser`).
  `v4/Cargo.toml`'s `datafusion = "55"` line doesn't customize this at
  all — every one of those is compiled in by default.
- Confirmed via grep against `crates/sic/src/{lib,lookup,similarity}.rs`:
  this project genuinely needs the `sql` feature —
  `ctx.sql(&sql_string)` string-based queries run throughout
  (`lookup.rs:91,115,140,157`, `similarity.rs:61`) — but shows **no use
  of DataFusion's `parquet` API anywhere**; the SIC data source is
  `.feather` (Arrow IPC), loaded via `register_table`/
  `file_extension: ".feather"` (`crates/sic/src/lib.rs:29-33`), not
  Parquet.
- **Checked and resolved, not left as a blocking unknown**: `edgarkit`
  (external dependency, sharing this same DataFusion instance per
  `go-duckdb-rewrite.md`/`edgar-backend.md`'s decision) has **zero
  dependency on DataFusion or Arrow at all** — confirmed by reading its
  published `Cargo.toml` directly (it's a standalone SEC EDGAR HTTP
  client: `reqwest`, `tokio`, `governor`, `flate2` for its own index
  decompression, `quick-xml`, nothing DataFusion-related). Cargo's
  feature unification only matters across crates that *both* depend on
  the same crate — since edgarkit doesn't touch DataFusion, trimming
  DataFusion's default features in `v4/Cargo.toml` is entirely within
  company_dns's own control, not something edgarkit could silently
  re-widen.

### 1.2 Feather/data-file size — measured, and small

- Current dev-scale data in `tmp/`: `us_flat.feather` (92KB),
  `us_flat_embedded.feather` (1.4MB), plus two EDGAR catalog files
  (~1.4MB each). **Total: ~4.4MB** — roughly thirty-to-forty times
  smaller than the binary itself.
- This is the basis for §0's "two independent problems" claim: bundling
  this data into the image via a multi-stage `COPY` would barely move
  image size at today's scale. Whether that holds at real production
  scale is genuinely open (§6) — if the full national SIC dataset plus
  embeddings turns out to be materially larger than this dev sample,
  §3.2's bundling-strategy tradeoffs matter more than they do today.

### 1.3 Existing container/CI state

- `Dockerfile` (repo root) is V3's — `python:3.13-alpine`, entirely
  unrelated to V4's Rust binary beyond being the thing V4 eventually
  replaces.
- `.github/workflows/main.yml`: V3's monthly scheduled build,
  `docker/build-push-action@v4` → GHCR (`ghcr.io/<repo>/company_dns`),
  multi-platform (`linux/amd64,linux/arm64` via
  `docker/setup-buildx-action@v2`), GHA layer caching
  (`cache-from`/`cache-to: type=gha`). **No application secret is used
  in this build today** — only `secrets.GITHUB_TOKEN` for registry
  auth. This *is* a real, already-working template for §3.1's
  build-secret approach (`build-push-action` supports a `secrets:`
  input backed by BuildKit's native `--secret` mechanism), just not
  demonstrated with an application secret yet.
- No Rust Dockerfile exists anywhere in the repo yet.

## 2. A mismatch worth flagging before designing §3.1

Two genuinely different things both get called "secret" across the two
requests that opened this doc, and treating them as one would undo a
decision `v4-security-hardening.md` §3.5 already made deliberately.

**Build-time secrets** (BuildKit `--secret` / "Docker secrets" in the
sense raised here; `docker/build-push-action`'s `secrets:` input):
mounted into the build container's ephemeral filesystem only for the
`RUN` step that needs them, and — the actual property that makes them
worth using — **never written into any image layer or the image's
layer history**. `docker history` on the resulting image shows nothing.
Right tool for a secret genuinely needed only *during* `docker build` —
e.g. a private crate-registry auth token, or credentials to fetch SIC
feather data from an internal source as part of the build if §3.2 lands
on that option.

**Runtime secrets** — specifically `MEDIUMROAST_SHARED_SECRET`, which
`v4-security-hardening.md` §3.5 already designed: the *running server
process* reads it at startup and recomputes an hourly rolling HMAC
against it on every incoming request. This is not a build-time need.
**Baking it into the image via a build-time secret mechanism would be
a regression from what §3.5 already decided**, for three concrete
reasons: (1) rotation would require rebuilding and redeploying the
image instead of just updating a K8s Secret and rolling pods — §3.5's
own "Rotation" paragraph already assumes the lighter-weight path is
available; (2) a built image is typically pulled by more environments
and cached more widely than a deploy-time secret store, so baking a
secret into every image pull widens exposure versus injecting it only
where the pod actually runs; (3) it conflates the build artifact
(should be identical across dev/staging/prod) with environment-specific
config (the secret differs, or must be rotatable independently, per
environment) — the same reasoning that already keeps
`SIC_DATA_PATH`/`EDGAR_CATALOG_PATH`/`PORT` as runtime env vars
(`v4/README.md`'s "Running it" section) rather than baked in.

**Recommendation:** keep `MEDIUMROAST_SHARED_SECRET` exactly as §3.5
already decided — a runtime env var sourced from company_dns's own K8s
Secret, never touched by the image build at all. Reserve BuildKit
`--secret` for a genuine build-time need, if one turns out to exist
once §3.2 is decided. This doc is not proposing to reopen §3.5's
design — it's flagging that one reading of "inject the secret into the
image when built" would, and recommending against that reading
specifically.

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

No concrete build-time secret is identified yet — this section exists
so the mechanism is documented and ready the moment §3.2 lands on an
option that needs one (e.g. private-source credentials to fetch feather
data during the image build). Not built until there's a real secret to
protect this way.

### 3.2 Getting SIC/EDGAR feather data into a running container

Three options, real tradeoffs, not yet decided:

- **(a) Bake into the image** (multi-stage `COPY tmp/*.feather` into
  the final stage). Simplest to reason about — the image is fully
  self-contained. Cost: couples the "code" image to one data snapshot;
  every SIC-data or EDGAR-catalog refresh needs a full image rebuild
  and redeploy just to move a few MB of data, even though `v4/README.md`
  already treats EDGAR ingest (`cargo run --bin ingest-edgar`) as a
  separate operation from running the server — baking data in would
  work against that separation, not with it.
- **(b) Mount as an external volume at deploy time** (K8s
  PersistentVolume, or a ConfigMap/similar for data this small),
  populated by a separate process — matches the existing precedent of
  `ingest-edgar` already being a distinct binary from `server`, and
  decouples data-refresh cadence from image-build cadence entirely.
  Cost: more moving parts in the deployment (something has to populate
  the volume before/alongside the server starting).
- **(c) Fetch at container startup** from object storage (S3/GCS/etc.),
  as an init step in the entrypoint or a K8s `initContainer`. Similar
  decoupling benefit to (b), less infrastructure than a volume mount,
  but adds a startup-time dependency on that storage being reachable —
  a new failure mode `v4/README.md`'s current "point env vars at local
  files" model doesn't have.

**Leaning (b) or (c)** over (a), given the existing `ingest-edgar`/
`server` separation and the monthly EDGAR-refresh cadence already
implying data changes on a different schedule than code — but not
decided here; real production data size (§6) and actual deployment
tooling available (`docs/plans/onprem-k8s-migration.md`) should settle
it, not this doc alone.

### 3.3 Binary size reduction — independent levers, each needs its own spike before committing to numbers

1. **`[profile.release]` tuning.**
   - `strip = true` — **already confirmed** to save ~44MB (26%) via
     this doc's own manual test (§1.1). Free, no known downside for a
     server binary (no need for symbols in a shipped image).
   - `lto = "thin"` or `"fat"` — not yet measured. Real Rust binaries
     with heavy generic-monomorphization-prone dependencies (Arrow's
     columnar/generic code is exactly this shape) often see meaningful
     size reduction from LTO, but it has to be measured on *this*
     dependency graph, not assumed from general Rust folklore — §4.
   - `codegen-units = 1` — smaller/faster binaries at the cost of
     slower builds; worth measuring alongside LTO since both trade
     build time for binary size.
   - **`panic = "abort"` — explicitly NOT recommended without further
     study**, flagged here so it isn't reached for reflexively as a
     "free" size win. Tokio's per-task unwind isolation is what keeps
     a single panicking request handler from taking down the whole
     server today (the panic unwinds out of that task, the connection
     it was handling fails, the rest of the process keeps running).
     `panic = "abort"` removes unwinding entirely — the same panic
     would abort the whole process instead of just that one request.
     That's an availability regression for an HTTP service, not a
     harmless build tweak, and it isn't worth chasing without first
     confirming nothing in the request path actually depends on
     per-task unwind recovery.
2. **DataFusion feature trimming — split into two very different risk
   categories, not one flat "unused, cut it" list.** `default-features
   = false` on the workspace `datafusion` dependency, then:
   - **File-format/codec support — the safe part to cut.** `parquet`,
     avro-adjacent datasource support, and the compression codecs
     (`bzip2`/`flate2`/`zstd`/`liblzma` via `compression`) gate what
     *storage formats* DataFusion can read/write. They're orthogonal to
     SQL expressiveness — cutting them has no effect on what a `ctx.sql()`
     query can *say*, only on what file formats a `CREATE EXTERNAL
     TABLE`/`register_*` call could point at. §1.1 already confirmed no
     Parquet API use anywhere in company_dns's own code, and the SIC
     data source is `.feather` (Arrow IPC), not Parquet/Avro — this
     part of the trim looks genuinely safe.
   - **Expression-function libraries — deliberately NOT trimmed by
     default, kept conservative.** `crypto_expressions`,
     `datetime_expressions`, `encoding_expressions`, `regex_expressions`,
     `string_expressions`, `unicode_expressions`, `nested_expressions`
     are a different thing entirely: they gate what a `ctx.sql()` query
     can actually *express* — date/time functions, regex matching,
     string manipulation, array/nested functions. **Raised directly as
     a forward-looking concern**: more expressive SQL may well be
     needed later (the whole point of moving SIC/EDGAR lookups onto a
     real SQL engine rather than hand-rolled filtering), and cutting
     these now to save binary size risks silently blocking a future
     query from working, discovered only when someone writes it and it
     fails to compile against a trimmed engine. **Decided: keep the
     full expression-function feature set enabled by default in the
     first pass of this trim**, and only reconsider cutting specific
     ones later, with an explicit tradeoff conversation at that point,
     if binary size is still a real problem after the format/codec cut
     and the other levers in this section (§3.3.1, §3.3.3) are already
     applied.
   - `sql` itself stays on regardless (§1.1: genuinely required,
     `ctx.sql()` used throughout `crates/sic`).
   - Real savings from the format/codec-only cut not yet measured;
     needs a spike (§4) that actually builds with that narrower trimmed
     feature list and confirms both that it still compiles/passes tests
     *and* how much smaller the binary gets. Expect a more modest
     number than trimming everything, since the expression-function
     libraries are being kept — that's the accepted tradeoff here.
3. **Multi-stage Docker build.** A Rust build stage (full toolchain,
   large) should never be the runtime image — the final stage should
   carry only the compiled binary plus whatever minimal base a
   `strip`+trimmed binary actually needs (`debian:bookworm-slim`, or a
   `distroless`/`scratch`-style base if the binary ends up fully static
   via musl — needs checking whether `reqwest`'s `rustls-tls` feature,
   already chosen project-wide over `native-tls`, is compatible with a
   static musl target). This doesn't shrink the binary itself, but
   avoids compounding an already-large binary with an unnecessarily
   large base image on top of it.

## 4. Research spike (before any implementation)

Following this project's established pattern (`experiments/` spikes
before promoting into `v4/` proper — most recently
`experiments/rate-limit-spike/`):

1. Add `strip = true`, try `lto = "thin"` and `lto = "fat"`,
   `codegen-units = 1`, in various combinations — measure real binary
   size and build-time cost for each, don't guess.
2. Trim DataFusion's `default-features` down to the format/codec-only
   cut §3.3.2 outlines (`parquet`, avro-adjacent support, compression
   codecs — the expression-function libraries stay on, deliberately),
   confirm `cargo build`/`cargo test` still pass across `crates/sic`,
   `crates/edgar`, `crates/server` — measure the resulting binary size
   delta. Don't widen the cut to the expression-function features as
   part of this spike even if the format/codec-only savings turn out
   small — that's a separate, harder tradeoff §3.3.2 deliberately
   deferred, not something to fold in opportunistically.
3. Prototype a real multi-stage Dockerfile using the smallest binary
   §4.1/§4.2 produce, measure the final image size end to end (not
   just the binary in isolation) — including confirming whether a
   static-musl build is realistic given `reqwest`'s `rustls-tls`
   feature choice, or whether a glibc-slim base is the practical
   floor.
4. Prototype whichever data-bundling option §3.2 lands on, once it's
   decided — not blocked on the size work above, can run in parallel.

## 5. Implementation steps (once spike confirms numbers)

1. `v4/Cargo.toml`: add `[profile.release]` with whatever §4.1 confirms
   (at minimum `strip = true`, which already has a confirmed number
   behind it).
2. `v4/Cargo.toml`: trim `datafusion`'s features per §4.2's confirmed
   safe list.
3. Add a real `v4/Dockerfile` (multi-stage, per §3.3.3/§4.3) — first
   Rust Dockerfile this repo will have.
4. Wire §3.2's chosen data-bundling approach into that Dockerfile
   and/or the deployment manifests it needs alongside it.
5. Extend `.github/workflows/` (or a new V4-specific workflow) to build
   and push the V4 image, following the existing `main.yml` template
   (`docker/build-push-action@v4`, GHCR, multi-platform) — decide
   whether V4 replaces V3's workflow outright or runs alongside it
   during a transition period (not decided here, `v4-server-prototype.md`
   scope question).
6. If §3.1's build-time secret mechanism ends up needed for §3.2's
   chosen data source, wire it in following §3.1's pattern.
7. Update `v4/README.md` with a "Building the container" section,
   matching the existing "## API docs"/"## Endpoints" style.

## 6. Open questions

- **Whether the expression-function features ever get cut.** §3.3.2
  deliberately keeps them on in the first pass, given the forward-
  looking concern that more expressive SQL may be needed for future
  SIC/EDGAR lookups. If the format/codec-only trim plus §3.3.1's
  profile tuning still leaves the binary too large, revisiting this
  needs its own explicit decision — which specific expression families
  are actually safe to drop for *this* project's query patterns, not a
  blanket re-cut — not something to fall back to quietly.
- **Real production-scale SIC/embedding data size.** §1.2's ~4.4MB is
  dev-scale. If the full national dataset plus embeddings is
  meaningfully larger, §3.2's tradeoffs shift — worth confirming before
  committing to an option.
- **Which data-bundling option (a/b/c, §3.2).** Depends partly on the
  above, partly on what deployment tooling `onprem-k8s-migration.md`
  actually lands on.
- **Multi-platform (`linux/amd64,linux/arm64`) build strategy for
  Rust specifically.** V3's existing workflow builds both platforms via
  QEMU emulation under `buildx` — fine for an interpreted Python image,
  but Rust compilation under QEMU emulation is often dramatically
  slower than native compilation; V4's build may need per-architecture
  native runners or a cross-compilation toolchain (e.g. `cross`)
  instead of straight `buildx`+QEMU, or may need to accept a slower CI
  build. Not sized or decided here — a real cost worth knowing before
  committing to the same multi-platform pattern V3 uses.
- **Static musl vs. glibc-slim runtime base.** Depends on whether
  `reqwest`'s `rustls-tls` (already the project-wide choice, no
  `native-tls` anywhere in `v4/Cargo.toml`) builds cleanly against
  `x86_64-unknown-linux-musl`/`aarch64-unknown-linux-musl` targets —
  not yet checked.
- **Whether V4's build replaces V3's `.github/workflows/main.yml`
  outright, runs alongside it, or gets its own workflow file** during
  whatever transition period V4's promotion to production takes —
  genuinely a `v4-server-prototype.md`-scope decision, not this doc's
  to make alone.

## 7. Explicitly out of scope for this doc

- Choosing V4's actual production deployment platform/topology — that's
  `docs/plans/onprem-k8s-migration.md`'s job; this doc only covers how
  the container image itself is built and sized.
- Any change to `v4-security-hardening.md` §3.5's rolling-secret
  *design* — §2 above explicitly keeps that decision as-is and only
  addresses how its one input (`MEDIUMROAST_SHARED_SECRET`) reaches a
  deployed instance, which was already partially specified there
  (company_dns's own K8s Secret) and isn't reopened here.
