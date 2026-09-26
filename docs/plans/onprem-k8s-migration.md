# Migrate company_dns from Azure Container Apps to on-prem MicroK8s

Status: **In progress.** Manifests authored (`k8s/prod/`), EDGAR/Wikipedia
performance fixes landed, live cluster survey done, all open questions
resolved. Not yet merged to `main` — see "Step-by-step execution guide" for
exactly where execution starts and what's left.
Owner: michael.hay@mediumroast.io
Target cluster: on-prem MicroK8s HA cluster, worker nodes `cafe-1` and `espresso-1`
Reference implementation: `mediumroast.io` repo, `V6_K8s` branch, `k8s/prod/` +
`scripts/build-and-deploy.sh`

## Goal

Stop running `company_dns` as an Azure Container App and run it instead as a
Deployment on the existing on-prem MicroK8s cluster, alongside other
mediumroast.io services, with TLS termination handled the same way
(cert-manager + Traefik + Let's Encrypt) and no change to the public hostname
(`company-dns.mediumroast.io`).

## Why this shape

- `company_dns` is a small, stateless FastAPI service. Its "database" is a
  SQLite cache file built at image-build time from `makedb.py` — no
  persistent volume, no external DB dependency, no session state. This is the
  easiest possible workload to run on k8s: a single Deployment + Service +
  Ingress + Certificate, no StatefulSet, no PVC.
- The cluster already runs `mediumroast-website` in namespace
  `mediumroast-web` using exactly this shape (see
  `~/dev/mediumroast.io/k8s/prod/`). We are reusing that pattern rather than
  inventing a new one.
- Per user decision, this migration is **single-environment (prod only)** —
  no dev/staging/prod tiering. `company_dns` currently runs as one Azure
  Container App revision; the k8s version should match that footprint, not
  add tiers it doesn't need today. (Tiering can be added later the same way
  `mediumroast.io` did, if ever needed.)
- The `ghcr.io/miha42-github/company_dns/company_dns` image is public (per
  README: `docker pull` works with no login), so unlike
  `mediumroast-website` we do **not** need a SealedSecret /
  `imagePullSecrets` for GHCR — one less moving part.

## Non-goals

- No change to the application code, API surface, or data sources.
- No introduction of dev/staging tiers (can be a later follow-up if needed).
- No change to the monthly EDGAR-data-refresh build cadence
  (`.github/workflows/main.yml` schedule stays as-is other than the Azure
  deploy step).

---

## Current state (as of this plan)

### Azure Container App (to be decommissioned)

Defined in [container-app-config.yaml](../../container-app-config.yaml):

| Setting | Value |
|---|---|
| Image | `ghcr.io/miha42-github/company_dns/company_dns:latest` |
| Ingress | external, target port `8000`, CORS `*` |
| Resources | 0.5 CPU / 1Gi memory |
| Scale | min 0, max 10 replicas, 300s cooldown |
| Env | `COMPANY_DNS_HOST=company-dns.mediumroast.io` |

Deployed by [.github/workflows/main.yml](../../.github/workflows/main.yml) on
a monthly cron (`0 12 1 * *`) and on manual dispatch, via
`azure/container-apps-deploy-action@v2`, using secrets:
`AZURE_CREDENTIALS`, `AZURE_RESOURCE_GROUP`, `AZURE_CONTAINER_APP_NAME`,
`AZURE_CONTAINER_APP_ENV`.

### Target cluster (reference: mediumroast.io `k8s/prod/`)

| Setting | Value |
|---|---|
| Ingress controller | Traefik (`ingressClassName: traefik`) |
| TLS | cert-manager, `ClusterIssuer/letsencrypt-prod` (cluster-wide, already exists — HTTP-01 via Traefik) |
| LoadBalancer IPs | MetalLB pool `192.168.1.200-192.168.1.219` |
| Scheduling | 2 effective worker nodes: `cafe-1`, `espresso-1` (pod anti-affinity spreads replicas across them) |
| Secrets | Bitnami SealedSecrets controller (used for private creds; not needed here — image is public) |
| Existing namespace pattern | one namespace per app+tier, e.g. `mediumroast-web` |

**These rows are taken from the reference repo's docs, not a live query of
the cluster.** Section "Live cluster survey" below has open items to confirm
before writing manifests for real.

---

## Live cluster survey — run before finalizing manifests

Run these and report back (paste output into this doc's "Survey results"
subsection, or hand output back in chat):

```bash
microk8s kubectl get nodes -o wide
microk8s kubectl get namespaces
microk8s kubectl get pods -A -o wide
microk8s kubectl -n ingress get svc,pods
microk8s kubectl get clusterissuer
microk8s kubectl get storageclass
microk8s kubectl -n mediumroast-web get certificate
microk8s kubectl get crd | grep -i sealedsecret
microk8s kubectl get ingressclass
```

