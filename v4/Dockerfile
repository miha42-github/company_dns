# syntax=docker/dockerfile:1.7
#
# company_dns V4 image. Self-contained, and prepared the way V3's is: V3's `RUN python makedb.py` builds its EDGAR database
# while the image is built, and this build does the same with `ingest-edgar`, so the image is ready to run the moment it starts.
# The binary, the UI, the classification data files, the EDGAR catalog and the embedding model all travel inside it, so a pod
# starts with no outbound access and no volume (docs/plans/v4-deployment.md section 3.2, docs/plans/v4-release-to-staging.md
# step 6 and "Data supply"). A volume mounted at /app/data replaces the data without a rebuild.
#
# Build from the REPOSITORY ROOT (the gate script lives under docs/). Or just run v4/scripts/docker-build.sh, which fills this in.
#
#   docker buildx build -f v4/Dockerfile \
#       --build-context data=/path/to/dir-with-the-sic-feather-files \    # only with DATA_SOURCE=dir:/in (the default)
#       --build-context model=/path/to/.fastembed_cache \
#       --build-arg PROFILE=release-lean \
#       -t company-dns-v4:dev .
#
# Where the pieces come from:
#   classification files (4)  v4/scripts/fetch_data.py, from DATA_SOURCE: dir:/in (the `data` build context, default) or
#                             url:https://BASE/ (an optional BuildKit secret `data_auth` holds one "Header: value" line).
#                             SHA-256 checked against v4/data-manifest.json (DATA_VERIFY=0 skips), then check_ic_feather.py.
#   EDGAR catalog             EDGAR_CATALOG=ingest (default): `ingest-edgar` runs during the build against sec.gov, like V3's makedb.py.
#                             EDGAR_CATALOG=data: taken from the `data` context instead (a frozen file, for a like-for-like comparison).
#                             EDGAR_REFRESH (any string, the build script sets today's date) busts the layer cache so a rebuild re-ingests.
#   embedding model           the `model` build context (the fastembed cache), SHA-256 checked.
#
# Why glibc (debian-slim) and not musl/scratch: the ONNX runtime that fastembed links is a prebuilt glibc library;
# there is no musl build of it, so a static musl binary is not available. Why Debian 13 (trixie) and not 12: the prebuilt
# runtime needs a newer libstdc++ than Debian 12 ships (the link fails on __cxa_call_terminate and std::string symbols).
# Build and runtime stay on the same Debian release so the libstdc++ the binary links is the one it runs with. Decided 2026-10-08.

ARG PROFILE=release-lean
ARG RUST_IMAGE=rust:1-trixie
ARG RUNTIME_IMAGE=debian:trixie-slim

# ---------------------------------------------------------------------------------------------------------------------
# Inputs that are not in git. If a named context is not supplied these are empty, and the gates below fail with a clear
# message instead of building an image that cannot start.
FROM scratch AS data
FROM scratch AS model

# ---------------------------------------------------------------------------------------------------------------------
# Data supply: the four classification files, from a directory or a URL, verified against the manifest.
FROM python:3.12-slim AS data-fetch
ARG DATA_SOURCE=dir:/in
ARG DATA_VERIFY=1
COPY v4/scripts/fetch_data.py /fetch/fetch_data.py
COPY v4/data-manifest.json /fetch/data-manifest.json
COPY --from=data . /in
RUN --mount=type=secret,id=data_auth,required=false \
    set -eu; \
    args="--source ${DATA_SOURCE} --out /fetched --manifest /fetch/data-manifest.json"; \
    [ -f /run/secrets/data_auth ] && args="$args --header-file /run/secrets/data_auth"; \
    [ "${DATA_VERIFY}" = "1" ] || args="$args --no-verify"; \
    python /fetch/fetch_data.py $args

# Data gate: every file is checked, and a bad file fails the build (docs/plans/research/check_ic_feather.py).
FROM python:3.12-slim AS data-gate
RUN pip install --no-cache-dir pyarrow
COPY docs/plans/research/check_ic_feather.py /gate/check_ic_feather.py
COPY --from=data-fetch /fetched /in
RUN set -eu; \
    mkdir -p /out; \
    for f in us_flat_embedded japan_rev13_flat_embedded nace_rev2_flat_embedded isic_rev4_flat_embedded; do \
        [ -f "/in/$f.feather" ] || { echo "MISSING $f.feather from the data source (see the header of v4/Dockerfile)"; exit 1; }; \
        echo "== $f"; python /gate/check_ic_feather.py "/in/$f.feather"; \
        cp "/in/$f.feather" "/out/$f.feather"; \
    done

