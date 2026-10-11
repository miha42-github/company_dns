# V4 staging scripts: follow the established pattern, automate more, fold into `svc_ctl.sh` later

Status: **Implemented (2026-10-11): steps A to D below are done; step E, the first real run on `cafe-1`, is next.** The scripts are tested against stubs only (`python3 scripts/test_v4_scripts.py`, 45 tests); neither has run against a registry or the cluster yet. Decisions in section 5: apply-time tag with the cluster as the record, one run on `cafe-1`, tokens sealed on `cafe-1`.
Owner: michael.hay@mediumroast.io
Replaces the script parts of work packages WP2, WP4 and WP5 in [`v4-staging-rollout.md`](v4-staging-rollout.md) (the manifests, WP3, stay as they are).
Goal: **V4 operable on staging** (`https://company-dns-staging.mediumroast.io`). Some technical debt is accepted to get there; section 6 sketches paying it off.

---

## 1. What went wrong, and the direction (decided 2026-10-11)

PR #121 added three scripts that look nothing like the one that already deploys V3 ([`scripts/build-and-deploy.sh`](../../scripts/build-and-deploy.sh)): `v4/scripts/build-and-push.sh`,
`k8s/staging/deploy.sh` and `k8s/staging/make-credentials.sh`, with a separate runbook, `k8s/staging/CREDENTIALS.md`. They split one job across three places, use different
conventions (flags, tag handling, the way they report) and put executables in a directory meant for configuration. That is the wrong approach: the repository already has an
established pattern, and V4 should follow it.

Decisions:

1. **`k8s/staging/` holds configuration only.** No scripts, no runbooks (the manifests, ConfigMaps, and the sealed secret once it exists).
2. **Two scripts under `scripts/`, modelled on `build-and-deploy.sh`:** `scripts/build-and-deploy-v4.sh` and `scripts/seal-secrets-v4.sh`. Same layout, same conventions, with **more lights-out
   automation** than the V3 script (section 3).
3. **One guide, [`docs/v4-bringup.md`](../v4-bringup.md),** goes through every step needed to bring V4 to an operable state on staging, start to finish, so nobody needs the plan documents to do it.
4. **Long term, `svc_ctl.sh` becomes the single entry point** for both V3 and V4 (section 6). Not implemented now.

## 2. What `build-and-deploy.sh` establishes, and what V4 keeps

| Convention in the V3 script | V4 script |
|---|---|
| One script, run from the repository root, builds from the current checkout and deploys with `kubectl` on the same machine | **Keep.** Run it on `cafe-1`, which has Docker, the data and `microk8s kubectl`. |
| Header comment with usage, arguments, what it does **not** do | **Keep**, same shape. |
| `set -euo pipefail`; `SCRIPT_DIR`, `REPO_ROOT`, constants at the top (`REGISTRY`, `NAMESPACE`, `MANIFEST_DIR`...) | **Keep.** |
| Positional `TAG`, always pinned, never `latest` | **Keep.** Default `MMDDYYYY-<git sha7>` (decision S3: the tag names its source). |
| `GITHUB_PAT` from the gitignored `.env`; login to `ghcr.io` automatically | **Keep**, identical. |
| `==> step` progress lines | **Keep**, the same wording and order. |
| **Edits the image tag in the Deployment manifest with `sed`**, then applies the directory | **Changed on purpose (decided 2026-10-11).** That step leaves a modified working tree that has to be committed, and the V3 manifest once drifted from what production ran. V4 puts the tag in **as the manifest is applied** (`sed` on the stream; the file in the repository keeps its `UNSET` placeholder) and records what is running **in the cluster**: see "Where the truth lives" below. Everything else keeps the V3 shape. |
| Applies the whole manifest directory, then `rollout status`, then lists pods | **Keep** the shape; section 3 adds ordering and checks around it. |

## 3. What V4 adds (the lights-out part), without changing the shape

Everything below runs unattended after one command. Nothing asks a question; a problem stops the script with the exact fix.

**`scripts/build-and-deploy-v4.sh [TAG] [--check] [--status] [--no-build] [--dry-run] [--rollback [TAG]] [--suite] [--allow-dirty]`**

