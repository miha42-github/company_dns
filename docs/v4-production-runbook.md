# Putting V4 into production: the runbook, from the build to the cutover

For the person at the cluster, on the **build node** (a native amd64 Linux machine with Docker, `kubectl` reaching the cluster, and the SIC data in `tmp/`). It runs from "the code is merged" to "production is served by V4", one command per step, and says what to expect after each. It carries out work packages WP3, WP5 and WP6 of [plans/v4-production-cutover.md](plans/v4-production-cutover.md) by hand, because the cutover script (WP4) is not written yet.

The parts:

1. **Build the image and put it on staging.** The only build in the whole procedure.
2. **Prove it on staging, and write down the tag.**
3. **Deploy V4 to production beside V3**, with no public traffic.
4. **The cutover.**
5. **The way back.** Works at any moment.
6. **After the cutover**, including the soak, which runs on production.

**Promote, do not rebuild.** The image is built once (part 1), tested on staging (part 2) and then production runs *the very same tag* (part 3). Nothing is built after part 1.

No addresses or host names of the lab's machines appear here (the repository is open source): `<traefik-lan-ip>` stands for Traefik's address on the LAN.

The idea: V4 runs in the `company-dns` namespace beside V3 as its own Deployment and Service (`company-dns-v4`), with its own labels, so V3's Service never sees V4's pods. The cutover changes one thing, the backend of the two Ingresses, from V3's Service (`company-dns`) to V4's (`company-dns-v4`). The host, the certificate and the redirect do not change. The rollback is the same change in the other direction.

## What you need before you start

- Every pull request for this work is merged to `main` (the liveness probe, the production manifests, the credentials script, the standard-tier change for trusted origins, the runbook itself). Part 1 checks this.
- The build node has: Docker with `buildx`, about 20 GB free for the build, `kubectl` (or `microk8s kubectl`), `python3`, `curl`, `kubeseal` (for production credentials), `tmux`, `git`.
- `.env` in the repository root with a line `GITHUB_PAT=<a token with write:packages>` (gitignored).
- The SIC data in `tmp/` (the `.feather` files) and the embedding model in `tmp/.fastembed_cache` (the script looks for both and says what is missing).
- Staging's credentials in `~/company_dns-staging-secrets/` (the `staging-test` token, used by the suite).
- Time: the build takes 15 to 25 minutes the first time; the rest of parts 1 to 3 about an hour; the cutover and its two-hour watch are part 4.

If the build node only has `microk8s kubectl`, define this once in the shell you use below, so every `kubectl` command in this document works as written:

```bash
kubectl() { microk8s kubectl "$@"; }
```

## Before part 1: can the build node reach the names?

Several steps below use the staging and production names (the origin check, the suite, the public-name checks of the cutover). The build node is a cluster node, and its own resolver does not necessarily answer these names with Traefik's LAN address: it can answer with the public address, which a machine inside the network cannot use, and a request by name then stalls for its whole timeout. The deploy script and the origin check's `--connect-to` do not depend on this; the rest does.

**0.1. See what the build node resolves** (the staging name and the production name). Both should print Traefik's LAN address:

```bash
getent hosts company-dns-staging.mediumroast.io company-dns.mediumroast.io
```

**0.2. If they print a public address, or nothing, make this machine use Traefik's address for these two names.** Get the address first (the Ingress's load balancer address) and check it prints one:

```bash
LB=$(kubectl -n company-dns-staging get ingress company-dns -o jsonpath='{.status.loadBalancer.ingress[0].ip}'); echo "$LB"
```

Then add both names to this machine's hosts file (it affects this machine only, not the pods or other machines):

```bash
echo "$LB company-dns-staging.mediumroast.io company-dns.mediumroast.io" | sudo tee -a /etc/hosts
```

**0.3. Check again.** Both names must now print the address from 0.2:

```bash
getent hosts company-dns-staging.mediumroast.io company-dns.mediumroast.io
```

From here on, a check by name from this machine tests the path inside the network. That is why the cutover also asks for a check from outside the LAN (a phone on mobile data): only that proves the public path.

## Part 1: build the image and put it on staging

**1.1. Open a `tmux` session**, so a dropped connection does not kill a build that has taken twenty minutes:

```bash
tmux new -s release
```

(If it is already running: `tmux attach -t release`.)

**1.2. Go to the repository and get `main` exactly as it is on GitHub:**

