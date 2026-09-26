#!/usr/bin/env bash
# build-and-deploy.sh
# Build a company_dns image, push it to GHCR, and roll it out to the
# on-prem MicroK8s cluster (namespace: company-dns).
#
# Usage:
#   ./scripts/build-and-deploy.sh [TAG]
#
# Arguments:
#   TAG   Image tag to build/push/deploy (default: MMDDYYYY, matching the
#         mediumroast.io deploy scripts' convention). Always an explicit,
#         pinned tag - this script intentionally never deploys `:latest`.
#         See docs/plans/onprem-k8s-migration.md ("Image tagging") for why:
#         pinned tags make "what's actually running" and rollback both
#         unambiguous, at the cost of one extra bump per deploy.
#
# GHCR authentication:
#   Reads GITHUB_PAT from .env in the repo root (gitignored) and logs in to
#   ghcr.io automatically, same convention as mediumroast.io's script. The
#   PAT needs write:packages scope. No manual `docker login` required.
#
# This script must be run from the root of this repo, with `kubectl` (or
# `microk8s kubectl`, aliased to `kubectl`) already configured to reach the
# cluster. It intentionally builds directly from this checkout - unlike
# mediumroast.io's script, there's no separate branch to clone, since
# company_dns's k8s manifests live in the same repo as the app.
#
# What this script does NOT do:
#   - It does not apply k8s/prod/ingress.yaml, middleware-redirect.yaml, or
#     certificate.yaml on a fresh/first run in a way that's safe to blindly
#     repeat before DNS points at the cluster - see the migration plan's
#     step-by-step ordering for the *first* cutover. This script is meant
#     for ROUTINE REDEPLOYS once company-dns.mediumroast.io is already live
#     on the cluster; it applies everything in k8s/prod/ every time.
#   - It does not touch DNS. DNS is changed manually (Namecheap), per the
#     migration plan.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"

REGISTRY="ghcr.io/miha42-github/company_dns"
IMAGE_NAME="company_dns"
NAMESPACE="company-dns"
DEPLOYMENT="company-dns"
MANIFEST_DIR="k8s/prod"
DEPLOYMENT_MANIFEST="${MANIFEST_DIR}/deployment.yaml"

TAG="${1:-$(date +%m%d%Y)}"
FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"

cd "${REPO_ROOT}"

# --- GHCR authentication ---
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "ERROR: ${ENV_FILE} not found. Cannot authenticate to GHCR." >&2
  echo "Create it with a line: GITHUB_PAT=<your PAT with write:packages scope>" >&2
  exit 1
fi

GITHUB_PAT="$(grep -E '^GITHUB_PAT=' "${ENV_FILE}" | cut -d= -f2- | tr -d '[:space:]')"
if [[ -z "${GITHUB_PAT}" ]]; then
  echo "ERROR: GITHUB_PAT not set in ${ENV_FILE}." >&2
  exit 1
fi

echo "==> Authenticating to ghcr.io..."
GITHUB_USER="$(curl -sf -H "Authorization: Bearer ${GITHUB_PAT}" \
  https://api.github.com/user | python3 -c "import sys,json; print(json.load(sys.stdin)['login'])")"
echo "${GITHUB_PAT}" | docker login ghcr.io -u "${GITHUB_USER}" --password-stdin

echo "==> Image       : ${FULL_IMAGE}"
echo "==> Namespace   : ${NAMESPACE}"

echo "==> Building image"
docker build -t "${FULL_IMAGE}" "${REPO_ROOT}"

echo "==> Pushing image"
docker push "${FULL_IMAGE}"

echo "==> Syncing image tag in ${DEPLOYMENT_MANIFEST}"
sed -i.bak "s|image: ${REGISTRY}/${IMAGE_NAME}:.*|image: ${FULL_IMAGE}|" "${DEPLOYMENT_MANIFEST}"
rm -f "${DEPLOYMENT_MANIFEST}.bak"

echo "==> Applying manifests in ${MANIFEST_DIR}"
kubectl apply -f "${MANIFEST_DIR}/"

echo "==> Waiting for rollout to complete"
kubectl rollout status deployment/"${DEPLOYMENT}" -n "${NAMESPACE}"

echo "==> Done. Pods:"
kubectl -n "${NAMESPACE}" get pods -o wide
