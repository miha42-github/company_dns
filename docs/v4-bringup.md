# Bringing V4 up on staging

From a clean checkout to **V4 serving `https://company-dns-staging.mediumroast.io` from twenty pods**, verified. Follow it top to bottom.

> **Status: proven for deployment and stability (2026-10-13).** The scripts and this guide were followed on the build node on 2026-10-11 (tag `10112026-f255f85`; the API suite
> passed, 57 OK and 3 skipped) and fixed wherever the first runs found a fault. A 24-hour soak from outside the network then passed (5.18 million requests, no errors, 7,200 of 7,200
> known-answer checks correct, p95 between 110 and 126 ms, no drift) at a steady 60 requests/s: [`performance-report.md`](performance-report.md). **Not recorded or not yet run:** the shape and image tag staging ran during the soak were not written down; at the current size (20 pods) these have not been run:
> the rate-limit check of step 6.3, the CORS check, the rollback drill and a rolling update; the stability result covers one known workload, not the capacity ceiling
> (the sizing results are in the report).

## What you end up with

| | |
|---|---|
| URL | `https://company-dns-staging.mediumroast.io` (Traefik at `<traefik-lan-ip>`, certificate from `letsencrypt-prod`) |
| Workload | Namespace `company-dns-staging`; Deployment `company-dns`, **20 replicas**, port 4000, 500m / 512Mi to 1000m / 1Gi each, read-only root filesystem, UID 10001 |
| Image | `ghcr.io/miha42-github/company_dns/company_dns_v4:MMDDYYYY-<sha7>` (public, `linux/amd64`, the `release-small` profile, data and model inside) |
| Config | `k8s/staging/` (manifests only): rules and log level ConfigMaps, the sealed credentials |
| Profiles | `mediumroast.io` and `staging-test`, both with **no rate limit** and SQL access (the suite sends hundreds of requests in seconds, so a quota throttles it to 429s); the SQL endpoint is **on** here and off in production |
| Not touched | Production (`company-dns`, V3). The scripts can only act on `company-dns-staging`. |

## 1. What you need first (once)

| Need | How to check |
|---|---|
| A machine that is both a Docker build host and a cluster client: **the build node** (a native amd64 worker with Docker and buildx, and `microk8s kubectl`; this guide calls it "the build node"). **Do every step on the build node**: the staging tokens are made there, and the script's checks and `--suite` read them from there. | `docker buildx version && kubectl get nodes` (or `microk8s kubectl get nodes`) |
| This repository on `main` | `git pull` |
| A GitHub PAT with `write:packages` in `.env` in the repository root (gitignored) | `grep -c '^GITHUB_PAT=' .env` prints 1 |
| The SIC data files in `tmp/` and the embedding model in `tmp/.fastembed_cache` | `ls tmp/*.feather tmp/.fastembed_cache`. Anything missing: [`v4-amd64-build-and-compare.md`](plans/v4-amd64-build-and-compare.md) §0 and §1 say where each comes from. |
| `kubeseal` (for step 3) | `kubeseal --version`. Install: the release binary from github.com/bitnami-labs/sealed-secrets, for the controller's major version. |
| `openssl`, `python3`, `curl`, `dig` | `openssl version && python3 --version` |
| DNS: `company-dns-staging.mediumroast.io` resolves to the public address (**done 2026-10-10**, it points where production does); ports 80 and 443 are forwarded from the router (Firewalla) to Traefik at `<traefik-lan-ip>`; **and CoreDNS answers the name with `<traefik-lan-ip>` inside the cluster** (the `hosts` block below). Without the CoreDNS block the certificate never issues: cert-manager checks its own challenge from inside the cluster, and a pod cannot reach the public address (the router does not loop LAN traffic back). Found on the first real run, after the port forward moved to `<traefik-lan-ip>`; it affects every name served by the cluster and every certificate renewal (the earliest was due 2026-10-19). | `kubectl -n kube-system get cm coredns -o yaml \| grep -A3 hosts` shows the block, and a pod resolves the name to `<traefik-lan-ip>` (below) |
| Roughly 20 GB free disk and 16 GB memory for the build | `df -h /var/lib/docker && free -g` |

Nothing about V4 needs AVX2: the image loads Microsoft's ONNX Runtime at run time, so it runs on the build node's 2013 Xeons. Docker and buildx details for the nodes are in
[`v4-amd64-build-and-compare.md`](plans/v4-amd64-build-and-compare.md).

### The CoreDNS block (once per cluster, and when a new site is added)

```bash
kubectl -n kube-system edit configmap coredns
```

Add this above the `forward` line, listing **every** name the cluster serves that has an HTTP-01 certificate (`kubectl get ingress -A` shows them; do not use a wildcard, which would capture names served elsewhere):