```bash
cd ~/company_dns && git checkout main && git pull --ff-only
```

Adjust the path if the checkout lives elsewhere. `--ff-only` makes git stop, rather than merge, if the local copy has drifted.

**1.3. Check the tree is clean.** It must print nothing (a tag has to name its source; the script refuses a build from uncommitted changes):

```bash
git status --porcelain --untracked-files=no
```

**1.4. Check the merged work is in the checkout.** Look at the recent history and find the standard-tier change for trusted origins ("A trusted Origin or Referer earns the standard tier"), the liveness probe change ("A patient liveness probe") and the production manifests:

```bash
git log --oneline -12
```

Then confirm the code is what you expect, the two lines that matter most. The first prints the trusted-origin handling (it should mention `from_trusted_origin`), the second the patient liveness probe in staging's manifest (it should show `failureThreshold: 6`):

```bash
grep -n "from_trusted_origin" v4/crates/server/src/rate_limit.rs | head -3
```

```bash
grep -n -A6 "livenessProbe" k8s/staging/deployment.yaml
```

**1.5. Set the tag, once, in this shell.** The tag is `MMDDYYYY-` and the first seven characters of the commit, for example `10172026-8a1effd`. It names its source, and it is what production will run. This is the same name the script would choose by default; setting it yourself means you know it before the build starts:

```bash
export TAG="$(date +%m%d%Y)-$(git rev-parse --short=7 HEAD)"
```

**1.6. Write the tag down**, now, somewhere other than this shell (a note, the channel where the release is coordinated). The shell can be lost; the tag also lives in the build log and on the staging Deployment (step 2.2), but write it down anyway:

```bash
echo "$TAG"
```

**1.7. Ask the script whether everything it needs is in place.** It changes nothing and lists every problem at once. Fix whatever it lists (it names each fix), then run it again until it says `Preflight passed`:

```bash
./scripts/build-and-deploy-v4.sh --check "$TAG"
```

**1.8. See what is running on staging now**, so you can tell afterwards that it changed:

```bash
./scripts/build-and-deploy-v4.sh --status
```

**1.9. Build, push and deploy to staging, and run the API suite.** One command. It logs in to GHCR with the token in `.env`, builds the image (15 to 25 minutes), smoke-tests it with no network *before* pushing it, pushes it, checks it can be pulled without credentials, applies staging's manifests, waits for the rollout, checks it through a port-forward and then through HTTPS, stamps the Deployment with the tag, commit and digest, appends a line to `v4/.build-log`, and runs the suite (layers L0, L1, L2 and L4). If the rollout fails it rolls staging back by itself:

```bash
./scripts/build-and-deploy-v4.sh --suite "$TAG"
```

Expect it to end with `Done. <your tag> is running` and 20 of 20 replicas ready. If the **container smoke test** fails before anything is pushed (a long list of failures from `docker-smoke.sh`), nothing has reached the registry or the cluster: send the output to the maintainer, and after a fix is merged start again from step 1.2. The commit changes, so **the tag changes too: set it again in step 1.5 and write the new one down.** Docker's build cache makes the second build much faster. If the suite reports failures, **stop here**: the image does not go to production. If the package is reported as private, the script says exactly where to make it public and waits; the package was made public for staging, so this should not happen.

## Part 2: prove it on staging, and write down the tag

**2.1. See that staging runs the tag you just built:**

```bash
./scripts/build-and-deploy-v4.sh --status
```

`Tag` must be your `$TAG`, `Commit` the commit from step 1.4, and the pods all ready.

**2.2. Get the tag back from the cluster.** This is how to recover the tag if the shell is lost, and how you check your note against the cluster. It must print your tag:

```bash
kubectl -n company-dns-staging get deployment company-dns -o go-template='{{index .metadata.annotations "company-dns.mediumroast.io/deployed-tag"}}{{"\n"}}'
```

The build log has the same record, one JSON line per deploy (tag, image, digest, commit, time):

```bash
tail -n 1 v4/.build-log
```

**2.3. Check staging has the patient liveness probe** (the 5-second timeout and six failures). It must print `5` and `6`:

```bash
kubectl -n company-dns-staging get deployment company-dns -o jsonpath='{.spec.template.spec.containers[0].livenessProbe.timeoutSeconds} {.spec.template.spec.containers[0].livenessProbe.failureThreshold}{"\n"}'
```