What we're confirming:

1. `cafe-1` / `espresso-1` are still the effective worker nodes (i.e. no
   topology change since the mediumroast.io doc was written).
2. `letsencrypt-prod` `ClusterIssuer` still exists and is `Ready` — if so, we
   reuse it as-is (no new `certmanager.yaml` needed, just a `Certificate`
   resource for `company-dns.mediumroast.io`).
3. Traefik ingress class name and entrypoints (`web` / `websecure`) match
   what's assumed below.
4. No naming collision with `company-dns` as a namespace name.
5. MetalLB / external IP path is unchanged (only matters if DNS needs to
   point at a new IP — see Cutover section).

### Survey results

Run 2026-09-25/26 against the live cluster. All core assumptions confirmed;
one new item to decide (ingress class choice).

- **Nodes** (`get nodes -o wide`): 3 control-plane nodes total —
  `cafe-1` and `espresso-1` are `control-plane,worker` (schedule pods, Ubuntu
  24.04, v1.35.6); `cortado-1` is `control-plane` only (no `worker` role,
  running on a Jetson/tegra kernel) and does **not** schedule regular
  workloads. Confirms: pod anti-affinity should target `cafe-1` /
  `espresso-1` as originally planned — no topology change.
- **Namespaces**: `company-dns` does not exist — no naming collision.
  Existing app namespaces: `mediumroast-web`, `mediumroast-staging`,
  `mediumroast-dev`, `vault-prod`, `vault-staging`. Also present:
  `cert-manager`, `cnpg-system` (CloudNativePG — not needed here, no DB),
  `ingress`, `metallb-system`, `observability` (Prometheus/Grafana/Loki/Tempo
  stack — company_dns pods will show up here automatically via
  node-exporter/kube-state-metrics, no extra work needed to get basic
  cluster metrics).
- **Ingress**: single `traefik` Service (`LoadBalancer`) in the `ingress`
  namespace, external IP `192.168.1.200`, ports `80`/`443` (nodePorts
  `31103`/`32705`). Matches the mediumroast.io doc's MetalLB pool.
  **Resolved**: `get ingressclass` shows three IngressClasses —
  `nginx`, `public`, `traefik` — but all three point to the exact same
  `controller: traefik.io/ingress-controller`, installed by one Helm release
  (`traefik`/`ingress` namespace). Traefik's pod args confirm this is one
  Traefik deployment with a `providers.kubernetesingressnginx` compat shim
  (`--providers.kubernetesingressnginx.ingressclass=nginx`, for ingress-nginx
  style manifests) plus a Helm-marked "default" alias class (`public`,
  `ingressclass.kubernetes.io/is-default-class: "true"`) and the chart's own
  native class (`traefik`). They are not different network paths or
  entrypoints — same LoadBalancer, same `web`/`websecure` entrypoints either
  way. Confirmed via `-n mediumroast-web get ingress -o yaml` that the live,
  working `mediumroast-website` Ingress explicitly sets
  `ingressClassName: traefik` (not `public`, despite the tempting name) on
  both its HTTPS ingress (`router.entrypoints: websecure`,
  `router.tls: "true"`) and its HTTP→HTTPS-redirect ingress
  (`router.entrypoints: web`, `router.middlewares:
  mediumroast-web-redirect-https@kubernetescrd`, referencing a `Middleware`
  resource — see `middleware-redirect.yaml` in the reference repo). **Decision:
  `company-dns`'s manifests use `ingressClassName: traefik` too**, matching
  the proven-working pattern exactly, plus its own
  `Middleware/company-dns-redirect-https` in the `company-dns` namespace
  (Middleware resources aren't shared across namespaces in Traefik's CRD
  provider, so each app needs its own copy — same reason
  `mediumroast-staging` etc. would need their own if they used the redirect
  pattern).
- **TLS**: `letsencrypt-prod` `ClusterIssuer` exists and is `Ready` (age
  133d) — reuse as-is, no new `certmanager.yaml` needed. Confirmed
  `mediumroast-io-tls` Certificate in `mediumroast-web` is `Ready`, proving
  the pattern works end-to-end on this cluster today.
