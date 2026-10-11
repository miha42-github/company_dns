#!/usr/bin/env bash
# build-and-deploy-v4.sh
# Build the V4 image, push it to GHCR, and roll it out to the on-prem MicroK8s
# cluster (namespace: company-dns-staging, https://company-dns-staging.mediumroast.io).
# The V4 counterpart of scripts/build-and-deploy.sh; the whole procedure, start to
# finish, is docs/v4-bringup.md. Plan: docs/plans/v4-staging-scripts.md.
#
# Usage:
#   ./scripts/build-and-deploy-v4.sh [TAG]                 build, push, deploy
#   ./scripts/build-and-deploy-v4.sh --check               preflight only: list EVERYTHING missing, change nothing
#   ./scripts/build-and-deploy-v4.sh --status              what is running (tag, commit, digest, time), change nothing
#   ./scripts/build-and-deploy-v4.sh --no-build TAG        deploy a tag that is already pushed
#   ./scripts/build-and-deploy-v4.sh --rollback [TAG]      previous revision, or deploy TAG
#   ./scripts/build-and-deploy-v4.sh --dry-run [TAG]       preflight + server-side dry run of every manifest, change nothing
#   options: --suite (also run the API test suite), --allow-dirty (build from a tree with uncommitted changes)
#
# Arguments:
#   TAG   Image tag (default: MMDDYYYY-<git sha7>: the date and the commit, so a tag always
#         names its source). Always an explicit, pinned tag - this script never deploys `:latest`.
#
# GHCR authentication:
#   Reads GITHUB_PAT from .env in the repo root (gitignored) and logs in to ghcr.io
#   automatically, exactly as scripts/build-and-deploy.sh does. The PAT needs write:packages.
#
# Run it from the root of this repo ON cafe-1 (native amd64, Docker with buildx, the data in
# tmp/, and `kubectl` or `microk8s kubectl` for the cluster). One run does everything and asks
# nothing; a problem stops it with the exact fix.
#
# How it differs from the V3 script, on purpose:
#   - The image tag is put into the Deployment AS IT IS APPLIED. The manifest in the repository
#     is never edited (it keeps the placeholder tag UNSET), so there is nothing to commit
#     afterwards and the repo cannot drift from the cluster. What is running is recorded on the
#     Deployment itself (annotations: tag, commit, digest, time) and read back with --status.
#   - The preflight lists every missing prerequisite at once, before anything changes.
#   - A new GHCR package starts private: the script waits for it to be made public.
#   - The workload is verified (a port-forward smoke test) BEFORE the Ingress and certificate are
#     applied; the first run is detected, and waits for the certificate.
#   - A failed rollout is rolled back automatically.
#
# What this script does NOT do:
#   - It does not touch DNS (company-dns-staging.mediumroast.io must already resolve to the cluster).
#   - It does not create the credentials: run scripts/seal-secrets-v4.sh first (docs/v4-bringup.md, step 3).
#   - It can only act on the namespace company-dns-staging, and it never deletes anything.

set -Eeuo pipefail
# Never fail silently: any command that stops the script says which one and where (set -E so functions and substitutions report too).
trap 'echo "ERROR: unexpected failure (exit $?) at line ${LINENO}: ${BASH_COMMAND}" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"

REGISTRY="ghcr.io/miha42-github/company_dns"
OWNER="miha42-github"   # the GitHub account that owns the packages (the part after ghcr.io/)
IMAGE_NAME="company_dns_v4"
NAMESPACE="company-dns-staging"
DEPLOYMENT="company-dns"
SERVICE="company-dns"
SECRET="company-dns-credentials"
CERTIFICATE="company-dns-staging-io-tls"
MANIFEST_DIR="k8s/staging"
DEPLOYMENT_MANIFEST="${REPO_ROOT}/${MANIFEST_DIR}/deployment.yaml"
STAGING_HOST="company-dns-staging.mediumroast.io"
PROFILE="release-small"
PLATFORM="linux/amd64"
TEST_PROFILE="staging-test"
SECRETS_DIR="${V4_SECRETS_DIR:-${HOME}/company_dns-staging-secrets}"
ANNOTATION="company-dns.mediumroast.io"
BUILD_LOG="${REPO_ROOT}/v4/.build-log"
UA="company_dns-v4-deploy/1.0 (+https://github.com/miha42-github/company_dns)"
PF_PORT=18089
# Waits (seconds) and the poll interval; environment variables so a test can shorten them.
WAIT_PUBLIC_SECS="${V4_WAIT_PUBLIC_SECS:-600}"
WAIT_CERT_SECS="${V4_WAIT_CERT_SECS:-600}"
POLL_SECS="${V4_POLL_SECS:-10}"

