# V4 documentation update: a plan to work through in small steps, alongside the move to production

Status: **PLAN, nothing executed (2026-10-12).** Decisions recorded below were made by the owner on 2026-10-12.
Owner: michael.hay@mediumroast.io
Scope: the root `README.md`, `v4/README.md`, the changelog, the plans, the guides, and the open-source hygiene that goes with them, for the V4.0.0-pre release. It runs **next to**
[`v4-production-cutover.md`](v4-production-cutover.md) (which owns the deployment and calls the repository clean-up WP10) and uses the same rule: every document change is its own small pull
request, merged by the owner, and **a document never claims something that is not yet true** when it merges.

---

## 1. Decisions already made

| # | Decision | Consequence |
|---|---|---|
| R1 | **The root README does not advertise the staging URL** before the event. The URL goes in the client guide sent to the teams. | The README describes V4 and where staging fits without a link; DP3 and DP7. |
| R2 | **Documents call this release `V4.0.0-pre`.** The version strings in code are **`4.0.0`** everywhere (`/health`, the OpenAPI document, all Cargo crates), so nothing is reset at release. | Dropping "-pre" at release is a documents-only change (DP1). |
| R3 | **No Zetaris mention in the user-facing guide for now.** Later: a configuration example, a pointer to the Zetaris getting-started repository and its worked examples, and an example link from the README. The owner (also the Zetaris CTO) will make sure the integration guide material exists. | DP9 is a parked item with its place reserved; nothing is written now. |
| R4 | **Be honest that the scripts are maintainer-focused**, state the intention to make them generic, report what is already generic, and keep a debt list. | DP4 and the appendix. |
| R5 | **Data terms.** Redistribution rights are in hand for the **US SIC, Japan SIC and EU NACE** data. **ISIC (UN) is pending**: an email has gone out with no answer yet. The README states this and carries a risk that the ISIC data could be removed. | DP5. |
| R6 | **Sweep the repository for IP addresses and internal host names, and clean the Git history** (an action, not just a note). | DP2. |
| R7 | **The 24-hour soak from outside the network is running** (started the evening of 11 October). Its results, combined with the single-image performance work, become a performance report. The bring-up guide is marked "proven" when the soak passes. | DP11 and DP12. |

## 2. What is true today (read from the repository, 2026-10-12)

- The root `README.md` is entirely V3.3.0: install via the V3 image and `svc_ctl.sh`, port 8000, the Python dependency list, `build-and-deploy.sh`, and the V3 live links. **V4 is not mentioned.**
- `v4/README.md` is titled "company_dns V4 (prototype)" and describes the prototype's scope; its settings table is current (including the rate-limit settings).
- `CHANGELOG.md` stops at 3.2.0 although the README narrates 3.3.0. There is no V4 entry.
- Plan statuses disagree with reality ("Planned", "In progress", "Built"); several are superseded. There is no index.
- `/health` and the OpenAPI document say `4.0.0`; the Cargo crates say `0.1.0`.
- `v4/THIRD_PARTY_NOTICES.md` exists; `v4/data-manifest.json` lists the four SIC data files including the ISIC one. The SIC data is baked into the public image.
- Documents in the repository carry the staging host name (public) in the plans and the bring-up guide; node names and addresses were removed or replaced with placeholders in earlier passes, but the commit messages still mention node names.

## 3. Work packages

Each is one small pull request unless noted. "Gate" says what must be true before it merges.

### DP1. Version labels (a small code PR)

- Set `version = "4.0.0"` in the workspace and every crate; check nothing derives behaviour from the old value; update any test that pins a version (`api_tests` already expects `4.0.0` from `/health`).
- Fix the one spelling for documents: **V4.0.0-pre**, used in titles and banners. A short "How we label versions" paragraph in `v4/README.md`: the code says 4.0.0, the documents say V4.0.0-pre until release.
- **Done when:** `cargo test --workspace` passes, `/health` and `/openapi.json` say `4.0.0`, and a grep shows no `0.1.0` crate versions.
- **Gate:** none. Do it first so everything after is consistent.

### DP2. Open-source hygiene: the sweep, a guard, and the history clean-up (an action with an owner)

