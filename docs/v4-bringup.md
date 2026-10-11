# Bringing V4 up on staging

From a clean checkout to **V4 serving `https://company-dns-staging.mediumroast.io` from two pods**, verified. Follow it top to bottom.

> **Status: draft, written ahead of the scripts (2026-10-11).** Steps 3 to 6 use `scripts/seal-secrets-v4.sh` and `scripts/build-and-deploy-v4.sh`, which are planned in
> [`docs/plans/v4-staging-scripts.md`](plans/v4-staging-scripts.md) and not written yet; the commands show their intended interface. Everything else works today. The guide is marked
> **proven** (with a date) only after someone has followed it end to end on `cafe-1` (plan step E), fixing whatever it got wrong.

## What you end up with

| | |
|---|---|
| URL | `https://company-dns-staging.mediumroast.io` (Traefik at `192.168.1.200`, certificate from `letsencrypt-prod`) |
| Workload | Namespace `company-dns-staging`; Deployment `company-dns`, **2 replicas**, port 4000, 100m / 256Mi to 500m / 1Gi each, read-only root filesystem, UID 10001 |
| Image | `ghcr.io/miha42-github/company_dns/company_dns_v4:MMDDYYYY-<sha7>` (public, `linux/amd64`, the `release-small` profile, data and model inside) |
| Config | `k8s/staging/` (manifests only): rules and log level ConfigMaps, the sealed credentials |
| Profiles | `mediumroast.io` (no rate limit, SQL) and `staging-test` (own quota, SQL); the SQL endpoint is **on** here and off in production |
| Not touched | Production (`company-dns`, V3). The scripts can only act on `company-dns-staging`. |

## 1. What you need first (once)

| Need | How to check |
|---|---|
| A machine that is both a Docker build host and a cluster client: **`cafe-1`** (native amd64, Docker with buildx, `microk8s kubectl`). **Do every step on `cafe-1`**: the staging tokens are made there, and the script's checks and `--suite` read them from there. | `docker buildx version && kubectl get nodes` (or `microk8s kubectl get nodes`) |
| This repository on `main` | `git pull` |
| A GitHub PAT with `write:packages` in `.env` in the repository root (gitignored) | `grep -c '^GITHUB_PAT=' .env` prints 1 |
| The SIC data files in `tmp/` and the embedding model in `tmp/.fastembed_cache` | `ls tmp/*.feather tmp/.fastembed_cache`. Anything missing: [`v4-amd64-build-and-compare.md`](plans/v4-amd64-build-and-compare.md) §0 and §1 say where each comes from. |
| `kubeseal` (for step 3) | `kubeseal --version`. Install: the release binary from github.com/bitnami-labs/sealed-secrets, for the controller's major version. |
| `openssl`, `python3`, `curl`, `dig` | `openssl version && python3 --version` |
| DNS: `company-dns-staging.mediumroast.io` resolves (**done 2026-10-10**, it points where production does) | `dig +short company-dns-staging.mediumroast.io` |
| Roughly 20 GB free disk and 16 GB memory for the build | `df -h /var/lib/docker && free -g` |

Nothing about V4 needs AVX2: the image loads Microsoft's ONNX Runtime at run time, so it runs on `cafe-1`'s 2013 Xeons. Docker and buildx details for the nodes are in
[`v4-amd64-build-and-compare.md`](plans/v4-amd64-build-and-compare.md).

## 2. Check before changing anything

```bash
./scripts/build-and-deploy-v4.sh --check
```

Lists **every** missing prerequisite at once (token, Docker, buildx, cluster access, data, model, DNS, issuer, ingress class, sealed credentials) and changes nothing. Fix what it lists, run it
again until it is clean. (It reports the sealed credentials as missing until step 3; that is expected the first time.)

## 3. Make and seal the credentials (once, then only to rotate)

```bash
./scripts/seal-secrets-v4.sh
```

It finds the sealed-secrets controller itself, makes a token for each staging profile (`mediumroast.io`, `staging-test`), and writes:

- `~/company_dns-staging-secrets/tokens`: `profile:TOKEN`, mode 600, **the only copy**. Put each token in the password manager now. Nothing is printed. It lives on `cafe-1`, next to the deploy script,
  so the script's HTTPS checks and `--suite` can use it (staging tokens only; production's never exist here).
