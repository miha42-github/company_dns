# V4 staging rollout: Kubernetes, manifests and build scripting for `company-dns-staging.mediumroast.io`

Status: **Decisions S1, S6 and S8 made (2026-10-10); ready to start WP1 to WP3.**
Owner: michael.hay@mediumroast.io
Scope: everything between "a V4 image that has passed the amd64 comparison" and "V4 is running on the MicroK8s cluster at
`company-dns-staging.mediumroast.io`, verified, with a rollback that works". This is step 7 of
[`v4-release-to-staging.md`](v4-release-to-staging.md) and Steps C (publish), E and G of [`v4-deployment.md`](v4-deployment.md) §5, written as a
work list. **Out of scope:** promotion to production, the dev tier, the quarterly build workflow, and any comparison with V3 (the V3 image no longer matters
for this work; V3 stays production until a separate promotion decision).

This document links to the plans that own each design decision rather than restating them: tiers and sizing
([`v4-deployment.md`](v4-deployment.md) §3.4, §3.8), secrets and profiles ([`v4-deployment.md`](v4-deployment.md) §2 addendum,
[`v4-sql-endpoint.md`](v4-sql-endpoint.md) §5a, §5c), rate limits ([`v4-security-hardening.md`](v4-security-hardening.md)), the cluster itself
([`onprem-k8s-migration.md`](onprem-k8s-migration.md)).

---

## 1. Where we start (verified in the repository, 2026-10-10)

