#!/usr/bin/env bash
# Deploy V4 to STAGING (company-dns-staging.mediumroast.io). docs/plans/v4-staging-rollout.md, WP5.
#
#   k8s/staging/deploy.sh [--first-time] [--dry-run] TAG
#   k8s/staging/deploy.sh --rollback [TAG]
#
#   TAG          an image tag pushed by v4/scripts/build-and-push.sh (for example 10112026-a1b2c3d). Never "latest".
#   --first-time adds the first-rollout guidance at the end. The ORDER is the same on every run, and is the safe one: namespace, config, workload, a
#                port-forward smoke test, and only then the Ingress and certificate (the certificate needs DNS to point here; the workload should be
#                verified first). Every run stops, applying nothing further, if the credentials Secret `company-dns-credentials` is missing.
#   --dry-run    `kubectl apply --dry-run=server` of everything with the tag in place; changes nothing. Do this once before the first apply.
#   --rollback   with no TAG: `kubectl rollout undo`, the previous revision; with a TAG: deploy that tag.
#
# Safety: this script can only touch the namespace company-dns-staging. The namespace is a constant, every kubectl call names it, and the manifests are
# checked by k8s/test_staging_manifests.py to carry it. It does not edit the repository: the tag is put into the Deployment as it is applied, so what the
# repository says and what runs cannot drift (the V3 script edits the manifest, which is how the manifest came to name a tag production did not run).
#
# Needs kubectl pointed at the cluster (microk8s kubectl, aliased). It prints the context it is using first.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NS="company-dns-staging"; DEPLOY="company-dns"; SECRET="company-dns-credentials"
IMAGE_BASE="ghcr.io/miha42-github/company_dns/company_dns_v4"
UA="company_dns-staging-deploy/1.0 (+https://github.com/miha42-github/company_dns)"
first=0; dry=0; rollback=0; tag=""
while [ $# -gt 0 ]; do
  case "$1" in
    --first-time) first=1; shift;;
    --dry-run) dry=1; shift;;
    --rollback) rollback=1; shift;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 0;;
    -*) echo "unknown argument $1" >&2; exit 2;;
    *) [ -z "$tag" ] || { echo "one TAG only" >&2; exit 2; }; tag="$1"; shift;;
  esac
done
k() { kubectl -n "$NS" "$@"; }

if [ -n "$tag" ]; then
  case "$tag" in latest|*[!A-Za-z0-9._-]*) echo "the tag must be pinned (never latest) and a plain Docker tag, got $tag" >&2; exit 2;; esac
fi
if [ "$rollback" = 1 ]; then
  [ "$first" = 0 ] && [ "$dry" = 0 ] || { echo "--rollback does not combine with --first-time or --dry-run" >&2; exit 2; }
else
  [ -n "$tag" ] || { echo "give the image TAG to deploy (see v4/.build-log for what was pushed)" >&2; exit 2; }
fi

echo "==> kubectl context: $(kubectl config current-context 2>/dev/null || echo unknown)   namespace: $NS (the only one this script touches)"

# The Deployment with the tag put in as it is applied.
with_tag() { sed "s|image: ${IMAGE_BASE}:.*|image: ${IMAGE_BASE}:${tag}|" "$here/deployment.yaml"; }
apply_file() { if [ "$dry" = 1 ]; then kubectl apply --dry-run=server -f "$1"; else kubectl apply -f "$1"; fi; }
apply_deployment() { with_tag | if [ "$dry" = 1 ]; then kubectl apply --dry-run=server -f -; else kubectl apply -f -; fi; }

smoke() {
  echo "==> Smoke test through a port-forward (no Ingress involved)"
  k port-forward "svc/$DEPLOY" 18089:80 >/dev/null 2>&1 &
  local pf=$! ok=0 rc=0
  for _ in $(seq 1 20); do curl -fsS -A "$UA" http://127.0.0.1:18089/health >/dev/null 2>&1 && { ok=1; break; }; sleep 1; done
  if [ "$ok" = 1 ]; then
    echo "   /health ok"
    curl -fsS -A "$UA" http://127.0.0.1:18089/V4.0/na/sic/code/3571 | head -c 120 && echo && echo "   a SIC lookup ok" || rc=1
  else
    echo "ERROR: /health did not answer through the port-forward" >&2; rc=1
  fi
  kill "$pf" 2>/dev/null || true
  return "$rc"
}

report() {
  echo "==> Pods:"; k get pods -o wide
  local want ready
  want="$(k get deployment "$DEPLOY" -o jsonpath='{.spec.replicas}')"; ready="$(k get deployment "$DEPLOY" -o jsonpath='{.status.readyReplicas}')"
  echo "==> Ready replicas: ${ready:-0} of $want   Image: $(k get deployment "$DEPLOY" -o jsonpath='{.spec.template.spec.containers[0].image}')"
  [ "${ready:-0}" = "$want" ] || { echo "ERROR: not every replica is ready" >&2; return 1; }
}

if [ "$rollback" = 1 ]; then
  if [ -z "$tag" ]; then
    echo "==> Rolling back to the previous revision"
    k rollout undo "deployment/$DEPLOY"
  else
    echo "==> Rolling back by deploying $tag"
    apply_deployment
  fi
  k rollout status "deployment/$DEPLOY" --timeout=300s
  smoke; report; echo "==> Rolled back."; exit 0
fi

echo "==> Image: ${IMAGE_BASE}:${tag}"
if [ "$dry" = 1 ]; then
  echo "==> Server-side dry run of everything (nothing changes)"
  for f in namespace sealedsecret-credentials configmap-rules configmap-loglevel; do [ -f "$here/$f.yaml" ] && apply_file "$here/$f.yaml"; done
  apply_deployment; apply_file "$here/service.yaml"
  for f in middleware-redirect ingress certificate; do apply_file "$here/$f.yaml"; done
  echo "==> Dry run complete."; exit 0
fi

echo "==> Applying namespace and configuration"
apply_file "$here/namespace.yaml"
if [ -f "$here/sealedsecret-credentials.yaml" ]; then
  echo "==> Applying the sealed credentials (the controller turns them into the Secret $SECRET)"
  apply_file "$here/sealedsecret-credentials.yaml"
  for _ in $(seq 1 30); do k get secret "$SECRET" >/dev/null 2>&1 && break; sleep 1; done
fi
if ! k get secret "$SECRET" >/dev/null 2>&1; then
  echo "ERROR: the Secret $SECRET does not exist in $NS. The pods mount it and will not start without it. Make and seal it with k8s/staging/make-credentials.sh (see k8s/staging/CREDENTIALS.md), commit sealedsecret-credentials.yaml, then run this again." >&2
  exit 1
fi
apply_file "$here/configmap-rules.yaml"; apply_file "$here/configmap-loglevel.yaml"

echo "==> Applying the workload"
apply_deployment; apply_file "$here/service.yaml"
k rollout status "deployment/$DEPLOY" --timeout=300s
smoke

if [ "$first" = 1 ]; then
  echo "==> First time: the workload is verified; now the Ingress, redirect and certificate (DNS for company-dns-staging.mediumroast.io must resolve here)"
fi
echo "==> Applying the Ingress, redirect and certificate"
for f in middleware-redirect ingress certificate; do apply_file "$here/$f.yaml"; done
report
echo "==> Certificate:"; k get certificate
[ "$first" = 0 ] || echo "==> Watch it become ready: kubectl -n $NS get certificate -w  (then smoke test https://company-dns-staging.mediumroast.io/health)"
echo "==> Done."