- `k8s/staging/sealedsecret-credentials.yaml`: the hashes, encrypted for the cluster, valid only as `company-dns-staging/company-dns-credentials`.

Then commit **only** the sealed file:

```bash
git status --short                       # only k8s/staging/sealedsecret-credentials.yaml is new
git grep -n -E "stringData|[0-9a-f]{64}" -- k8s/staging/sealedsecret-credentials.yaml   # no output
git add k8s/staging/sealedsecret-credentials.yaml && git commit -m "Staging sealed credentials"
```

(Open a pull request for it as usual. The next step reads the file from your checkout, so you do not have to wait for the merge.) Add `--apply` to apply it at once and have the Secret
ready: `./scripts/seal-secrets-v4.sh --apply`. If the cluster's sealing key was lost or the controller reinstalled, sealed files stop opening: run the script again.

## 4. Build, push and deploy

```bash
./scripts/build-and-deploy-v4.sh                  # tag = MMDDYYYY-<sha7>; or give one:  ./scripts/build-and-deploy-v4.sh 10112026-a1b2c3d
```

One command, no questions. About 15 to 25 minutes the first time (the Rust build is most of it; later builds reuse the cache). In order, it:

1. Runs the preflight of step 2, then logs in to `ghcr.io` with the PAT.
2. **Builds** the `release-small` amd64 image from this checkout, and **smoke-tests** it with no network (a failure stops here, before anything is pushed).
3. **Pushes** it, then pulls it back with no credentials. **First time only:** a new GHCR package starts private. The script prints the link to the package settings, and waits (up to 10
   minutes) for you to set `company_dns_v4` to **Public**; it continues by itself when the pull works. (The image is meant to be public: production and staging pods pull it without a secret.)
4. Prints what was running and what it is about to deploy. **The repository is not edited**: the tag is put into the Deployment as it is applied, so there is nothing to commit afterwards.
5. Applies, in order: the namespace, the sealed credentials (waiting for the Secret), the ConfigMaps, the Deployment (with the tag) and Service, then waits for the rollout. **A failed rollout is rolled
   back automatically** and the script exits with an error.
6. Port-forward smoke test (`/health` and a lookup, no Ingress involved). Only then the Ingress, the HTTP redirect and the Certificate; **the first time** it waits (up to 10 minutes) for the
   certificate to become ready (it needs the DNS name to point at the cluster, which it does).
7. Verifies through HTTPS: `/health`, a SIC lookup, **401** on `/V4.0/sql` with no credentials, and **200** with the `staging-test` token if `~/company_dns-staging-secrets/tokens` is present.
8. **Records** what is running (annotations on the Deployment: tag, commit, image digest, time) and appends a line to `v4/.build-log`; prints the summary (tag, digest, pods, URL).

Useful variants: `--status` (what is running, from the Deployment's annotations; changes nothing), `--dry-run` (preflight plus a server-side dry run of every manifest, changes nothing; do this once before the first real run), `--no-build TAG` (deploy a tag already
pushed), `--suite` (also run the API test suite with the staging token, which the script passes through the environment, never on a command line), `--rollback` (back to the previous revision) or `--rollback TAG`.

## 5. Check by hand that it is really up

```bash
H=https://company-dns-staging.mediumroast.io
curl -s $H/health
curl -s -A "bringup-check/1.0 (you@mediumroast.io)" $H/V4.0/na/sic/code/3571 | head -c 200; echo
./scripts/build-and-deploy-v4.sh --status             # the tag, commit, image digest and time of what is running (read from the Deployment's annotations)
kubectl -n company-dns-staging get pods -o wide        # two pods Running and Ready, on different nodes if the scheduler could
kubectl -n company-dns-staging get certificate         # READY True
kubectl -n company-dns-staging logs deploy/company-dns --tail=20     # includes the "CPU:" line (no AVX2 on cafe-1 is normal) and the replica and CORS settings
```

Open `$H/docs` (Swagger) and `$H/redoc` in a browser: the SQL endpoint should be listed (it is on in staging).

Credentials, directly:

