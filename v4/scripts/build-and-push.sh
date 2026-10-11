#!/usr/bin/env bash
# Build the V4 image for staging, smoke-test it, push it to GHCR and record what was pushed.
# (docs/plans/v4-staging-rollout.md, WP2.)
#
#   v4/scripts/build-and-push.sh [--tag TAG] [-p release-small|release-lean] [--platform linux/amd64] [--no-push] [--skip-smoke] [--allow-dirty]
#
#   --tag        default MMDDYYYY-<git sha7>: the date and the commit, so a tag always names its source (decision S3). Pinned; never "latest".
#   -p           default release-small (decision S2, from the 2026-10-10 rerun).
#   --platform   default linux/amd64, the cluster's architecture. Build on a native amd64 machine (cafe-1): an emulated build of this Rust workspace is very slow.
#   --no-push    build and smoke-test only.
#   --skip-smoke skip v4/scripts/docker-smoke.sh (not for a tag that will be deployed).
#   --allow-dirty  build from a tree with uncommitted changes (the tag then carries "-dirty"; never deploy such a tag).
#
# What it needs, on the build machine: docker with buildx, the SIC data files in tmp/ (DATA_DIR) and the embedding model in tmp/.fastembed_cache (MODEL_DIR),
# the same as v4/scripts/docker-build.sh; and, to push, a .env in the repository root with GITHUB_PAT=<a PAT with write:packages> (gitignored; the V3
# script's convention). Set ENV_FILE to use another file.
#
# After the push it pulls the image back WITHOUT any credentials: the package is meant to be public (decision S1), and a brand-new GHCR package starts
# private. If that check fails, make the package public once (GitHub > your profile or org > Packages > company_dns_v4 > Package settings > Change visibility).
#
# The record: one JSON line appended to v4/.build-log (gitignored) with the tag, image, digest, commit, profile, platform and the data manifest's hash.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
registry="ghcr.io/miha42-github/company_dns"; package="company_dns_v4"
tag=""; profile="release-small"; platform="linux/amd64"; push=1; smoke=1; dirty_ok=0
while [ $# -gt 0 ]; do
  case "$1" in
    --tag) tag="$2"; shift 2;;
    -p) profile="$2"; shift 2;;
    --platform) platform="$2"; shift 2;;
    --no-push) push=0; shift;;
    --skip-smoke) smoke=0; shift;;
    --allow-dirty) dirty_ok=1; shift;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 0;;
    *) echo "unknown argument $1" >&2; exit 2;;
  esac
done
case "$profile" in release-small|release-lean) ;; *) echo "profile must be release-small or release-lean, got $profile" >&2; exit 2;; esac
cd "$repo"
sha="$(git rev-parse --short=7 HEAD)"
dirty=0; [ -z "$(git status --porcelain --untracked-files=no)" ] || dirty=1
if [ "$dirty" = 1 ] && [ "$dirty_ok" = 0 ]; then
  echo "the working tree has uncommitted changes; commit them, or pass --allow-dirty for a throwaway build (its tag will say -dirty)" >&2; exit 1
fi
[ -n "$tag" ] || tag="$(date +%m%d%Y)-$sha"
[ "$dirty" = 0 ] || tag="$tag-dirty"
case "$tag" in latest|"") echo "the tag must be pinned, never latest" >&2; exit 2;; esac
case "$tag" in *[!A-Za-z0-9._-]*) echo "tag $tag has characters Docker does not allow" >&2; exit 2;; esac
image="$registry/$package:$tag"
echo "==> Image    : $image"
echo "==> Profile  : $profile   Platform: $platform   Commit: $sha$([ "$dirty" = 1 ] && echo ' (dirty)')"

echo "==> Building"
"$repo/v4/scripts/docker-build.sh" -t "$image" -p "$profile" --platform "$platform" --load

if [ "$smoke" = 1 ]; then
  echo "==> Smoke test (no network, then the offline test layers)"
  "$repo/v4/scripts/docker-smoke.sh" "$image"
else
  echo "==> Smoke test skipped"
fi

digest=""
if [ "$push" = 1 ]; then
  env_file="${ENV_FILE:-$repo/.env}"
  [ -f "$env_file" ] || { echo "$env_file not found. Create it with a line: GITHUB_PAT=<your PAT with write:packages scope>" >&2; exit 1; }
  pat="$(grep -E '^GITHUB_PAT=' "$env_file" | cut -d= -f2- | tr -d '[:space:]')"
  [ -n "$pat" ] || { echo "GITHUB_PAT is not set in $env_file" >&2; exit 1; }
  user="$(curl -sf -H "Authorization: Bearer $pat" https://api.github.com/user | python3 -c "import sys,json; print(json.load(sys.stdin)['login'])")"
  echo "==> Pushing as $user"
  printf '%s' "$pat" | docker login ghcr.io -u "$user" --password-stdin
  docker push "$image"
  digest="$(docker inspect --format '{{index .RepoDigests 0}}' "$image" 2>/dev/null || true)"
  echo "==> Checking that the image pulls with no credentials (the package must be public)"
  anon="$(mktemp -d)"
  if DOCKER_CONFIG="$anon" docker pull "$image" >/dev/null; then
    echo "   anonymous pull works"
  else
    rm -rf "$anon"
    echo "ERROR: the image was pushed but cannot be pulled anonymously. Make the package public (see this script's header) and run: docker pull $image from a machine that is not logged in." >&2
    exit 1
  fi
  rm -rf "$anon"
else
  echo "==> Not pushing (--no-push)"
fi

manifest_hash="$(shasum -a 256 "$repo/v4/data-manifest.json" | cut -d' ' -f1)"
record="$(python3 - "$tag" "$image" "$digest" "$sha" "$dirty" "$profile" "$platform" "$manifest_hash" "$push" <<'PY'
import json, sys, time
tag, image, digest, sha, dirty, profile, platform, mh, pushed = sys.argv[1:]
print(json.dumps({"tag": tag, "image": image, "digest": digest or None, "commit": sha, "dirty": dirty == "1", "profile": profile,
                  "platform": platform, "data_manifest_sha256": mh, "pushed": pushed == "1", "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}))
PY
)"
echo "$record" >> "$repo/v4/.build-log"
echo "==> Recorded in v4/.build-log:"; echo "$record"
echo "==> Done. Deploy with: k8s/staging/deploy.sh $tag"
