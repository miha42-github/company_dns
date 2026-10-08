# V4.0.0: the remaining steps from "feature complete" to running on staging

Status: **In progress (updated 2026-10-07).** Seven steps proposed by the owner, reviewed here, with changes, additions and the
remaining open questions. **Done so far: step 5's size measurements and the two release profiles, step 1 (API docs), step 2 (Swagger and ReDoc), New E (the 15 non-US
endpoints, the two `/v2/` aliases, and, added back by the owner, V3's limited V2.0 set), and step 3's suite (`api_tests/`, 87 tests across layers L0 to L5), which
found and fixed several defects and measured four remaining gaps in the V3 aliases.** Not started: the parity run itself, CI wiring, the containers and staging.
See "Progress" below for the item-by-item state.
Owner: michael.hay@mediumroast.io
Scope: the work between "V4 is feature complete" and "V4 runs on staging and has been
verified against V3". Out of scope: promotion to production, the dev tier, and anything
the existing plans already own (this doc **links to them rather than restating them**).

Existing plans this builds on:

| Topic | Owning doc |
|---|---|
| Image, binary thinning, data bundling, environments, the API test suite design | [`v4-deployment.md`](v4-deployment.md) (§3.2 data, §3.3 thinning, §3.4 tiers, §3.5 pipeline, §3.6 parity suite, §3.7 multi-platform, §3.8 manifests, §3.9 API test suite, §4 spike, §5 steps A to G) |
| OpenAPI generation and `/V3.0/` aliases | [`v4-openapi-docs.md`](v4-openapi-docs.md) |
| Rate limiting, the User-Agent ladder, trusted origin | [`v4-security-hardening.md`](v4-security-hardening.md) |
| SQL endpoint, profiles (credentials and rules files), staging capacity test | [`v4-sql-endpoint.md`](v4-sql-endpoint.md) §5a, §5c, §8 |
| Release scope, V3 parity decisions, secrets audit, CORS | [`v4-initial-release-roadmap.md`](v4-initial-release-roadmap.md) §2, §3, §3a, §6, §8 |
| Industry Match | [`company-sic-match.md`](company-sic-match.md) |

---

## Progress (as of 2026-10-07)

Step 5 was picked up first, by choice, because its measurements (where the bytes are, what each option costs) did not depend on anything else. **The Swagger fix
(step 2) was skipped over, not decided against: it is a one-line change and is the cheapest thing left.** Everything below is verified against the repository, not remembered.