| Step | What it does |
|---|---|
| 0. Preflight (all of it, before any change; `--check` stops here) | `.env` and `GITHUB_PAT`; Docker with buildx and enough disk; `kubectl` or `microk8s kubectl` reaches the cluster and the context is printed; the data files and the model are present (`tmp/`); the credentials SealedSecret or Secret exists; `company-dns-staging.mediumroast.io` resolves; the `letsencrypt-prod` issuer and the `traefik` ingress class exist; the working tree is clean enough to name the commit. **All failures are listed together**, not one per run. |
| 1. Authenticate | As V3. |
| 2. Build | `v4/scripts/docker-build.sh` (small profile, `linux/amd64`) from the checkout, then `docker-smoke.sh` (no network, offline layers). A failed smoke stops before any push. |
| 3. Push | As V3, then **pulls the image back with no credentials**. A new GHCR package starts private; if the pull fails the script prints the one-click fix (the package settings URL) and **polls for up to 10 minutes** for it to become public, then continues by itself. |
| 4. Name the tag | Prints `was running <tag>, deploying <tag>` (read from the Deployment's annotations). **The repository is not edited**: the tag is put into the Deployment as it is applied (step 5). |
| 5. Apply, in the safe order | namespace, sealed secret (waits for the controller to create the Secret), ConfigMaps, Deployment (tag substituted on the stream) and Service, `rollout status`. **First run is detected, not flagged** (no Certificate yet): the Ingress, redirect and certificate are applied only after the port-forward smoke test passes, then it waits up to 10 minutes for the certificate to become ready. |
| 6. Verify | Port-forward smoke test; then through HTTPS: `/health`, a SIC lookup, no credentials gives 401 on `/V4.0/sql`, and with the staging token (if the token file is present) 200. `--suite` runs the API test suite (L0, L1, L2, L4) with the staging profile, **passing the profile and token to `run.py` in environment variables** (`API_TESTS_PROFILE`, `API_TESTS_TOKEN`), never on the command line, where another user of the node could read them from the process list. Both the 200 check and `--suite` need the token file; without it they are skipped and the report says so. |
| 7. Safety net | **A failed rollout is rolled back automatically** (`rollout undo`) and the script exits non-zero. Pod restarts and every non-ready replica are reported. |
| 8. Record and report | **Stamps the Deployment** with annotations (`company-dns.mediumroast.io/deployed-tag`, `.../commit`, `.../digest`, `.../deployed-at`) and appends one line to `v4/.build-log` (gitignored). Prints a short summary: tag, digest, pods, URL. |

**Where the truth lives (instead of a committed manifest change).** What is running is read with `./scripts/build-and-deploy-v4.sh --status` (or
`kubectl -n company-dns-staging get deploy company-dns -o jsonpath='{.metadata.annotations}'`): the tag, the commit, the image digest and when. The build log keeps the history. Costs and
consequences, stated plainly: the repository no longer says which version is deployed (the annotation does); production promotion later reads "the tag that passed staging" from the annotation or the
build log; and a manual `kubectl apply -f k8s/staging/` is harmless, because the placeholder tag cannot be pulled and `maxUnavailable: 0` keeps the running pods serving. If the repository should
record deployed versions later (GitOps style), a tag file changed through a pull request can be added without changing this design.

`--no-build` deploys a tag that is already pushed. `--status` prints what is running and changes nothing. `--rollback` undoes the last rollout, or deploys a named tag. `--dry-run` runs the preflight and a server-side dry run of everything. The
namespace is a constant (`company-dns-staging`): the script cannot touch production, and it never deletes anything.

**`scripts/seal-secrets-v4.sh [--rotate] [--reseal] [--apply] [--out DIR]`**

| Step | What it does |
|---|---|
| 0. Preflight | `kubectl` reaches the cluster, `kubeseal` and `openssl` are installed (it names the install command if not; it never downloads anything itself). |
| 1. Find the controller | Discovers the sealed-secrets controller's namespace and name from the cluster (`kubectl get pods -A`); flags or environment variables override. |
| 2. Tokens | One per profile named in `k8s/staging/configmap-rules.yaml`, into a directory **outside the repository** (`~/company_dns-staging-secrets`, mode 600, never printed). Existing tokens are kept; `--rotate` replaces them. |
| 3. Seal | Builds `credentials` (profile:sha256 lines), pipes it through `kubeseal` into `k8s/staging/sealedsecret-credentials.yaml` (strict scope: opens only as `company-dns-staging/company-dns-credentials`), and checks the result is a SealedSecret with nothing in the clear. A bad result is not left behind. |
| 4. Apply (optional, `--apply`) | Applies it and waits for the controller to create the Secret, so `build-and-deploy-v4.sh` finds it. |
| 5. Report | Where the tokens are (store them in the password manager), and what to commit: only `sealedsecret-credentials.yaml`. |

Idempotent: run again and nothing changes unless you ask (`--rotate`, or `--reseal`: sealing is not repeatable byte for byte, so an unchanged credentials file is left alone and the committed sealed file does not churn).

## 4. Moving what #121 added

| Now | Becomes |
|---|---|
| `k8s/staging/deploy.sh` | **Removed**; its logic is step 5 to 8 of `build-and-deploy-v4.sh`. |
| `k8s/staging/make-credentials.sh` | **Removed**; its logic is `scripts/seal-secrets-v4.sh`. |
| `k8s/staging/CREDENTIALS.md` | **Removed**; its content is a section of `docs/v4-bringup.md`. |
| `v4/scripts/build-and-push.sh` | **Removed**; its logic is step 1 to 4. `v4/scripts/docker-build.sh` and `docker-smoke.sh` stay: they are the Dockerfile's own tooling, and the new script calls them. |
| `k8s/test_staging_scripts.py` | **Moved** to `scripts/test_v4_scripts.py` and re-pointed; the stub `kubectl`, `docker`, `kubeseal` and `curl` approach and every property it pins carry over (namespace constant, no `latest`, order, missing secret stops, rollback, hashes match tokens, tokens never printed, nothing written inside the repo). |
| `k8s/test_staging_manifests.py` | **Stays** (it tests configuration). The placeholder-tag test stays as it is: with apply-time substitution the committed Deployment keeps `UNSET`, and a test will pin that. |
| `k8s/README.md` | Layout section only (configuration), with a pointer to `docs/v4-bringup.md`. |

## 5. Work, in order

| # | Work | State |
|---|---|---|
| A | This plan and the draft `docs/v4-bringup.md` merged. | **Done** (PR #122) |
| B | `scripts/seal-secrets-v4.sh` and its tests. | **Done** (2026-10-11) |
| C | `scripts/build-and-deploy-v4.sh` and its tests. | **Done** (2026-10-11); its `--dry-run` against the real cluster is the first check on `cafe-1` |
| D | Remove the #121 scripts and runbook (section 4); update `k8s/README.md` and the rollout plan. | **Done** (2026-10-11): `k8s/staging/` holds only configuration, and a manifest test keeps it so |
| E | **The first real run on `cafe-1`, following `docs/v4-bringup.md` literally.** Every place the guide or a script is wrong is fixed in the guide or the script, and the guide is dated as proven. | **Next.** Done when V4 serves `https://company-dns-staging.mediumroast.io` from two pods and the guide's verification section passes. |

Built as planned, with these additions that the tests surfaced: **the authenticated check gives curl its credentials on standard input** (`-K -`), because `-u user:token` would have put the token on a command
line visible to other users of the node (a test caught this in the first draft); `--allow-dirty`; `--reseal`; the waits and the smoke-test retries are environment variables (`V4_WAIT_PUBLIC_SECS`,
`V4_WAIT_CERT_SECS`, `V4_POLL_SECS`, `V4_SMOKE_TRIES`) so the tests run in seconds, with the production defaults unchanged.

**Decisions (2026-10-11):**

- **The tag is applied, not committed.** Apply-time substitution plus annotations on the Deployment and the build log as the record (section 3, "Where the truth lives"). This replaces the V3 convention of editing
  the manifest, as asked, to take the commit-afterwards step away.
- **One run on `cafe-1` does build, push and deploy.** What only you can do first: a `GITHUB_PAT` (write:packages) in `.env` on `cafe-1`; `kubeseal` installed there; set the new GHCR package
  `company_dns_v4` to Public once after the first push (the script waits for it); save the staging tokens in the password manager; merge the pull request that adds the sealed secret; check
  `kubectl` reaches the cluster from `cafe-1`. The data, the model and buildx are already there.
- **Tokens are sealed on `cafe-1`**, so `~/company_dns-staging-secrets/tokens` is on the same machine as the script: the automatic 200 check works, and `--suite` (off by default) works when asked, with the
  token passed through the environment. The cost: plaintext staging tokens (mode 600, staging-only) sit in one home directory on a node that also runs production. A Mac can still run `--check`, the
  stubbed tests, and the suite by hand with a token from the password manager.

## 6. Long term: `svc_ctl.sh` as the one entry point (sketch, not for now)

Today `svc_ctl.sh` is a local-Docker controller for V3 only: it checks for `company_dns.py`, builds `company_dns:latest`, runs it on port 8000 and keeps the container's lifecycle (`start`, `stop`,
`kill`, `build`, `rebuild`, `foreground`, `tail`, `status`, `cleanup`). Its helpers (`print_action`, `print_status`, `check_error`) are good and should be kept. It knows nothing about
Kubernetes, V4, tags or secrets. The aim: **the same commands for V3 and V4, locally and on the cluster.**

**Shape**

```
svc_ctl.sh <command> [--service v3|v4] [--env local|staging|prod] [options]
```

- A small library, `scripts/lib/common.sh` (the printing helpers, `.env` and GHCR login, `kubectl` detection, the preflight runner, tag and sed handling), sourced by `svc_ctl.sh` and by
  today's scripts, so there is one copy of each convention.
- **A target file per service and environment** (`scripts/targets/v3-prod.env`, `v4-staging.env`, `v4-local.env`) holding what the scripts currently hard-code: image name and registry, port
  (8000 or 4000), health path, namespace, manifest directory, where the data and model come from, DNS name, the build command. Adding V4 production later is a new file, not a new script.
- **Commands** keep today's names and gain the missing ones: `build`, `push`, `deploy`, `rollback`, `status` (local container, or pods and certificate on the cluster), `tail` (docker or
  `kubectl logs`), `smoke`, `verify` (the suite), `seal` (the secrets steps), `bringup` (preflight, seal, build, push, deploy, verify: the whole of `docs/v4-bringup.md`),
  `check-deps` (generalised preflight), `cleanup`.
