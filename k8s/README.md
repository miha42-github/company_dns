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

## Cluster DNS (not a manifest here)

CoreDNS answers the cluster's public host names with Traefik's LAN address (`<traefik-lan-ip>`), because pods cannot reach the router's public address and cert-manager's self-check of an HTTP-01 challenge needs to. It is a manual edit of `kube-system`'s `coredns` ConfigMap, so it is **not** in this directory; it is recorded, with the host list and the rules for keeping it right, in [docs/plans/onprem-k8s-migration.md](../docs/plans/onprem-k8s-migration.md) ("In-cluster DNS for the public names"). Add a host there and in the ConfigMap whenever a site with a certificate is added.

## Staging (V4): `k8s/staging/`

> **Maintainer-focused.** These manifests and the scripts that apply them assume this project's cluster (Traefik, cert-manager with an issuer named `letsencrypt-prod`, SealedSecrets, our host names and registry). The application and the container image are general; the manifests are a reference to adapt. The intention is to make the scripts generic: see the table in [v4/README.md](../v4/README.md#deploying-it-three-layers).

V4 at `https://company-dns-staging.mediumroast.io`, twenty replicas in the `company-dns-staging` namespace, on the same cluster. It is **not** a copy of
`k8s/prod/` (which is V3): V4 listens on **4000**, runs as UID 10001 with a read-only root filesystem, and takes its credentials, rules and log level from
mounted files. Plan and order of work: [docs/plans/v4-staging-rollout.md](../docs/plans/v4-staging-rollout.md).

```
k8s/staging/
  namespace.yaml           company-dns-staging
  configmap-rules.yaml     profiles' rules (no secrets); every profile needs a line in the credentials Secret
  configmap-loglevel.yaml  the live log level (a directory mount, so an edit reaches the pod)
  deployment.yaml          20 replicas, port 4000, /health probes, 500m/512Mi to 1000m/1Gi, locked down
  service.yaml             ClusterIP 80 -> 4000
  ingress.yaml             HTTPS and the HTTP redirect for company-dns-staging.mediumroast.io
  middleware-redirect.yaml
  certificate.yaml         letsencrypt-prod
```

### Build, push and deploy

`k8s/staging/` holds configuration only. The scripts live in `scripts/`, next to the V3 one, and the whole procedure is [docs/v4-bringup.md](../docs/v4-bringup.md):

```bash
./scripts/seal-secrets-v4.sh            # once: tokens (outside the repo) and k8s/staging/sealedsecret-credentials.yaml; commit only that file
./scripts/build-and-deploy-v4.sh --check   # preflight: lists everything missing, changes nothing
./scripts/build-and-deploy-v4.sh        # build, push, deploy, verify (run on the build node)
./scripts/build-and-deploy-v4.sh --status  # what is running (tag, commit, digest, time)
```

The committed Deployment keeps the placeholder tag `UNSET` on purpose: the deploy script puts the real tag in as it applies the manifest and records it on the Deployment's annotations, so there is
nothing to commit after a deploy.

The credentials are delivered as a SealedSecret (`sealedsecret-credentials.yaml`, which opens only as `company-dns-staging/company-dns-credentials`). The Deployment mounts the Secret, so the pods
will not start without it, and the deploy script applies the sealed file first and stops if the Secret is missing.

Without a cluster, `python3 -m unittest k8s/test_staging_manifests.py` (needs PyYAML) checks that staging touches only its own namespace, host, secret and certificate, that port, probes,
Service and Ingress agree, that `COMPANY_DNS_REPLICAS` equals `replicas`, that the container is locked down, and that no script lives here. `python3 scripts/test_v4_scripts.py` exercises both
scripts against stub `kubectl`, `docker`, `curl` and `kubeseal` (no cluster, registry or network). Against the cluster, `./scripts/build-and-deploy-v4.sh --dry-run` is a server-side dry run of
every manifest.