| Item | State | What exists | Next action |
|---|---|---|---|
| **1. API docs include SQL, marked experimental** | **Done (2026-10-07)** | Spec description (access ladder, rate limits, experimental), 401 and 429 on every operation but `/health`, all 17 tags described, request examples for `/match`, `/map`, `/sql`, the empty licence fixed; seven new spec checks in the live battery (58 total), shown to fail on the old spec. | The spec checks move into the step 3 suite when it exists. |
| **2. Swagger look and feel** | **Done (2026-10-07)** | `/docs`: base layout (no top bar or logo), Basic credential persists, request duration shown. `/redoc`: our own template pinned to a light scheme, **the Redoc 2.5.4 bundle vendored and served by the server (MIT, licences and notices alongside, SHA-256 pinned by a test), and no web fonts**. **Decided: both documentation sites stay light.** Verified in the browser with the system theme forced to dark: both light and readable, and every request the `/redoc` page makes goes to `localhost` (nothing to a CDN or a font host). | Nothing open. Branding stays deferred. |
| **New E. 15 non-US endpoints, two `/v2/` aliases, and the V2.0 set** | **Done (2026-10-07)** | The 15 EU NACE, ISIC and Japan lookups, each at `/V4.0/` (a list) and `/V3.0/` (V3's exact shape); the two `/v2/` Wikipedia and merged aliases; **V3's limited V2.0 set added back (11 paths)**; the five US `/V3.0/na/sic/` aliases switched to V3's shape; About page and README updated. 15 of 19 captured V3 production responses are matched exactly, the other 4 differ only in data. | The EDGAR, Wikipedia and merged `/V3.0/` aliases still need comparing with V3 (step 4); an item in step 4 below. |
| **3. Python test suite** | **Done except CI wiring (2026-10-07)** | `api_tests/`: 90 tests in layers L0 smoke, L1 contract (every one of the 75 operations, table-checked against the live spec), L2 data readiness, L3 parity with V3 (25 V3 production fixtures), L4 V4-only functions, L5 limits and profiles (the shell battery ported; starts its own server). `run.py --layers --report` and `compare.py`. Found and fixed 4 defects (below). | Wire the fast layers into CI (item D); decide the four V3-shape gaps (Q14). |
| **4. Parity run on live V3 and V4** | **Inputs ready** | The suite and 25 V3 fixtures; the parity method proven on New E (15 of 19 identical) and measured on EDGAR, Wikipedia and merged: **summary and Wikipedia match V3's shape; `ciks`, `detail`, firmographics-by-CIK and merged do not** (Q14). No parity matrix yet. | Write the matrix. `api_tests/parity_report.py` already runs the 25 requests against V3 and V4 live, with timings: 16 identical, 5 same shape (data differs), 4 different (Japan description search, `ciks` catalog vintage, Wikipedia `performance` key, merged); local lookups about 16x faster than V3 (median 4.3 ms against 67 ms), upstream-backed routes faster only when warm (cold Wikipedia and EDGAR detail are comparable to V3). |
| **5. Thin the binary** | **Measurement and options done; acceptance pending** | The size spike (component map, nine variants, latency, memory, the 51-case battery); two named profiles `release-lean` (89.2 MiB) and `release-small` (62.3 MiB) and the DataFusion feature trim in `v4/Cargo.toml`, built and verified; results in this doc. | Linux amd64 sizes, the regression check against the step 4 baseline, the model's packaging decision, and the lean-or-small choice (after step 6). |
| **6. Docker builds, V3 and V4** | **Not started** | V3 has a `Dockerfile`; **V4 has none**. | Write the V4 Dockerfile (a build argument selects the profile), with the data gate. |
| **7. Staging** | **Not started** | `k8s/prod/` only; no `k8s/staging/`. | Needs step 6. |
| **A. Data-integrity gate** | **Not started** | `check_ic_feather.py` exists and works by hand. | Wire into the V4 build (step 6). |
| **B. Security and CORS review** | **Not started** | CORS is still `permissive()`. | Decide the CORS policy; secrets audit. |
| **C. Release hygiene** | **Not started** | | Version, changelog, migration note. |
| **D. CI for V4** | **Not started** | No V4 workflow. | A workflow running tests and the fast suite layers. |
| **F, G. Rollback, observability** | **Not started** | | Rehearse on staging. |

**Out of order, and what that means.** Step 5 ran before step 4, so the "no regression" half of its acceptance rule (against a step 4 baseline) has not been applied
yet. The measurements and the two profiles stand on their own; what waits is the regression check, the Linux numbers and the choice between the options.

**Suggested next:** write the parity matrix and run the parity run (step 4); wire the fast test layers into CI (item D).

---

## 0. Things I found while reviewing that change the plan

These are the reason the steps below differ from the original seven.

1. **The embedding model and ONNX runtime are not in the packaging plan.** V4 uses
   `fastembed` (all-MiniLM-L6-v2). The model (about 87MB, `models--Qdrant--all-MiniLM-L6-v2-onnx`)
   is downloaded from the network into a cache directory relative to the working directory
   (`.fastembed_cache`) the first time the server starts. In a container that means one of three
   things: it is baked into the image, it is on a mounted volume, or the pod needs outbound access at
   start (and fails to start without it). `v4-deployment.md` sizes the image as "binary plus about
   17MB of data"; the real runtime payload is the binary, the data, **and the model**, and the
   ONNX runtime has to work on the chosen base image (this is also the real constraint behind the
   open static-musl-versus-glibc question in §6 of that doc). This must be settled before step 5 or 6.
2. **Parity scope had a gap, and the roadmap's count of it was off.** Counted from `company_dns.py`, V3 has 46
   routes (45 in the public spec; `/` is hidden): 11 under `/V2.0/`, 9 US (`/V3.0/na/`: SIC five, EDGAR four),
   **15 non-US per-system endpoints** (EU 5, International 5, Japan 5), **2 UK**, 7 under `/V3.0/global/`
   (global SIC description, and Wikipedia and merged firmographics each as default, `/v1/` and `/v2/`), and
   `/health`. (The roadmap said 22 non-US endpoints; the code says 17 including UK.) V4 served 12 of these under `/V3.0/`.
   **Resolved 2026-10-07:** the 15 per-system endpoints (Q3, built before release) and the two `/v2/` aliases are built, and **the owner added the
   limited V2.0 set back** (see "The V2.0 set is back" below). Still not in V4, by decision: the UK pair and the `/v1/` wptools backends.
   **Found while building: V4's existing "V3 aliases" did not answer in V3's shape** (see below).
3. **The OpenAPI documentation items from roadmap §2 are still unchecked**, and they belong in step 1:
   429 responses on every data endpoint, and the `User-Agent` and rate-limit behaviour in the spec's
   own `info.description` (today it is one line, "Company firmographics and SIC code lookup service").
4. **The order matters for the thinning check.** The original order thins the binary, then
   containerises, then compares. To show that thinning did not regress anything there has to be a
   baseline taken **before** thinning. Step 4 provides it, if it runs on the unthinned binary.
5. **There is no "live V4" until step 6 or 7.** Step 4 says "run against live V3 and V4". The only V4
   that exists today is a local process. The plan below runs step 4 against a local V4 binary and re-runs
   the same suite against the containers (step 6) and staging (step 7), with `compare.py` between runs.
6. **The binary has grown; the size spike (step 5) measured where the bytes are, and it is not where I first guessed.** Measured 2026-10-06 on the macOS
   arm64 release build: **181 MiB unstripped, 136 MiB stripped** (the owner's figure was about 127MB; the Linux amd64 build will differ and must be
   re-measured). `v4-deployment.md` §1.1 measured 172 and 128 before the embedding work. By linked symbol bytes, **DataFusion and Arrow are about two thirds
   of the binary, and the ONNX Runtime is about 16 MiB**: its prebuilt static library is 67 to 77 MiB, but the linker discards most of it. See step 5 for the table.
   The 50MB goal therefore turns mostly on DataFusion, not on the embedding stack.
7. **`CorsLayer::permissive()` is on for every route** (`v4/crates/server/src/main.rs`). With HTTP Basic
   Auth and an SQL endpoint now present, CORS should be a deliberate decision before staging, not a
   default. Roadmap §8 already lists CORS and the secrets audit as "before release".

### The V2.0 set is back, and what the V3 aliases now are (decided 2026-10-07)

**V2.0.** V4 had excluded V3's `/V2.0/` paths (decided 2026-09-28: "`/V3.0/` only"). The owner reversed that on 2026-10-07: the **limited V2.0 set is served again**, and the
About page says so. "Limited" is what V3 itself has: 11 paths, US and global only (no regional prefix): `/V2.0/sic/{description,code,division,industry,major}/...`,
`/V2.0/companies/edgar/{detail,summary,ciks}/...`, `/V2.0/company/edgar/firmographics/...`, `/V2.0/company/wikipedia/firmographics/...`, `/V2.0/company/merged/firmographics/...`.
V3 serves each with the **same handler as its `/V3.0/` twin** (confirmed against a production call: the two answers are byte-identical), so in V4 each is an alias of its twin. They are in
the OpenAPI document (tags "... (V2.0, alias)"), on the About page (a "V2.0 (Limited Legacy)" tab beside V4.0 and V3.0), and in the README. The decision records in `v4-openapi-docs.md` and
`v4-initial-release-roadmap.md` carry a dated reversal note.

**The V3 aliases and the data shape (a finding, then a decision).** Comparing V4 with V3 production for the same US lookup showed that V4's `/V3.0/na/sic/...` aliases returned V4's shape (a list with flat
field names) while V3 answers with a dictionary keyed by code, a `total`, and V3's own field names, messages and module strings. The envelope matched; the data, message and module did not, so a V3
integration pointed at V4 would have broken. **Decided (owner, 2026-10-07): the `/V3.0/` and `/V2.0/` paths answer in V3's exact shape, and `/V4.0/` answers in V4's.** Done for the US SIC
aliases and for all the new non-US ones. **Not yet checked against V3: the `/V3.0/` aliases for EDGAR, Wikipedia and merged firmographics**; they are a step 4 item.

## 1. The seven steps, reviewed

| # | Original step | Verdict | Change |
|---|---|---|---|
| 1 | API doc includes SQL, marked experimental | Keep, widen; **done 2026-10-07** | The SQL operation was already tagged `experimental` with a Basic-auth scheme. Added: how SQL shows when the flag is off (nothing), the access ladder and rate limits in the spec, 401 and 429 on every operation, tag descriptions, examples, and roadmap §2 closed. |
| 2 | Reskin Swagger | Keep; small | Most of the "ugliness" is Swagger's standalone top bar. One setting removes it. **Decided (Q4): top bar now, branding later.** **Done 2026-10-07**, including pinning `/redoc` to a light theme (it was unreadable under a dark system theme); both sites stay light. |
| 3 | Extend the perf suite, V3 core then V4, in Python | Keep; reshape | Build a **functional layer beside** the perf suite, as `v4-deployment.md` §3.9 already designs, with stdlib plus `requests` only. Port the SQL shell battery into it. |
| 4 | Run against live V3 and V4 for parity | Keep; define parity | Parity needs classes (identical, equivalent, absent by decision), normalisation of live data, and a politeness policy for live V3. Run it **before** thinning so it is the baseline. |
| 5 | Thin the binary | Keep; measured, two options preserved | Follow `v4-deployment.md` §3.3 and §4. **Measured 2026-10-06:** 50MB raw is not reachable at acceptable speed; two named profiles (lean about 89 MiB, small about 62 MiB) are kept and the choice is confirmed after testing. Still open: the model and ONNX packaging question, Linux sizes, and the regression check. |
| 6 | Docker builds of V3 and V4 side by side on amd64 (and arm64) | Keep; add a definition of "fair" | Equal resource limits, same test runner, same data, cold and warm. **Decided (Q2, Q8): the two amd64 worker nodes plus the Mac Studio for arm64, no quiet-window constraint.** Includes the data-integrity gate from `v4-deployment.md`. |
| 7 | Deploy on staging | Keep; add what has to be true first | Wiring for profiles, the SQL capacity test, the §3.6 platform-parity checks, and go/no-go criteria for later promotion. |
| New E | Build the 15 per-system non-US endpoints and the two `/v2/` aliases | Add (decided, Q3) | Ahead of step 3, because the V3 inventory and the parity matrix include them. See §4. |
| New A | Data-integrity gate | Add | `check_ic_feather.py` as a build gate (already planned, not wired; see step 6). |
| New B | Security and CORS review | Add | Before staging holds real credentials. |
| New C | Release hygiene | Add | Version, changelog, V3-to-V4 migration notes, tagging. |
| New D | CI for V4 | Add | There is no CI for V4 yet (roadmap §6). Steps 3 and 6 need it. |

## 2. Order and dependencies

```
 1 API docs ─┐
 2 Swagger  ─┤  (independent, small, can start now)
 New E non-US endpoints ─┐
             │           ▼
 3 Test suite ──► 4 Parity run on V3 live + local V4 (unthinned)  ──► baseline results
                                      │
 New B security/CORS review ──────────┤
                                      ▼
                 5 Thin the binary  ──►  6 Docker, V3 and V4 side by side (amd64)
                                          (rerun suite; compare with step 4 baseline)
                                      │
                 New A data gate and New D CI feed step 6
                                      ▼
                                7 Staging  (rerun suite, SQL capacity test, platform checks)
```

Step 5's measurement and profiles were done early (2026-10-06; see "Progress"), so the box for step 5 in the diagram is only half drawn: its regression check still follows step 4. Steps 1, 2, New E and the first layers of step 3 can run in parallel; the parity layer of step 3 and step 4 need New E. Step 4 needs step 3. Step 5 needs the step 4 baseline and the
model-packaging decision (§0.1). Step 6 needs step 5 and an amd64 host. Step 7 needs step 6 and the
staging manifests.

## 3. The steps in detail

### Step 1: API documentation includes SQL, marked experimental

**Status: done (2026-10-07).**

**What was done**, all in `v4/crates/server/src/` (`main.rs`, `sql_endpoint.rs`, `api_description.md`):
- **The spec's own description** (`info.description`, `api_description.md`, rendered as Markdown by both `/docs` and `/redoc`): the access ladder as a table (nothing or a generic `User-Agent`, a
  self-identifying `User-Agent`, an authenticated profile), the rate-limit behaviour (`429` with `Retry-After`, a wrong Basic credential is a `401`, `Origin` and `Referer` are not identity, the exempt routes),
  an **Experimental** section about `POST /V4.0/sql`, and links to the README's Security, Profiles and Experimental SQL sections.
