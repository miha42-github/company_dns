# V4 to production, and V3 demoted to source code

Status: **PLAN, nothing executed (2026-10-11).** Decisions D1 to D8 are open; recommendations are given first.
Owner: michael.hay@mediumroast.io
Scope: everything between "V4 is verified on staging" and "`company-dns.mediumroast.io` is served by V4, V3 is gone from the cluster, and V3 is only source code in the
repository". It follows [`v4-staging-rollout.md`](v4-staging-rollout.md) (staging, done) and [`v4-staging-scripts.md`](v4-staging-scripts.md) (the script conventions this plan extends), uses the
sizing results in [`v4-sizing-test.md`](v4-sizing-test.md), and the cluster facts in [`onprem-k8s-migration.md`](onprem-k8s-migration.md). **Out of scope:** the dev tier, new V4 features, the
quarterly data build itself (only the gate that it exists before the V3 build is switched off, WP9), moving the repository's layout.

No addresses or internal host names appear here (the repository is open source): `<build-node>`, `<traefik-lan-ip>` and the like are placeholders, as elsewhere.

---

## 1. Where we start

| Fact | Source |
|---|---|
| **V3 production:** namespace `company-dns`, Deployment `company-dns`, 4 replicas (a deliberate ceiling), requests 100m / 256Mi, limits 500m / 1Gi, port 8000, Ingress for `company-dns.mediumroast.io` (HTTPS, plus an HTTP redirect Middleware), certificate `company-dns-io-tls`. | `k8s/prod/` (to be confirmed against the live Deployment: `kubectl -n company-dns get deploy company-dns -o yaml`; an earlier V3 manifest drifted from production) |
| **V4 staging:** namespace `company-dns-staging`, 20 replicas at 1000m / 1Gi, the per-IP quota 6000 a minute with a burst of 600, SQL endpoint on. Verified: HTTPS valid, 401 without and 200 with a token, the API suite 57 OK / 3 skipped on tag `10112026-f255f85`. | `k8s/staging/`, [`v4-bringup.md`](../v4-bringup.md), [`v4-sizing-test.md`](v4-sizing-test.md) |
| **V4 answers V3's URLs.** Every route is also served at its `/V3.0/` and `/V2.0/` path in V3's envelope; the one deliberate difference is the additive top-level `total`. `/` redirects to `/ui/`; `/health`, `/docs` and the UI exist. | `v4/README.md`, the differences ledger |
| **Capacity at 20 pods:** about 1900 lookups a second (2300 repeated), p95 about 400 ms; embeddings follow the pod count (about 19 a second per pod). | [`v4-sizing-test.md`](v4-sizing-test.md) |
| **Deploy tooling:** `scripts/build-and-deploy-v4.sh` (build, push, apply with the tag substituted, smoke test, certificate, HTTPS check, suite, rollback, build log) and `scripts/seal-secrets-v4.sh`, both staging only today. V3 has `scripts/build-and-deploy.sh` and `svc_ctl.sh`. | `scripts/` |
| **A monthly GitHub workflow rebuilds and pushes V3's `latest` image**, which is how V3's data (EDGAR especially) stays current. V4 has no equivalent: its EDGAR catalog is made during an image build, and where the SIC files are delivered from is still open (item H of [`v4-release-to-staging.md`](v4-release-to-staging.md)). | `.github/workflows/main.yml` |
| **Hackathon, 22 to 25 October:** up to 300 teams, mostly the US SIC lookups with client-side caching, some other SIC data, little or no embedding search. The platform partner's integration test (V3 swapped for V4) comes first. | the owner, 2026-10-11 |
| Certificates on this cluster only renew because of the CoreDNS `hosts` block; the earliest renewal is 2026-10-19. | [`onprem-k8s-migration.md`](onprem-k8s-migration.md) |

## 2. The outcome, and how we will know

1. `https://company-dns.mediumroast.io` is served by V4 from a pinned, registry-pulled image **that is the one that passed staging** (same tag, same digest), at the size chosen in D2,
   with production credentials and rules that staging and V3 never saw, and the SQL endpoint off (unless D4 says otherwise).