TAG=""; MODE="deploy"; BUILD=1; DRY=0; SUITE=0; ALLOW_DIRTY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) MODE="check"; shift;;
    --status) MODE="status"; shift;;
    --rollback) MODE="rollback"; BUILD=0; shift;;
    --no-build) BUILD=0; shift;;
    --dry-run) DRY=1; shift;;
    --suite) SUITE=1; shift;;
    --allow-dirty) ALLOW_DIRTY=1; shift;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 0;;
    -*) echo "ERROR: unknown argument $1" >&2; exit 2;;
    *) [[ -z "${TAG}" ]] || { echo "ERROR: one TAG only" >&2; exit 2; }; TAG="$1"; shift;;
  esac
done

# --- kubectl (or microk8s kubectl, as the cluster nodes have it) ---
if command -v kubectl >/dev/null 2>&1; then KUBECTL=(kubectl)
elif command -v microk8s >/dev/null 2>&1; then KUBECTL=(microk8s kubectl)
else KUBECTL=(); fi
k() { "${KUBECTL[@]}" -n "${NAMESPACE}" "$@"; }   # every namespaced call names the staging namespace

cd "${REPO_ROOT}"

# --- The tag ---
SHA="$(git rev-parse --short=7 HEAD 2>/dev/null || echo nogit)"
DIRTY=0; [[ -z "$(git status --porcelain --untracked-files=no 2>/dev/null)" ]] || DIRTY=1
if [[ -n "${TAG}" ]]; then
  case "${TAG}" in latest|*[!A-Za-z0-9._-]*) echo "ERROR: the tag must be pinned (never latest) and a plain Docker tag, got ${TAG}" >&2; exit 2;; esac
elif [[ "${BUILD}" -eq 1 || "${MODE}" == "check" || "${DRY}" -eq 1 ]]; then
  TAG="$(date +%m%d%Y)-${SHA}"
  [[ "${DIRTY}" -eq 0 ]] || TAG="${TAG}-dirty"
elif [[ "${MODE}" == "deploy" ]]; then
  echo "ERROR: --no-build needs the TAG to deploy (see v4/.build-log, or --status for what is running)" >&2; exit 2
fi
FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"

