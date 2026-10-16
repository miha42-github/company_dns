# Putting V4 into production: the runbook

For the person at the cluster (the build node, with `kubectl` reaching the cluster). It carries out work packages WP3, WP5 and WP6 of [plans/v4-production-cutover.md](plans/v4-production-cutover.md) by hand, step by step, because the cutover script (WP4) is not written yet. Each step is one command and says what to expect. **Part A changes nothing the public can see.** Part B is the cutover. Part C is the way back, and works at any moment.

No addresses or host names of the lab's machines appear here (the repository is open source): `<traefik-lan-ip>` stands for Traefik's address on the LAN.

The idea: V4 runs in the `company-dns` namespace beside V3 as its own Deployment and Service (`company-dns-v4`), with its own labels, so V3's Service never sees V4's pods. The cutover changes one thing, the backend of the two Ingresses, from V3's Service (`company-dns`) to V4's (`company-dns-v4`). The host, the certificate and the redirect do not change. The rollback is the same change in the other direction.

## Before you start

- V4 has already passed staging and **you know the tag** that did. It is the tag the staging Deployment runs (`./scripts/build-and-deploy-v4.sh --status` prints it). Production runs exactly that tag: **promote, do not rebuild.**
- You are on the build node, in a checkout of this repository on `main`, up to date.
- `kubeseal` is installed (`seal-secrets-v4.sh` tells you if not).

## Part A: deploy V4 beside V3, with no public traffic

**A1. Set the tag**, once, in the shell you use for everything below (replace with the tag staging runs):

```bash
export TAG=<the tag that passed staging>
```

**A2. Look at production as it is**, so you can tell afterwards that V3 was not disturbed. Four V3 pods, ready:

```bash
kubectl -n company-dns get pods -o wide
```

**A3. Make the production credentials and seal them.** This creates the token for the `mediumroast.io` profile in `~/company_dns-prod-secrets` (a separate directory from staging's; the script refuses to use staging's), seals it for the cluster, and applies the sealed secret:

```bash
./scripts/seal-secrets-v4.sh --env prod --apply
```

Expect `company-dns-v4-credentials exists`. **Copy the token into the password manager now** (`~/company_dns-prod-secrets/tokens`, the only copy). Then commit only `k8s/prod-v4/sealedsecret-credentials.yaml` (a pull request, as for staging).

**A4. Ask the cluster to check the manifests**, changing nothing:

```bash
kubectl apply --dry-run=server -f k8s/prod-v4/
```

Every object should print `created (server dry run)` or `configured (server dry run)`. The Deployment's tag is the placeholder `UNSET`; that is fine for a dry run.

**A5. Apply the configuration and the Service:**

```bash
kubectl apply -f k8s/prod-v4/configmap-rules.yaml -f k8s/prod-v4/configmap-loglevel.yaml -f k8s/prod-v4/service.yaml
```

**A6. Apply the Deployment with the tag put in** (the repository file keeps the placeholder; the tag is substituted as it is applied):

```bash
sed "s|company_dns_v4:UNSET|company_dns_v4:${TAG}|" k8s/prod-v4/deployment.yaml | kubectl apply -f -
```

**A7. Wait for all 20 pods to be ready:**

```bash
kubectl -n company-dns rollout status deployment/company-dns-v4 --timeout=600s
```

**A8. Record what is running on the Deployment**, as staging does:

```bash
kubectl -n company-dns annotate deployment company-dns-v4 company-dns.mediumroast.io/tag=${TAG} company-dns.mediumroast.io/deployed-at=$(date -u +%FT%TZ) --overwrite
```

**A9. Check the pods are spread across the nodes and V3 is untouched:**

```bash
kubectl -n company-dns get pods -o wide
```

You should see 20 `company-dns-v4-...` pods on both nodes and the same 4 V3 pods as in A2, with no new restarts.

**A10. Look at V4 without public traffic.** In one terminal:

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

**A11. Check the credentials work and staging's do not.** Put the production token in the shell without printing it (use the token file from A3). The checks below hand it to `curl` on its standard input, so it never appears on a command line:

```bash
PROD_TOKEN=$(grep '^mediumroast.io:' ~/company_dns-prod-secrets/tokens | cut -d: -f2)
```

The production token must be accepted (`200`):

```bash
printf 'user = "mediumroast.io:%s"\n' "${PROD_TOKEN}" | curl -s -K - -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18090/V4.0/na/sic/code/3571
```

A staging token must be refused (`401`). Put one in the shell the same way from staging's token file, then:

```bash
STAGING_TOKEN=$(grep '^staging-test:' ~/company_dns-staging-secrets/tokens | cut -d: -f2)
```

```bash
printf 'user = "staging-test:%s"\n' "${STAGING_TOKEN}" | curl -s -K - -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18090/V4.0/na/sic/code/3571
```