1. **Sweep the working tree.** Search for IPv4 addresses, private ranges, internal host names and node names, internal URLs, home-network details, e-mail addresses beyond the project contact, tokens or key-like strings. Replace with the placeholders already used (`<traefik-lan-ip>`, `<public-ip>`, `<build-node>`), or remove. Allow the documentation address ranges reserved for examples (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24).
2. **Add a guard** so it stays clean: a small script (`scripts/check_hygiene.py`) that fails on those patterns with an allow-list, run by the existing test files' habit (a unit test calls it), and documented in the contributing section. Stub-based like the others.
3. **Clean the Git history. ACTION, owner: michael.hay.** Commit messages and some past file versions mention node names and similar. Rewriting history is irreversible for everyone who has cloned, so the steps are written down first:
   - make a full mirror backup (`git clone --mirror`) kept outside the repository;
   - list the strings to remove (a file kept **outside** the repository) and run `git filter-repo --replace-text` / `--replace-message`; run a secret scanner over the result;
   - choose a window with **no open pull requests** and no event (not 22 to 25 October); close or rebase open PR branches first;
   - force-push `main` and tags; ask everyone with a clone (the remote soak tester, the platform partner, forks) to re-clone; note that old commit hashes quoted in plans and the build log (`v4/.build-log`) will no longer resolve and need a mapping note;
   - GHCR images are unaffected, but the image labels carry the source commit: record the old-to-new mapping for the tags in use.
   - Recommendation: **after the hackathon (from 26 October), together with V3's retirement**, unless the owner wants it earlier; the working-tree sweep (steps 1 and 2) does not wait.
- **Done when:** the guard passes on a clean tree; a written history clean-up runbook exists; the owner schedules the rewrite and later records its date here.

### DP3. Root README: the V4.0.0-pre section (Stage 1; merges before the cutover)

- A new section near the top: what V4 is (the Rust rewrite, same URLs, the additive `total`, semantic and hybrid SIC search, an experimental SQL endpoint, `/docs` and `/ui`), its status (**V4.0.0-pre**, running on a staging environment, **V3 still the live service**), and a link to `v4/README.md`. **No staging URL** (R1).
- A "Running V4" section in the **three layers** of DP4.
- Contributing: where V4 development lives and how its tests run.
- V3 text stays as is.
- **Done when:** nothing in the README says V4 is in production, and every link resolves.

### DP4. Deployment documentation, honest about what is general (R4)

Three layers in the root README and `v4/README.md`:

1. **Run the container.** `docker run` of the public image with the settings table; this is the general path and comes first.
2. **Run it on Kubernetes.** The `k8s/` manifests as a reference example, with their assumptions listed (the appendix) and "adapt these" said plainly.
3. **How Mediumroast deploys it.** The maintainers' cluster and `scripts/build-and-deploy-v4.sh`, labelled **maintainer-focused**, with the stated intention to make the scripts generic and a link to the debt list.

Also: `k8s/README.md` gets the same honesty paragraph; `docs/v4-bringup.md` is labelled as the maintainers' guide. The appendix below is the first version of the inventory and the debt list; it moves to its own page when it grows.

### DP5. Data sources and terms (R5)

- A "Data sources and terms" table in the root README and `v4/README.md`, one row per source: US SIC, Japan SIC (JSIC), EU NACE Rev. 2, ISIC Rev. 4 (UN), the SEC EDGAR data, Wikipedia and Wikidata; for each, where it comes from, what the image does with it, and the terms. **The owner supplies the exact rights wording and attributions** (this plan does not guess them).
- Rows as decided: redistribution rights held for US SIC, Japan SIC and EU NACE. **ISIC: permission requested from the UN, no reply yet.**
- A **risk statement** in the same place: the ISIC data could be removed from the image and the service if the answer is no or never comes; what would stop working (the `international` routes, and the `global` and hybrid searches that use ISIC: to be confirmed in step 2) and that clients should not build on ISIC yet.
- **Work behind the statement (a small engineering item):** (1) list exactly what depends on ISIC (routes, the global/hybrid search, tests, the data manifest); (2) make the build able to leave ISIC out (the manifest and the Docker build), and the routes answer with a clear "not available" rather than failing; (3) a rehearsed removal: build an image without ISIC and run the suite against it.
- Keep `v4/THIRD_PARTY_NOTICES.md` current (the software licences) and link it.
- **Gate for the cutover:** the owner confirms the wording; the cutover plan's WP1 gets a row "data terms stated, ISIC position recorded".