| Fact | Source | Consequence for staging |
|---|---|---|
| The V4 image builds for `linux/amd64` on `cafe-1`, starts healthy with no network, and is **self-contained** (binary, UI, SIC data, EDGAR catalog, embedding model, Microsoft ONNX Runtime loaded at run time, so it runs on the nodes' CPUs without AVX2). | `v4/Dockerfile`, `v4/scripts/docker-build.sh`, results report | Nothing to mount for data; a pod needs no network to start. |
| It listens on **4000** (V3 listens on 8000), runs as UID 10001, has a `/health` endpoint and a `HEALTHCHECK`. | `v4/Dockerfile` | `k8s/staging/` cannot be a copy of `k8s/prod/`: port, probes and the security context differ. |
| Measured at production limits (0.5 CPU, 1 GiB): idle about 160 MiB, **peak 187 MiB**; at headroom peak 255 MiB; ready in 1 to 2 s. Faster than V3 on 26 of 28 checks. | `docs/results/2026-10-10-rerun/` | Size staging at the production limits (requests 100m / 256Mi, limits 500m / 1Gi): it is the tested regime, and there is room to spare. |
| **The rate limiter divides quotas by a hard-coded `REPLICA_COUNT = 4`.** | `v4/crates/server/src/rate_limit.rs:57` | Two staging replicas would each grant a quarter of the fleet quota, so the fleet allows **double** the intended rate, and the §3.6 check of rate limiting at two replicas cannot pass. A code change is needed first (work package 1). |
| Runtime configuration is environment variables plus two mounted files (credentials, rules) and an optional log-level file. No YAML or `.env` loader. | `v4/README.md`, `v4-deployment.md` §2 | Staging config is: env in the Deployment, a Secret for credentials, ConfigMaps for rules and log level. |
| Cluster: MicroK8s, two schedulable amd64 workers (`cafe-1`, `espresso-1`; `cafe-1` also runs production pods), Traefik ingress at `192.168.1.200`, `letsencrypt-prod` ClusterIssuer, SealedSecrets controller, `microk8s-hostpath` and NFS storage classes. Namespaces `company-dns` (V3 prod) exist; `company-dns-staging` does not. | `v4-deployment.md` §1.3, `k8s/prod/` | Staging shares nodes with production: it must stay small and never be able to starve prod. |
| `k8s/prod/` has namespace, Deployment, Service, Ingress (HTTPS and an HTTP redirect), Middleware, Certificate. `scripts/build-and-deploy.sh` builds V3's root `Dockerfile`, pushes to GHCR, `sed`-bumps the tag, applies, waits. | `k8s/`, `scripts/` | The staging scripts follow the same shape and conventions, for V4's Dockerfile. |
| No V4 image has been pushed to a registry. No V4 CI exists. | repo | Publishing is part of this work. |

## 2. The outcome, and how we will know

V4 runs on the cluster as **two replicas** at `https://company-dns-staging.mediumroast.io`, started from an image built by a script and
pulled from a registry, with its own credentials and rules that production never sees, reachable over HTTPS with a valid certificate, and
**verified by the suite and the platform checks**. A written rollback has been exercised. Everything is repeatable by script: a clean checkout
plus the documented prerequisites produces the same running staging.

## 3. Decisions needed before building (recommendations first)

| # | Decision | Recommendation | Why it matters |
|---|---|---|---|
| S1 | **DECIDED: public** (2026-10-10). **Image name and visibility.** A new GHCR package such as `ghcr.io/miha42-github/company_dns/company_dns_v4`, public or private? | A **separate package** (V3's `company_dns` package and prod stay untouched). **Public**, as V3's is, unless the baked-in SIC data's licence restricts redistribution; if it does, private plus an `imagePullSecret` (extra work package). | The image contains Mediumroast's SIC files. If they cannot be public, the image cannot be. |
| S2 | **Image variant.** Lean or small. | **Small** (rerun data: equal latency, CPU and memory; 72 MB smaller; 9 minutes faster to build). | Recorded in the plan; staging runs one variant. |
| S3 | **Tag scheme.** | `MMDDYYYY-<git sha7>` (V3's date convention plus the commit, so a tag always names its source); pinned, never `latest`. | Rollback and "what is running" must be unambiguous. |
| S4 | **Who builds and where.** | Build on `cafe-1` (native amd64, the same machine the comparison used) with a script now; a GitHub workflow later (plan item D) once the data location is decided. | Avoids waiting on CI, as decided for item H. |
| S5 | **SQL endpoint on in staging**, off in prod (Q6). | On, with staging-only credentials. | The capacity test needs it. |
| S6 | **DONE** (2026-10-10). **DNS.** `company-dns-staging.mediumroast.io` is registered and resolves to 75.80.225.46, the same address as `company-dns.mediumroast.io`. (The plans previously said `staging-company-dns`; every reference now uses the registered name.) | Nothing left; the certificate can issue once the Ingress exists. | HTTP-01 needs the name to resolve to the cluster. |
| S7 | **Rate limit replicas.** Make `REPLICA_COUNT` a setting (`COMPANY_DNS_REPLICAS`, default 4 so production behaviour is unchanged) set from the Deployment. | Yes; this is the only application change on the critical path. | Section 1, fourth row. |
| S8 | **DECIDED** (2026-10-10). **CORS** (item B). | **Lookups stay open to any origin** (read-only public data, as V3; no existing browser client breaks). **Credentialed routes (SQL and profile-gated) get an allow-list**, set by `COMPANY_DNS_CORS_ORIGINS` (comma-separated; default: the `mediumroast.io` origins and localhost). The open lookup policy is the default, so nothing changes for current clients. WP1 first confirms the routers allow two policies. | Auth is a Basic header, not cookies, so open CORS does not expose credentials; the allow-list covers the routes where it matters. |

## 4. Work packages, in order

Each has a deliverable and a way to see it is done. Branches are small and independent where possible; merges are yours.

### WP1. Code prerequisites (one PR)

- `COMPANY_DNS_REPLICAS` replaces the constant in `rate_limit.rs` (default 4), validated at start; a test covers 2 and 4 and the floor of 1; the README settings
  gain a line. **Done when:** `cargo test --workspace` passes and a server started with `COMPANY_DNS_REPLICAS=2` reports per-pod quotas of double the default's.
- CORS per S8: open for lookups, allow-list (`COMPANY_DNS_CORS_ORIGINS`) on the credentialed routes; tests for a foreign origin on a lookup (allowed), on a credentialed route (blocked: no `Access-Control-Allow-Origin`), an allowed origin, and the preflight. Settings reference for every variable (the gap noted on 2026-10-10): name, default, effect, where to set it per deployment.

### WP2. Publish script: `v4/scripts/build-and-push.sh` (written 2026-10-10; to be run on `cafe-1`)

Builds the amd64 image with `docker-build.sh` (small profile by default), runs `docker-smoke.sh` on it, tags it per S3, logs in to GHCR with the PAT in the
repository's gitignored `.env` (the V3 script's convention), pushes, and prints the digest and a one-line record (tag, commit, profile, data manifest hash)
to `v4/.build-log` (gitignored). It refuses to push if the smoke test fails or the tree is dirty without `--allow-dirty`.
**Done when:** a run on `cafe-1` produces a pullable image and a second machine can `docker pull` it by tag (anonymously if public).

### WP3. Manifests: `k8s/staging/`

Mirroring `k8s/prod/`, with V4's differences:

```
k8s/staging/
  namespace.yaml          company-dns-staging
  configmap-rules.yaml    COMPANY_DNS_RULES_FILE content (no secrets)
  configmap-loglevel.yaml LOG_LEVEL_CONFIG_PATH file (to prove the live reload on a real edit)
  sealedsecret-credentials.yaml   sealed profile:sha256 lines (generated, section WP4)
  deployment.yaml         2 replicas; port 4000; /health probes; requests 100m/256Mi, limits 500m/1Gi (the tested regime);
                          env: COMPANY_DNS_REPLICAS=2, COMPANY_DNS_SQL_ENABLED=true (and the SQL limits), COMPANY_DNS_CREDENTIALS_FILE, COMPANY_DNS_RULES_FILE,
                          LOG_LEVEL_CONFIG_PATH; the three mounts; anti-affinity across the two nodes; runAsNonRoot, drop ALL capabilities,
                          read-only root filesystem if V4 runs with a small writable `/tmp` (test it), `allowPrivilegeEscalation: false`
  service.yaml            ClusterIP 80 -> 4000
  ingress.yaml            HTTPS and HTTP-redirect ingresses for company-dns-staging.mediumroast.io, traefik class, per-namespace Middleware reference
  middleware-redirect.yaml
  certificate.yaml        cert-manager, letsencrypt-prod
```

**Checked without a cluster first:** `kubectl apply --dry-run=client` and `--dry-run=server` against the real cluster (no resources created), and a manifest test (a small script in
`k8s/` that asserts staging uses its own namespace and hostname, never mounts a prod secret, names the V4 image package, and has the replica setting equal to `replicas`).
**Done when:** the dry runs pass and the test is green.

### WP4. Secrets: staging credentials and rules

Generate staging-only profiles (`mediumroast.io`-style and a test profile for the suite and capacity test), hash the tokens, seal with the cluster's controller (`kubeseal`),
commit only the sealed file; plaintext tokens stay in the owner's password manager. Rules ConfigMap from `v4/rules.example.json` with staging values.
**Done when:** the SealedSecret decrypts in `company-dns-staging` and in no other namespace, and `git grep` finds no token or plaintext hash.

### WP5. Deploy script: `k8s/staging/deploy.sh` (written 2026-10-10; to be run against the cluster)

Same conventions as `scripts/build-and-deploy.sh`, for staging only: takes a tag, **refuses any namespace other than `company-dns-staging`**, bumps the image tag in the
Deployment, applies in the safe first-time order (namespace, secret, configmaps, deployment, service; a port-forward smoke; then ingress, middleware, certificate), waits for the rollout,
prints pod status and the first `/health`. Routine redeploys apply everything. `--rollback` redeploys the previous recorded tag (WP2's log).
**Done when:** a first-time run on the cluster ends with two ready pods and a passing port-forward smoke, and a second run with another tag rolls without downtime
(`maxUnavailable: 0`).

### WP6. First rollout, as a runbook (written into `k8s/README.md`, run by you with me alongside)

1. Merge WP1 to WP5; run WP2 on `cafe-1` (image pushed).
2. You create the DNS record (S6) and confirm it resolves.
3. Run `deploy.sh` (first-time mode): pods ready; port-forward smoke passes.
4. Ingress, middleware and certificate apply; `kubectl -n company-dns-staging get certificate -w` until ready.
5. HTTPS smoke from outside the cluster: `/health`, a US SIC lookup, an embedding search, the docs pages.
**Done when:** `https://company-dns-staging.mediumroast.io/health` answers from both pods (checked by their pod names in the logs).

### WP7. Verification on staging (the gate, `v4-release-to-staging.md` step 7)

1. The full suite (`api_tests/run.py`, all layers) against the staging URL with the test profile.
2. The platform checks: a real `kubectl edit configmap` changes the log level without a restart; rate limiting at two replicas (the fleet ceiling matches the intended quota, not double);
   the image runs on the real nodes' CPUs (`CPU:` log line shows no AVX2 and the runtime loaded dynamically).
3. The SQL capacity test with its agreed pass criteria; the resulting limits go into the ConfigMap.
4. A soak for a defined period (I suggest 72 hours with a steady light load): no restarts, no memory growth, error rate near zero. The metrics already flow into the cluster's observability stack.
5. The human passes: `/docs` as a first-time consumer; a hand-run security pass over rate limits, profiles and Basic auth over TLS.
6. **Rollback drill:** redeploy the previous tag with `--rollback`; confirm the service never goes down and staging returns to the first image.
7. A production safety check done before and after each of the above: production pods' restart count and the nodes' load (the same courtesy the matrix kept).

### WP8. Release hygiene that must precede a credentialed staging

Items B (secrets audit, CORS) and C (version 4.0.0 in the spec, `/health`, crate versions, changelog, migration note) from the release plan, scheduled before WP4 puts credentials on a shared cluster. Item D (V4 CI) is
**not** on this critical path.

## 5. Order, and what can run in parallel

```
WP1 (code) ──┐
WP2 (publish script) ──┼─> WP6 (first rollout) ─> WP7 (verification) ─> exit
WP3 (manifests) ──┤
WP4 (secrets; needs WP8's audit) ──┤
WP5 (deploy script; needs WP3) ──┘
S1, S6 decisions at the start; S8 before WP4
```

WP1, WP2 and WP3 can be written in parallel as three branches. I would start with WP1 (smallest, unblocks a real check) and WP3 (the longest design piece).

## 6. Risks

- **Shared nodes.** `cafe-1` carries production. Staging requests stay small, limits match the tested regime, anti-affinity spreads the pods, and the production restart count is watched. If production degrades the soak stops.
- **Slow embeddings on the 2013 CPUs.** The offline suite took about 10 s there against 1.8 s on the Mac. A search-heavy soak may need its request rate tuned; this is expected, not a defect.
- **Public image with licensed data.** Decision S1 must come first, or a push could publish files that cannot be redistributed.
- **The replica count drifting from `replicas`.** WP3's manifest test enforces that the two agree.
- **Wikipedia `maxlag` 500s.** Seen once in the matrix (unconfirmed cause). On staging the service log is available; the soak is where we learn whether it recurs.
- **Certificate issuance depends on DNS and on the node reachable from the internet.** If HTTP-01 cannot complete, the certificate stays pending; the runbook order keeps the workload verifiable without it.

## 7. Definition of done for "running on staging"

- [x] S1 (public), S6 (DNS resolves), S8 (CORS) decided 2026-10-10; [ ] S2 to S5 and S7 confirmed.
- [ ] WP1 merged: replica count and (if decided) CORS; settings reference written.
- [ ] WP2: the small image is built and pushed by `v4/scripts/build-and-push.sh`; the tag, digest and data manifest hash are recorded.
- [ ] WP3 to WP5: `k8s/staging/` and `deploy.sh` merged; manifest test green; dry runs clean.
- [ ] WP4: staging credentials sealed; no secret in the repository.
- [ ] WP6: `https://company-dns-staging.mediumroast.io` serves from two pods with a valid certificate.
- [ ] WP7: suite green; platform checks pass; capacity test criteria met and the limits recorded; soak clean; rollback exercised.
- [ ] `v4-release-to-staging.md` step 7 and the checklist updated with the results.