```
    hosts {
      <traefik-lan-ip> company-dns-staging.mediumroast.io company-dns.mediumroast.io dev.mediumroast.io staging.mediumroast.io www.mediumroast.io dex.mediumroast.io mediumroast.io
      fallthrough
    }
```

then `kubectl -n kube-system rollout restart deploy/coredns`. `<traefik-lan-ip>` is the Ingress controller's LAN address: `kubectl get ingress -n company-dns-staging` shows it in the ADDRESS column. Check from a pod:

```bash
kubectl -n company-dns-staging run c1 --rm -it --restart=Never --image=curlimages/curl -- curl -sv -m 10 http://company-dns-staging.mediumroast.io/.well-known/acme-challenge/test
# resolves to <traefik-lan-ip> and answers a 301 redirect to https (the path is not a real challenge token)
```

Re-enabling MicroK8s DNS resets manual CoreDNS edits: repeat this step if you ever run `microk8s disable dns`. (The router doing NAT loopback would make this unnecessary.)

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

- `~/company_dns-staging-secrets/tokens`: `profile:TOKEN`, mode 600, **the only copy**. Put each token in the password manager now. Nothing is printed. It lives on the build node, next to the deploy script,
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
7. Verifies through HTTPS **via Traefik's LAN address** (the Ingress's load balancer IP, with the real host name for TLS and routing), because a machine on the LAN cannot reach the public address: `/health`, a SIC lookup, **401** on `/V4.0/sql` with no credentials, and **200** with the `staging-test` token if `~/company_dns-staging-secrets/tokens` is present.
8. **Records** what is running (annotations on the Deployment: tag, commit, image digest, time) and appends a line to `v4/.build-log`; prints the summary (tag, digest, pods, URL).

Useful variants: `--status` (what is running, from the Deployment's annotations; changes nothing), `--dry-run` (preflight plus a server-side dry run of every manifest, changes nothing; do this once before the first real run), `--no-build TAG` (deploy a tag already
pushed), `--suite` (also run the API test suite with the staging token, which the script passes through the environment, never on a command line), `--rollback` (back to the previous revision) or `--rollback TAG`.

## 5. Check by hand that it is really up

```bash
H=https://company-dns-staging.mediumroast.io
curl -s $H/health
curl -s -A "bringup-check/1.0 (you@example.org)" $H/V4.0/na/sic/code/3571 | head -c 200; echo
./scripts/build-and-deploy-v4.sh --status             # the tag, commit, image digest and time of what is running (read from the Deployment's annotations)
kubectl -n company-dns-staging get pods -o wide        # two pods Running and Ready, on different nodes if the scheduler could
kubectl -n company-dns-staging get certificate         # READY True
kubectl -n company-dns-staging logs deploy/company-dns --tail=20     # includes the "CPU:" line (no AVX2 on the build node is normal) and the replica and CORS settings
```