- **401 and 429 responses on every operation except `/health`** (30 annotations edited; `/V4.0/sql` already had them). Before: 30 of 32 operations documented neither.
- **Tag descriptions:** all 17 tags are declared with a description (V4 groups first, then the `/V3.0/` aliases, `experimental` and `System`), so groups read as explanations.
- **Examples** for the three V4-only request bodies: `/match`, `/map`, `/sql` (the Swagger "Example Value").
- **The empty licence fixed:** the spec's licence name was blank (ReDoc showed "License:" with nothing after it); it is now Apache-2.0 (the repository's licence), with a contact link to the project.

**Decisions made while doing it:**
- **When SQL is off, the docs show nothing** (as recommended): the route is not registered, so `/docs` and `/redoc` never mention an endpoint that does not exist. The spec's description still explains the
  experimental endpoint in general terms ("appears here only on servers where it is enabled"), and the README documents it.
- **No separate "Experimental features" page**: the README's "Experimental: SQL endpoint" section is the page, and the spec links to it. Revisit if a second experimental feature appears.

**The spec check** (the plan's "spec test") is in the live battery for now: `v4/scripts/sql-try.sh check` gained seven spec checks (every operation except `/health` documents 429 and 401; every tag in use is
declared with a description; the description explains the ladder and marks SQL experimental; the licence is filled in; the three request bodies have examples), on top of the two that were there (SQL is tagged
`experimental`; the Basic scheme is declared). **Verified they have teeth:** six of the seven fail against the spec as it was before these changes. The battery is now 58 checks. They move into the step 3 suite (L1 contract) when that exists.

**Exit met:** `/docs` and `/redoc` on a local server with SQL on show SQL clearly as experimental with its access rules; the roadmap §2 boxes are checked (`v4-initial-release-roadmap.md`); the spec checks pass.

### Step 2: Swagger look and feel

**Status: done (2026-10-07). Decided: both documentation sites stay in a light theme.**