- **Local mode** for V4 runs the image with the same mounts and settings as staging (a compose file under `v4/`), so "does it run" is the same question everywhere.
- **Guards** instead of conventions: `--env prod` requires an explicit flag and a tag that passed staging (read from the build log), and refuses a dirty tree.

**Migration, in steps that each leave things working**

1. Extract the shared helpers into `scripts/lib/common.sh` and make the V4 scripts source it (no behaviour change).
2. Add target files; make the V4 scripts read them instead of constants.
3. Teach `svc_ctl.sh` the new commands for `--service v4 --env staging` by calling the V4 scripts' functions.
4. Bring V3 under the same commands (`--service v3 --env prod`), replacing `scripts/build-and-deploy.sh` with a thin wrapper, then retire it.
5. Fix the debts: `svc_ctl.sh`'s `latest` tag and its mediumroast.io service name; bring V3's deploy to the same apply-time tag and annotations method V4 uses (retiring its `sed`-the-manifest step, which is how its manifest drifted from production); a stub-based test file for `svc_ctl.sh` itself.
   a stub-based test file for `svc_ctl.sh` itself.

**Open questions for later:** whether `svc_ctl.sh` should be split by concern once it grows; how production promotion reads "passed staging" (the build log, a tag annotation, or a
cluster label); whether a GitHub workflow takes over build and push while `svc_ctl.sh` keeps deploy and verify.