**2.4. Check that a trusted `Origin` no longer skips the rate limit.** This sends about 1,500 lookups seven ways, one flood after another, and takes about three to four minutes. It changes nothing on the cluster. From the build node the staging name does not always resolve (a plain `curl` by name can stall for its whole timeout, while a request straight to the ingress answers in milliseconds), so reach the service through Traefik's own LAN address (the Ingress's load balancer address, which is what the deploy script does). First get it, and check it prints an address:

```bash
LB=$(kubectl -n company-dns-staging get ingress company-dns -o jsonpath='{.status.loadBalancer.ingress[0].ip}'); echo "$LB"
```

Then run the check through it. It starts with one lookup and says at once if it cannot reach the service (it prints `reached ...` and then a line before each flood). It must end with **CLOSED** (if it ends with BYPASS PRESENT, the image does not have the change: stop):

```bash
python3 perf_tests/origin_check.py --expect closed --connect-to "$LB"
```

**2.5. Part 2 is done when** staging runs your tag with all pods ready, the suite passed in step 1.9, the probe shows 5 and 6, and the origin check says CLOSED. The tag you have written down is the release. **There is no soak on staging**: the soak runs on production after the cutover (part 6).

## Part 3: deploy V4 to production, beside V3, with no public traffic

Nothing in this part changes what the public sees: V3 keeps serving, and V4's Service has no Ingress.

**3.1. Check the tag is still set in this shell** (if not, set it from your note: `export TAG=<the tag>`):

```bash
echo "$TAG"
```

**3.2. Look at production as it is**, so you can tell afterwards that V3 was not disturbed. Four V3 pods, ready:

```bash
kubectl -n company-dns get pods -o wide
```

**3.3. Make the production credentials and seal them.** This creates the token for the `mediumroast.io` profile in `~/company_dns-prod-secrets` (a separate directory from staging's; the script refuses to use staging's), seals it for the cluster, and applies the sealed secret:

```bash
./scripts/seal-secrets-v4.sh --env prod --apply
```

Expect `company-dns-v4-credentials exists`. **Copy the token into the password manager now** (`~/company_dns-prod-secrets/tokens`, the only copy).

**3.4. Commit the sealed secret** (the only file to commit; it opens only in this cluster, as this one Secret). From a branch, then a pull request that you merge:

```bash
git checkout -b chore/prod-sealed-secret && git add k8s/prod-v4/sealedsecret-credentials.yaml && git status --short
```

`git status` must show only that one file. Then:

```bash
git commit -m "The sealed production credentials for V4" && git push -u origin chore/prod-sealed-secret
```

Open the pull request on GitHub. Then return to `main` for everything below:

```bash
git checkout main
```

**3.5. Ask the cluster to check the manifests**, changing nothing:

```bash
kubectl apply --dry-run=server -f k8s/prod-v4/
```

Every object should print `created (server dry run)` or `configured (server dry run)`. (If `sealedsecret-credentials.yaml` is not on `main` yet, that file is the one not listed; it was applied in step 3.3.) The Deployment's tag is the placeholder `UNSET`; that is fine for a dry run.

**3.6. Apply the configuration and the Service:**

```bash
kubectl apply -f k8s/prod-v4/configmap-rules.yaml -f k8s/prod-v4/configmap-loglevel.yaml -f k8s/prod-v4/service.yaml
```

**3.7. Apply the Deployment with the tag put in.** The file in the repository keeps the placeholder `UNSET`, which can never be pulled; the tag is substituted as the file is applied. This is where production gets the same image staging ran:

```bash
sed "s|company_dns_v4:UNSET|company_dns_v4:${TAG}|" k8s/prod-v4/deployment.yaml | kubectl apply -f -
```

**3.8. Wait for all 20 pods to be ready** (up to ten minutes; the image is pulled once per node):

```bash
kubectl -n company-dns rollout status deployment/company-dns-v4 --timeout=600s
```

**3.9. Record what is running on the Deployment**, as staging does:

```bash
kubectl -n company-dns annotate deployment company-dns-v4 company-dns.mediumroast.io/tag=${TAG} company-dns.mediumroast.io/deployed-at=$(date -u +%FT%TZ) --overwrite
```

**3.10. Check that production runs the same image as staging**, byte for byte. These two print the image digest of a staging pod and a production pod; the two lines must be identical (`ghcr.io/...@sha256:...`):