### DP6. Changelog

- Close the 3.3.0 gap (the README already has the text) and add a **V4.0.0-pre (unreleased)** entry in the same style: what is new, what is the same, and the differences clients will notice (the additive `total` on V3 paths, `/` redirecting to `/ui/`, the per-IP rate-limit model and its settings, the SQL endpoint off in production, the ISIC position).
- Conventions: Keep a Changelog headings (`Added`, `Changed`, `Removed`); one line per change with a pointer to the document that explains it.

### DP7. "Using the API" guide for client teams (before the hackathon; high priority)

- A short page (`docs/using-the-api.md`) written for the hackathon teams and other clients: choose V3 or V4 paths (both work), identify yourself with a User-Agent that carries a contact, the per-IP limit and burst (the figures are the operator's: quote the deployed ones in the copy sent to teams, not in the repository), handle `429` with `Retry-After`, cache answers on your side, the envelope and `total`, error codes, a few `curl` examples for US SIC, EU NACE and Japan SIC, and where `/docs` is.
- The staging URL appears in the **copy sent to the teams**, not in the README (R1).
- **Done when:** a developer who has never seen the project can make the three kinds of lookup and handle a `429` using only this page.

### DP8. Migration note and the differences ledger

- `docs/migrating-to-v4.md`: what is identical, what is added, what differs, what to test in a client; link the differences ledger (`docs/results/differences.json` and its readable form) so it is found from the README and the changelog.

### DP9. Zetaris integration example (parked; R3)

- **Not written now.** When the owner has the integration guide material: a short `docs/integrations/zetaris.md` that points to the Zetaris getting-started repository and its worked examples, a configuration example for the three data sets (US SIC, EU NACE, Japan SIC), and a README link under an "Integrations" heading. The owner coordinates the content with Zetaris; this repository only links to it.
- **Placeholder:** the README's "Integrations" heading is added only when there is something to link to.

### DP10. Plans index and status headers

- `docs/plans/README.md`: one line per plan with a status (done, in progress, superseded, historical) and what replaced it; fix the stale "Planned / In progress / Built" headers; `docs/README.md` indexes the guides (bring-up, soak, using the API, migration) and the plans.
- Cheap, mechanical, and reduces confusion for anyone arriving from outside.

### DP11. The performance report (inputs arrive with the soak results)

Combine into one document (replacing or extending [`v4-results-report.md`](v4-results-report.md)):

1. **Single-image performance:** the V3-versus-V4 comparison at the production limits (`docs/results/2026-10-10-rerun/`), as already analysed.
2. **Cluster sizing:** the replica-shape comparison and the pod-count scaling ([`v4-sizing-test.md`](v4-sizing-test.md)): 12 cores at three shapes, then 16 and 20 pods.
3. **The soak from outside the network:** the ramp and the 24-hour hold, from `windows.csv` and `summary.md`: throughput and latency by step, drift while holding, canary results, errors and `429`s, the tester's network noted.
4. **A capacity statement** an operator can use: what the deployed shape carries for lookups and for embeddings, with the caveats (shared nodes, closed-loop load, one run per cell).
5. **Method and limits**, and how to reproduce (the scripts and commands).
- Figures are produced by `perf_tests/report.py` from committed result files; raw per-window CSV from the soak is small enough to commit under `docs/results/`.
- **Gate:** the soak's output directory comes back from the tester; the owner reviews it first.

### DP12. Guides marked "proven", and the cluster documents

- After the soak passes and the WP1 gate of the cutover plan: mark `docs/v4-bringup.md` proven (tag, date, suite result), refresh its numbers (20 replicas, the quota), and update `k8s/README.md`.
- After the cutover: the root README swap (Stage 2 of the earlier outline) happens **in the cutover PR**: the install section (image name, port 4000), the production deployment text, the live links, the dependency list, the Future work list.
- After V3's retirement (the cutover plan's WP8): the README banner that V3 is source only, `svc_ctl.sh` described as V3's local controller, `k8s/` restructured to one production directory, the V3-era plans marked historical.

