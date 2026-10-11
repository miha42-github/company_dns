# company_dns on MicroK8s

Kubernetes manifests for running `company_dns` on the on-prem MicroK8s HA
cluster (worker nodes `host-1` / `host-2`), replacing the Azure
Container App. Full context and rationale: see
[docs/plans/onprem-k8s-migration.md](../docs/plans/onprem-k8s-migration.md).

## Layout

```
k8s/prod/
  namespace.yaml            # the "company-dns" namespace
  deployment.yaml           # 2-replica Deployment, spread across host-1/host-2
  service.yaml               # ClusterIP :80 -> pod :8000
  ingress.yaml               # HTTPS ingress + HTTP->HTTPS redirect ingress
  middleware-redirect.yaml   # Traefik Middleware used by the redirect ingress
  certificate.yaml           # cert-manager Certificate (letsencrypt-prod issuer)
```

Single environment (prod only) - no dev/staging tiers, matching the
footprint of the single Azure Container App revision this replaces.

## Staging (V4): `k8s/staging/`

V4 at `https://company-dns-staging.mediumroast.io`, two replicas in the `company-dns-staging` namespace, on the same cluster. It is **not** a copy of
`k8s/prod/` (which is V3): V4 listens on **4000**, runs as UID 10001 with a read-only root filesystem, and takes its credentials, rules and log level from
mounted files. Plan and order of work: [docs/plans/v4-staging-rollout.md](../docs/plans/v4-staging-rollout.md).

```
k8s/staging/
  namespace.yaml           company-dns-staging
  configmap-rules.yaml     profiles' rules (no secrets); every profile needs a line in the credentials Secret
  configmap-loglevel.yaml  the live log level (a directory mount, so an edit reaches the pod)
  deployment.yaml          2 replicas, port 4000, /health probes, 100m/256Mi to 500m/1Gi, locked down
  service.yaml             ClusterIP 80 -> 4000
  ingress.yaml             HTTPS and the HTTP redirect for company-dns-staging.mediumroast.io
  middleware-redirect.yaml
  certificate.yaml         letsencrypt-prod
```

### Build, push and deploy

```bash
# 1. On the amd64 build machine (cafe-1): build, smoke-test, push, and check the image pulls anonymously. Needs GITHUB_PAT (write:packages) in .env.
v4/scripts/build-and-push.sh                 # tag = MMDDYYYY-<git sha7>; prints it and records it in v4/.build-log
# 2. Anywhere with kubectl on the cluster. Changes only company-dns-staging; does not edit the repository.
k8s/staging/deploy.sh --dry-run TAG          # server-side dry run of everything; once, before the first apply
k8s/staging/deploy.sh --first-time TAG       # namespace, config, workload, port-forward smoke test, then Ingress and certificate
k8s/staging/deploy.sh TAG                    # routine redeploy
k8s/staging/deploy.sh --rollback             # back to the previous revision (or --rollback TAG for a specific one)
```

A brand-new GHCR package starts **private**: after the first push, make `company_dns_v4` public once (the push script's anonymous-pull check fails with instructions until you do).

The credentials are delivered as a SealedSecret: `k8s/staging/make-credentials.sh` makes the tokens and their hashes (outside the repository), seals the hashes for the cluster, and
[`k8s/staging/CREDENTIALS.md`](staging/CREDENTIALS.md) is the runbook (make, seal, deploy, verify, rotate). The Deployment mounts the Secret, so the pods will not start without it, and the
deploy script applies the sealed file first and stops if the Secret is missing.

Not here yet (a later work package): the first-rollout runbook (WP6).

Without a cluster, `python3 -m unittest k8s/test_staging_manifests.py` (needs PyYAML) checks that staging touches only its own namespace, host, secret and certificate,
that port, probes, Service and Ingress agree, that `COMPANY_DNS_REPLICAS` equals `replicas`, and that the container is locked down. Against the cluster, before the first apply:
`k8s/staging/deploy.sh --dry-run TAG`. `python3 -m unittest k8s/test_staging_scripts.py` exercises the scripts against stub `kubectl`, `docker` and `curl` (no cluster, registry or network).

## First-time cutover (do this once, in order)

Don't just `kubectl apply -f k8s/prod/` on the very first run - the
Ingress/Certificate need DNS to already point at the cluster before
cert-manager's HTTP-01 challenge can succeed, and you don't want to touch
DNS before the workload itself is verified. Follow the migration plan's
step-by-step order:

1. `kubectl apply -f k8s/prod/namespace.yaml -f k8s/prod/deployment.yaml -f k8s/prod/service.yaml`
2. Smoke-test via `kubectl -n company-dns port-forward svc/company-dns 8080:80`
   and hit `http://localhost:8080/health`, `/V3.0/...` endpoints, etc.
3. `kubectl apply -f k8s/prod/ingress.yaml -f k8s/prod/middleware-redirect.yaml -f k8s/prod/certificate.yaml`
   (cert-manager will retry/backoff harmlessly until DNS points here - see
   step 4)
4. Cut over DNS manually (Namecheap) - see the migration plan's "DNS
   cutover" section.
5. `kubectl -n company-dns get certificate -w` until `READY=True`, then
   smoke-test again over `https://company-dns.mediumroast.io`.

After that, the Azure Container App is decommissioned per the migration
plan's Teardown section.

## Routine redeploys (after the first cutover)

```bash
./scripts/build-and-deploy.sh            # tags with today's date, MMDDYYYY
./scripts/build-and-deploy.sh 20261101   # explicit tag
```

This builds the image from the current working tree's `Dockerfile`, pushes
it to `ghcr.io/miha42-github/company_dns/company_dns:<tag>`, bumps the
`image:` field in `k8s/prod/deployment.yaml` to match, applies everything in
`k8s/prod/`, and waits for the rollout to finish. Requires a `.env` file in
the repo root with `GITHUB_PAT=<a PAT with write:packages scope>` (see the
script's header comment), and `kubectl` already pointed at the cluster.

Image tags are always pinned (`MMDDYYYY` or an explicit tag) - never
`:latest` - so it's always unambiguous what's running and easy to roll back
by re-running the script with a prior tag.

## Useful commands

```bash
kubectl -n company-dns get pods -o wide
kubectl -n company-dns get certificate
kubectl -n company-dns rollout status deployment/company-dns
kubectl -n company-dns logs -l app.kubernetes.io/name=company-dns --tail=100 -f
```