```bash
B='{"dataset":"sic","sql":"select 1 as one"}'
curl -s -o /dev/null -w "no credentials: %{http_code}\n" -H 'content-type: application/json' -d "$B" $H/V4.0/sql                      # 401
curl -s -o /dev/null -w "wrong token:    %{http_code}\n" -u staging-test:wrong -H 'content-type: application/json' -d "$B" $H/V4.0/sql  # 401
TOKEN=$(grep '^staging-test:' ~/company_dns-staging-secrets/tokens | cut -d: -f2)
curl -s -o /dev/null -w "staging-test:   %{http_code}\n" -u staging-test:$TOKEN -H 'content-type: application/json' -d "$B" $H/V4.0/sql   # 200
```

## 6. Verify it (the staging gate)

This is plan step 7 ([`v4-release-to-staging.md`](plans/v4-release-to-staging.md)): do all of it before anyone talks about promotion.

1. **The test suite.** From any machine with the repository and the staging token:

   ```bash
   python3 api_tests/run.py --base-url $H --profile staging-test --token "$TOKEN" --layers L0,L1,L2,L4 --report /tmp/staging-suite.json
   ```

   Expect no failures. (L3, parity with live V3, is not a staging question. L5 starts its own server and does not apply to a remote one.)
2. **Log level changes without a restart.** `kubectl -n company-dns-staging edit configmap company-dns-log-level`, set `log-level: "debug"`, and within about a minute
   `kubectl -n company-dns-staging logs deploy/company-dns` shows the level change and more detail. Set it back to `"info"`.
3. **Rate limiting at two replicas.** The fleet allows a burst of about 20 to an identified caller (each pod 10). From one machine:

   ```bash
   for i in $(seq 1 40); do curl -s -o /dev/null -w "%{http_code}\n" -A "bringup-check/1.0 (you@mediumroast.io)" $H/V3.0/na/sic/code/7372; done | sort | uniq -c
   ```

   Expect roughly **20 `200`s and 20 `429`s**, not 40 `200`s (that would mean the limiter still thinks there are four replicas: check `COMPANY_DNS_REPLICAS` in the Deployment).
4. **CORS.** A browser page on another origin can call lookups; only mediumroast.io, its subdomains and localhost can call `/V4.0/sql`:

   ```bash
   curl -s -i -X OPTIONS -H "Origin: https://partner.example" -H "Access-Control-Request-Method: POST" $H/V4.0/sql | grep -i access-control-allow-origin   # no output
   curl -s -i -X OPTIONS -H "Origin: https://app.mediumroast.io" -H "Access-Control-Request-Method: POST" $H/V4.0/sql | grep -i access-control-allow-origin # echoes the origin
   ```
5. **The SQL capacity test** with the pass criteria in [`v4-sql-endpoint.md`](plans/v4-sql-endpoint.md) §5c. Its result sets the server-wide SQL limits; put them in the Deployment's environment
   (the `COMPANY_DNS_SQL_*` settings, listed in `v4/README.md`) and redeploy.
6. **A soak.** Leave it up for a defined period (suggested 72 hours) with a light steady load, and watch restarts, memory and the error rate:

   ```bash
   while true; do curl -s -o /dev/null -w "%{http_code} " -A "soak/1.0 (you@mediumroast.io)" $H/V4.0/na/sic/code/3571; sleep 5; done
   kubectl -n company-dns-staging get pods                  # RESTARTS stays 0
   kubectl -n company-dns-staging top pods                  # (if the cluster has metrics) memory stays flat (about 160 MiB idle, under 260 MiB peak was measured)
   ```

   Production shares these nodes: also watch `kubectl -n company-dns get pods` (its restart count must not move) and the nodes' load. If production degrades, stop the soak.
7. **The human passes.** Walk `/docs` as a first-time consumer; a hand-run security pass over rate limits, profiles and Basic auth over TLS.
8. **Rollback drill.** `./scripts/build-and-deploy-v4.sh --rollback`, check `/health` throughout and that staging returns to the previous image; then deploy the tag again.

**Go / no-go:** suite green; capacity-test criteria met; soak clean (no restarts, no memory growth); rollback exercised; V3 stays the production service until promotion (a separate decision).

## 7. Day-to-day

