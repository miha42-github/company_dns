# Staging credentials: make, seal, deploy, verify, rotate

Runbook for work package WP4 of [`docs/plans/v4-staging-rollout.md`](../../docs/plans/v4-staging-rollout.md). Staging has **its own** credentials: production's
tokens never exist here and staging's never exist there, so a noisy or leaked staging client can do nothing to production.

**How it fits together.** The server reads a *credentials file* (`profile:sha256-of-token` lines, hashes only) and a *rules* file (JSON, no secrets; here the ConfigMap
`configmap-rules.yaml`). Clients call with HTTP Basic Auth: the profile name as the user, the token as the password. The credentials file is mounted from the Kubernetes
Secret `company-dns-credentials`. That Secret is delivered as a **SealedSecret**: an encrypted file that is safe to commit and that only the cluster's controller can
open, and (strict scope) only as that Secret name in the `company-dns-staging` namespace. Plaintext tokens exist in exactly one place: your password manager.

Profiles staging defines (`configmap-rules.yaml`): **`mediumroast.io`** (no rate limit; SQL on `sic` and `edgar`) for the site, and **`staging-test`** (a generous quota; SQL)
for the suite, the capacity test and you. Every profile in the rules needs a credential, and every credential a profile in the rules or the server refuses to start.
To add a profile, add it to `configmap-rules.yaml`, then run the steps below again with `--rotate` **not** set (existing tokens are kept).

## What you need

- `kubectl` pointed at the cluster, and `openssl`.
- `kubeseal` (`brew install kubeseal` on a Mac; or the release binary from github.com/bitnami-labs/sealed-secrets for the same major version as the cluster's controller).
- The controller's namespace and name. Find them once:

  ```bash
  kubectl get pods -A | grep -i sealed
  # for example: kube-system   sealed-secrets-controller-xxxxx  -> namespace kube-system, name sealed-secrets-controller
  ```

## 1. Make the tokens and the credentials file

```bash
k8s/staging/make-credentials.sh                      # writes ~/company_dns-staging-secrets/{tokens,credentials}, mode 600, outside the repo
```

- `tokens` holds `profile:TOKEN` for each profile: **the only copy**. Put each line in the password manager now. Nothing is printed to the terminal.
- `credentials` holds the matching hashes: this is what goes into the Secret.
- The script refuses to write inside the repository, and keeps the tokens it already made unless you pass `--rotate`.

## 2. Seal it

```bash
k8s/staging/make-credentials.sh --seal --controller-namespace kube-system --controller-name sealed-secrets-controller
# (use the values from the grep above; tokens already made are kept)
```

This writes `k8s/staging/sealedsecret-credentials.yaml`. **Commit that file and nothing else from this step.** Check before committing:

```bash
git status --short                                   # only sealedsecret-credentials.yaml is new
git grep -n -i -E "stringData|[0-9a-f]{64}" -- k8s/staging/sealedsecret-credentials.yaml   # no output: nothing in the clear
head -8 k8s/staging/sealedsecret-credentials.yaml    # kind: SealedSecret, namespace: company-dns-staging, name: company-dns-credentials
```

(Sealing needs the cluster, because the controller's public certificate is fetched from it. If the cluster is unreachable, fetch the certificate on a machine that can reach it
with `kubeseal --fetch-cert > cert.pem`, and pass `--cert cert.pem` to `make-credentials.sh --seal`.)

## 3. Deploy picks it up

`k8s/staging/deploy.sh` applies the SealedSecret before the workload and waits for the controller to create the Secret. If the file is missing or the controller cannot open it,
the script stops before the pods are created, with a message. Check by hand:

```bash
kubectl -n company-dns-staging get sealedsecret company-dns-credentials     # SYNCED should be True
kubectl -n company-dns-staging get secret company-dns-credentials           # exists
kubectl -n company-dns-staging describe sealedsecret company-dns-credentials | tail -5   # the controller's events, if it is not
```

## 4. Verify the credentials work (after the first deploy)

```bash
H=https://company-dns-staging.mediumroast.io
B='{"dataset":"sic","sql":"select 1 as one"}'
curl -s -o /dev/null -w "no credentials:  %{http_code}\n" -H 'content-type: application/json' -d "$B" $H/V4.0/sql              # 401
curl -s -o /dev/null -w "wrong token:     %{http_code}\n" -u staging-test:wrong -H 'content-type: application/json' -d "$B" $H/V4.0/sql   # 401
TOKEN=$(grep '^staging-test:' ~/company_dns-staging-secrets/tokens | cut -d: -f2)
curl -s -o /dev/null -w "staging-test:    %{http_code}\n" -u staging-test:$TOKEN -H 'content-type: application/json' -d "$B" $H/V4.0/sql   # 200
```

The same three results were produced locally against the V4 image with these scripts' output (a read-only container with the credentials and the rules mounted), so a different
result on the cluster points at the Secret or the mounts, not at the server.

## 5. The two must-checks

- **Nothing sensitive in the repository:** `git grep -n -E "[0-9a-f]{64}" -- k8s/` finds no token or hash; the manifest test also refuses a plain `Secret` in `k8s/staging/`.
- **Not usable elsewhere:** the SealedSecret is bound to `company-dns-staging/company-dns-credentials`. Applying it in any other namespace leaves the controller unable to open it
  (do not try this in production; the binding is the point).

## Rotating a token, or a lost token

1. `k8s/staging/make-credentials.sh --rotate` (every profile gets a new token), then step 2 again, commit the new sealed file, `k8s/staging/deploy.sh TAG`.
2. The pods read the credentials once at start; the deploy restarts them with the new Secret (a changed Secret alone does **not** restart a pod: run
   `kubectl -n company-dns-staging rollout restart deployment/company-dns` if you change only the Secret).
3. Hand the new token to its client, and update the password manager. The old token stops working when the pods restart.

## If the cluster's sealing key is lost or the controller is reinstalled

Existing SealedSecrets can no longer be opened. Run steps 2 and 3 again (the plaintext tokens in `tokens` are still good; only the sealed file changes). Back up the controller's
key as the cluster's own runbook says; that is a cluster concern, not this repository's.

## What not to do

Do not commit `tokens` or `credentials`, paste a token into a ticket, a chat or a shell history line, reuse a production token here (staging's whole point is that it holds none),
or put the credentials in the image or a ConfigMap.
