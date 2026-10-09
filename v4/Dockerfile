# syntax=docker/dockerfile:1.7
#
# company_dns V4 image. Self-contained: the binary, the UI, the classification and EDGAR data files, and the embedding
# model all travel inside it, so a pod starts with no outbound access and no volume (docs/plans/v4-deployment.md §3.2,
# docs/plans/v4-release-to-staging.md step 6). A volume mounted at /app/data replaces the data without a rebuild.
#
# Build from the REPOSITORY ROOT (the data gate script lives under docs/), with two named contexts that are not in git:
#
#   docker buildx build -f v4/Dockerfile \
#       --build-context data=/path/to/dir-with-the-feather-files \
#       --build-context model=/path/to/.fastembed_cache \
#       --build-arg PROFILE=release-lean \
#       -t company-dns-v4:dev .
#
# or just run v4/scripts/docker-build.sh, which fills those in. See v4/README.md ("Docker").
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
# Data gate: every file is checked, and a bad file fails the build (docs/plans/research/check_ic_feather.py).
FROM python:3.12-slim AS data-gate
RUN pip install --no-cache-dir pyarrow
COPY docs/plans/research/check_ic_feather.py /gate/check_ic_feather.py
COPY --from=data . /in
RUN set -eu; \
    mkdir -p /out; \
    for f in us_flat_embedded japan_rev13_flat_embedded nace_rev2_flat_embedded isic_rev4_flat_embedded; do \
        [ -f "/in/$f.feather" ] || { echo "MISSING data file $f.feather in the 'data' build context (see the header of v4/Dockerfile)"; exit 1; }; \
        echo "== $f"; python /gate/check_ic_feather.py "/in/$f.feather"; \
        cp "/in/$f.feather" "/out/$f.feather"; \
    done; \
    [ -f /in/edgar_10x_catalog.feather ] || { echo "MISSING edgar_10x_catalog.feather in the 'data' build context"; exit 1; }; \
    python - <<'PY'
import pyarrow.ipc as ipc, sys
r = ipc.open_file("/in/edgar_10x_catalog.feather")
m = {k.decode(): v.decode() for k, v in (r.schema.metadata or {}).items()}
rows = r.read_all().num_rows
print("EDGAR catalog:", rows, "rows,", m.get("first_quarter"), "to", m.get("last_quarter"), m.get("quarters"), "quarters")
if rows < 10000 or not m.get("last_quarter"):
    sys.exit("EDGAR catalog looks empty or has no quarter metadata")
PY
RUN cp /in/edgar_10x_catalog.feather /out/edgar_10x_catalog.feather

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
# The ONNX runtime is downloaded by the build (ort), so this stage needs network access.
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/usr/local/cargo/git \
    --mount=type=cache,target=/src/v4/target \
    if [ -n "${CARGO_LTO}" ]; then \
        export CARGO_PROFILE_RELEASE_LEAN_LTO="${CARGO_LTO}" CARGO_PROFILE_RELEASE_SMALL_LTO="${CARGO_LTO}"; \
        echo "WARNING: validation build with LTO=${CARGO_LTO}; not the release binary"; \
    fi \
    && cargo build --locked --profile "${PROFILE}" -p company-dns-server --bin company-dns-server \
    && install -D "target/${PROFILE}/company-dns-server" /out/company-dns-server

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