| To do this | Run |
|---|---|
| Deploy a new build | `./scripts/build-and-deploy-v4.sh` (nothing to commit: the tag is applied, not written into the repository) |
| See what is running | `./scripts/build-and-deploy-v4.sh --status` |
| Redeploy a tag already pushed | `./scripts/build-and-deploy-v4.sh --no-build TAG` |
| Roll back | `./scripts/build-and-deploy-v4.sh --rollback` |
| Change the log level on a live pod | Edit the `company-dns-log-level` ConfigMap (step 6.2) |
| Change profiles' rules | Edit `k8s/staging/configmap-rules.yaml`, redeploy (profiles are read at start) |
| Add a profile | Add it to the rules, then `./scripts/seal-secrets-v4.sh` (existing tokens are kept), redeploy |
| Rotate every token | `./scripts/seal-secrets-v4.sh --rotate`, commit the sealed file, redeploy, hand out the new tokens (a changed Secret alone does not restart pods: the redeploy does) |
| Change a setting (`COMPANY_DNS_*`) | Edit the Deployment's `env` in `k8s/staging/deployment.yaml`; the settings are in `v4/README.md` ("Settings reference"). `COMPANY_DNS_REPLICAS` must equal `replicas`. |
| Look at the pods | `kubectl -n company-dns-staging get pods -o wide` |
| Follow the logs | `kubectl -n company-dns-staging logs -f deploy/company-dns` |

## 8. When something is wrong

| Symptom | Likely cause and fix |
|---|---|
| Preflight lists a missing item | Fix it as listed; the list is complete, so one more run should be clean. |
| The build is killed or the link fails | Docker's VM or the host is short of memory (the fat-LTO link needs about 16 GB). |
| `ImagePullBackOff` | The package is still private: set `company_dns_v4` to Public (GitHub, Packages, Package settings), or the tag was never pushed. |
| Pods `ContainerCreating` for a long time, event says secret `company-dns-credentials` not found | The sealed credentials were not applied, or the controller cannot open them: `kubectl -n company-dns-staging describe sealedsecret company-dns-credentials`; re-run step 3. |
| The server exits at start with "rules name profile(s) with no credential" | `configmap-rules.yaml` names a profile with no token: run `seal-secrets-v4.sh` again (it covers every profile in the rules). |
| The server exits at start with a message about `COMPANY_DNS_REPLICAS` or `COMPANY_DNS_CORS_ORIGINS` | A bad value: the message says what is accepted (`v4/README.md`). |
| Certificate stays `False` | DNS does not point at the cluster, or the HTTP-01 challenge cannot reach Traefik: `kubectl -n company-dns-staging describe certificate,challenge`. The workload still works through a port-forward meanwhile. |
| 429s on your own checks | Use a self-identifying `User-Agent` (`name/1.0 (you@example.com)`) or the `staging-test` credentials; an anonymous caller gets 5 requests a minute. |
| 401 with the right token | The tokens file and the sealed secret are from different runs: seal again from the current tokens, redeploy (pods read credentials only at start). |
| A pod restarts | `kubectl -n company-dns-staging logs deploy/company-dns --previous`; note it, it is a soak failure. |

## 9. Where things live

| Thing | Path |
|---|---|
| The two scripts | `scripts/build-and-deploy-v4.sh`, `scripts/seal-secrets-v4.sh` (the V3 equivalent is `scripts/build-and-deploy.sh`) |
| Staging configuration (no scripts) | `k8s/staging/` |
| The image's tooling | `v4/Dockerfile`, `v4/scripts/docker-build.sh`, `v4/scripts/docker-smoke.sh` |
| What is running now | The annotations on the Deployment (`--status` prints them). The committed `k8s/staging/deployment.yaml` keeps the placeholder tag `UNSET` on purpose: do not edit it, and a manual `kubectl apply -f k8s/staging/` cannot replace a good image with a broken one (the placeholder cannot be pulled, and the running pods keep serving). |
| What was built and pushed | `v4/.build-log` (gitignored, one JSON line per run) on the machine that ran the script |
| Tokens | `~/company_dns-staging-secrets/` on `cafe-1` (mode 600, staging-only), and the password manager |
| Settings reference | `v4/README.md`, "Settings reference" |
| Plans | [`v4-staging-rollout.md`](plans/v4-staging-rollout.md) (the outcome and the verification gate), [`v4-staging-scripts.md`](plans/v4-staging-scripts.md) (the scripts) |
