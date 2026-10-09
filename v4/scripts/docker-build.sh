#!/usr/bin/env bash
# Build the V4 image from the repository root.
#
#   v4/scripts/docker-build.sh [-t TAG] [-p release-lean|release-small] [--platform linux/amd64] [--lto off|thin] [--data-source dir:/in|url:BASE] [--edgar ingest|data] [--no-verify] [--load|--push]
#
# DATA_DIR  directory with the SIC feather files (default: <repo>/tmp, or COMPANY_DNS_DATA_DIR if set); used when --data-source is dir:/in
#           (and for the EDGAR catalog when --edgar data)
# MODEL_DIR the fastembed cache with the model (default: <repo>/v4/.fastembed_cache; create it by running the server once)
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tag="company-dns-v4:dev"; profile="release-lean"; edgar="ingest"; datasrc="dir:/in"; extra=()
while [ $# -gt 0 ]; do
  case "$1" in
    -t) tag="$2"; shift 2;;
    -p) profile="$2"; shift 2;;
    --platform) extra+=(--platform "$2"); shift 2;;
    --data-source) datasrc="$2"; extra+=(--build-arg "DATA_SOURCE=$2"); shift 2;;       # dir:/in (default, the DATA_DIR context) or url:https://BASE/
    --edgar) edgar="$2"; shift 2;;                                        # ingest (default, like V3's makedb.py) or data (a frozen file)
    --no-verify) extra+=(--build-arg "DATA_VERIFY=0"); shift;;
    --lto) extra+=(--build-arg "CARGO_LTO=$2"); shift 2;;   # validation builds only (small Docker VM); see the Dockerfile
    --load|--push) extra+=("$1"); shift;;
    *) echo "unknown argument $1" >&2; exit 2;;
  esac
done
data="${DATA_DIR:-${COMPANY_DNS_DATA_DIR:-$repo/tmp}}"
model="${MODEL_DIR:-$repo/v4/.fastembed_cache}"
# A URL source with an ingested EDGAR catalog needs no local data at all: give the build an empty directory as its `data` context.
if [ "${datasrc#url:}" != "$datasrc" ] && [ "$edgar" = "ingest" ]; then data="$(mktemp -d)"; fi
[ -d "$data" ]  || { echo "data directory not found: $data (set DATA_DIR)" >&2; exit 1; }
[ -d "$model" ] || { echo "model cache not found: $model (set MODEL_DIR, or run the server once to download it)" >&2; exit 1; }
case " ${extra[*]} " in *" --load "*|*" --push "*) ;; *) extra+=(--load);; esac
# A data URL needs a header file for private servers: DATA_AUTH_FILE (one "Name: value" line) is passed as a BuildKit secret, never as an argument.
[ -z "${DATA_AUTH_FILE:-}" ] || extra+=(--secret "id=data_auth,src=$DATA_AUTH_FILE")
cd "$repo"
exec docker buildx build -f v4/Dockerfile \
  --build-context "data=$data" --build-context "model=$model" \
  --build-arg "PROFILE=$profile" --build-arg "EDGAR_CATALOG=$edgar" --build-arg "EDGAR_REFRESH=$(date +%Y%m%d)" -t "$tag" "${extra[@]}" .
