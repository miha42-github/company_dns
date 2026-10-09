#!/usr/bin/env bash
# Smoke-test a built V4 image with NO network, which proves the model and the data are inside it.
#
#   v4/scripts/docker-smoke.sh [IMAGE] [PORT]
#
# Starts the container with --network none, waits for /health, checks a SIC lookup, an embedding-backed search and the UI,
# then, because --network none cannot publish a port, runs the offline test layers against a second container.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ua="company_dns-docker-smoke/1.0 (+https://github.com/miha42-github/company_dns)"  # a self-identifying User-Agent gets the normal rate limit
image="${1:-company-dns-v4:dev}"; port="${2:-4100}"; name="company-dns-smoke-$$"
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; docker rm -f "$name-net" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "== 1. offline start: --network none (the model and data must be in the image)"
docker run -d --name "$name-net" --network none "$image" >/dev/null
for i in $(seq 1 60); do
  [ "$(docker inspect -f '{{.State.Running}}' "$name-net")" = "true" ] || { docker logs "$name-net" | tail -20; echo "container exited"; exit 1; }
  docker exec "$name-net" curl -fsS -A "$ua" http://127.0.0.1:4000/health >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$name-net" curl -fsS -A "$ua" http://127.0.0.1:4000/health >/dev/null || { docker logs "$name-net" | tail -20; echo "no health after 60 s"; exit 1; }
echo "   healthy with no network"
docker exec "$name-net" curl -fsS -A "$ua" http://127.0.0.1:4000/V4.0/na/sic/code/3571 | head -c 160; echo
docker exec "$name-net" curl -fsS -A "$ua" "http://127.0.0.1:4000/V4.0/na/sic/similarity/computers" | head -c 160; echo
docker exec "$name-net" curl -fsS -A "$ua" -o /dev/null -w "UI /ui/: HTTP %{http_code}, %{size_download} bytes\n" http://127.0.0.1:4000/ui/
docker exec "$name-net" sh -c 'id -u; ls /app/data'
docker rm -f "$name-net" >/dev/null

echo "== 2. the test layers that need no upstream calls, against a published port"
# SQL on with the checked-in placeholder profiles (no token matches their zero hashes), so the contract layer sees the whole
# API surface, as in the staging configuration.
docker run -d --name "$name" -p "$port:4000" \
  -v "$repo/v4/credentials.example:/run/secrets/credentials:ro" -v "$repo/v4/rules.example.json:/run/secrets/rules.json:ro" \
  -e COMPANY_DNS_SQL_ENABLED=true -e COMPANY_DNS_CREDENTIALS_FILE=/run/secrets/credentials -e COMPANY_DNS_RULES_FILE=/run/secrets/rules.json \
  "$image" >/dev/null
for i in $(seq 1 60); do curl -fsS "http://127.0.0.1:$port/health" >/dev/null 2>&1 && break; sleep 1; done
python3 "$repo/api_tests/run.py" --base-url "http://127.0.0.1:$port" --layers L0,L1,L2,L4 --report "${REPORT:-/tmp/docker-smoke-report.json}"
echo "== done"