# ---------------------------------------------------------------------------------------------------------------------
# Model gate: the all-MiniLM-L6-v2 ONNX model in the Hugging Face cache layout fastembed reads. The weights file is
# pinned by SHA-256 (its blob name in the cache is that hash), so a wrong or truncated model fails the build.
FROM debian:bookworm-slim AS model-gate
ARG MODEL_REPO=models--Qdrant--all-MiniLM-L6-v2-onnx
ARG MODEL_SHA256=bbd7b466f6d58e646fdc2bd5fd67b2f5e93c0b687011bd4548c420f7bd46f0c5
COPY --from=model . /in
RUN set -eu; \
    [ -d "/in/$MODEL_REPO" ] || { echo "MISSING $MODEL_REPO in the 'model' build context (see the header of v4/Dockerfile)"; exit 1; }; \
    mkdir -p /out; cp -a "/in/$MODEL_REPO" /out/; \
    find /out -name '*.lock' -delete; \
    echo "$MODEL_SHA256  /out/$MODEL_REPO/blobs/$MODEL_SHA256" | sha256sum -c -; \
    for f in model.onnx tokenizer.json tokenizer_config.json config.json special_tokens_map.json; do \
        ls /out/$MODEL_REPO/snapshots/*/$f >/dev/null || { echo "model file $f missing"; exit 1; }; \
    done

# ---------------------------------------------------------------------------------------------------------------------
FROM ${RUST_IMAGE} AS build
ARG PROFILE
# Validation builds only: the release profiles use fat LTO, whose final link needs well over 8 GB of memory (Docker Desktop's
# default VM on a 48 GB Mac failed with "cannot allocate memory"). `--build-arg CARGO_LTO=off` (or `thin`) lets a small VM prove
# the rest of the image. The result is NOT the measured release-lean/release-small binary: never publish or benchmark it.
ARG CARGO_LTO=
WORKDIR /src
COPY v4 /src/v4
WORKDIR /src/v4
# The ONNX runtime is downloaded by the build (ort), so this stage needs network access. `ingest-edgar` is built with the
# server (same profile) so the EDGAR catalog can be made below.
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/usr/local/cargo/git \
    --mount=type=cache,target=/src/v4/target \
    if [ -n "${CARGO_LTO}" ]; then \
        export CARGO_PROFILE_RELEASE_LEAN_LTO="${CARGO_LTO}" CARGO_PROFILE_RELEASE_SMALL_LTO="${CARGO_LTO}"; \
        echo "WARNING: validation build with LTO=${CARGO_LTO}; not the release binary"; \
    fi \
    && cargo build --locked --profile "${PROFILE}" -p company-dns-server -p company-dns-edgar \
         --bin company-dns-server --bin ingest-edgar \
    && install -D "target/${PROFILE}/company-dns-server" /out/company-dns-server \
    && install -D "target/${PROFILE}/ingest-edgar" /out/ingest-edgar

# ---------------------------------------------------------------------------------------------------------------------
# EDGAR catalog, made during the build like V3's makedb.py: the last 8 completed quarters of the SEC's form index
# (about a minute or two and a few hundred MB of downloads, sec.gov must be reachable). A failed quarter fails the build.
FROM ${RUNTIME_IMAGE} AS edgar-catalog
ARG EDGAR_CATALOG=ingest
ARG EDGAR_REFRESH=
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=build /out/ingest-edgar /usr/local/bin/ingest-edgar
COPY --from=data . /in
RUN set -eu; mkdir -p /out; \
    case "${EDGAR_CATALOG}" in \
      ingest) echo "ingesting the EDGAR catalog from sec.gov (refresh token: ${EDGAR_REFRESH:-none})"; \
              ingest-edgar --out /out/edgar_10x_catalog.feather ;; \
      data)   [ -f /in/edgar_10x_catalog.feather ] || { echo "EDGAR_CATALOG=data but edgar_10x_catalog.feather is not in the 'data' context"; exit 1; }; \
              cp /in/edgar_10x_catalog.feather /out/ ;; \
      *)      echo "EDGAR_CATALOG must be ingest or data"; exit 1 ;; \
    esac

FROM python:3.12-slim AS edgar-gate
RUN pip install --no-cache-dir pyarrow
COPY --from=edgar-catalog /out/edgar_10x_catalog.feather /in/edgar_10x_catalog.feather
RUN python - <<'PY'
import pyarrow.ipc as ipc, sys
r = ipc.open_file("/in/edgar_10x_catalog.feather")
m = {k.decode(): v.decode() for k, v in (r.schema.metadata or {}).items()}
rows = r.read_all().num_rows
print("EDGAR catalog:", rows, "rows,", m.get("first_quarter"), "to", m.get("last_quarter"), m.get("quarters"), "quarters, generated", m.get("generated_at"))
if rows < 10000 or not m.get("last_quarter"):
    sys.exit("EDGAR catalog looks empty or has no quarter metadata")
PY

# ---------------------------------------------------------------------------------------------------------------------
FROM ${RUNTIME_IMAGE} AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Numeric non-root UID, as V3 does (Kubernetes runAsNonRoot cannot resolve a user name).
RUN groupadd --system --gid 10001 company_dns \
    && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin company_dns

WORKDIR /app
COPY --from=build /out/company-dns-server /app/company-dns-server
COPY v4/crates/server/static /app/static
COPY --from=data-gate /out /app/data
COPY --from=edgar-gate /in/edgar_10x_catalog.feather /app/data/edgar_10x_catalog.feather
COPY --from=model-gate /out /opt/fastembed

# The vendored Redoc bundle is MIT and its notice has to travel with any redistribution.
COPY v4/THIRD_PARTY_NOTICES.md /usr/share/doc/company-dns/THIRD_PARTY_NOTICES.md
COPY v4/crates/server/assets/redoc/LICENSE v4/crates/server/assets/redoc/redoc.standalone.js.LICENSE.txt v4/crates/server/assets/redoc/README.md /usr/share/doc/company-dns/redoc/

RUN chown -R 10001:10001 /app
USER 10001

ENV COMPANY_DNS_DATA_DIR=/app/data \
    FASTEMBED_CACHE_DIR=/opt/fastembed \
    PORT=4000
EXPOSE 4000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1
CMD ["/app/company-dns-server"]