# --- Helpers ---
say() { echo "==> $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }
need_kubectl() { [[ ${#KUBECTL[@]} -gt 0 ]] || die "kubectl not found (or microk8s kubectl): run this on a machine that reaches the cluster, such as cafe-1"; }

annotation() {   # value of one of our annotations on the Deployment, or "none"
  local v
  v="$(k get deployment "${DEPLOYMENT}" -o go-template="{{index .metadata.annotations \"${ANNOTATION}/$1\"}}" 2>/dev/null || true)"
  [[ -n "${v}" && "${v}" != "<no value>" ]] && echo "${v}" || echo "none"
}
running_image() { k get deployment "${DEPLOYMENT}" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || true; }
token_of() { [[ -f "${SECRETS_DIR}/tokens" ]] && awk -F: -v p="$1" '$1 == p {print substr($0, length(p) + 2); exit}' "${SECRETS_DIR}/tokens" || true; }

# --- Preflight: every problem at once ---
preflight() {
  local problems=() warnings=()
  [[ ${#KUBECTL[@]} -gt 0 ]] || problems+=("kubectl not found (or microk8s kubectl): run this on a machine that reaches the cluster, such as cafe-1")
  command -v curl >/dev/null 2>&1 || problems+=("curl is not installed")
  command -v python3 >/dev/null 2>&1 || problems+=("python3 is not installed")
  if [[ "${BUILD}" -eq 1 ]]; then
    [[ -f "${ENV_FILE}" ]] || problems+=("${ENV_FILE} not found: create it with a line GITHUB_PAT=<a PAT with write:packages>")
    [[ -f "${ENV_FILE}" ]] && ! grep -qE '^GITHUB_PAT=.+' "${ENV_FILE}" && problems+=("GITHUB_PAT is not set in ${ENV_FILE}")
    if ! command -v docker >/dev/null 2>&1; then problems+=("docker is not installed")
    else
      docker buildx version >/dev/null 2>&1 || problems+=("docker buildx is missing: sudo apt-get install -y docker-buildx docker-compose-v2")
      docker info >/dev/null 2>&1 || problems+=("the Docker daemon is not reachable by this user")
      local root free
      root="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)"
      free="$(df -Pk "${root}" 2>/dev/null | awk 'NR==2 {print int($4/1048576)}' || true)"
      [[ -z "${free}" || "${free}" -ge 20 ]] || problems+=("only ${free} GB free under ${root}; the build needs about 20 GB")
    fi
    local data="${DATA_DIR:-${COMPANY_DNS_DATA_DIR:-${REPO_ROOT}/tmp}}"
    [[ -d "${data}" ]] || problems+=("the SIC data directory ${data} does not exist (set DATA_DIR): docs/plans/v4-amd64-build-and-compare.md, step 0")
    [[ -d "${data}" ]] && ! ls "${data}"/*.feather >/dev/null 2>&1 && problems+=("no .feather data files in ${data}")
    [[ -n "$(model_dir)" ]] || problems+=("the embedding model cache was not found (looked in \$MODEL_DIR, tmp/.fastembed_cache, v4/.fastembed_cache)")
    [[ "$(uname -m)" == "x86_64" || "$(uname -m)" == "amd64" ]] || warnings+=("this host is $(uname -m): a ${PLATFORM} build is emulated and very slow; build on cafe-1")
    if [[ "${DIRTY}" -eq 1 && "${ALLOW_DIRTY}" -eq 0 ]]; then
      problems+=("uncommitted changes in the working tree: a tag must name its source (commit them, or pass --allow-dirty for a throwaway build)")
    fi
  fi
  if [[ ${#KUBECTL[@]} -gt 0 ]]; then
    if ! "${KUBECTL[@]}" get nodes -o name >/dev/null 2>&1; then
      problems+=("the cluster is not reachable with ${KUBECTL[*]} (check the kubeconfig and context)")
    else
      "${KUBECTL[@]}" get ingressclass traefik >/dev/null 2>&1 || problems+=("the traefik ingress class does not exist on this cluster")
      "${KUBECTL[@]}" get clusterissuer letsencrypt-prod >/dev/null 2>&1 || problems+=("the letsencrypt-prod ClusterIssuer does not exist on this cluster")
      if [[ "${MODE}" == "deploy" || "${MODE}" == "check" ]]; then
        if [[ ! -f "${REPO_ROOT}/${MANIFEST_DIR}/sealedsecret-credentials.yaml" ]] && ! k get secret "${SECRET}" >/dev/null 2>&1; then
          problems+=("no credentials: neither ${MANIFEST_DIR}/sealedsecret-credentials.yaml nor the Secret ${SECRET} exists; run ./scripts/seal-secrets-v4.sh (docs/v4-bringup.md, step 3)")
        fi
      fi
    fi
  fi
  if [[ "${MODE}" == "deploy" || "${MODE}" == "check" ]]; then
    python3 -c "import socket,sys; socket.gethostbyname(sys.argv[1])" "${STAGING_HOST}" >/dev/null 2>&1 \
      || problems+=("${STAGING_HOST} does not resolve (the DNS record must exist before the certificate can issue)")
  fi
  [[ -f "${DEPLOYMENT_MANIFEST}" ]] || problems+=("${MANIFEST_DIR}/deployment.yaml not found: run this from a checkout of the repository")
  for w in "${warnings[@]+"${warnings[@]}"}"; do echo "WARNING: ${w}" >&2; done
  if [[ ${#problems[@]} -gt 0 ]]; then
    echo "ERROR: cannot continue; fix these and run again:" >&2
    for p in "${problems[@]}"; do echo "  - ${p}" >&2; done
    return 1
  fi
  return 0
}

model_dir() {   # where the embedding model cache is, if anywhere
  local d
  for d in "${MODEL_DIR:-}" "${REPO_ROOT}/tmp/.fastembed_cache" "${REPO_ROOT}/v4/.fastembed_cache"; do
    [[ -n "${d}" && -d "${d}" ]] && { echo "${d}"; return; }
  done
}

# --- Status ---
show_status() {
  need_kubectl
  say "Context      : $("${KUBECTL[@]}" config current-context 2>/dev/null || echo unknown)   Namespace: ${NAMESPACE}"
  "${KUBECTL[@]}" get nodes -o name >/dev/null 2>&1 || die "the cluster is not reachable with ${KUBECTL[*]} (check the kubeconfig and context)"
  if ! k get deployment "${DEPLOYMENT}" >/dev/null 2>&1; then echo "    nothing is deployed in ${NAMESPACE} yet"; return 0; fi
  echo "    Image      : $(running_image)"
  echo "    Tag        : $(annotation deployed-tag)"
  echo "    Commit     : $(annotation commit)"
  echo "    Digest     : $(annotation digest)"
  echo "    Deployed at: $(annotation deployed-at)"
  k get pods -o wide || true
  k get certificate "${CERTIFICATE}" 2>/dev/null || true
}

# --- Build, push ---
ghcr_login() {
  local pat user
  pat="$(grep -E '^GITHUB_PAT=' "${ENV_FILE}" | cut -d= -f2- | tr -d '[:space:]')"
  say "Authenticating to ghcr.io..."
  user="$(curl -sf -H "Authorization: Bearer ${pat}" https://api.github.com/user | python3 -c "import sys,json; print(json.load(sys.stdin)['login'])")" \
    || die "the GitHub PAT in ${ENV_FILE} was refused by api.github.com"
  echo "${pat}" | docker login ghcr.io -u "${user}" --password-stdin
}

build_image() {
  local model
  model="$(model_dir)"
  say "Building image (${PROFILE}, ${PLATFORM}; the Rust build takes most of 15 to 25 minutes the first time)"
  MODEL_DIR="${model}" "${REPO_ROOT}/v4/scripts/docker-build.sh" -t "${FULL_IMAGE}" -p "${PROFILE}" --platform "${PLATFORM}" --load
  say "Smoke test (no network, then the offline test layers); a failure stops here, before anything is pushed"
  "${REPO_ROOT}/v4/scripts/docker-smoke.sh" "${FULL_IMAGE}"
}

push_image() {
  say "Pushing image"
  docker push "${FULL_IMAGE}"
  DIGEST="$(docker inspect --format '{{index .RepoDigests 0}}' "${FULL_IMAGE}" 2>/dev/null || true)"
  say "Checking the image pulls with no credentials (the package must be public)"
  local anon tries=0 max
  max=$((WAIT_PUBLIC_SECS / (POLL_SECS > 0 ? POLL_SECS : 1)))
  anon="$(mktemp -d)"
  local pull_err=""
  until pull_err="$(DOCKER_CONFIG="${anon}" docker pull "${FULL_IMAGE}" 2>&1 >/dev/null)"; do
    if [[ ${tries} -eq 0 ]]; then
      echo "    The anonymous pull said: $(printf '%s' "${pull_err}" | tail -1)"
      echo "    (denied or unauthorized: the package is private. manifest unknown or not found: the push did not leave this tag in ${REGISTRY}/${IMAGE_NAME}.)"
      echo "    A new GHCR package starts private. Make it public once. It is a DIFFERENT package from V3's (company_dns/company_dns): company_dns/${IMAGE_NAME}."
      echo "    A private package is visible only to its owner, and it is not listed on the repository's Packages page until it is linked to the repository, so look under the owner's profile:"
      echo "      https://github.com/${OWNER}?tab=packages   (sign in as the owner)"
      echo "      or directly: https://github.com/users/${OWNER}/packages/container/package/company_dns%2F${IMAGE_NAME}"
      echo "    Then: Package settings > Danger Zone > Change visibility > Public (it asks you to type the package name)."
      echo "    Waiting up to $((WAIT_PUBLIC_SECS / 60)) minutes for that; this script continues by itself."
    fi
    [[ ${tries} -lt ${max} ]] || { rm -rf "${anon}"; die "the image is still not pullable without credentials after waiting; make the package public and run again with: --no-build ${TAG}"; }
    sleep "${POLL_SECS}"; tries=$((tries + 1))
  done
  rm -rf "${anon}"
  echo "    anonymous pull works"
}

# --- Apply ---
with_tag() { sed "s|image: ${REGISTRY}/${IMAGE_NAME}:.*|image: ${FULL_IMAGE}|" "${DEPLOYMENT_MANIFEST}"; }
apply() {   # apply one file, or the Deployment from stdin with the tag; a dry run changes nothing
  local flag=(); [[ "${DRY}" -eq 0 ]] || flag=(--dry-run=server)
  if [[ "$1" == "-" ]]; then with_tag | "${KUBECTL[@]}" apply "${flag[@]+"${flag[@]}"}" -f -
  else "${KUBECTL[@]}" apply "${flag[@]+"${flag[@]}"}" -f "${REPO_ROOT}/${MANIFEST_DIR}/$1"; fi
}

wait_for_secret() {
  local _
  for _ in $(seq 1 "${V4_WAIT_SECRET_TRIES:-60}"); do k get secret "${SECRET}" >/dev/null 2>&1 && return 0; sleep "${V4_SECRET_POLL_SECS:-1}"; done
  return 1
}

rollout() {   # wait for the rollout; roll back automatically if it fails
  if ! k rollout status deployment/"${DEPLOYMENT}" --timeout=300s; then
    echo "ERROR: the rollout did not complete." >&2
    k get pods -o wide || true
    k describe pods -l app.kubernetes.io/name=company-dns 2>/dev/null | tail -25 || true
    if k rollout undo deployment/"${DEPLOYMENT}" >/dev/null 2>&1; then
      k rollout status deployment/"${DEPLOYMENT}" --timeout=300s || true
      die "rolled back to the previous revision (it is serving again); fix the problem above and run again"
    fi
    die "there was no earlier revision to roll back to; see the pod events above"
  fi
}

smoke_forward() {   # through a port-forward: no Ingress involved
  say "Smoke test through a port-forward"
  k port-forward "svc/${SERVICE}" "${PF_PORT}:80" >/dev/null 2>&1 &
  local pf=$! ok=0 rc=0 _
  for _ in $(seq 1 "${V4_SMOKE_TRIES:-20}"); do curl -fsS -A "${UA}" "http://127.0.0.1:${PF_PORT}/health" >/dev/null 2>&1 && { ok=1; break; }; sleep 1; done
  if [[ ${ok} -eq 1 ]]; then
    echo "    /health ok"
    # capture the answer, then show the start of it: `curl | head -c` fails under pipefail whenever the answer is longer than head reads
    local body
    if body="$(curl -fsS -A "${UA}" "http://127.0.0.1:${PF_PORT}/V4.0/na/sic/code/3571")"; then echo "    ${body:0:120}"; echo "    a SIC lookup ok"; else rc=1; fi
  else
    echo "ERROR: /health did not answer through the port-forward" >&2; rc=1
  fi
  kill "${pf}" 2>/dev/null || true
  return "${rc}"
}

wait_for_certificate() {
  local tries=0 max
  max=$((WAIT_CERT_SECS / (POLL_SECS > 0 ? POLL_SECS : 1)))
  say "Waiting for the certificate (up to $((WAIT_CERT_SECS / 60)) minutes; it needs ${STAGING_HOST} to point at the cluster)"
  while [[ "$(k get certificate "${CERTIFICATE}" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || true)" != "True" ]]; do
    [[ ${tries} -lt ${max} ]] || return 1
    sleep "${POLL_SECS}"; tries=$((tries + 1))
  done
}

verify_https() {
  local H="https://${STAGING_HOST}" code token rc=0
  say "Verifying through HTTPS"
  curl -fsS -A "${UA}" "${H}/health" >/dev/null && echo "    /health ok" || { echo "ERROR: ${H}/health failed" >&2; rc=1; }
  curl -fsS -A "${UA}" "${H}/V4.0/na/sic/code/3571" >/dev/null && echo "    a SIC lookup ok" || { echo "ERROR: a SIC lookup failed" >&2; rc=1; }
  code="$(curl -s -o /dev/null -w '%{http_code}' -A "${UA}" -H 'content-type: application/json' -d '{"dataset":"sic","sql":"select 1 as one"}' "${H}/V4.0/sql" || true)"
  [[ "${code}" == "401" ]] && echo "    /V4.0/sql with no credentials: 401 (as it should)" || { echo "ERROR: /V4.0/sql with no credentials gave ${code}, expected 401" >&2; rc=1; }
  token="$(token_of "${TEST_PROFILE}")"
  if [[ -n "${token}" ]]; then
    # the credentials go to curl on its standard input (-K -), never as an argument another user could read with ps
    code="$(printf 'user = "%s:%s"\n' "${TEST_PROFILE}" "${token}" | curl -s -K - -o /dev/null -w '%{http_code}' -A "${UA}" -H 'content-type: application/json' -d '{"dataset":"sic","sql":"select 1 as one"}' "${H}/V4.0/sql" || true)"
    [[ "${code}" == "200" ]] && echo "    /V4.0/sql as ${TEST_PROFILE}: 200" || { echo "ERROR: /V4.0/sql as ${TEST_PROFILE} gave ${code}, expected 200 (are the tokens file and the sealed secret from the same run?)" >&2; rc=1; }
  else
    echo "    (no ${TEST_PROFILE} token in ${SECRETS_DIR}/tokens: the authenticated check is skipped)"
  fi
  return "${rc}"
}

run_suite() {
  local token; token="$(token_of "${TEST_PROFILE}")"
  if [[ -z "${token}" ]]; then echo "WARNING: --suite skipped: no ${TEST_PROFILE} token in ${SECRETS_DIR}/tokens" >&2; return 0; fi
  say "Running the API test suite (L0, L1, L2, L4) against ${STAGING_HOST}"
  # the profile and token go in the environment, never on a command line another user could read
  BASE_URL="https://${STAGING_HOST}" API_TESTS_PROFILE="${TEST_PROFILE}" API_TESTS_TOKEN="${token}" \
    python3 "${REPO_ROOT}/api_tests/run.py" --layers L0,L1,L2,L4 --report "${REPO_ROOT}/v4/.staging-suite.json"
}

record() {   # stamp the Deployment with what is running, and append to the build log
  local image tag; image="$(running_image)"; tag="${image##*:}"
  [[ "${DRY}" -eq 0 ]] || return 0
  k annotate deployment "${DEPLOYMENT}" --overwrite \
    "${ANNOTATION}/deployed-tag=${tag}" "${ANNOTATION}/commit=${COMMIT_RECORD:-unknown}" \
    "${ANNOTATION}/digest=${DIGEST:-unknown}" "${ANNOTATION}/deployed-at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null
  python3 - "${BUILD_LOG}" "${tag}" "${image}" "${DIGEST:-}" "${COMMIT_RECORD:-unknown}" "${PROFILE}" "${PLATFORM}" "${BUILD}" <<'PY'
import json, sys, time
log, tag, image, digest, commit, profile, platform, built = sys.argv[1:]
with open(log, "a") as f:
    f.write(json.dumps({"tag": tag, "image": image, "digest": digest or None, "commit": commit, "profile": profile, "platform": platform,
                        "built": built == "1", "namespace": "company-dns-staging", "deployed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}) + "\n")
PY
}

summary() {
  local image; image="$(running_image)"
  say "Done. ${image##*:} is running."
  k get pods -o wide
  local want ready
  want="$(k get deployment "${DEPLOYMENT}" -o jsonpath='{.spec.replicas}')"; ready="$(k get deployment "${DEPLOYMENT}" -o jsonpath='{.status.readyReplicas}')"
  echo "    Ready replicas: ${ready:-0} of ${want}   URL: https://${STAGING_HOST}"
  [[ "${ready:-0}" == "${want}" ]] || die "not every replica is ready"
}

# ===================================================================== main
if [[ "${MODE}" == "status" ]]; then show_status; exit 0; fi

say "Context     : $("${KUBECTL[@]}" config current-context 2>/dev/null || echo unknown)"
say "Namespace   : ${NAMESPACE} (the only namespace this script touches)"
preflight || exit 1
if [[ "${MODE}" == "check" ]]; then say "Preflight passed: everything this script needs is in place (tag would be ${TAG})."; exit 0; fi
need_kubectl

if [[ "${MODE}" == "rollback" ]]; then
  say "Was running: $(annotation deployed-tag)"
  if [[ -z "${TAG}" ]]; then
    say "Rolling back to the previous revision"
    k rollout undo deployment/"${DEPLOYMENT}"
  else
    say "Rolling back by deploying ${TAG}"
    apply -
  fi
  rollout; smoke_forward
  COMMIT_RECORD="rollback"; DIGEST=""
  record; summary; exit 0
fi

say "Image       : ${FULL_IMAGE}"
say "Was running : $(annotation deployed-tag) (commit $(annotation commit))"
COMMIT_RECORD="${SHA}$([[ ${DIRTY} -eq 0 ]] || echo -dirty)"
DIGEST=""

if [[ "${DRY}" -eq 1 ]]; then
  say "Server-side dry run of every manifest (nothing changes)"
  apply namespace.yaml
  [[ ! -f "${REPO_ROOT}/${MANIFEST_DIR}/sealedsecret-credentials.yaml" ]] || apply sealedsecret-credentials.yaml
  apply configmap-rules.yaml; apply configmap-loglevel.yaml; apply -; apply service.yaml
  apply middleware-redirect.yaml; apply ingress.yaml; apply certificate.yaml
  say "Dry run complete."; exit 0
fi

if [[ "${BUILD}" -eq 1 ]]; then
  ghcr_login
  build_image
  push_image
else
  say "Not building: deploying ${FULL_IMAGE} as pushed"
  DIGEST="$(annotation digest)"; COMMIT_RECORD="$(annotation commit)"
fi

FIRST=0; k get certificate "${CERTIFICATE}" >/dev/null 2>&1 || FIRST=1
[[ ${FIRST} -eq 0 ]] || say "First deployment detected: the Ingress and certificate follow the smoke test"

say "Applying the namespace and the credentials"
apply namespace.yaml
if [[ -f "${REPO_ROOT}/${MANIFEST_DIR}/sealedsecret-credentials.yaml" ]]; then apply sealedsecret-credentials.yaml; fi
wait_for_secret || die "the Secret ${SECRET} does not exist in ${NAMESPACE} (the controller could not open the sealed secret? see: ${KUBECTL[*]} -n ${NAMESPACE} describe sealedsecret ${SECRET})"

say "Applying the configuration and the workload"
apply configmap-rules.yaml; apply configmap-loglevel.yaml
apply -; apply service.yaml
rollout
smoke_forward || die "the smoke test failed; the Ingress was not applied. Logs: ${KUBECTL[*]} -n ${NAMESPACE} logs deploy/${DEPLOYMENT}"

say "Applying the redirect, Ingress and certificate"
apply middleware-redirect.yaml; apply ingress.yaml; apply certificate.yaml
if [[ ${FIRST} -eq 1 ]]; then
  wait_for_certificate || die "the certificate is not ready: ${KUBECTL[*]} -n ${NAMESPACE} describe certificate,challenge (the workload itself is up and verified)"
fi
VERIFIED=0; verify_https && VERIFIED=1
record
[[ ${SUITE} -eq 0 ]] || run_suite
summary
[[ ${VERIFIED} -eq 1 ]] || die "the deploy completed but the HTTPS verification above failed"