2. Every client that worked against V3 still works (the platform partner's integration, the mediumroast.io applications), with the differences communicated beforehand.
3. A **one-command rollback to V3** exists and has been exercised before the cutover, and V3 stays available until the soak and the hackathon are over.
4. V3 is then removed from the cluster, its image, manifests and monthly build are retired in an orderly way, and the repository says plainly that V3 is source code kept for reference.
5. The whole sequence is scripted and repeatable, like staging, and the data stays current (WP9).

## 3. Decisions (recommendation first)

| # | Decision | Recommendation | Why |
|---|---|---|---|
| D1 | **How traffic moves.** In-place replacement of V3's Deployment, a second namespace with a new host, or **blue/green inside `company-dns`**. | **Blue/green in `company-dns`:** V4 runs as its own Deployment and Service (`company-dns-v4`) beside V3 with no Ingress traffic until the cutover; the cutover is **one change of the Ingress backend** from V3's Service to V4's; rollback is the same change back. The host, certificate and redirect do not change, so nothing depends on DNS or a new certificate. | Instant, tested rollback; no DNS or certificate step on the day; V3 keeps its pods through the soak. A weighted split (a Traefik `IngressRoute` with `TraefikService`) was considered and rejected for now: more moving parts than a flip, and the staging run is the rehearsal. |
| D2 | **Production shape.** | The staging shape, **20 x 1000m / 1Gi, `COMPANY_DNS_REPLICAS=20`**, for the hackathon; revisit after 26 October (the sizing numbers say 12 pods carry about 1260 lookups a second if the load turns out lower). V3's four pods stay during the soak, so 20 + 4 pods share the nodes. | Measured, not guessed. A `replicas` and `COMPANY_DNS_REPLICAS` change is one line each. |
| D3 | **What is deployed.** | **Promote, do not rebuild:** the exact tag (and digest) that passed staging. The script refuses a tag the build log does not show as having passed the staging suite. | Build once; the thing tested is the thing run. |
| D4 | **Profiles, SQL and quotas in production.** | Production's own Secret and rules (sealed with a production secrets directory, never reusing staging tokens). SQL stays **off** in production. Profiles: `mediumroast.io` (bypass), and one for the platform partner and the hackathon if they need a quota of their own. Per-IP quota for the hackathon 6000 a minute, burst 600; the anonymous tier stays at its default (5 a minute) unless the owner decides otherwise. | Least privilege; the SQL endpoint is experimental. Hackathon teams are anonymous or identified-by-User-Agent callers per IP, so the per-IP numbers are what matter. |
| D5 | **When to cut over, relative to the hackathon.** | **Before it, with at least five days of soak** (cutover by about 15 October), keeping V3 as the standing rollback through the event. The alternative, running the hackathon on the staging host and cutting over afterwards, leaves production untouched during the event but makes the event depend on an environment with the SQL endpoint on and shared test credentials. | The event is the real load test; better on the endpoint the partner will actually use. |
| D6 | **When V3 leaves the cluster.** | **After the hackathon and a short quiet period (about 26 October to 2 November),** not before: V3 is the cheapest rollback during the riskiest week. Until then it can run at two replicas to free cores. | Headroom matters less than a safe fallback for that week. |
| D7 | **What "V3 as source code" means.** | **Tag, banner, retire; no restructure now.** Tag `v3-final`; a banner in the README and in `docs/` saying V3 is no longer deployed and V4 is the service; stop the monthly workflow (or repoint it at V4, WP9); keep `company_dns.py`, `lib/`, `html/`, `makedb.py`, the root `Dockerfile`, `requirements.txt` and `svc_ctl.sh` where they are; keep GHCR's V3 package (do not delete tags; mark the last production tag in the changelog). Moving V3 into a `v3/` directory is possible later and is a separate, mechanical change. | Moving files breaks links, the parity tests and history for no operational gain. |
| D8 | **What the parity tests become.** `api_tests` L3 compares V4 to a live V3. | Before the cutover: run L3 once against live V3 (still open from the staging checks) and keep the report. After V3 is gone: L3 runs against a locally started V3 container from the `v3-final` tag, or is retired and its report kept as the record; the owner picks. | Keeps the evidence that V4 matches V3 without keeping V3 deployed. |

## 4. Work packages

Each has a deliverable and a way to see it is done. Merges are the owner's.

### WP1. Gates before touching production

- Merge the open staging PRs; deploy the current `main` to staging with `scripts/build-and-deploy-v4.sh` (20 pods, the rate-limit settings in the image).
- The verification gate of [`v4-staging-rollout.md`](v4-staging-rollout.md) WP7 at the new size: the log-level edit without a restart; the rate-limit check across 20 pods (`v4-bringup.md` step 6.3, parallel requests, some `429`s); CORS; the SQL capacity numbers recorded; a rollback drill (roll to the previous tag and back); a soak under a steady synthetic load (the repeated mix at a modest rate) for as long as the calendar allows (at least 48 hours; 72 preferred), watching restarts, memory and latency.
- L3 parity against live V3; the UI pass; the overhead of the `total` layer; the Cargo crate versions at 4.0.0, a changelog entry for V4 and for the `total` addition on V3's paths (WP8 of the staging plan).
- The platform partner's integration test against staging, with results written down.
- Cluster hygiene: the CoreDNS block is present and covers `company-dns.mediumroast.io`; `dex-staging-tls` renewed (due 2026-10-19); the apex name's second public address checked before its November renewal.
- **Done when:** a short gate report lists each item with its result; any open item is accepted in writing by the owner.

### WP2. Production manifests (config only)

- New `k8s/prod-v4/`: Deployment `company-dns-v4` (20 replicas, port 4000, probes on `/health`, locked down as staging, `maxSurge` 4, the same anti-affinity), Service `company-dns-v4`, the rules ConfigMap, the log-level ConfigMap, the SealedSecret. **No Ingress, Middleware or Certificate** in this directory: those stay in `k8s/prod/` and keep serving V3 until the flip. No scripts in the directory.
- `COMPANY_DNS_SQL_ENABLED` absent (off); `COMPANY_DNS_CORS_ORIGINS` explicit; the rate-limit settings per D4; `COMPANY_DNS_REPLICAS` equal to `replicas` (a test pins it, as for staging).
- A manifest test file in the style of `k8s/test_staging_manifests.py`: placeholder tag `UNSET`, replicas agree, no SQL, no secrets in the tree, the Service selects the Deployment, no Ingress in the directory.
- **Done when:** the tests pass and `kubectl apply --dry-run=server` accepts the directory.

### WP3. Production secrets

- `scripts/seal-secrets-v4.sh --env prod`: tokens and credentials into a **separate** directory outside the repository (mode 600), sealed to `k8s/prod-v4/sealedsecret-credentials.yaml`; refuses to run if the production directory would be the staging one; `--rotate`, `--reseal` as for staging.
- The tokens go to their owners over a channel the owner chooses (never the repository, never a chat log).
- **Done when:** a production profile authenticates against the deployed V4 and a staging token does not.

### WP4. Script: promotion and cutover

Extend `scripts/build-and-deploy-v4.sh` (not a new script) with a production mode, keeping its conventions (preflight listing every problem, `--check`, `--status`, `--dry-run`, annotations on the Deployment, the build log):

- `--env prod` selects `k8s/prod-v4/` and the `company-dns` namespace; **no build in this mode** (`--tag` names a tag already pushed); refuses a tag that the build log does not show passing the staging suite, or one not built from a clean tree.
- `--cutover` points the Ingress backend at `company-dns-v4` (a patch, recorded with the tag and time in an annotation and the log) after the pre-checks of WP5; `--rollback-cutover` points it back at V3's Service; both print the exact state before and after.
- Verification as for staging: HTTPS through the Ingress address with `--resolve`, the suite, then a check from outside the LAN left to the owner (a phone on mobile data), which the script asks for and waits on.
- Stub-based tests in `scripts/test_v4_scripts.py` for the new mode, including: refusing an unproven tag, refusing the staging secrets directory, the flip and the flip back, nothing touched in `--dry-run`.
- **Done when:** the tests pass and a `--dry-run --env prod` against the live cluster prints a plan and changes nothing.

### WP5. Deploy V4 beside V3 (no traffic)

1. Seal and apply the production secret and ConfigMaps; apply the V4 Deployment and Service in `company-dns`; wait for 20 ready pods spread over both nodes.
2. Pre-cutover checks **without public traffic:** the API suite through a port-forward to the Service; the parity report against live V3; the rate-limit check; a load run with `perf_tests/load.py` at a modest level to see the new pods under load beside V3's pods; V3's request latency before and after (to see the co-tenancy cost).
3. Record the resource picture of the nodes (requests and usage) with both running.
- **Done when:** the suite is green on production's V4, V3's latency is unchanged within noise, and the nodes have the headroom the plan assumed.

### WP6. Cutover day

Preconditions (all must hold): WP1 gate report accepted; WP5 done; the rollback command tested on the day with a harmless flip and flip back; a quiet period chosen; someone available to watch.

1. Announce to the known clients (the clients named in section 7), at least a week before and again the day before.
2. `--cutover`. Within a minute: `/health`, a lookup from each of the three families, an authenticated request, `/` redirect, the UI loads.
3. The suite against the public name; the owner's check from outside the LAN; the platform partner's smoke call.
4. **Watch window of two hours:** errors and `429` counts in the pod logs, p95 latency from a probe, pod restarts, memory, node load. **Rollback triggers:** any sustained 5xx rate above 1%, p95 above two seconds on lookups for five minutes, a crash loop, a client-breaking difference found. Rollback is `--rollback-cutover`, then the cause is written up.
- **Done when:** the watch window passes and the owner declares the cutover complete.

### WP7. Soak and the hackathon

- V3 stays up (four pods, or two to free cores), taking no traffic, as the standing rollback. Daily: a short health note (restarts, 429s, p95, memory, the busiest callers).
- During 22 to 25 October: a named watcher, the rollback trigger list, and a pre-agreed lever for a hot spot (raise or lower a quota by editing the ConfigMap and restarting; scale `replicas` and `COMPANY_DNS_REPLICAS` together).
- After the event: collect the real traffic mix and peak into [`v4-sizing-test.md`](v4-sizing-test.md) and decide D2 again.

### WP8. Retire V3 from the cluster

After D6's quiet period, in this order, each step reversible until the last:
1. Scale V3 to zero (keep its manifests and image); one more week without traffic, a rollback is a scale-up and a flip.
2. Delete V3's Deployment and Service. Move the Ingress, Middleware and Certificate manifests into the production V4 directory (so there is one production directory, `k8s/prod/`: `git mv` V3's out, V4's in), pointing at the V4 Service. Rename V4's Deployment and Service to `company-dns` only if that is wanted; renaming is a second cutover, so default is **keep `company-dns-v4`**.
3. `scripts/build-and-deploy.sh` and V3's use of `svc_ctl.sh` retire (the long-term plan in [`v4-staging-scripts.md`](v4-staging-scripts.md) §6 folds V4 into `svc_ctl.sh`; this plan does not require it).
4. Free the headroom: V3's requests go back to the nodes.
- **Done when:** `kubectl -n company-dns get deploy` shows only V4, and the public name still passes the suite.

### WP9. Data supply and the build workflow (a gate for turning off V3's monthly build)

V3's monthly workflow is what keeps V3's data fresh. **Do not stop it until V4 has its own path:** the EDGAR catalog rebuilt on a schedule (`ingest-edgar` already exists, and the image build makes the catalog), and a decided location for the SIC files (`v4/scripts/fetch_data.py`, `v4/data-manifest.json`). Then replace `main.yml` with a V4 build (the quarterly workflow of the earlier plans, item D) that builds and pushes a candidate tag that must still pass staging and the promotion rule of WP4 before production. Until then the V3 workflow keeps running harmlessly.

### WP10. V3 becomes source code (the repository)

- Tag `v3-final` on the last commit that built V3's production image; record that tag and image in the changelog.
- README and `docs/`: a banner that V3 is no longer deployed and V4 (`v4/`) is the service; the README's run instructions put V4 first and describe `svc_ctl.sh` as V3's local controller; the changelog gets a V4 entry and a migration note (what changed for clients: the additive `total`, the redirect at `/`, anything the ledger lists).
- `api_tests` L3 per D8; `perf_tests` baselines stay as the V3 record.
- GHCR: leave V3's package and tags (do not delete); mark the last production tag.
- **Done when:** a reader of the README learns in the first screen that V3 is not running and where V4 is.

## 5. Schedule against the hackathon (a proposal; today is 2026-10-11)

| When | What |
|---|---|
| 11 to 13 October | Merge the staging PRs; deploy to staging at 20 pods; WP1 verification gate and the soak begin; WP2 to WP4 written and tested without touching production. |
| 14 October | Platform partner's integration test on staging; WP1 report accepted; WP3 production secrets; WP5 deploy V4 beside V3 and pre-checks. |
| 15 to 16 October | WP6 cutover (D5), watch window; start of the soak with V3 as the standing rollback. 19 October: `dex-staging-tls` renewal checked. |
| 17 to 21 October | Soak; daily notes; fix anything found; freeze on 21 October (no deploys during the event unless a rollback trigger fires). |
| 22 to 25 October | The hackathon. |
| 26 October to 2 November | Review the real traffic; re-decide the size (D2); WP8 begins after the quiet period; WP9 and WP10 in parallel. |

If the gates slip, the fallback is D5's alternative: cut over after the event and let the hackathon use whichever endpoint is proven, decided no later than 17 October.

## 6. Risks

| Risk | Mitigation |
|---|---|
| A client depends on a V3 behaviour V4 does not reproduce. | The differences ledger and L3 report go to the known clients before the cutover; the partner's integration test; rollback is one command. |
| V4's 20 pods and V3's 4 crowd the nodes (other workloads share them). | Requests are half the limits, the nodes' usage is recorded in WP5, V3 can drop to two replicas, the sizing numbers allow 12 pods. |
| The per-pod share of the rate limit is too small for a bursty team (burst 600 over 20 pods is 30 each). | Settings are env vars; the step-6.3 check; raise the burst, or scale the quota, by a ConfigMap or env change and a restart. |
| Certificates fail to renew (CoreDNS block missing or reset). | WP1 check; the table in the cluster plan; re-apply the block if DNS addons are toggled. |
| A single bad pod or a bad tag reaches all traffic at once on the flip. | Pre-checks in WP5; the watch window; the rollback triggers; no deploy during the event without a trigger. |
| V3's data goes stale if its workflow is stopped too early, or V4's data is stale from day one. | WP9 gate; record the data dates in the build log and the changelog. |
| The sealed production secret or tokens leak, or staging tokens work in production. | Separate directories and sealing, the script refuses to mix them, a check that a staging token gets a 401 in production. |
| A history question: commit messages mention node names. | Not changed here; the owner decides separately whether to rewrite history. |

## 7. Open questions for the owner

1. D5 (before or after the event) and D6 (when V3 leaves).
2. Whether the platform partner and the hackathon need profiles of their own, and who holds those tokens.
3. Whether the anonymous tier (5 a minute, no identifying User-Agent) should stay as strict as it is for an event with unknown callers.
4. Whether production should keep the SQL endpoint off (recommended) and the `mediumroast.io` profile bypass.
5. A named watcher for 22 to 25 October and how an incident is raised.
6. Where the SIC files will be delivered from (WP9), and whether the monthly or a quarterly cadence is wanted for the V4 build.
