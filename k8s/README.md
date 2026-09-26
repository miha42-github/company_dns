# company_dns on MicroK8s

Kubernetes manifests for running `company_dns` on the on-prem MicroK8s HA
cluster (worker nodes `cafe-1` / `espresso-1`), replacing the Azure
Container App. Full context and rationale: see
[docs/plans/onprem-k8s-migration.md](../docs/plans/onprem-k8s-migration.md).

## Layout

```
k8s/prod/
  namespace.yaml            # the "company-dns" namespace
  deployment.yaml           # 2-replica Deployment, spread across cafe-1/espresso-1
  service.yaml               # ClusterIP :80 -> pod :8000
  ingress.yaml               # HTTPS ingress + HTTP->HTTPS redirect ingress
  middleware-redirect.yaml   # Traefik Middleware used by the redirect ingress
  certificate.yaml           # cert-manager Certificate (letsencrypt-prod issuer)
```

Single environment (prod only) - no dev/staging tiers, matching the
footprint of the single Azure Container App revision this replaces.

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