```bash
kubectl -n company-dns-staging get pods -l app.kubernetes.io/name=company-dns -o jsonpath='{.items[0].status.containerStatuses[0].imageID}{"\n"}'
```

```bash
kubectl -n company-dns get pods -l app.kubernetes.io/name=company-dns-v4 -o jsonpath='{.items[0].status.containerStatuses[0].imageID}{"\n"}'
```

If they differ, stop: production is not running what staging proved.

**3.11. Check the pods are spread across the nodes and V3 is untouched:**

```bash
kubectl -n company-dns get pods -o wide
```

You should see 20 `company-dns-v4-...` pods on both nodes and the same 4 V3 pods as in step 3.2, with no new restarts.

**3.12. Look at V4 without public traffic.** In one terminal (a second `tmux` window works: `Ctrl-b c`):

```bash
kubectl -n company-dns port-forward svc/company-dns-v4 18090:80
```

In another, check health and a lookup (a port-forward reaches one pod, which is enough to see it answers):

```bash
curl -s http://127.0.0.1:18090/health
```

```bash
curl -s -A "runbook/1.0 (you@example.org)" http://127.0.0.1:18090/V4.0/na/sic/code/3571 | head -c 300
```

**3.13. Check the credentials work and staging's do not.** Put the production token in the shell without printing it (from the token file made in step 3.3). The checks below hand it to `curl` on its standard input, so it never appears on a command line:

```bash
PROD_TOKEN=$(grep '^mediumroast.io:' ~/company_dns-prod-secrets/tokens | cut -d: -f2)
```

The production token must be accepted (`200`):

```bash
printf 'user = "mediumroast.io:%s"\n' "${PROD_TOKEN}" | curl -s -K - -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18090/V4.0/na/sic/code/3571
```

A staging token must be refused (`401`). Put one in the shell the same way from staging's token file:

```bash
STAGING_TOKEN=$(grep '^staging-test:' ~/company_dns-staging-secrets/tokens | cut -d: -f2)
```

```bash
printf 'user = "staging-test:%s"\n' "${STAGING_TOKEN}" | curl -s -K - -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18090/V4.0/na/sic/code/3571
```

**3.14. The API test suite against it** (still through the port-forward; the production token has no rate limit; the SQL layer does not apply because the endpoint is off):

```bash
BASE_URL=http://127.0.0.1:18090 API_TESTS_PROFILE=mediumroast.io API_TESTS_TOKEN="${PROD_TOKEN}" python3 api_tests/run.py --layers L0,L1,L2
```

Stop the port-forward (`Ctrl-c` in its window). **Part 3 is done when** all 20 pods are ready, the digests match, V3 is unchanged, the production token is accepted, the staging token is refused and the suite passes.

## Part 4: the cutover (a quiet moment, someone watching)

Preconditions: part 3 done; the clients have been told; the rollback (part 5) is open in front of you; the pod watcher is running (step 4.1).

**4.1. Start the cluster-side watcher** in its own `tmux` window (`Ctrl-b c`), so there is a record (it reads only):

```bash
python3 perf_tests/pod_watch.py --namespace company-dns --interval 5 --out ./tmp/watch-cutover
```

Switch back to the first window (`Ctrl-b 0`).

**4.2. Record the Ingresses as they are:**

```bash
kubectl -n company-dns get ingress -o yaml > ingress-before-cutover.yaml
```

**4.3. Flip the HTTPS Ingress to V4:**

```bash
kubectl -n company-dns patch ingress company-dns --type=json -p '[{"op":"replace","path":"/spec/rules/0/http/paths/0/backend/service/name","value":"company-dns-v4"}]'
```

**4.4. Flip the HTTP (redirect) Ingress too**, so both name the same Service:

```bash
kubectl -n company-dns patch ingress company-dns-http --type=json -p '[{"op":"replace","path":"/spec/rules/0/http/paths/0/backend/service/name","value":"company-dns-v4"}]'
```

**4.5. Confirm both now point at V4:**

```bash
kubectl -n company-dns get ingress -o jsonpath='{range .items[*]}{.metadata.name}{" -> "}{.spec.rules[0].http.paths[0].backend.service.name}{"\n"}{end}'
```

**4.6. Within a minute, check the public name.** Health, then lookups from each family, then the V3-shaped path, then the redirect (from the build node this uses the hosts entry of step 0.2; from a machine that cannot reach the public address and has no such entry, add `--resolve company-dns.mediumroast.io:443:${LB}` to each `curl`, with `LB` set as in step 0.2):