- **Storage classes**: `microk8s-hostpath` and two `nfs-nas*` classes exist
  (used by `vault-prod`'s Postgres/backups) — not needed for company_dns
  (stateless, SQLite baked into the image at build time). No PVC in the
  manifests.
- **SealedSecrets**: controller (`sealedsecrets.bitnami.com` CRD) is running
  cluster-wide — available if ever needed, but not used here since the GHCR
  image is public.

No changes to the plan's manifest shape are needed from this survey, other
than resolving the ingress-class question above before writing
`k8s/prod/ingress.yaml`.

---

## k8s manifests (authored — see `k8s/`)

Directory in this repo, mirroring `mediumroast.io/k8s/`:

```
k8s/
  prod/
    namespace.yaml
    deployment.yaml
    service.yaml
    ingress.yaml
    middleware-redirect.yaml
    certificate.yaml
  README.md          # short "how to deploy" note, links to scripts/build-and-deploy.sh
scripts/
  build-and-deploy.sh
```

### `k8s/prod/namespace.yaml`
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: company-dns
  labels:
    app.kubernetes.io/name: company-dns
```

### `k8s/prod/deployment.yaml`
Key points, adapted from `mediumroast-website`'s deployment and from
`container-app-config.yaml`'s existing resource sizing:

- `replicas: 2`, `RollingUpdate` (`maxSurge: 1`, `maxUnavailable: 0`) —
  zero-downtime deploys, matching the reference pattern. (Azure Container App
  scaled 0–10; on k8s we run a fixed small replica count instead — no
  scale-to-zero equivalent needed for a low-traffic internal API.)
- Pod anti-affinity on `app.kubernetes.io/name: company-dns` /
  `topologyKey: kubernetes.io/hostname` to spread the 2 replicas across
  `cafe-1` and `espresso-1`.
- No `imagePullSecrets` (public image).
- `containerPort: 8000` (matches `EXPOSE 8000` in the
  [Dockerfile](../../Dockerfile) and `targetPort: 8000` in the old Azure
  config).
- Env: `COMPANY_DNS_HOST=company-dns.mediumroast.io` (carried over from
  `container-app-config.yaml`).
- Resources: `requests` 100m CPU / 256Mi memory, `limits` 500m CPU / 1Gi
  memory (Azure's 0.5 CPU / 1Gi is now the `limits` ceiling; `requests` are
  lighter since the cluster is shared with other apps) — **decided**;
  revisit against actual observed usage once running.
- `livenessProbe` / `readinessProbe` target **`/health`**, not `/` —
  [company_dns.py:518](../../company_dns.py) already has a dedicated,
  lightweight health endpoint (plain JSON, no DB/network calls), found while
  resolving this question. Better than probing `/`, which does a file read
  and isn't meant for repeated polling.
- `securityContext`: `runAsNonRoot: true`, drop all capabilities — **done**.
  The [Dockerfile](../../Dockerfile) now adds a non-root `company_dns` user
  (`addgroup`/`adduser` + `chown -R` + `USER company_dns`) after `makedb.py`
  runs (which still executes as root during build, before the user switch,
  so the baked-in `companies.db` and `edgar_data/` are owned correctly).
  No explicit `runAsUser` needed — `runAsNonRoot: true` just checks the
  container isn't UID 0, which the Dockerfile's `USER` directive already
  guarantees regardless of the exact UID Alpine's `adduser -S` assigns.

### `k8s/prod/service.yaml`
`ClusterIP`, port 80 → `targetPort: 8000`, matching the service pattern used
for `mediumroast-website`.

### `k8s/prod/ingress.yaml`
Two Ingress resources, `ingressClassName: traefik` on both (confirmed as the
correct class — see Survey results above), copied field-for-field from the
**live** `mediumroast-website` Ingress config (not just the repo file, which
matches):

- HTTPS ingress: host `company-dns.mediumroast.io`, annotations
  `cert-manager.io/cluster-issuer: letsencrypt-prod`,
  `traefik.ingress.kubernetes.io/router.entrypoints: websecure`,
  `traefik.ingress.kubernetes.io/router.tls: "true"`, `tls.secretName:
  company-dns-io-tls`.
- HTTP redirect ingress: same host(s), annotations
  `traefik.ingress.kubernetes.io/router.entrypoints: web`,
  `traefik.ingress.kubernetes.io/router.middlewares:
  company-dns-redirect-https@kubernetescrd` (references the `Middleware`
  below — note the `@kubernetescrd` provider suffix and namespace-local
  Middleware name, exactly as `mediumroast-web-redirect-https@kubernetescrd`
  works today).

CORS: **confirmed** — `company_dns.py` already sets FastAPI's
`CORSMiddleware` with `allow_origins=["*"]` at the app layer
(`company_dns.py:94-101`); the old Azure `corsPolicy` block in
`container-app-config.yaml` was redundant with it. No ingress-level CORS
annotations needed.

### `k8s/prod/middleware-redirect.yaml`
```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: redirect-https
  namespace: company-dns
spec:
  redirectScheme:
    scheme: https
    permanent: true
```
Identical to `mediumroast.io/k8s/prod/middleware-redirect.yaml`, just in the
`company-dns` namespace, `metadata.name: redirect-https` kept the same as
the reference. **Gotcha confirmed from the live data above**: Traefik's
annotation-based Middleware reference on a plain Kubernetes `Ingress`
(as opposed to a native `IngressRoute`) is namespace-prefixed —
`mediumroast-web`'s middleware, named `redirect-https`, is referenced as
`mediumroast-web-redirect-https@kubernetescrd`, i.e.
`<namespace>-<name>@kubernetescrd`, not just `<name>@kubernetescrd`. So
`company-dns`'s `ingress.yaml` must reference it as
`company-dns-redirect-https@kubernetescrd`.

### `k8s/prod/certificate.yaml`
`Certificate` resource, `secretName: company-dns-io-tls`, `dnsNames:
[company-dns.mediumroast.io]`, `issuerRef: letsencrypt-prod` (ClusterIssuer),
`renewBefore: 720h` — mirrors `mediumroast.io/k8s/prod/certificate.yaml`.

---

## CI/CD changes

Per decision: **GitHub Actions keeps building/pushing the image only; the
cluster deploy step is manual/local**, matching how `mediumroast.io` runs
`scripts/build-and-deploy.sh` from a workstation with cluster access.

**Resolved** (image tagging): pinned dated tags, not `:latest` +
`imagePullPolicy: Always` — same rollback-safety reasoning `mediumroast.io`
used. Implemented in [scripts/build-and-deploy.sh](../../scripts/build-and-deploy.sh):
it does its **own** `docker build`/`docker push` to
`ghcr.io/miha42-github/company_dns/company_dns:<TAG>` (default tag
`MMDDYYYY`) rather than reusing whatever CI most recently pushed to
`:latest` — this keeps "what tag is deployed" fully explicit and
independent of CI's monthly/dispatch cadence, and sidesteps needing to
`docker pull`+`retag` an existing `:latest` image (which doesn't actually
save a build). The script then `sed`-updates the `image:` field in
`k8s/prod/deployment.yaml`, applies everything in `k8s/prod/`, and waits for
rollout — see [k8s/README.md](../../k8s/README.md) for the full flow
(first-cutover ordering vs. routine redeploys).

Remaining CI change (not yet done — see Migration step 10): in
[.github/workflows/main.yml](../../.github/workflows/main.yml), remove the
`Azure Login` and `Deploy to Azure Container App` steps once Azure is
decommissioned. The `Build and push` step to `ghcr.io:latest` can stay as-is
even though the k8s deploy script no longer consumes it directly — other
things may still reasonably want a floating `:latest` (e.g. someone doing
`docker pull` to try the service locally), and removing it isn't necessary
for this migration.

---

## Migration steps (execution order)

1. ~~**Survey** the live cluster (see above) and update this doc's
   assumptions.~~ **Done.**
2. ~~**Author manifests** (`k8s/prod/*.yaml`) and
   `scripts/build-and-deploy.sh`; resolve the Dockerfile's non-root user
   question.~~ **Done** — see `k8s/prod/`, `scripts/build-and-deploy.sh`,
   `k8s/README.md`, and the `Dockerfile`'s new `USER company_dns` step.
3. **Deploy in parallel** with Azure still live: `kubectl apply -f
   k8s/prod/` creates namespace `company-dns`, Deployment, Service. **Do not
   apply the Ingress/Certificate yet** if that would collide with the DNS
   record still pointing at Azure — test the Service directly first
   (`kubectl -n company-dns port-forward` or a temporary
   `*.mediumroast.io` test host) before touching DNS.
4. **Smoke test**: hit a handful of representative endpoints (SIC lookup,
   EDGAR firmographics, the SPA at `/`) against the new pod directly, compare
   responses to the live Azure instance.
5. **Apply Ingress + Middleware + Certificate** (`kubectl apply -f
   k8s/prod/ingress.yaml -f k8s/prod/middleware-redirect.yaml -f
   k8s/prod/certificate.yaml`) — do this **before** touching DNS. cert-manager
   will attempt an HTTP-01 challenge immediately and fail/retry (DNS still
   points at Azure at this point, so Let's Encrypt can't reach the cluster
   yet) — that's expected and harmless; it just backs off and retries. Azure
   traffic is completely unaffected since DNS hasn't moved.
6. **Cut over DNS — Phase 1 (CNAME to `www.mediumroast.io`)** — see "DNS
   cutover — Namecheap instructions" below for exact steps. This phase is
   deliberately the *lower-risk* option first: it reuses `www`'s already-
   proven-working Dynamic DNS tracking rather than setting up a new DDNS
   host for `company-dns` before the cluster deployment itself is even
   verified end-to-end. Once DNS propagates, cert-manager's next retry
   succeeds (watch with `kubectl -n company-dns get certificate -w`) and the
   certificate goes `Ready` — this closes the only real downtime window
   (DNS propagation + one cert-manager retry cycle, typically a few
   minutes), since applying the Ingress before DNS eliminates any gap where
   traffic would arrive at Traefik with no route at all.
7. **Verify TLS + traffic** against the new hostname: cert is `Ready`, TLS
   handshake succeeds, and the same representative endpoints from step 4
   (SIC lookup, EDGAR firmographics, SPA at `/`) return correct responses
   over `https://company-dns.mediumroast.io`. **No extended burn-in window**
   — per decision below, once this smoke test passes we treat the migration
   as successful and move straight to teardown. Fallback to Azure (DNS
   revert) only happens if this step turns up a real failure, not
   preemptively.
8. **Decommission Azure Container App immediately** once step 7 passes (see
   Teardown below) — no soft "scale to zero and wait" window, no multi-day
   observation period. The point of keeping Azure's config backed up (see
   Teardown step 2) and the `asuid.company-dns` TXT record intact until
   Teardown's last step is that a rollback is still *possible* after
   deletion (redeploy from the backup + `container-app-config.yaml`), just
   not fast — this plan takes on that risk in exchange for not carrying two
   production deployments of the same service longer than necessary. This
   step does not wait on DNS Phase 2 below — the CNAME-to-`www` setup from
   step 6 is already fully functional and independent of Azure.
9. **Cut over DNS — Phase 2 (dedicated Dynamic DNS host), manual, deferred**:
   once Phase 1 (step 6) has been running and verified for a while, manually
   register `company-dns` as its own Namecheap Dynamic DNS-tracked host
   (same mechanism `www.mediumroast.io` uses), decoupling
   `company-dns.mediumroast.io` from `www`'s DNS lifecycle. Not a blocker
   for anything else in this plan — Azure teardown (step 8) and repo cleanup
   (step 10) don't depend on it. Done manually by the user; not something
   this plan schedules a date for.
10. **Remove Azure-specific files** from this repo: `container-app-config.yaml`,
   the Azure steps in `.github/workflows/main.yml`, and any Azure secrets in
   the repo's GitHub Actions settings (`AZURE_CREDENTIALS`,
   `AZURE_RESOURCE_GROUP`, `AZURE_CONTAINER_APP_NAME`,
   `AZURE_CONTAINER_APP_ENV`, `AZURE_SUBSCRIPTION`) — the user has Azure and
   GitHub admin access to do this directly.

---

## Step-by-step execution guide

This is the operational checklist — concrete commands, in order, with who
runs each one and where. The numbered rationale above ("Migration steps")
explains *why*; this section is what to actually type.

**Where things stand right now** (as of this write-up): all of the code for
this migration — the EDGAR/Wikipedia performance fixes, the Dockerfile
non-root user change, and everything under `k8s/` and `scripts/` — exists
only as uncommitted/local-to-this-worktree changes on the
`claude/repo-overview-ed2879` branch. **Nothing is merged to `main` yet**,
and `.github/workflows/main.yml` has **deliberately not been touched** —
removing its Azure deploy steps is migration step 10, which only makes
sense *after* Azure is actually torn down (step 8/9 below). Until then, the
existing monthly/dispatch workflow continues deploying to Azure exactly as
before; this migration doesn't interfere with it.

None of the remaining steps below (image build, `kubectl apply`, DNS edits,
`az` commands) can be run from this Claude session — no `docker`, `kubectl`,
or `az` CLI access here, by design (see "Live cluster survey" above). Steps
are marked **[you]** where you run them yourself, on a machine with the
relevant access (your workstation, or directly on `cafe-1`).

### 0. Land the code on `main`

1. **[Claude]** Commit and push the worktree's changes, open a PR.
2. **[you]** Review the PR (bug fixes to `lib/edgar.py`/`lib/wikipedia.py`
   in one commit, k8s/Dockerfile/docs in another) and merge it to `main`.
3. **[you]** On whatever machine you'll run `build-and-deploy.sh` from
   (needs `docker`, `kubectl` pointed at the cluster, and `git`):
   ```bash
   cd ~/dev/company_dns   # or wherever your clone lives
   git checkout main
   git pull
   ```
4. **[you]** Create `.env` in the repo root (gitignored) with a GitHub PAT
   that has `write:packages` scope, if you haven't already:
   ```bash
   echo "GITHUB_PAT=ghp_xxxxxxxxxxxxxxxxxxxx" > .env
   ```

### 1. Bring the workload up (no traffic yet)

**[you]**, from the `main` checkout with `kubectl` pointed at the cluster:

```bash
kubectl apply -f k8s/prod/namespace.yaml -f k8s/prod/deployment.yaml -f k8s/prod/service.yaml
```

This still references the placeholder `image: ...:bootstrap` tag in
`deployment.yaml` — the pods will `ImagePullBackOff` until the first real
build. Build and push one now:

```bash
./scripts/build-and-deploy.sh
```

This builds from your current `main` checkout (so it includes the EDGAR/
Wikipedia fixes and the non-root Dockerfile change), pushes
`ghcr.io/miha42-github/company_dns/company_dns:<today's-date>`, updates
`deployment.yaml`'s `image:` field to match, re-applies everything in
`k8s/prod/` (harmless at this point — Ingress/Certificate don't exist yet
so nothing new happens there), and waits for the rollout.

```bash
kubectl -n company-dns get pods -o wide
# Expect 2/2 pods Running, spread across cafe-1 and espresso-1
```

### 2. Smoke test directly against the Service (Azure still live, no DNS touched)

**[you]**:

```bash
kubectl -n company-dns port-forward svc/company-dns 8080:80
```

In another terminal:

```bash
curl -s http://localhost:8080/health | jq .
curl -s http://localhost:8080/V3.0/na/sic/description/oil | jq '.data | keys[:3]'
curl -s http://localhost:8080/V3.0/global/company/merged/firmographics/IBM | jq '.code, .message'
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/
```

Compare a couple of these against the live Azure instance
(`https://company-dns.mediumroast.io/...`) to confirm parity. This is also
the first real chance to observe whether the EDGAR/Wikipedia fixes actually
moved the needle on latency for `merged/firmographics` — worth timing both.
Stop the port-forward (`Ctrl-C`) once satisfied.

### 3. Apply Ingress + Middleware + Certificate (still before touching DNS)

**[you]**:

```bash
kubectl apply -f k8s/prod/ingress.yaml -f k8s/prod/middleware-redirect.yaml -f k8s/prod/certificate.yaml
kubectl -n company-dns get certificate
# STATE will show it's not Ready yet - expected, DNS doesn't point here yet
```

### 4. DNS cutover — Phase 1

**[you]**, manually on Namecheap — see "DNS cutover — Namecheap
instructions" → "Phase 1" below for the exact record edit. Then:

```bash
dig @1.1.1.1 +short company-dns.mediumroast.io

kubectl -n company-dns get certificate -w
# wait for READY=True, then Ctrl-C
```

### 5. Verify over the real hostname

**[you]**:

```bash
curl -sv https://company-dns.mediumroast.io/health
curl -s https://company-dns.mediumroast.io/V3.0/global/company/merged/firmographics/IBM | jq '.code'
curl -s -o /dev/null -w '%{http_code}\n' https://company-dns.mediumroast.io/
```

If any of this fails: revert the Namecheap CNAME back to
`company-dns-dev.bluetree-243cfc38.westus.azurecontainerapps.io.` (see DNS
cutover → Phase 1 → Rollback) and stop here — diagnose before proceeding.
Azure is completely untouched at this point, so this rollback is instant.

If it all passes: per the aggressive-migration decision earlier in this
doc, proceed straight to Azure teardown — no extended burn-in.

### 6. Tear down Azure

**[you]** — now unblocked, you have Azure admin access. Find the actual
resource names first if you don't have them memorized (the GitHub Actions
secrets `AZURE_RESOURCE_GROUP` / `AZURE_CONTAINER_APP_NAME` /
`AZURE_CONTAINER_APP_ENV` hold these, but secret *values* aren't readable
from GitHub once set — easier to just ask Azure):

```bash
az account show   # confirm you're on the right subscription
az containerapp list -o table
```

Then follow "Teardown plan — Azure Container App" below step by step
(backup export → delete Container App → delete Container App Environment if
unused → remove GitHub Actions secrets → remove the `asuid.company-dns` TXT
record → remove `container-app-config.yaml` from the repo).

### 7. Update the GitHub Actions workflow

**[you or Claude]**, once Azure is torn down: remove the `Azure Login` and
`Deploy to Azure Container App` steps from
`.github/workflows/main.yml`, in the same PR that removes
`container-app-config.yaml`. This is intentionally the *last* code change,
not something to do preemptively — until Azure is actually gone, that
workflow is the thing keeping Azure in sync if anyone pushes to `main` or
manually dispatches it in the meantime.

### 8. (Later, unscheduled) DNS Phase 2

**[you]**, whenever — see "DNS cutover — Namecheap instructions" → "Phase 2"
below. Not blocking, not time-boxed.

---

## DNS cutover — Namecheap instructions

**All DNS steps in this section are performed manually by the user, not by
Claude** — noted here for completeness/reference only. This is a deliberate
two-phase approach: Phase 1 is the lower-risk option to prove the cluster
deployment actually works before investing in a dedicated DNS host for it;
Phase 2 decouples `company-dns` from `www`'s DNS lifecycle once that's
proven, and is not time-boxed or required for anything else in this plan.

**Current live records for `company-dns.mediumroast.io`** (looked up
2026-09-26, `dig`):

| Type | Host | Value |
|---|---|---|
| CNAME | `company-dns` | `company-dns-dev.bluetree-243cfc38.westus.azurecontainerapps.io.` |
| TXT | `asuid.company-dns` | `A2A0F9669E8D47DF65FD3500D85253C2C75BE9DA140D7801B25E4A70F30BEAA4` |

The TXT record is Azure's custom-domain *ownership verification* record
(`asuid.<subdomain>` is the format Azure Container Apps requires to bind a
custom hostname) — it has no effect once the CNAME no longer points at
Azure, but **do not delete it until Azure teardown** (Teardown step 6): if
you need a fast rollback to Azure before teardown, re-pointing the CNAME
back works instantly *only if* the TXT verification record is still there —
Azure re-checks it.

**Reference pattern already working on this cluster**: `www.mediumroast.io`
is a plain Namecheap **Dynamic DNS A record**, currently `98.150.72.44`
(the home router's public IP, auto-updated by a DDNS client whenever the IP
changes — see `~/dev/mediumroast.io/CLAUDE.md`). No separate router
port-forward is needed for `company-dns` — port 80/443 → Traefik
(`192.168.1.200`) is already forwarded for `www`, and Traefik does
host-header-based routing to pick the right Ingress (`company-dns.mediumroast.io`
→ the `company-dns` namespace's Ingress). The only thing that needs to
change is where the DNS name resolves to.

### Phase 1 — CNAME to `www.mediumroast.io` (migration step 6)

Rather than registering `company-dns` as its own DDNS-tracked A record up
front, point it at the name that's *already* DDNS-tracked, to isolate "does
the cluster deployment work" from "does a new DDNS host work":

```
Type:  CNAME Record
Host:  company-dns
Value: www.mediumroast.io.
TTL:   Automatic (or match whatever TTL www.mediumroast.io uses)
```

This way `company-dns.mediumroast.io` resolves to whatever IP
`www.mediumroast.io` currently has, with zero extra DDNS configuration.

**Steps in the Namecheap dashboard:**

1. Log in to [namecheap.com](https://www.namecheap.com) → **Domain List** →
   `mediumroast.io` → **Manage** → **Advanced DNS** tab.
2. Find the existing record: Type `CNAME Record`, Host `company-dns`, Value
   `company-dns-dev.bluetree-243cfc38.westus.azurecontainerapps.io.`
3. Edit that record's **Value** field only — change it to
   `www.mediumroast.io.` (keep the trailing dot, matching Namecheap's own
   convention for CNAME targets). Leave Host (`company-dns`) and Type
   (`CNAME Record`) unchanged.
4. Leave the `asuid.company-dns` TXT record alone for now (removed later,
   during Azure teardown).
5. Save.

**Verify propagation:**

```bash
# From an external resolver (bypasses any local DNS cache)
dig @1.1.1.1 +short company-dns.mediumroast.io
# Should eventually return the same A record www.mediumroast.io resolves to

dig @1.1.1.1 +short www.mediumroast.io
```

Namecheap's DNS typically propagates within minutes, but can take up to the
old record's TTL to fully clear cached resolvers worldwide. Once it
resolves to the cluster's IP, confirm cert-manager picked it up:

```bash
microk8s kubectl -n company-dns get certificate -w
# WAIT for READY=True, then Ctrl-C

curl -v https://company-dns.mediumroast.io/
```

**Rollback (Phase 1):** edit the same CNAME record's Value back to
`company-dns-dev.bluetree-243cfc38.westus.azurecontainerapps.io.` — Azure
Container App is untouched until the Teardown section runs, so this is a
fast, low-risk revert as long as teardown hasn't happened yet (and the
`asuid.company-dns` TXT record — Azure's ownership check — hasn't been
deleted).

### Phase 2 — dedicated Dynamic DNS host (migration step 9, deferred)

Once Phase 1 has been live and verified for a while, replace the CNAME with
`company-dns`'s own DDNS-tracked A record, using whatever Dynamic DNS client
mechanism already updates `www.mediumroast.io` (see
`~/dev/mediumroast.io/CLAUDE.md` for how that client is configured — this
plan doesn't duplicate that setup detail since it's specific to the DDNS
client already running on the user's network, not to company_dns). This
removes the indirection through `www`'s CNAME so `company-dns.mediumroast.io`
has no dependency on `www.mediumroast.io`'s own DNS record continuing to
exist or resolve correctly.

Not a blocker for Azure teardown or repo cleanup — those only need Phase 1
working. This phase has no target date in this plan; it's a follow-up
cleanup step, done manually, at the user's discretion.

## Teardown plan — Azure Container App

**Requires Azure CLI + credentials not available in this session — to be run
by the user, or handed to Claude with `az` access and explicit go-ahead.**

**Decision (aggressive migration posture)**: no soft "scale to zero and
wait" window and no multi-day observation period. Once migration step 7
(smoke test against the new `https://company-dns.mediumroast.io`) passes,
proceed straight to deletion in the same session. Fallback to Azure is
reserved for an actual detected failure during cutover/smoke-test — not
scheduled as a matter of course after a successful migration.

1. Confirm migration step 7 (smoke test against the new hostname) passed.
2. Export/record the current Container App config for rollback reference —
   cheap insurance, do this regardless of the faster timeline:
   `az containerapp show -n <name> -g <resource-group> -o yaml > azure-company-dns-backup.yaml`
   (keep outside the repo, or in `docs/plans/` as a dated snapshot — it may
   contain resource IDs but no secrets since none are configured in
   `container-app-config.yaml`).
3. Delete the Container App directly:
   `az containerapp delete -n <name> -g <resource-group>`.
4. Delete the Container App Environment if nothing else uses it:
   `az containerapp env delete -n <env-name> -g <resource-group>`
   (**confirm nothing else in the resource group depends on this
   environment first** — this check still applies even on the faster
   timeline, since it's irreversible and affects things beyond company_dns).
5. Remove the now-unused `AZURE_*` GitHub Actions secrets from the repo
   settings.
6. On Namecheap, delete the `asuid.company-dns` TXT record (Azure's
   ownership-verification record — no longer meaningful once the Container
   App itself is deleted, and leaving it around is just clutter).
7. Remove [container-app-config.yaml](../../container-app-config.yaml) from
   the repo in the same PR that strips the Azure steps from the workflow.

## Rollback plan

- Before DNS cutover: trivial — just don't touch the Namecheap CNAME record,
  nothing user-facing changed. `ingress.yaml`/`certificate.yaml` can already
  be applied at this point (per migration step 5) without affecting Azure.
- **During DNS cutover / smoke test (migration steps 6–7), if something's
  actually broken**: revert the Namecheap CNAME record back to
  `company-dns-dev.bluetree-243cfc38.westus.azurecontainerapps.io.` (see
  "DNS cutover" → Rollback above). Azure Container App is still running
  untouched at this point (nothing in Teardown has run yet), so this is a
  fast, low-risk rollback — the `asuid.company-dns` TXT record must still be
  in place too (it's only removed at Teardown step 6). **This is the only
  rollback path this plan expects to actually use** — once step 7 passes,
  Teardown runs immediately, closing this window.
- After Azure teardown (Container App deleted — the expected end state once
  step 7 passes): rollback means redeploying from the backed-up YAML
  (Teardown step 2) and `container-app-config.yaml` (restore from git
  history if already removed from `main`), then re-verifying the Azure
  custom domain binding (may need the `asuid.company-dns` TXT record
  recreated if it was already deleted) — slower and more manual, but the
  image is still on GHCR so nothing is lost. This path is the accepted
  tradeoff for not keeping Azure alive "just in case."
- After Azure teardown (Container App deleted): rollback means redeploying
  from `azure/container-apps-deploy-action` using the backed-up YAML from
  Teardown step 2 and `container-app-config.yaml` (restore from git history
  if already removed from `main`) — slower, but the image is still on GHCR
  so nothing is lost.

## Open questions for follow-up (not blocking the plan doc, but before execution)

1. ~~Does `company_dns.py` already set FastAPI `CORSMiddleware`...~~
   **Resolved**: yes, `company_dns.py:94-101`. No action needed.
2. ~~Confirm the Dockerfile can run as non-root without breaking
   `makedb.py`'s file writes...~~ **Resolved**: `makedb.py` still runs as
   root during the build (before the `USER company_dns` switch), and the
   Dockerfile `chown -R`s `/app` after, so the non-root runtime user owns
   everything it needs to read.
3. ~~Confirm whether `/` is a safe probe target...~~ **Resolved**: use the
   existing `/health` endpoint instead — it's lighter than `/` and clearly
   intended for exactly this.
4. ~~Decide on `:latest` + `Always` vs. pinned/dated tags...~~ **Resolved**:
   pinned dated tags, implemented in `scripts/build-and-deploy.sh`.
5. ~~Confirm who has Azure admin access...~~ **Resolved**: the user has
   Azure admin access and will run the Teardown `az` commands themselves
   (this session still has neither `az` CLI nor Azure credentials, so
   Teardown remains a user-executed step either way).