**From outside your network** (a phone on cellular, Wi-Fi off), open `$H/health` (a small JSON answer), then `$H/` (it redirects to the web UI at `/ui/`, as V3's root page did; before 2026-10-11 the bare URL was a 404, which looks like a failure but was only a missing route). The checks above run from inside the LAN; this is the one that shows the internet path works.

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
3. **Rate limiting across the replicas.** The fleet allows an identified caller 6000 requests a minute with a burst of 600 (30 per pod over 20 pods). One sequential `curl` loop refills as fast as it spends, so use parallel requests from one machine:

   ```bash
   seq 1 2000 | xargs -P 100 -I{} curl -s -o /dev/null -w "%{http_code}\n" -A "bringup-check/1.0 (you@example.org)" $H/V3.0/na/sic/code/7372 | sort | uniq -c
   ```

   Expect mostly `200`s and **some `429`s** once the per-pod bursts are used up; the exact counts depend on how the requests spread across the pods. All `200`s from a much larger run would mean the limiter divides by too many replicas; a `429` after only a few dozen requests would mean it divides by too few (check `COMPANY_DNS_REPLICAS` and `COMPANY_DNS_RATE_LIMIT_*` in the Deployment, and the "Per-IP rate limits" line in the pod log).
4. **CORS.** A browser page on another origin can call lookups; only mediumroast.io, its subdomains and localhost can call `/V4.0/sql`:

   ```bash
   curl -s -i -X OPTIONS -H "Origin: https://partner.example" -H "Access-Control-Request-Method: POST" $H/V4.0/sql | grep -i access-control-allow-origin   # no output
   curl -s -i -X OPTIONS -H "Origin: https://app.mediumroast.io" -H "Access-Control-Request-Method: POST" $H/V4.0/sql | grep -i access-control-allow-origin # echoes the origin
   ```
5. **The SQL capacity test** with the pass criteria in [`v4-sql-endpoint.md`](plans/v4-sql-endpoint.md) §5c. Its result sets the server-wide SQL limits; put them in the Deployment's environment
   (the `COMPANY_DNS_SQL_*` settings, listed in `v4/README.md`) and redeploy.
6. **A soak.** Leave it up for a defined period (suggested 72 hours) with a light steady load, and watch restarts, memory and the error rate:

   ```bash
   while true; do curl -s -o /dev/null -w "%{http_code} " -A "soak/1.0 (you@example.org)" $H/V4.0/na/sic/code/3571; sleep 5; done
   kubectl -n company-dns-staging get pods                  # RESTARTS stays 0
   kubectl -n company-dns-staging top pods                  # (if the cluster has metrics) memory stays flat (about 160 MiB idle, under 260 MiB peak was measured)
   ```

   Production shares these nodes: also watch `kubectl -n company-dns get pods` (its restart count must not move) and the nodes' load. If production degrades, stop the soak.
7. **The human passes.** Walk `/docs` as a first-time consumer; a hand-run security pass over rate limits, profiles and Basic auth over TLS.
8. **Rollback drill.** `./scripts/build-and-deploy-v4.sh --rollback`, check `/health` throughout and that staging returns to the previous image; then deploy the tag again.

**Go / no-go:** suite green; capacity-test criteria met; soak clean (no restarts, no memory growth); rollback exercised; V3 stays the production service until promotion (a separate decision).

**Sizing the replicas (optional, before changing their size).** To compare, for example, two larger replicas against four smaller ones with the same total, see [`docs/plans/v4-sizing-test.md`](plans/v4-sizing-test.md): `python3 perf_tests/run_cluster.py --dry-run`, then without `--dry-run`. It changes only the staging Deployment, restores it afterwards, and stops if a production pod restarts.

## 7. Day-to-day

| To do this | Run |
|---|---|
| Deploy a new build | `./scripts/build-and-deploy-v4.sh` (nothing to commit: the tag is applied, not written into the repository) |
| See what is running | `./scripts/build-and-deploy-v4.sh --status` |
| Redeploy a tag already pushed | `./scripts/build-and-deploy-v4.sh --no-build TAG` |
| Roll back | `./scripts/build-and-deploy-v4.sh --rollback` |
| Change the log level on a live pod | Edit the `company-dns-log-level` ConfigMap (step 6.2) |
| Change profiles' rules | Edit `k8s/staging/configmap-rules.yaml`, run `./scripts/build-and-deploy-v4.sh --no-build TAG`: the script restarts the pods itself when the rules or credentials changed but the image did not (profiles are read only at start) |
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
| `ERROR: uncommitted changes in the working tree` | A tag must name its source: commit, or pass `--allow-dirty` for a throwaway build (its tag ends in `-dirty`; do not leave it deployed). |
| The server exits at start with "rules name profile(s) with no credential" | `configmap-rules.yaml` names a profile with no token: run `seal-secrets-v4.sh` again (it covers every profile in the rules). |
| The server exits at start with a message about `COMPANY_DNS_REPLICAS` or `COMPANY_DNS_CORS_ORIGINS` | A bad value: the message says what is accepted (`v4/README.md`). |
| Certificate stays `False`, and `describe challenge` says "failed to perform self check GET request ... context deadline exceeded" | **No route from a pod to the public address** (hit on the first real run): add the name to the CoreDNS `hosts` block (prerequisites above) and restart CoreDNS. cert-manager retries by itself; to hurry it, `kubectl -n company-dns-staging delete challenge --all` (cert-manager recreates it). Then re-run `./scripts/build-and-deploy-v4.sh --no-build TAG` (the tag is in the running Deployment's image): it waits for the certificate if needed and continues with the HTTPS checks. |
| The challenge is `pending` with Let's Encrypt's own error, for example "Timeout during connect (likely firewall problem)" | Port 80 is not reaching Traefik from the internet: check the router's forward of 80 (and 443) to `<traefik-lan-ip>`, and test from a phone on cellular: `http://company-dns-staging.mediumroast.io/.well-known/acme-challenge/test` should answer, not hang. |
| Certificate stays `False` for another reason | DNS does not point at the cluster, or the HTTP-01 challenge cannot reach Traefik: `kubectl -n company-dns-staging describe certificate,challenge`. The workload still works through a port-forward meanwhile. |
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
| Tokens | `~/company_dns-staging-secrets/` on the build node (mode 600, staging-only), and the password manager |
| Settings reference | `v4/README.md`, "Settings reference" |
| Plans | [`v4-staging-rollout.md`](plans/v4-staging-rollout.md) (the outcome and the verification gate), [`v4-staging-scripts.md`](plans/v4-staging-scripts.md) (the scripts) |
