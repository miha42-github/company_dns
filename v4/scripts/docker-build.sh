#!/usr/bin/env bash
# Build the V4 image from the repository root.
#
#   v4/scripts/docker-build.sh [-t TAG] [-p release-lean|release-small] [--platform linux/amd64] [--lto off|thin] [--load|--push]
#
# DATA_DIR  directory with the feather files   (default: <repo>/tmp, or COMPANY_DNS_DATA_DIR if set)
# MODEL_DIR the fastembed cache with the model (default: <repo>/v4/.fastembed_cache; create it by running the server once)
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tag="company-dns-v4:dev"; profile="release-lean"; extra=()
while [ $# -gt 0 ]; do
  case "$1" in
    -t) tag="$2"; shift 2;;
    -p) profile="$2"; shift 2;;
    --platform) extra+=(--platform "$2"); shift 2;;
    --lto) extra+=(--build-arg "CARGO_LTO=$2"); shift 2;;   # validation builds only (small Docker VM); see the Dockerfile
    --load|--push) extra+=("$1"); shift;;
    *) echo "unknown argument $1" >&2; exit 2;;
  esac
done
data="${DATA_DIR:-${COMPANY_DNS_DATA_DIR:-$repo/tmp}}"
model="${MODEL_DIR:-$repo/v4/.fastembed_cache}"
[ -d "$data" ]  || { echo "data directory not found: $data (set DATA_DIR)" >&2; exit 1; }
[ -d "$model" ] || { echo "model cache not found: $model (set MODEL_DIR, or run the server once to download it)" >&2; exit 1; }
[ "${#extra[@]}" -gt 0 ] || extra=(--load)
cd "$repo"
exec docker buildx build -f v4/Dockerfile \
  --build-context "data=$data" --build-context "model=$model" \
  --build-arg "PROFILE=$profile" -t "$tag" "${extra[@]}" .
