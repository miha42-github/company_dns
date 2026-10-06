# V4 initial development release roadmap

Status: **Tracking doc (2026-09-30) — a checklist, not a design doc.**
Each major area below has its own detailed plan doc where one exists;
this doc sequences them toward one goal and adds the cross-cutting
items none of them individually own. Update checkboxes here as work
lands; keep the design detail in the linked docs, not duplicated here.
Owner: michael.hay@mediumroast.io
Scope: everything standing between where V4 is today (a working,
security-hardened, dynamically-logged server with no deployment
pipeline, no client examples, and large untested surfaces) and a real
**initial development release running in K8s** — not necessarily
replacing V3 in production yet (§0 makes that an explicit decision, not
an assumption).

**Decided (2026-09-30), from a user perspective, not the endpoint-by-
endpoint framing this doc's first draft defaulted to**, then corrected
twice against the real V3 OpenAPI spec (see §3's full rewrite — the
first two drafts of §3 were both wrong, kept below only as visible
history of how the scope actually got nailed down): **full V3.0 parity
ships in the initial dev/staging release for everything US-scoped**
(NA SIC full dataset, NA EDGAR including the catalog-backed
ciks/detail/summary endpoints, Wikipedia/merged v2), **plus one new
V4-only capability** (semantic search for SIC, with chunking for
descriptions longer than the embedding model's input limit — not yet
built). **Non-US SIC systems (EU, International/ISIC, Japan — UK
excluded indefinitely) are real, tracked, but explicitly NOT part of
this release** — they gate a later, separate `V4.0.0` milestone that
replaces V3 in production, staged as source data becomes available
(Japan next, others "over time"). UX is explicitly decoupled onto its
own track (§1); client SDKs ship Python and TypeScript only for v1, Go
and Rust deferred (§7); updating the top-level repo docs is its own
tracked item (§8).

---

## 0. First: decide what "initial development release" actually means

Not decided anywhere yet — needed before the rest of this doc's
sequencing makes sense.

- [x] **Decided (2026-09-30): two distinct milestones, not one.**
      1. **This roadmap's actual target — "initial development
         release"**: deployed to `company-dns-dev`/`company-dns-staging`
         only (per `v4-deployment.md` §3.4), **not** replacing V3 in
         `company-dns` (prod). Full US-scoped V3 parity (§3) plus the
         new semantic-search capability (§3).
      2. **A later, separate milestone — `V4.0.0`, the actual cutover
         from V3 in production** — explicitly gated on non-US SIC data
         (EU, International/ISIC, Japan — not UK) being sourced and
         wired in (§3a). Not this roadmap's job to complete, only to
         track as a known, named follow-on so it doesn't get
         conflated with "initial release" again.