## 4. Order, and how it fits the calendar

| When | Package | Why then |
|---|---|---|
| Now to 15 October | DP1, DP3, DP4, DP6, DP10 | Small, independent, true today. |
| Before 22 October | DP7 (the client guide), DP2 steps 1 and 2 (the sweep and the guard), DP5's statement | The teams and any outside reader need these first. |
| When the soak results arrive | DP11, then the first half of DP12 | They depend on the data and the soak's PASS. |
| In the cutover PR | the README swap (DP12) | Must flip with the traffic. |
| Not 22 to 25 October | no history rewrite, no repository changes that need clones to reset | The event. |
| From 26 October | DP2 step 3 (the history clean-up) with V3's retirement, DP12's last part, DP5's ISIC engineering if the answer is still pending | A quiet window, no open branches. |
| Whenever the Zetaris material exists | DP9 | The owner's timing. |

## 5. Risks

| Risk | Handling |
|---|---|
| The README claims V4 is live before it is. | The rule at the top; the swap is in the cutover PR, not before. |
| A history rewrite breaks clones, open pull requests and quoted hashes. | A mirror backup, a quiet window, a hash mapping note, a message to everyone with a clone (DP2). |
| The UN says no to ISIC (or never answers) after the image is public. | DP5: the statement now, the dependency list, a build that can omit ISIC, and a rehearsed removal. |
| Rights wording stated wrongly. | The owner supplies it; the plan never invents it. |
| The README links to the Zetaris material before it exists. | DP9 is parked; no link until the content does. |
| Documents drift from the code again. | Version strings are 4.0.0 in code (R2), the hygiene guard (DP2), and the plans index with statuses (DP10). |

## Appendix A. What is general, and the debt (first version)

**Already general**
- The application and image: self-contained, non-root, read-only filesystem, a `/health` endpoint, all settings as environment variables or two optional mounted files, no Kubernetes dependency, a public image.
- The manifest shapes (Deployment, Service, probes, resources, anti-affinity) are standard.
- The script's pattern (preflight, apply-time image tag, rollback, build log) is reusable.
- The sizing and soak tools (`perf_tests/`) work against any URL.

**Specific to the Mediumroast lab, and the debt**
1. `scripts/build-and-deploy-v4.sh` and `scripts/seal-secrets-v4.sh` hard-code the registry and owner, the namespace, the host and certificate names, the Traefik ingress class and the `letsencrypt-prod` issuer; they assume SealedSecrets, a GitHub token in `.env`, and `microk8s kubectl`. **Intent:** move the constants into a config file or environment overrides, and make the cluster checks configurable.
2. The manifests assume Traefik (including a Traefik `Middleware` object), cert-manager with a named issuer, and the lab's host names. **Intent:** Kustomize overlays (a shared base plus per-environment changes), or documented substitutions.
3. The application's default allow-list for the credentialed routes, and the rate limiter's trusted-origin bypass, name `mediumroast.io` and its subdomains. **Intent:** make the trusted origins an explicit setting with no built-in default for outside deployments, and document it.
4. `COMPANY_DNS_REPLICAS` must equal the Deployment's `replicas` by hand. **Intent:** derive it automatically where possible, and warn loudly when it cannot.
5. The verification path (through the ingress address with `--resolve`) and the CoreDNS section of the bring-up guide are workarounds for this lab's router. **Intent:** label them as lab-specific; the generic check is the public name.
6. `svc_ctl.sh` is V3-only and uses a `latest` tag. **Intent:** fold V3 and V4 into one controller ([`v4-staging-scripts.md`](v4-staging-scripts.md) §6), or retire it with V3.
7. A stub-based test file for `svc_ctl.sh`; the monthly image workflow builds V3 only (the cutover plan's WP9).

## Appendix B. Open questions for the owner

1. The exact wording and attributions for the data terms (DP5), and who at the UN the request went to, for the record.
2. When to run the history rewrite (DP2): after 26 October (recommended) or earlier.
3. Whether the performance report (DP11) is published in the repository, or kept in the maintainers' area with a summary published.