*Swagger (`/docs`):* `SwaggerUi::new("/docs").url("/openapi.json", api).config(Config::default().use_base_layout().persist_authorization(true).display_request_duration(true))`
in `v4/crates/server/src/main.rs` (the crate's own pattern: `.url()` registers the spec, so the config does not repeat it). Verified in the browser: no top bar or logo,
the white theme and the Authorize button intact, the generated config serves `"layout": "BaseLayout"`, and the experimental SQL operation appears with its lock icon.

*ReDoc (`/redoc`):* the default page turned unreadable under a dark system theme (a near-black main panel with low-contrast text beside a light sidebar; fine in light mode), because the
template sets no colour scheme. It is now served from our own copy of the template, `v4/crates/server/src/redoc.html` (utoipa-redoc's default plus `color-scheme: light` and a white
background; `$spec` and `$config` kept), through `Redoc::with_url("/redoc", api).custom_html(include_str!("redoc.html"))`. Verified with the browser forced to dark: **both `/docs` and
`/redoc` render light and readable.**

*Self-hosted (done 2026-10-07, the owner asked for it after the licence question):* the `/redoc` page used to load its script from `cdn.redoc.ly` (unpinned, "latest") and its fonts from
Google Fonts. That needed internet access in the reader's browser, ran whatever Redocly published next, and sent every reader's IP address to Google (a 2022 Munich court found embedding
Google Fonts that way breached GDPR). Now: Redoc **2.5.4**, the unmodified standalone bundle, is vendored in `v4/crates/server/assets/redoc/` (the pinned URL was byte-identical to what
the page had been loading), embedded in the binary and served at `/redoc/redoc.standalone.js` (`v4/crates/server/src/docs.rs`); the fonts are the system stack. Licences: Redoc is MIT
(Rebilly, Inc.), its bundled libraries are MIT and DOMPurify (Apache-2.0 or MPL-2.0); the texts sit next to the file and `v4/THIRD_PARTY_NOTICES.md` lists them, including Swagger UI
(Apache-2.0). Montserrat and Roboto were OFL, but they are no longer used. Tests pin the bundle's SHA-256, require the licence files beside it, and fail if the page template ever references a third party.
**Size:** the bundle adds about 1.05 MiB to the binary (about 319 KiB compressed); the lean and small numbers in step 5 were measured before it and each rise by about that much, to be re-measured.
**Obligation going forward:** anything that redistributes the binary or an image containing it must keep the notices file and the licence files with it (build the image step to copy them).

*Also visible and belonging to step 1:* the SQL group is the bare tag name "experimental" with no description.

The white theme stays. The part that looks poor is the **top bar with the Swagger logo**.

- **Smallest fix:** `utoipa-swagger-ui`'s `Config::use_base_layout()` switches from the standalone layout to
  the base layout, which removes the top bar and its logo. One line in `main.rs`. Confirm in the browser.
- **If branding is wanted:** `Config` has no custom-CSS option, so the choices are (a) serve our own small
  `/docs` page that loads the Swagger UI assets the crate already serves and adds a stylesheet (logo, colours,
  fonts matching the app UI), or (b) keep the default page and accept the base layout. (a) is about an hour of
  work and keeps the two pages (`/docs`, `/redoc`) visually consistent with the app.
- **ReDoc** at `/redoc` should get the same treatment, or be left plain if it already looks acceptable.
- No functional change; it must not break "Authorize" for the Basic scheme.

**Decided (Q4, 2026-10-06): remove the top bar now, branding later.** So this step is the one-line
`use_base_layout()` change (confirmed in the browser; if it turns out not to remove the logo, fall back to hiding the
top bar with a small custom page), plus a look at `/redoc`. Branding (own `/docs` page, logo, colours) is deferred until after
staging and needs the logo asset and brand colours from the owner.

**Exit:** `/docs` and `/redoc` reviewed in light and dark system themes by the owner; screenshots attached to
the PR.

### Step 3: The test suite (Python)

Design lives in [`v4-deployment.md`](v4-deployment.md) §3.9 and `perf_tests/README.md`; this step builds it.
What is new here is the inventory and the structure.

**Constraints (from §3.9):** Python, only the standard library plus `requests`, runnable from a laptop or a CI
runner unchanged, pointed at any server with `--base-url` and `--profile v3|v4`, results as JSON stamped with
git commit and image, diffable with `compare.py`.

**Layers**, each runnable on its own:

| Layer | Question it answers | Runs against |
|---|---|---|
| L0 Smoke | Is it up and sane? (`/health`, spec loads, one lookup per family) | anything |
| L1 Contract | Right status codes, the `{code, message, module, data, dependencies}` envelope, error shapes (404, 400, 401, 403, 429, 504), every route listed in the spec | V3 and V4 |
| L2 Data readiness | All four classification systems return results, the EDGAR catalog is loaded and spans the expected quarters, merged firmographics finds EDGAR for known companies | V4 (and V3 where the data exists there) |
| L3 Parity | Do V3-parity endpoints return equivalent content on V3 and V4? (step 4) | V3 and V4 together |
| L4 V4-only functions | Global keyword, semantic and hybrid search, Industry Match (`/match`, `/map`), SQL and profiles | V4 |
| L5 Limits and abuse | Rate-limit tiers, profile quotas, SQL caps, read-only guard, throttling, concurrency refusal | **non-production** V4 only |
| L6 Performance | Latency, concurrency, correctness under concurrency | V3 and V4 (existing `baseline.py`) |

**Inventory of V3 core functionality to cover** (from the live spec and `perf_tests/baseline.py`'s `ENDPOINTS`):
US SIC (description, code, division, industry, major), EDGAR (ciks, detail, summary, firmographics by CIK),
Wikipedia firmographics, merged firmographics, global SIC description, health, **and the 15 non-US per-system
endpoints once New E lands** (EU section, division, group, class, description; International the same five;
Japan division, major group, group, industry group, description). The current catalog covers
about seven of these with a `v4_path`; the rest get added. Companies come from the existing ten in
`perf_tests/companies.py`, plus a small set of deliberately awkward cases (a name with a corporate suffix, an
unknown company, an empty or very long query, non-ASCII).

**V4-only coverage:** global hybrid, similarity and similarity-check, Industry Match including the stepper's
`chunks` re-match and `map`, the SQL battery (port `v4/scripts/sql-try.sh check`'s 51 cases to Python so one
suite owns them; keep the shell script as the developer's local playground), and the profile cases (anonymous,
wrong credential, no grant, bypass, quota).

**Credentials for the tests:** L4 and L5 need profiles. The runner generates throwaway credentials and rules
(as `sql-try.sh setup` does) when it is told to start its own server, and otherwise reads a token from the
environment. No real credentials are ever committed or logged.

**Structure proposal:** keep `perf_tests/` as is (L6) and add `api_tests/` beside it (L0 to L5), sharing
`companies.py` and the base-URL plumbing; one runner `python3 api_tests/run.py --profile v4 --base-url ... --layers L0,L1,L2,L4`.
The standard library's `unittest` as the runner keeps dependencies at zero; a JSON report is written next to the
perf results.

**Run in CI:** L0, L1, L2, L4 and the non-network parts of L5 against a V4 started in the workflow, on every push
(this is also what makes "tests run automatically" true for V4, roadmap §6). L3 and L6 need live upstreams and a
stable environment and are run on demand and at the staging gate.

**Status: done except CI wiring (2026-10-07).**

**What was built** (`api_tests/`, standard library only; `api_tests/README.md` has the run options):

| Layer | File | Tests |
|---|---|---|
| L0 smoke | `test_smoke.py` | health, the spec, the docs pages (and that `/redoc` loads nothing third-party), one lookup per family, Industry Match |
| L1 contract | `test_contract.py`, `test_non_us_sic.py` | a table of **every route in the live spec** that fails if a route has no entry; a match is a 200 envelope; a no-match a 404 envelope **that the spec documents**; every error is the JSON envelope; 400s for bad input; the spec documents what the server returns |
| L2 data readiness | `test_data_readiness.py` | all four systems loaded with at least the classes they shipped with, hierarchies complete, parents correct, the embedding model loaded, the EDGAR catalog spanning at least 5 quarters for Apple, Microsoft and IBM, merged firmographics finding EDGAR data (network) |
| L3 parity with V3 | `test_non_us_sic.py`, `test_edgar_wikipedia_parity.py` | 25 production V3 fixtures: the non-US, US and V2.0 shapes identical, EDGAR summary and Wikipedia matching, and **one known gap (merged) marked `expectedFailure`** |
| L4 V4-only | `test_v4_functions.py` | global keyword, semantic and hybrid search, the tokeniser check, Industry Match (2 to 5 codes per system with evidence, chunking, the default system, re-matching kept segments) and map |
| L5 limits and profiles | `test_limits_and_profiles.py`, `server.py` | 32 tests: access, the User-Agent ladder, profile grants and quotas, the SQL guard and caps, per-profile limits, throttling. Starts its own server with throwaway credentials and small limits; skipped without a built binary |

87 tests: all pass against a local V4 (7 need `--network`, which also exercises the Wikipedia, SEC and merged routes). `run.py --report` writes a JSON report stamped with the commit and
`compare.py` diffs two of them (it exits 1 on a regression or when a known gap unexpectedly passes). `v4/scripts/sql-try.sh` stays as the developer's playground; its 58-check `check` and L5 cover the same behaviour.

**Defects the contract tests found, all fixed 2026-10-07:**
1. **An unknown `model` on `similarity`, `global similarity`, `hybrid` and `similarity-check` returned 500**; it is now a 400 (the match endpoint already did this).
2. **`match` with an unknown or empty `systems` list returned 200 with zero systems**; it is now a 400 naming the valid systems (as `map` already did).
3. **Axum's own rejections returned an empty, non-JSON body** (a bad `k`, a wrong method, a wrong content type); a small outermost layer (`v4/crates/server/src/errors.rs`, 5 tests) turns every such error into the JSON envelope and keeps the status and headers (`Allow`, `Retry-After`).
4. **The spec did not document the 404s and 400s the server really returns**: 22 operations now document their 404 and four their 400 (the contract test checks that every status the server returns is documented).

**What it measured (decision Q14, step 4):** four V3-shape gaps in the EDGAR and merged aliases; three are closed, and merged is the one `expectedFailure`, listed under step 4.

**Deviations from the design above, stated plainly:** (1) the V3 side of L1 and L2 is covered by fixtures captured from V3, not by running the suite against live V3 (running it live is the parity run, step 4); (2) the layers are test files, selected by `--layers`, rather than separate programs; (3) CI wiring (item D) is not done yet.

**Exit:** met: the suite passes against a local V4; the report format is stable and `compare.py` diffs two runs. Not met: running L1 and L2 against live V3 (moved to step 4), and green in CI (item D).

### Step 4: Parity run against live V3 and V4

Owning detail: `perf_tests/shadow_compare.py` already compares two V3 backends field by field and exits non-zero
on a mismatch; `perf_tests/results/v3-vs-v4-*.json` are the earlier V3-versus-V4 runs. This step extends that to the
whole V3-parity surface and states what "parity" means.

**Parity classes.** Every V3 path gets one of these in a checked-in matrix (`api_tests/parity.json`):

| Class | Meaning | Test |
|---|---|---|
| Identical | Same envelope and same data | exact field comparison after dropping volatile fields (timestamps, version) |
| Equivalent | Same meaning, expected differences | compare a defined set of fields; tolerate listed differences |
| Absent by decision | V4 intentionally does not serve it: the 2 UK paths and the legacy `/v1/` wptools backends (the 11 `/V2.0/` paths were on this list until 2026-10-07 and are served again) | assert V4 returns the documented 404, and that the spec does not list it |
| Intentionally different | V4 behaves differently on purpose | assert the V4 behaviour and name the reason |

**Measured 2026-10-07 for the EDGAR, Wikipedia and merged `/V3.0/` aliases** (V3 production responses in `api_tests/fixtures/v3/`, tests in `test_edgar_wikipedia_parity.py`):

| Route | Against V3 | Detail |
|---|---|---|
| EDGAR `summary` | **matches** (shape) | message and module text differ |
| Wikipedia firmographics | **matches** (shape and stable fields) | V3's message text differs |
| EDGAR `ciks` | **closed (Q14)** | `/V3.0/` and `/V2.0/` return V3's `{"companies": {name: cik-string}, "totalCompanies": N}` (`/V4.0/` keeps `{name: cik}`) |
| EDGAR `detail` | **closed (Q14)** | `/V3.0/` and `/V2.0/` nest V3's response per company (`code`, `data`, `dependencies`, `forms`, `message`, `module`) |
| EDGAR firmographics by CIK | **closed (Q14)** | `/V3.0/` and `/V2.0/` add `division`, `divisionDescription`, `majorGroup`, `majorGroupDescription`, `industryGroup`, `industryGroupDescription` from V4's US SIC data and use its `sicDescription`; Apple's values equal V3's (`v3_edgar.rs`) |
| Merged firmographics | **open gap, recorded as intentional for now (Q14)** | V3 returns one flat 41-field record (address, coordinates, Google links, SIC hierarchy, and so on); V4 returns `{edgar, edgar_match, query, source, wikipedia}`. (V3's coordinates and map links came from ArcGIS geocoding, which V4 does not do: an intentional difference already on this list) |

These are the `/V3.0/` and `/V2.0/` aliases only; the `/V4.0/` paths keep V4's shape, which the UI uses. Q14 closed the three smaller gaps; merged stays a recorded difference. The EDGAR `summary` answer now uses V3's message and module strings too.

**Known intentional differences recorded from New E (2026-10-07), against V3 production:** a no-match is a JSON 404 envelope (V3 answered with an HTML page); the `dependencies` block is V4's; V3's US `division` answer
carries a `full_description` narrative, which V4 serves from `v4/crates/sic/data/us_division_narratives.json` (generated from `source_data/sic_data/divisions.csv`, V3's text), so that answer is identical; V4's Japan file is the corrected one, so Japan division and group descriptions are upper-case (**confirmed by the owner on 2026-10-08: the government's English source HTML gives group names in upper case, and V3 was built from a partial extract of that project; source: https://www.soumu.go.jp/english/dgpp_ss/seido/sangyo/san13-3a.htm#a, JSIC Rev. 13, which prints `09 MANUFACTURE OF FOOD` and `091 LIVESTOCK PRODUCTS`, read 2026-10-08**)
and a Japan description search finds more classes (18 against V3's 13 for "food"); a `/V4.0/` answer is a list, not V3's dictionary.

**Other known intentional differences to record up front** (all from existing plans, not new decisions): the merged
endpoint is EDGAR plus Wikipedia with no ArcGIS geocoding; EDGAR `detail` and `summary` are catalog-only on V4; the
EDGAR catalog is a rolling two-year window on V4 against V3's full history; the version string differs; V4 caches
upstream responses (a repeat inside the TTL is a cache hit).

**Live data is not stable.** Wikipedia and EDGAR content changes, so L3 compares normalised, stable fields (CIK,
formal name, SIC code, country) rather than whole bodies, and any free-text field is compared loosely and reported,
not failed.

**Being polite to live V3 (decided, Q1: production V3, politely).** Production V3 calls SEC, Wikipedia and ArcGIS. The parity run uses the ten known
companies, runs sequentially with a pause, sets a self-identifying `User-Agent`, avoids business hours if asked, and
uses a low concurrency for any performance numbers. If Q1 is answered "a V3 we run ourselves", this concern largely
goes away and the run can be heavier.

**Output:** a parity report (counts per class, every mismatch with both bodies), a baseline JSON of V4 performance on
the **unthinned** binary, and the same for V3. These are the "before" for step 5.

**Exit:** zero unexplained mismatches; every mismatch either fixed or recorded in the matrix as an intentional difference
with a reason; the baseline JSONs are saved and referenced from this doc.

### Step 5: Thin the binary

Owning plan: [`v4-deployment.md`](v4-deployment.md) §3.3 (levers) and §4 (spike). Do not repeat it; execute it with
these additions.

**Target (Q5, 2026-10-06): the owner asked for the server binary at 50MB or less if it can be done safely; the measurements below show it cannot at acceptable speed with
compiler settings alone, so the outcome is two preserved options (decided in item 3), not 50MB.** "Safely" means: the step 3 suite passes unchanged, `compare.py` shows no latency
regression against the step 4 baseline (**not yet checked, because that baseline does not exist yet**), and cold start is not materially worse. Report **both** the binary and the
**image** (binary plus the embedding model plus the data), since the model alone is about 87MB and a 50MB binary is not a 50MB image.

**1. Measured 2026-10-06 (macOS arm64, release build as it is today; Linux amd64 still to do).**

*Where the bytes are* (from a linker map of the final link, by component; the map totals 133.5 MiB of symbols against a 136 MiB stripped file):

| Component | MiB | Share |
|---|---|---|
| DataFusion and Arrow crates (optimizer 8.8, core 7.2, expr 7.0, functions 5.9, physical-plan 5.2, aggregate 5.1, physical-expr 4.7, sql 3.9, nested functions 3.3, and the rest) | about 88 | 66% |
| of which `sqlparser` | 4.8 | |
| of which Parquet support (`parquet` 2.9 plus `datafusion-datasource-parquet` 2.1) | about 5 | (never used; safe to cut) |
| The server crate itself (all handlers, generics, `utoipa`) | 9.8 | 7% |
| ONNX Runtime bindings and the linked part of the static runtime (`ort-sys`) | 16.4 | 12% |
| Embedded Swagger UI assets (`utoipa-swagger-ui`) | 4.1 | 3% |
| Everything else (`chrono-tz` 1.2, `reqwest` 1.1, `regex-syntax`, and so on) | about 14 | 11% |

*By section:* code 98 MiB, **exception-unwinding tables 18 MiB** (12.3 `__eh_frame` plus 5.8 `__gcc_except_tab`), constants 14 MiB. The unwinding tables are the price of
`panic = "unwind"`, which stays (decided in §3.3: one panicking request must not take the server down).

*Baseline behaviour* of the current release binary, to compare every variant against: time to healthy about 0.3 s warm (2.9 s with a cold file cache), resident memory
**214 MiB idle and 266 MiB** after a semantic and a keyword query.

**Variant builds** (each stripped, each in its own target directory, the owner's tree untouched; macOS arm64, 2026-10-06). "gzip" is the compressed size of the
binary, which is closer to what an image layer costs to pull:

| Variant | Stripped (MiB) | gzip -6 (MiB) | Build time |
|---|---|---|---|
| Today's release profile, stripped (reference) | 136.0 | 46.6 | |
| C1: DataFusion without Parquet and compression codecs | 128.8 | | 3 min |
| A: `lto = "fat"`, `codegen-units = 1` | 94.9 | 35.6 | 10 min |
| **D1: C1 plus A** (the "safe" candidate) | **89.2** | about 34 | 9 min |
| D2: D1 plus dropping the crypto, encoding, regex and unicode SQL function libraries | 89.1 | | 9 min |
| **E: D1 plus `opt-level = "s"`** | **62.3** | **23.1** (zstd 16.6) | 6 min |
| F: D1 plus `opt-level = "z"` | 46.8 | | 4 min |
| H: D1 plus `panic = "abort"` | 74.8 | | 8 min |
| I: E plus `panic = "abort"` | 52.0 | | 5 min |

**What each variant does to speed and memory** (same machine, same data, 150 sequential requests per endpoint after warm-up, p50 in milliseconds; "x8" is 8 concurrent clients):

| Endpoint | Today | A | D1 | E (`s`) | F (`z`) |
|---|---|---|---|---|---|
| keyword SIC | 1.93 | 1.85 | 1.86 | 1.89 | 3.42 |
| EDGAR company lookup | 3.75 | 3.62 | 3.71 | 3.85 | 16.18 |
| global keyword | 4.81 | 4.62 | 4.60 | 4.69 | 8.32 |
| semantic search | 19.06 | 18.40 | 18.45 | 19.16 | 31.54 |
| hybrid search | 26.25 | 24.89 | 24.84 | 25.94 | 43.01 |
| Industry Match `/match` | 27.48 | 26.92 | 27.01 | 28.22 | 48.04 |
| SQL `group by` over the EDGAR catalog | 1.91 | 1.77 | 1.77 | 1.88 | 11.52 |
| SQL `like` scan over the EDGAR catalog | 1.89 | 1.76 | 1.79 | **2.42** | 12.98 |
| semantic, x8 (requests per second) | 89 | 92 | 92 | 88 | 64 |
| SQL scan, x8 (requests per second) | 2201 | 2263 | 2266 | 2017 | 508 |
| memory, idle / after load (MiB) | 215 / 466 | 211 / 448 | 211 / 447 | 210 / 446 | 209 / 407 |
| time to healthy | 0.3 s | | 0.30 s | | 0.29 s |

**Functional checks:** D1, E and F each passed the full 51-case live battery (`v4/scripts/sql-try.sh check`) unchanged; the unit tests (including 55 in the server crate)
pass with D1's DataFusion feature set. Not yet run: the step 3 suite (it does not exist yet), Linux amd64, and the V3 parity run.

**Reading the data:**
- **D1 is a free win**: 136 to 89 MiB (-34%), no slower (slightly faster), same memory. It is now the `release-lean` profile plus the DataFusion feature list in `v4/Cargo.toml` (built and verified), and costs about 9 minutes of build.
- **`opt-level = "s"` (E) gets to 62 MiB** (23 MiB gzipped) and matches today's speed everywhere except scan-heavy SQL, where it is about 28% slower per query and 8% lower in concurrent throughput.
- **`opt-level = "z"` (F) reaches 46.8 MiB, under the 50MB goal, but is 1.7x to 6x slower** (EDGAR lookups 4.3x, SQL scans about 6x). It fails the acceptance rule. Rejected.
- **The SQL expression-function libraries cost nothing under fat LTO** (0.1 MiB), so there is no reason to cut SQL capability; the earlier "keep them on" decision stands and needs no revisiting.
- **`panic = "abort"` saves 10 to 14 MiB** (the unwinding tables), and even with it the best size at acceptable speed (I) is **52.0 MiB, still above 50**. It also turns one panicking request into a process restart, so it stays off unless the owner decides otherwise.
- **Compressed, the 50MB goal is already met**: E is 23 MiB gzipped and D1 about 34 MiB.

**2. Levers, with the measured effect** (sizes in stripped MiB; the baseline is 136.0).

| Lever | Measured | Cost | Status |
|---|---|---|---|
| `strip` | 181 to 136 | none | do |
| DataFusion without Parquet and compression codecs | -7.2 | none (no Parquet use; the suite and the unit tests pass) | **do** |
| `lto = "fat"` and `codegen-units = 1` | -41 (with the above: 136 to 89) | longer builds (about 9 to 10 min); not slower | **do** |
| `opt-level = "s"` | a further -27 (to 62.3) | about 28% slower on scan-heavy SQL, otherwise equal | **owner's decision** (see below) |
| `opt-level = "z"` | a further -42 (to 46.8) | **1.7x to 6x slower** | **no** (fails the acceptance rule) |
| `panic = "abort"` | -10 to -14 | a panicking request restarts the process | **no** (decided in §3.3; the owner may reopen it) |
| SQL expression-function libraries (crypto, encoding, regex, unicode) | -0.1 | removes SQL capability for nothing | **no**, keep on |
| ONNX Runtime | its linked part is about 16 MiB of the 136 (12%), not the largest piece | reduced-operator build, per platform | only if 50MB raw is still wanted after the above; not the first lever |
| ONNX Runtime loaded dynamically | moves the 16 MiB out of the binary but **not** out of the image | an extra file to ship | not worth it for the image |
| A quantised (int8) model | shrinks the **image** (model about 87MB to about 25MB), not the binary | **changes the query vectors**; stored embeddings must be regenerated and quality re-validated | not by default |
| A different inference runtime | large | a big change, new accuracy risk | not by default |

**3. Decided (2026-10-06): keep two options, confirm after testing.** Both are defined as named Cargo profiles in `v4/Cargo.toml`, so any build, test or image can pick either
without anyone editing the file:

| Option | Command | Stripped (macOS arm64) | gzip | What it costs |
|---|---|---|---|---|
| **lean** | `cargo build --profile release-lean` | about 89 MiB | about 34 MiB | nothing measured: no slower than the old release build |
| **small** | `cargo build --profile release-small` | about 62 MiB | about 23 MiB | about 28% slower on scan-heavy SQL (8% lower concurrent SQL-scan throughput); otherwise level with lean |

The DataFusion feature trim (no Parquet, no compression codecs) applies to **every** build, because it is free. Plain `cargo build --release` is deliberately unchanged, so development builds stay quick.
Rejected for good: `opt-level = "z"` (1.7x to 6x slower). `panic = "abort"` stays off (§3.3). The 50MB-on-disk goal is **not** pursued further: with the flags alone the best acceptable
result is 62 MiB raw (23 MiB compressed), and the remaining route (a reduced ONNX Runtime build, or abort-on-panic) is not worth its cost.

**How the choice gets made (proposed criteria, applied in step 6 on the amd64 nodes and the Mac Studio, against the step 4 baseline):**
- Both options must pass the step 3 suite unchanged, and neither may regress against the baseline beyond the agreed threshold.
- Choose **small** only if, against **lean**, scan-heavy SQL is no more than 15% slower per query, no other endpoint is more than 5% slower, concurrent lookup throughput is at least 95% of lean's,
  and cold start is not worse. Otherwise choose **lean**.
- Record the choice here, make it the default build argument in the Dockerfile, and delete nothing: the other profile stays available.
- Step 6 builds **both** images (a build argument selects the profile) so V3, V4 lean and V4 small can be compared side by side.

Also to settle in step 5, alongside: Linux amd64 sizes (they may differ from macOS arm64), and the model's packaging (baked in, volume, or fetched; §0.1).

**4. Acceptance rule.** As above. A size win that fails the suite, regresses latency, or slows cold start is rejected.

**Exit:** the two profiles and the DataFusion feature set in `v4/Cargo.toml` (done 2026-10-06, built and size-checked); the measured table (binary and image, both platforms, and the component split) recorded in
`v4-deployment.md` §1.1 (update the numbers there rather than copying them here); the acceptance rule satisfied for both options; and the lean-or-small choice recorded after step 6.

### Step 6: Docker builds, V3 and V4, side by side on amd64 and arm64

Owning plan: [`v4-deployment.md`](v4-deployment.md) §3.5 (pipeline), §3.7 (multi-platform), §5 Step C. V3 already has a
`Dockerfile` (Python 3.13 alpine, non-root numeric UID, builds its database at image build). **V4 has no Dockerfile yet**; Step C
creates it.

**Build requirements (V4):** multi-stage; runtime image carries only the stripped binary, the data directory
(`COMPANY_DNS_DATA_DIR`), the model (§0.1), and a numeric non-root UID (as V3 does, for Kubernetes `runAsNonRoot`); `HEALTHCHECK`
on `/health`; built for `linux/amd64` first (the platform that matters), `linux/arm64` second. Data-integrity gate (New A):
`check_ic_feather.py` runs on every classification file in the build and fails the build on a bad file. The image must also carry `v4/THIRD_PARTY_NOTICES.md` and the licence files in `v4/crates/server/assets/redoc/` (the vendored Redoc is MIT and requires its notice to travel with any redistribution).

**The hosts (decided, Q2, Q8 and Q9, 2026-10-06): run the images on the Mac Studio and on the amd64 nodes.**
- **amd64 worker nodes** (two nodes, each over 20 cores and at least 384GB of memory): the authoritative `linux/amd64` numbers, the same
  hardware class as the real deployment.
- **Mac Studio** (128GB): the `linux/arm64` image, run natively through Docker's Linux VM. It is the developer's machine and a second platform to prove, but its
  absolute numbers are not comparable with the nodes' (a VM layer, different CPU). Use it for functional parity and for **relative** V3-versus-V4 comparison; use the
  nodes for the published numbers.
- **Timing:** the owner controls all of the hardware, so there is no quiet-window constraint; runs can happen whenever. The earlier abort-on-production-degradation rule
  stays only as a courtesy for the nodes while production pods are running on them (any production restart or sustained p95 well above normal means stop and look).
- **Fair-comparison settings on the nodes:** run the containers directly with Docker (outside Kubernetes, in their own network), with CPU and memory limits equal to the
  pods' (`k8s/prod/deployment.yaml`: 500m and 1Gi) for the characterisation run, and a second run with generous limits to show headroom on these large machines
  (a 500m limit on a 20-core host is a very different regime from an unconstrained one, and the server's parallelism follows the cores it sees). Never run V3 and V4
  performance passes at the same time on the same host. If one of the two nodes can be cordoned for the run, better still; if not, record node load beside every result.
- **Repeatability check:** repeat the same run on the second node, and treat a large difference between the two as a measurement problem to understand before trusting either.
- **Both architectures are now required**, so this step settles the open multi-platform mechanism in `v4-deployment.md` §3.7 and §6: **proposed: build natively on each
  architecture** (the Mac for arm64, an amd64 node or a GitHub runner for amd64) and publish one multi-architecture manifest, rather than emulating one under the other.
A GitHub-hosted runner still does the build and the smoke test on every push, since it is native amd64 (`v4-deployment.md` §3.5 step 2).

**What "side by side" means (so the comparison is fair):**
- Both containers on **the same amd64 host**, one at a time for performance runs (concurrent runs would contaminate each other),
  both for functional runs.
- Equal resource limits matching the real pods (`k8s/prod/deployment.yaml`: request 256Mi and 100m, limit 1Gi and 500m), plus an
  unconstrained run for headroom.
- A compose file, e.g. `docker-compose.compare.yml` (V3 on 8000, V4 on 4000), with the same network egress so live upstream
  calls behave alike.
- The same runner and the same ten companies, three runs each, cold start then warm, results in `perf_tests/results/`.

**Characterise:** image size; build time; time to healthy; idle and loaded memory and CPU; latency percentiles per endpoint;
throughput at rising concurrency; correctness under concurrency (existing assertions); and error rates. Present as one table
V3 versus V4 in a results doc (`v4-release-results.md`, created when there are numbers; do not pre-write it).

**Regression check:** run the step 3 suite against the **thinned** V4 container and diff against the step 4 baseline with
`compare.py`. Any regression is investigated before step 7.

**Exit:** both images build from a clean checkout; the suite passes on V4; the V3-versus-V4 table exists; no unexplained regression
against the pre-thinning baseline.
See Q2 for the amd64 host.

### Step 7: Staging

Owning plan: [`v4-deployment.md`](v4-deployment.md) §3.4 (staging is two replicas at `staging-company-dns.mediumroast.io`), §3.8
(manifests), §3.6 (platform-parity checks), §5 Steps E and G, and [`v4-sql-endpoint.md`](v4-sql-endpoint.md) §5c (capacity test).

**Must be true first:** a V4 image that passed step 6; `k8s/staging/` manifests (new, mirroring `k8s/prod/`); DNS and a
`letsencrypt-prod` certificate for the hostname; a staging **credentials SealedSecret** and a **rules ConfigMap** (distinct from
anything in prod, so staging can never hold prod's tokens); `SQL_ENABLED` on in staging, since the capacity test needs it.

**What runs on staging:**
1. The full step 3 suite (all layers, including L3 against live V3 and L5, which is safe here).
2. The §3.6 platform checks: log-level reload on a real `kubectl edit configmap`; rate limiting at **two replicas** (the per-pod
   division in `rate_limit.rs`); the chosen base image on the real target.
3. The SQL **capacity test** from `v4-sql-endpoint.md` §5c, with its agreed pass criteria. It produces the server-wide SQL limits
   for staging, which become ConfigMap values.
4. A soak: leave it up and exercised for a defined period and watch memory, restarts and error rate.
5. The human passes from roadmap §6: walk `/docs` as a first-time consumer, and a hand-run security pass over rate limits and profiles.

**Exit and go/no-go for later promotion (promotion itself is out of scope here):** suite green; capacity-test criteria met; soak clean
(no restarts, no memory growth); rollback proven (redeploy the previous image; V3 remains the production service until promotion).

## 4. Steps I added

**E. The 15 per-system non-US endpoints, the two `/v2/` aliases, and the V2.0 set (decided Q3; V2.0 added back 2026-10-07). Done 2026-10-07.** V3 serves, for each of EU (NACE), International
(ISIC) and Japan, five lookups: `section`, `division`, `group`, `class` and `description` (Japan: `division`, `major_group`, `group`, `industry_group`, `description`). V4 already held all three systems as flat tables with the
hierarchy columns, so these are lookups over data it has.
- **Built:** `v4/crates/sic/src/systems.rs` (one generic level lookup over all four systems, and the V3 response shaper, with 8 tests whose expected values are V3's own answers) and
  `v4/crates/server/src/sic_endpoints.rs` (the 43 routes, from two small macros: 30 for the 15 lookups at `/V4.0/` and `/V3.0/`, 11 V2.0 aliases, and the two `/v2/` aliases).
- **Level names (V3 versus V4's flat columns):** for Japan, V3's "division" is V4's `section_id` (A-T), "major group" is `division_id` (2 digits), "group" is `group_id` (3 digits), "industry group" is
  `class_id` (4 digits); for US SIC the same one-step shift (V3 "division" is `section_id`). EU NACE and ISIC use the same names in both.
- **Matching V3:** a case-insensitive substring match on the level's code, or on the class description, as V3 does. Messages and module strings are V3's per system (EU prefixes "EU SIC", ISIC has none, Japan prefixes "Japan SIC").
- **Verified against V3 production** (captured with a self-identifying User-Agent, one request at a time; fixtures in `api_tests/fixtures/v3/`): **15 of 19 responses identical** (code, message, module, data); the other four differ
  only as listed under "Known intentional differences".
- **Tests:** 9 in `api_tests/test_non_us_sic.py` (contract for all 15 in both shapes, no-match is a JSON 404 in both, parity with the fixtures, the V2.0 aliases equal their twins, including the Wikipedia, merged and `/v2/` aliases when run
  with `API_TESTS_NETWORK=1`, and the spec lists everything), plus 27 in the `sic` crate. The spec checks in the live battery still pass (every new operation documents 401 and 429, every new tag is described).
- **Also resolves** the roadmap's inconsistent count (22 versus the 17 in `company_dns.py`); corrected in `v4-initial-release-roadmap.md`.

**A. Data-integrity gate.** `check_ic_feather.py` validates the four classification feather files (counts, nesting, text encoding, and
each defect that previously got through). It is already planned as a build step in `v4-deployment.md` §3.2.4 and Steps C and D. It needs only
`pyarrow`. Wire it into the V4 build in step 6 so a bad file fails the build.

**B. Security and configuration review (before staging holds credentials).** Roadmap §8's secrets audit (no test or placeholder secret
left in the tree), a deliberate **CORS** decision (replace `permissive()` with an explicit policy, or document why not), confirm TLS is enforced at the
ingress for the Basic-auth endpoints, confirm SQL stays **off in production** by default, and a pass of `v4-security-hardening.md`'s open items.

**C. Release hygiene.** Bump to 4.0.0 consistently (spec, `/health`, crate versions), update `CHANGELOG.md`, update the top-level README for V4, write a
short **V3 to V4 migration note** (what is the same, what is absent by decision, what is new, what is experimental), and tag.

**D. CI for V4.** A workflow that builds, runs `cargo test --workspace`, clippy, and the fast layers of the suite against a freshly started V4 on every
push. This is the first CI V4 has (roadmap §6); the quarterly image build (Step D of the deployment plan) is a separate workflow.

**G. Observability check.** Confirm the structured logs, the dynamic log level and the SQL audit lines are usable on staging, and decide what is
alerted on (roadmap §8 lists monitoring as non-blocking).

**F. Rollback.** Written and exercised on staging: how to return to the previous image, and the rule that V3 stays production until promotion.

## 5. Questions

**Answered 2026-10-06:**

| # | Question | Answer |
|---|---|---|
| Q1 | Which live V3 for the parity run? | **Production V3, politely** (sequential, self-identifying `User-Agent`, the ten known companies, low concurrency). |
| Q2 | Which amd64 system for step 6? | **The two amd64 worker nodes**, and also the Mac Studio for arm64 (see Q8). |
| Q3 | How should V4.0.0 treat the non-US per-system endpoints? | **Build them before release**: the 15 EU, International and Japan endpoints, plus the two `/v2/` aliases. UK stays excluded. |
| Q4 | How far does the Swagger reskin go? | **Top bar now, branding later.** |
| Q5 | Binary or image size target? | **Asked for 50MB or less if safe. Settled 2026-10-06: 50MB raw is not reachable at acceptable speed, so keep both the lean (about 89 MiB) and small (about 62 MiB) options and confirm after testing.** Data in step 5. |
| Q8 | Which hardware, and what counts as "production degraded"? | **Two amd64 nodes (each over 20 cores, at least 384GB) and a Mac Studio (128GB)**; run the images on the Mac and on the nodes. The owner controls everything, so the degradation rule is a courtesy, not a gate. |
| Q9 | A quiet window? | **None needed**; run whenever. |
| Q12 | Should V3's limited V2.0 endpoints be served by V4 (excluded since 2026-09-28)? | **Yes, added back (2026-10-07)**, and the About page updated. 11 paths, aliases of their `/V3.0/` twins. |
| Q14 | **Decided (2026-10-07): close the three smaller gaps; merged stays a recorded difference.** Was: should the four gaps above (EDGAR `ciks`, `detail`, firmographics-by-CIK, and merged) be closed with V3-shaped answers on the `/V3.0/` and `/V2.0/` paths, or recorded as intentional differences? | Close `ciks` and the firmographics SIC fields (small) and `detail` (medium); for merged, decide separately because V3's flat record is the largest piece of work |
| Q13 | What data shape should the V3.0 and V2.0 paths return? | **V3's exact shape** on `/V3.0/` and `/V2.0/`, V4's list shape on `/V4.0/` (2026-10-07). Done for the US SIC and non-US aliases; EDGAR, Wikipedia and merged still to check in step 4. |

**Still open (my defaults apply unless changed):**

| # | Question | My default |
|---|---|---|
| Q6 | SQL on in staging (needed for the capacity test) and off in production. | Yes |
| Q7 | The suite as `api_tests/` beside `perf_tests/`, with only the standard library and `requests`. | `api_tests/` beside |
| Q10 | (Withdrawn: the linker map measured the embedding stack's cost without needing a Cargo feature.) | |
| Q11 | (Settled 2026-10-06: keep lean and small as options, confirm after testing; 50MB raw is not pursued.) | |

## 6. Definition of done for "released to staging"

- [x] Step 2: `/docs` and `/redoc` both light and readable, reviewed in the browser (2026-10-07).
- [x] Step 1: API documentation includes SQL, marked experimental, with the access and rate-limit text, 401 and 429 on every operation, tag descriptions and examples; spec checks in the live battery (2026-10-07).
- [x] New E: the 15 per-system endpoints, the two `/v2/` aliases and the V2.0 set built, tested against V3 fixtures, in the spec, on the About page (2026-10-07).
- [x] Step 3 suite built: 87 tests, layers L0 to L5, with a report and a diff tool (2026-10-07).
- [ ] Step 3 fast layers (L0, L1, L2, L4) green in CI (item D).
- [ ] Step 4 parity report with no unexplained mismatch, and the unthinned baseline saved.
- [x] Step 5 measurement, the two release profiles and the DataFusion feature trim, built and verified (2026-10-06).
- [ ] Step 5 remainder: sizes measured on Linux amd64 and recorded in `v4-deployment.md`; the no-regression check against the step 4 baseline; the model's packaging decided; the lean-or-small choice recorded after step 6.
- [ ] Step 6 images built from a clean checkout for amd64 and arm64, run on the nodes and the Mac Studio, the data gate in the build, the V3-versus-V4 results written up.
- [ ] Step 7 staging running two replicas, suite green, capacity test and soak passed, rollback exercised.
- [ ] Items A to G done or explicitly deferred with a reason.