**A12. The API test suite against it** (still through the port-forward; the production token has no rate limit; the SQL layer does not apply because the endpoint is off):

```bash
BASE_URL=http://127.0.0.1:18090 API_TESTS_PROFILE=mediumroast.io API_TESTS_TOKEN="${PROD_TOKEN}" python3 api_tests/run.py --layers L0,L1,L2
```

Stop the port-forward (`Ctrl-c`). **Part A is done when** all 20 pods are ready, V3 is unchanged, the production token is accepted, the staging token is refused and the suite passes.

## Part B: the cutover (a quiet moment, someone watching)

Preconditions: Part A done; the clients have been told; you have the rollback command (Part C) in front of you; the pod watcher is running (B1).

**B1. Start the cluster-side watcher** in `tmux`, so there is a record (it reads only):

```bash
python3 perf_tests/pod_watch.py --namespace company-dns --interval 5 --out ./tmp/watch-cutover
```

**B2. Record the Ingresses as they are:**

```bash
kubectl -n company-dns get ingress -o yaml > ingress-before-cutover.yaml
```

**B3. Flip the HTTPS Ingress to V4:**

```bash
kubectl -n company-dns patch ingress company-dns --type=json -p '[{"op":"replace","path":"/spec/rules/0/http/paths/0/backend/service/name","value":"company-dns-v4"}]'
```

**B4. Flip the HTTP (redirect) Ingress too**, so both name the same Service:

```bash
kubectl -n company-dns patch ingress company-dns-http --type=json -p '[{"op":"replace","path":"/spec/rules/0/http/paths/0/backend/service/name","value":"company-dns-v4"}]'
```

**B5. Confirm both now point at V4:**

```bash
kubectl -n company-dns get ingress -o jsonpath='{range .items[*]}{.metadata.name}{" -> "}{.spec.rules[0].http.paths[0].backend.service.name}{"\n"}{end}'
```

**B6. Within a minute, check the public name.** Health, then lookups from each family, then the V3-shaped path, then the redirect (from a machine that cannot reach the public address, add `--resolve company-dns.mediumroast.io:443:<traefik-lan-ip>` to each `curl`):

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

**B7. The suite against the public name:**

```bash
BASE_URL=https://company-dns.mediumroast.io API_TESTS_PROFILE=mediumroast.io API_TESTS_TOKEN="${PROD_TOKEN}" python3 api_tests/run.py --layers L0,L1,L2
```

**B8. Watch for two hours.** The pod watcher is recording. Look for: restarts, pods not ready, memory, `429`s and `5xx` in the logs:

```bash
kubectl -n company-dns logs -l app.kubernetes.io/name=company-dns-v4 --since=10m --max-log-requests=20 --tail=20
```

**Roll back (Part C) if** the `5xx` rate stays above 1%, p95 on lookups is above two seconds for five minutes, a pod crash-loops, or a client-breaking difference turns up. Otherwise the cutover is complete when the two hours pass and the owner says so.

## Part C: the way back (works at any moment)

Point both Ingresses back at V3. Nothing else changes; V3's pods have been running the whole time.

```bash
kubectl -n company-dns patch ingress company-dns --type=json -p '[{"op":"replace","path":"/spec/rules/0/http/paths/0/backend/service/name","value":"company-dns"}]'
```

```bash
kubectl -n company-dns patch ingress company-dns-http --type=json -p '[{"op":"replace","path":"/spec/rules/0/http/paths/0/backend/service/name","value":"company-dns"}]'
```

Confirm with the command in B5 (both should say `company-dns`), then check `https://company-dns.mediumroast.io/health` answers. Write down what made you roll back.

**Never apply `k8s/prod/ingress.yaml` while V4 is live:** it names V3's Service and would flip the traffic back. Moving the Ingress manifests into the V4 directory is a later step (WP8 of the plan), done after V3 is retired.

## Part D: after the cutover

- **Soak.** Start the long soak against production (a second machine and person; protocol in [soak-test.md](soak-test.md)): `python3 perf_tests/soak.py --url https://company-dns.mediumroast.io --label <name> --hours 48 --rps 60 --out ./soak-prod`. Keep `pod_watch.py` running beside it.
- **V3 stays up** (four pods, taking no traffic) as the standing rollback until after the event (plan D6). Do not scale it down or delete it before about 26 October.
- **Freeze on 21 October:** no deploys during the event unless a rollback trigger fires.
- **After the event** (about 26 October): put the anonymous tier back to its defaults by deleting the two `COMPANY_DNS_RATE_LIMIT_ANONYMOUS_*` lines in `k8s/prod-v4/deployment.yaml` and applying; re-decide the size from the real traffic; then WP8, retiring V3.