```bash
curl -s https://company-dns.mediumroast.io/health
```

```bash
curl -s -A "runbook/1.0 (you@example.org)" https://company-dns.mediumroast.io/V4.0/na/sic/code/3571 | head -c 300
```

```bash
curl -s -A "runbook/1.0 (you@example.org)" https://company-dns.mediumroast.io/V4.0/eu/sic/class/25.91 | head -c 300
```

```bash
curl -s -A "runbook/1.0 (you@example.org)" https://company-dns.mediumroast.io/V4.0/japan/sic/industry_group/0911 | head -c 300
```

```bash
curl -s -A "runbook/1.0 (you@example.org)" https://company-dns.mediumroast.io/V3.0/na/sic/code/3571 | head -c 300
```

```bash
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' https://company-dns.mediumroast.io/
```

The last one should print a redirect to `/ui/`. Open `https://company-dns.mediumroast.io/ui/` in a browser and run a search. **Then check from outside the LAN** (a phone on mobile data): the site loads and a lookup answers.

**4.7. The suite against the public name:**

```bash
BASE_URL=https://company-dns.mediumroast.io API_TESTS_PROFILE=mediumroast.io API_TESTS_TOKEN="${PROD_TOKEN}" python3 api_tests/run.py --layers L0,L1,L2
```

**4.8. Watch for two hours.** The pod watcher is recording. Look for: restarts, pods not ready, memory, `429`s and `5xx` in the logs:

```bash
kubectl -n company-dns logs -l app.kubernetes.io/name=company-dns-v4 --since=10m --max-log-requests=20 --tail=20
```

**Roll back (part 5) if** the `5xx` rate stays above 1%, p95 on lookups is above two seconds for five minutes, a pod crash-loops, or a client-breaking difference turns up. Otherwise the cutover is complete when the two hours pass and the owner says so.

## Part 5: the way back (works at any moment)

Point both Ingresses back at V3. Nothing else changes; V3's pods have been running the whole time.

```bash
kubectl -n company-dns patch ingress company-dns --type=json -p '[{"op":"replace","path":"/spec/rules/0/http/paths/0/backend/service/name","value":"company-dns"}]'
```

```bash
kubectl -n company-dns patch ingress company-dns-http --type=json -p '[{"op":"replace","path":"/spec/rules/0/http/paths/0/backend/service/name","value":"company-dns"}]'
```

Confirm with the command in step 4.5 (both should say `company-dns`), then check `https://company-dns.mediumroast.io/health` answers. Write down what made you roll back.

**Never apply `k8s/prod/ingress.yaml` while V4 is live:** it names V3's Service and would flip the traffic back. Moving the Ingress manifests into the V4 directory is a later step (WP8 of the plan), done after V3 is retired.

## Part 6: after the cutover

- **The soak runs here, on production** (not on staging): a second machine and person, protocol in [soak-test.md](soak-test.md). It is the extended stability evidence the plan asked for. Start it once step 4.7 has passed, with the pod watcher still running beside it:

  ```bash
  python3 perf_tests/soak.py --url https://company-dns.mediumroast.io --label <name> --hours 48 --rps 60 --out ./soak-prod
  ```

  If the soak shows a rollback trigger, use part 5.
- **V3 stays up** (four pods, taking no traffic) as the standing rollback until after the event (plan D6). Do not scale it down or delete it before about 26 October.
- **Freeze on 21 October:** no deploys during the event unless a rollback trigger fires.
- **After the event** (about 26 October): put the anonymous tier back to its defaults by deleting the two `COMPANY_DNS_RATE_LIMIT_ANONYMOUS_*` lines in `k8s/prod-v4/deployment.yaml` and applying (as in steps 3.6 and 3.7); re-decide the size from the real traffic; then WP8, retiring V3.

## Quick reference

| I need | Command |
|---|---|
| the tag, in this shell | `echo "$TAG"` |
| the tag, if the shell is lost | step 2.2 (staging's Deployment), or `tail -n 1 v4/.build-log` |
| the tag production runs | `kubectl -n company-dns get deployment company-dns-v4 -o jsonpath='{.spec.template.spec.containers[0].image}'` |
| what staging runs | `./scripts/build-and-deploy-v4.sh --status` |
| to go back to V3 | part 5 |