- [ ] Decide a version/tag convention distinguishing the two (e.g.
      `v4.0.0-dev.N` for dev/staging builds under this roadmap, `v4.0.0`
      reserved for the real cutover once §3a's gate clears) — needed
      before §5's CI/CD work can actually push something taggable.
- [ ] Confirm this roadmap's exit criteria for milestone 1 specifically:
      dev/staging deployment live and reachable, §2's rate-limit docs
      shipped, §3's full-US-parity endpoints all present and the new
      semantic-search/chunking feature built, §4's coverage roadmap has
      a committed first milestone even if not "done," §5's image builds
      and deploys via a real pipeline, §6 has run at least once, §7 has
      at least one working SDK example. **Not** in milestone 1's exit
      criteria: anything from §3a.

## 1. UX — explicitly a separate track, not this release's critical path

**Decided directly**: *"New UX -- we'll work that separately."* UX
work stays on `company-dns-ux.md`'s own timeline and does **not** gate
this roadmap's release. Kept as its own section only so the decision
to decouple it is recorded, not because there's a checklist here to
work through.

- [x] Decided: UX is out of scope for this release, tracked separately
      in `company-dns-ux.md`. Nothing in §0's exit criteria should
      depend on UX work landing first.

## 2. Document rate limiting in the API docs

**Owning doc**: [`v4-security-hardening.md`](v4-security-hardening.md)
§5 step 4 — explicitly flagged and skipped as "optional polish" when
rate limiting shipped. Time to close it.

- [ ] Add 429 `ApiEnvelope` responses to every data endpoint's
      `#[utoipa::path(...)]` `responses(...)` block, so `/openapi.json`
      (and `/docs`/`/redoc`) actually document the rate-limit behavior
      a caller will hit, not just the happy path.
- [ ] Document the User-Agent gate itself in the OpenAPI spec's `info`/
      `description` (currently only in `v4/README.md`'s "## Security"
      section, not discoverable from `/docs` itself — someone exploring
      the API via Swagger UI has no way to learn *why* they're getting
      429s without already knowing to read the README first).
- [ ] Cross-link `v4/README.md`'s "## Security" section from the
      OpenAPI `info.description` (or vice versa) so both surfaces point
      at each other instead of drifting independently.

## 3. SIC and company data: full V3 parity for US scope, plus semantic search

**Owning doc**: [`v4-deployment.md`](v4-deployment.md) §3.2 (data-
bundling options, still undecided) and §6 (real production data size,
still unknown). **Ground truth for this section**: V3's real, live
OpenAPI spec, pulled directly from
`https://company-dns.mediumroast.io/openapi.json` (45 paths total) —
not memory, not assumption. This section went through two wrong
readings before landing here; corrected directly against that spec
rather than guessed a third time.

**What the real V3 spec actually contains**, and what it means for v1:

- **12 `/V2.0/` paths** — confirmed intentionally excluded, matches
  what was said directly. No V4 work.
- **NA SIC (5)** and **NA EDGAR (4: `ciks`/`detail`/`summary`/
  `firmographics`)** — **V4 already has all of these**, confirmed
  against `main.rs` (including the catalog-backed `ciks`/`detail`/
  `summary` endpoints this doc's first two drafts wrongly proposed
  deferring — they stay, full stop, for V3 parity). Nothing to build,
  just to keep.
- **Wikipedia/merged `/v2/`-suffixed explicit URLs (2)** — V3's own
  spec says `"same as default"` for these; V4's existing bare-path
  handlers already have the right behavior, just missing the explicit
  `/v2/`-suffixed alias URL itself. Small, mechanical addition.
- **Wikipedia/merged `/v1/` "[LEGACY] (wptools backend)" (2)** —
  already deliberately excluded (`v4/README.md` already documents
  this: V4's client is a port of V3's v2 backend specifically, no
  wptools equivalent exists). No change.
- **Non-US SIC systems (EU, International/ISIC, Japan, UK — 22
  endpoints) and the global cross-system SIC search (1)** — real,
  intentional gaps, **explicitly not part of this release** — moved to
  §3a below, a separate milestone.
- **The one genuinely new V4 capability, beyond matching V3 at all**:
  semantic search for SIC — matching one or more SIC codes against a
  free-text company description, with **chunking** for descriptions
  longer than the embedding model's input-size limit. **Not built
  yet** — confirmed by grep: `sic_similarity`'s current implementation
  (`main.rs`, `crates/sic/src/embed.rs::embed_query`) makes exactly one
  embedding call against the raw query text, no chunking logic
  anywhere in the crate.

- [x] Decided: full US-scoped V3 parity (NA SIC, NA EDGAR including the
      catalog-backed endpoints, Wikipedia/merged v2) ships in v1 as-is
      — confirmed already built for everything except the two `/v2/`
      alias URLs.
- [ ] Add the two missing `/v2/`-suffixed alias URLs for
      `wikipedia_firmographics`/`merged_firmographics` (same handlers
      as the existing bare-path versions, confirmed via V3's own spec
      that they're meant to be identical).
- [ ] **Build the semantic-search chunking feature** — the actual new
      work this release adds beyond parity. Needs: a chunking strategy
      for descriptions exceeding the embedding model's token/size limit
      (`crates/sic/src/embed.rs`'s current single-call `embed_query`
      has no such logic), and a decision on how chunk-level results get
      combined into "one or more SICs" for the caller (e.g. per-chunk
      top-k, then merge/dedupe/re-rank across chunks — not designed
      yet, worth its own short design note once started rather than
      improvised inline).
- [ ] Source the full real US SIC dataset (not the dev-scale sample
      used throughout this session's testing) — "all SICs we can
      muster" is a real sourcing requirement, not just a research
      question about size anymore.
- [ ] Resolve `v4-deployment.md` §3.2's data-bundling question for the
      full US SIC dataset plus the (already-ingested-at-build-time) NA
      EDGAR catalog — both stay in scope, so this doesn't get the
      simplification either earlier draft of this section assumed.

## 3a. Non-US SIC systems — real, tracked, gates `V4.0.0`, not this release

**Decided directly**: *"They are in scope minus the UK for now. At this
time only the US is available with Japan coming next and others over
time. The final location for download will be an initially deferred
decision... This is the gating factor for V4.0.0 cutover from V3.0.0.
However we can run dev or staging environments until these are ready."*

This is a named, real milestone — not a vague "someday" — just one
this specific roadmap doesn't complete. Tracked here so it isn't lost,
detailed design deferred to its own doc once work on it actually
starts (matching this project's own pattern: a plan doc gets written
once there's real substance to plan, not preemptively).

- [x] Decided: EU, International/ISIC, and Japan SIC systems are real
      `V4.0.0` requirements, staged by data availability (Japan next,
      others "over time"). UK is excluded with no timeline given —
      treat like the already-excluded `/V2.0/` endpoints for now,
      revisit only if that changes.
- [x] Decided: **this milestone does not block the initial dev/staging
      release** (§0) — `company-dns-dev`/`company-dns-staging` can run
      indefinitely on US-only SIC data while non-US data gets sourced.
- [x] **Japan SIC data landed (2026-10-01)**,
      `tmp/japan_rev13_flat_embedded.feather` - same flat/embedded
      schema as US SIC's feather file (confirmed column-for-column,
      plus five `*_ja` Japanese-language description columns), same
      embedding model/dimension. Turned out to be a drop-in fit for
      `crates/sic`'s existing structure, not the divergent ingest path
      §3a originally expected to need confirming - no new crate or
      schema work required, see `sic-global-search.md`.
- [x] **EU NACE data landed (2026-10-02)**, `tmp/nace_rev2_flat_embedded.feather`,
      registered as a third system and live in every keyword/semantic
      surface (`sic-global-search.md`). The first file had two upstream
      defects (wrong section labels on 52% of rows; no group level) -
      reported, fixed at the source, and the corrected file verified and
      pulled in the same day.
- [x] **The global cross-system SIC search endpoint - keyword and
      semantic variants built and live-verified** (`sic-global-search.md`):
      `GET /V4.0/global/sic/description/{query}` (+ `/V3.0/` alias) and
      `GET /V4.0/global/sic/similarity/{query}`, both fanning out across
      every registered system (US SIC + Japan SIC today). Wired into
      every keyword/semantic surface in the UI - the Keyword and
      Semantic tabs, and both of Compare mode's columns - sidebar
      filters and result cards included, all previously inert for lack
      of a second system. Only hybrid global search is **not** built
      yet - own open item in `sic-global-search.md`.
- [ ] Data-location/download mechanism for *future* additional SIC
      systems (EU, ISIC) — still deferred, "wait until available."
      Japan's own loading is done (`JAPAN_SIC_DATA_PATH`, optional/
      warn-and-continue at startup, same pattern as the EDGAR catalog).

## 4. Test coverage: audit, then a roadmap, not just "add tests"

**Real, measured current state** (grepped directly, not estimated):
`crates/cache`, `crates/edgar`, `crates/sic`, `crates/firmographics`
have **zero** `#[test]`/`#[tokio::test]` functions. `crates/wikipedia`
has 5 (client.rs, promoted from the wikipedia spike).
`crates/server` has 21 — but every one of them is in the
rate-limiting-derived modules (`user_agent.rs`, `trusted_origin.rs`,
`secret_ua.rs`); the actual HTTP route handlers
(`sic_description`/`edgar_ciks`/etc.), `rate_limit.rs`'s own tiering
logic, and `logging.rs` have **no direct unit tests at all** — every
verification of them this session was live, manual `curl` testing,
which is real evidence but not a repeatable, CI-enforced safety net.

- [ ] **Audit** (this section's own first deliverable): for each crate,
      list what's actually exercised only by the live `curl`
      verification record scattered across this session's plan docs
      versus what's genuinely untested even manually — the wikipedia
      client, SIC lookup/similarity, EDGAR catalog queries, the merge
      logic, and every route handler in `main.rs` are candidates to
      check specifically.
- [ ] `crates/sic`: unit tests for `lookup.rs`/`similarity.rs` against
      a small fixture `.feather` file (not the real `us_flat*.feather`,
      which isn't committed) — the SIC crate is core to §3's v1 scope
      (and will need to generalize for §3a's Japan/EU/International
      systems later) and currently has the least direct coverage of
      anything in that critical path.
- [ ] `crates/edgar`: unit tests for `catalog.rs`'s query logic against
      a small fixture catalog, and for `client.rs`'s firmographics
      fetch/cache behavior (mockable the way
      `crates/wikipedia/src/client.rs` already proved out with
      `wiremock`).
- [ ] `crates/cache`, `crates/firmographics`: at minimum, tests for the
      `merge()` logic's real branches (`edgar+wikipedia`,
      `wikipedia-only`, neither) — this exact function had a real bug
      found and fixed earlier this session precisely because nothing
      caught it automatically.
- [ ] `crates/server`: integration-style tests for the route handlers
      themselves (axum's `tower::ServiceExt::oneshot` pattern, used
      throughout `experiments/rate-limit-spike/` and
      `experiments/dynamic-log-level-spike/` already this session —
      same technique, promoted) — and for `rate_limit.rs`'s tiering/
      bypass logic specifically, which currently has zero automated
      coverage despite being the most security-relevant code in the
      crate.
- [ ] Once the above lands: **the roadmap-as-features-increase piece**
      raised directly — decide a coverage expectation for *new* work
      going forward (e.g. "no new endpoint or security-relevant module
      ships without tests," matching how `experiments/rate-limit-spike/`
      and `experiments/dynamic-log-level-spike/` were already built
      test-first this session) so this doesn't become a one-time
      catch-up that immediately falls behind again.
- [ ] Wire whatever test suite results from this into CI (§5) so
      coverage is enforced going forward, not just improved once.

## 5. Deployment scaffolding and binary slimming

**Owning doc**: [`v4-deployment.md`](v4-deployment.md) — fully
designed, **nothing in it spiked or implemented yet**. This is the
single largest remaining body of work in this roadmap.

- [ ] §4.1: `[profile.release]` tuning spike (`strip`, `lto`,
      `codegen-units`) — `strip = true`'s ~44MB/26% saving is already
      confirmed by measurement; `lto`/`codegen-units` still need a real
      spike.
- [ ] §4.2: DataFusion feature-trimming spike (format/codec cut only,
      expression-function libraries deliberately kept — §3.3.2's
      already-made decision).
- [ ] §4.3: the real multi-stage `v4/Dockerfile` — first Rust
      Dockerfile this repo will have — including resolving the static-
      musl-vs-glibc-slim open question.
- [ ] §4.4: prototype whichever data-bundling option §3.2 lands on
      (simplified by §3 above narrowing the dataset to SIC-only for
      v1).
- [ ] §4.5/§4.6: the GitHub Actions `ubuntu-latest`-runner plain-
      `docker run` smoke test, and standing up `company-dns-dev` for
      real — the actual platform-parity verification this whole
      deployment-environments thread started from.
- [ ] §4.7: real `kubectl top nodes` capacity check against the two
      real worker nodes before finalizing dev/staging resource
      requests.
- [ ] §3.7's multi-platform build *mechanism* (native runners vs.
      `cross` vs. accepting slower QEMU builds) — still genuinely
      undecided, now blocking §5's CI work concretely rather than
      abstractly.
- [ ] `k8s/dev/` and `k8s/staging/` manifests (§3.8), mirroring
      `k8s/prod/`'s proven shape.
- [ ] The actual CI/CD pipeline (§3.5/§5 of that doc): build → plain-
      Docker-on-Ubuntu smoke test → deploy dev → (later) promote
      staging → (later) promote prod. For *this* roadmap's scope
      (§0's dev-tier-first decision), the pipeline only needs to reach
      "deploy dev" to satisfy an initial release — staging/prod
      promotion can follow once dev is real and stable.
- [ ] ~~Distinct `MEDIUMROAST_SHARED_SECRET` SealedSecret~~ **superseded
      2026-10-05: the setting was removed; a per-tier credentials file
      (`v4-sql-endpoint.md`) replaces it, needed only if the SQL endpoint is
      enabled.** Originally: provisioned for
      whichever environment(s) this release actually reaches (§3.4) —
      design already done in `v4-security-hardening.md` §3.5, not yet
      actually provisioned anywhere.
- [ ] `v4/README.md` "Building and deploying the container" section
      (§5 step 9 of that doc).

## 6. Testing: automated and human

- [ ] **Automated**: §4's growing test suite, run in CI on every push
      (ties directly into §5's pipeline work — there's no CI at all for
      V4 yet, so this is also where "tests run automatically" first
      becomes true, not just "tests exist").
- [ ] **Automated**: extend `perf_tests/baseline.py`'s `--profile v4`
      run (already exists, already used for the V3-vs-V4 comparison
      earlier this session) to cover whatever endpoint set §3 leaves in
      scope for v1, and re-run it as a release-gate check, not just a
      one-off comparison.
- [ ] **Human**: a deliberate exploratory/UAT pass against the deployed
      `company-dns-dev` environment once §5 makes that real — walking
      through `/docs` (Swagger UI) as a first-time external consumer
      would, which is exactly the audience `company-dns-ux.md` §1
      frames this project around.
- [ ] **Human**: a security-focused pass specifically exercising
      `v4-security-hardening.md`'s rate-limiting/bypass logic by hand
      against the real deployed environment (not just the local
      spike-stage live-verification already done) — confirms the
      §5 pipeline's real deployment behaves the same way the local
      testing proved.
- [ ] Decide and document where results/findings from both tracks get
      recorded (a lightweight test-plan doc, or just tracked here as
      this roadmap's own checkboxes get checked off) — not designed in
      detail in this doc, worth a short decision before §6 actually
      starts.

## 7. Sample client SDKs: Python and TypeScript for v1, Go and Rust deferred

**Decided directly**: *"New client SDKs (Python and Typescript to
start, others deferred)."* Go and Rust move out of this release's
scope entirely — not designed, not stubbed, revisit once Python/
TypeScript prove out the approach. Net new work either way, nothing
started. Directly serves `company-dns-ux.md` §1's framing of this
project as "a reference implementation of real, useful things you can
build on top of this data" — sample SDKs are exactly that, made
concrete.

- [x] Decided: v1 ships Python and TypeScript only. Go and Rust
      deferred, no target release set for them yet.
- [ ] Decide scope for the two in-scope languages: full-featured
      client library, or a minimal "here's how to call the API and
      handle the envelope shape" example — probably the latter for an
      initial release, given `company-dns-ux.md`'s "clarity over
      polish" framing; confirm rather than assume.
- [ ] Each SDK should demonstrate: the `ApiEnvelope` shape (§2's work
      makes the 429 case visible in the spec, worth demonstrating
      handling it), the required-`User-Agent` convention
      (`v4-security-hardening.md` §3.1 — a real external caller needs
      to know to set one), and at least one call into whatever §3
      leaves as v1's actual endpoint surface (SIC lookup/similarity,
      plus the three live-lookup endpoints).
- [ ] Once `/openapi.json` is real and stable (already true today) and
      §2's rate-limit documentation lands: consider whether Python/
      TypeScript should be **generated** from the OpenAPI spec (e.g.
      `openapi-generator`, language-specific codegen) rather than
      hand-written, for at least the request/response types — a real
      time-saver, worth evaluating before committing to hand-writing
      both from scratch.
- [ ] Decide where these live — a `sdks/`/`clients/` top-level
      directory in this repo, or separate repos per language — not
      decided here.

## 8. Additional items not in the original list, added here

Raised from this session's own accumulated knowledge of what's
actually outstanding, not from the original 7-item list:

- [ ] **CORS policy.** Explicitly deferred in `v4-security-hardening.md`
      §7 as "a product decision... worth its own short doc if/when it's
      raised." `CorsLayer::permissive()` currently matches V3's own
      wide-open behavior, so it's not a regression — but an *initial
      release* aimed at external SDK consumers (§7) is exactly the
      moment this decision stops being hypothetical. At minimum:
      confirm permissive CORS is the intended posture for a public dev
      release, don't just let it ride by default inertia.
- [ ] **Final V3-vs-V4 parity/perf sign-off.** The comparison harness
      (`perf_tests/compare.py`, `baseline.py --profile v4`) already
      exists and has already produced one real comparison earlier this
      session — but that was mid-development, not a release gate. Worth
      one final, deliberate run against whatever §3 leaves as v1's
      scope, treated as a checklist item this roadmap gates on, not
      just background information.
- [ ] **Secrets audit before anything public-facing.** Confirm
      the credentials file, if the SQL endpoint is enabled (formerly
      `MEDIUMROAST_SHARED_SECRET`, removed), is actually provisioned (§5) and that
      no test/placeholder secret value from this session's own spikes
      (`experiments/rate-limit-spike/`, `experiments/dynamic-log-level-spike/`)
      ever made it anywhere near a real deployment.
- [ ] **`v4/README.md` pass for an external-consumer audience.**
      Currently reads as an internal prototype doc ("V4 (prototype)")
      more than a release-facing README — worth a deliberate editing
      pass once §1's UX conversation and §7's SDK work clarify who's
      actually meant to read it.
- [ ] **Update the top-level repo docs.** Raised directly, and
      confirmed by checking: the root `README.md` has **zero mentions
      of V4 anywhere** — it's entirely V3-focused (install instructions,
      "On-prem Kubernetes (how the live deployment actually runs)",
      changelog through V3.3.0). Before an initial V4 release, someone
      landing on the repo root needs to learn V4 exists, what it is
      relative to V3 (a rewrite in progress, not yet replacing it per
      §0's dev-tier-first decision), and where to actually find it
      (`v4/README.md`). Root `CHANGELOG.md` likely needs a first V4
      entry too, once §0's version/tag convention is decided.
- [ ] **Basic monitoring/alerting for V4**, in the observability stack
      that already exists cluster-wide
      (Prometheus/Grafana/Loki/Tempo, `v4-deployment.md` §1.3 —
      company_dns pods show up there automatically via node-exporter/
      kube-state-metrics with zero extra work, but that's baseline
      infra metrics, not an application-aware alert). Given this
      session's entire rate-limiting thread started from *"the current
      python version is being hammered by attackers"* discovered only
      by manually pulling logs after the fact, at least one alert on a
      real signal (e.g. a sustained 429 rate, or repeated draconian-
      tier hits from one IP) seems worth having before or shortly after
      an initial release, not discovered the same reactive way again.
- [ ] **Decide V4's `.github/workflows/` relationship to V3's**,
      already flagged as undecided in both `v4-deployment.md` §6 and
      `v4-server-prototype.md` — needs resolving as part of §5's actual
      pipeline build, not left open indefinitely.
- [x] **Server-side pagination — scoped, explicitly deferred to
      `V4.1.0`.** Full design in `v4-server-pagination.md` (SIC
      keyword/semantic endpoints currently return a full result set,
      paginated only via client-side `.slice()`). Not part of this
      roadmap's initial dev/staging release or the `V4.0.0` cutover
      milestone (§3a) — raised and scoped now specifically so
      `sic-hybrid-search.md` and `sic-global-search.md` don't both
      build on the same unpaginated pattern and need the same fix
      applied twice more later.

## 9. Suggested sequencing

Not a strict waterfall — several tracks can run in parallel — but real
dependencies exist worth calling out:

1. **§0 first** — nothing else in this doc has a stable target without
   it.
2. **§3 is now decided** (this session, after two corrections) — its
   remaining checkboxes (the two `/v2/` alias URLs, the semantic-search
   chunking feature, sourcing the full US SIC dataset, the data-
   bundling decision) can proceed immediately, and narrow scope for §4
   (what needs tests), §5 (what needs bundling/deploying), §6 (what
   gets tested), and §7 (what the SDKs demonstrate).
3. **§3a is explicitly parked, not sequenced into this roadmap at
   all** — it proceeds on its own, separate timeline (data
   availability, not this roadmap's pace) and doesn't block, or get
   blocked by, anything else here. Revisit this roadmap's own
   sequencing only once §3a's gate gets closer to clearing.
4. **§4 and §5 in parallel** — test coverage doesn't block deployment
   scaffolding or vice versa, but both feed §6.
5. **§2 is small and independent** — can land anytime, no dependencies.
6. **§1 (UX) is fully decoupled** — explicitly not a dependency for
   any other section anymore; §7's SDKs proceed against §3's now-
   decided endpoint scope without waiting on it.
7. **§6 depends on §4 and §5 both being real**, not just designed —
   the human UAT pass specifically needs a real deployed
   `company-dns-dev` (§5) to walk through.
8. **§8's items are cross-cutting** — CORS and the secrets audit belong
   before release; the top-level repo docs update pairs naturally with
   whichever milestone §0's exit criteria treats as "release," so it
   can land last without blocking earlier work; monitoring/alerting can
   trail slightly behind without blocking an initial dev-tier release.
