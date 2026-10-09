#!/usr/bin/env bash
# Make a throwaway V4 profile with NO rate limit, for performance and parity runs against a V4 container.
#
#   v4/scripts/perf-profile.sh [DIR]          (default DIR: v4/perf-secrets, gitignored)
#
# Writes DIR/credentials (profile:sha256-of-token), DIR/rules.json (that profile bypasses the rate limiter) and DIR/token (the
# secret, mode 600), and prints the --auth value. Why: V4's limiter allows a generic User-Agent 5 requests a minute and an
# identified caller 200 a minute, so a load test without a bypass profile measures the limiter, not the server. Never use
# these files outside a test host; they are not secrets worth keeping, and nothing here is committed.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dir="${1:-$repo/v4/perf-secrets}"
mkdir -p "$dir"
token="$(openssl rand -hex 32)"
hash="$(printf '%s' "$token" | (shasum -a 256 2>/dev/null || sha256sum) | cut -d' ' -f1)"
printf 'perf:%s\n' "$hash" > "$dir/credentials"
printf '{"defaults": {}, "profiles": {"perf": {"rate_limit": {"bypass": true}}}}\n' > "$dir/rules.json"
printf '%s' "$token" > "$dir/token"; chmod 600 "$dir/token"
echo "wrote $dir/{credentials,rules.json,token}"
echo "use:  --auth perf:\$(cat $dir/token)      and start V4 with the perf override: docker-compose.perf.yml (PERF_SECRETS_DIR=$dir)"
