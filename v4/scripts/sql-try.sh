#!/usr/bin/env bash
# Try out, and test, the EXPERIMENTAL SQL endpoint (docs/plans/v4-sql-endpoint.md).
#
#   scripts/sql-try.sh setup            make local test profiles + tokens (once)
#   scripts/sql-try.sh start            run the server with SQL on (leave it running)
#   scripts/sql-try.sh start --off      run the server with SQL off (to see the 404)
#   scripts/sql-try.sh check            run the whole battery against the running server
#   scripts/sql-try.sh check --off      the one check for a server started with --off
#   scripts/sql-try.sh q sic "select ..." [profile]    one query, pretty-printed
#   scripts/sql-try.sh tables           list tables and columns for both datasets
#
# Everything private lives in v4/.local/sql/ (gitignored): `credentials` (profile:hash
# lines, like /etc/passwd) and `rules.json` (defaults plus per-profile overrides), which
# the server reads, and tokens.env (the tokens themselves, for this script's curl calls).
# Nothing here is a real credential.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$HERE/.local/sql"
BASE="${BASE:-http://localhost:${PORT:-4000}}"
UA='sql-try/1.0 (company_dns local testing)'

need() { command -v "$1" >/dev/null || { echo "needs $1"; exit 2; }; }
need curl; need jq; need openssl; need shasum

setup() {
  mkdir -p "$DIR"; chmod 700 "$DIR"
  if [ -f "$DIR/profiles.json" ] || { [ -f "$DIR/rules.json" ] && ! grep -q '"sql-rpm"' "$DIR/rules.json"; }; then
    echo "older setup layout: recreating it (tokens change; restart the server)"
    rm -f "$DIR/profiles.json" "$DIR/credentials" "$DIR/rules.json" "$DIR/tokens.env"
  fi
  if [ -f "$DIR/credentials" ] && [ -f "$DIR/rules.json" ]; then echo "already set up: $DIR (delete it to start over)"; return; fi
  h() { printf '%s' "$1" | shasum -a 256 | cut -d' ' -f1; }
  : > "$DIR/tokens.env"; : > "$DIR/credentials"
  echo "# profile:sha256-of-token (test profiles; the tokens are in tokens.env)" >> "$DIR/credentials"
  for p in tester sic-only no-sql unlimited capped sql-small sql-rpm; do
    t=$(openssl rand -hex 32)
    echo "$p:$(h "$t")" >> "$DIR/credentials"
    echo "$(printf '%s' "$p" | tr 'a-z-' 'A-Z_')_TOKEN=$t" >> "$DIR/tokens.env"
  done
  # defaults: no rate limit (so the battery is not throttled); overrides inherit it and change one thing
  cat > "$DIR/rules.json" <<'RULES'
{
  "defaults": {"rate_limit": {"bypass": true}},
  "profiles": {
    "tester":    {"sql": {"datasets": ["sic", "edgar"]}},
    "sic-only":  {"sql": {"datasets": ["sic"]}},
    "no-sql":    {"rate_limit": null},
    "unlimited": {},
    "capped":    {"rate_limit": {"requests_per_minute": 20, "burst": 20}},
    "sql-small": {"sql": {"datasets": ["sic"], "limits": {"max_rows": 5, "timeout_secs": 2, "concurrency": 1}}},
    "sql-rpm":   {"sql": {"datasets": ["sic"], "limits": {"requests_per_minute": 20}}}
  }
}
RULES
  chmod 600 "$DIR/credentials" "$DIR/rules.json" "$DIR/tokens.env"
  echo "created $DIR: credentials (hashes), rules.json (defaults + overrides), tokens.env (the tokens)"
  echo "profiles: tester, sic-only, no-sql, unlimited, capped, sql-small, sql-rpm"
}

tok() { # profile -> token
  var="$(printf '%s' "$1" | tr 'a-z-' 'A-Z_')_TOKEN"
  grep "^$var=" "$DIR/tokens.env" | cut -d= -f2
}

start() {
  [ -f "$DIR/credentials" ] || setup
  cd "$HERE" || exit 1
  if [ "${1:-}" = "--off" ]; then
    echo "starting with SQL OFF (flag unset)"
    exec env -u COMPANY_DNS_SQL_ENABLED cargo run -p company-dns-server
  fi
  echo "starting with SQL ON, small limits so they are easy to hit:"
  echo "  default 50 rows, max 200 rows, 5 s timeout, 128 MB, 2 concurrent, parallelism 2"
  exec env COMPANY_DNS_SQL_ENABLED=true COMPANY_DNS_CREDENTIALS_FILE="$DIR/credentials" COMPANY_DNS_RULES_FILE="$DIR/rules.json" \
    COMPANY_DNS_SQL_DEFAULT_ROWS=50 COMPANY_DNS_SQL_MAX_ROWS=200 COMPANY_DNS_SQL_TIMEOUT_SECS=5 \
    COMPANY_DNS_SQL_MEMORY_MB=128 COMPANY_DNS_SQL_MAX_CONCURRENT=2 COMPANY_DNS_SQL_PARALLELISM=2 \
    cargo run -p company-dns-server
}

# post <profile|-|raw:id:token> <json body> [extra curl args...]: prints "STATUS<TAB>body"
post() {
  who="$1"; body="$2"; shift 2
  auth=()
  case "$who" in
    -) ;;
    raw:*) auth=(-u "${who#raw:}");;
    *) auth=(-u "$who:$(tok "$who")");;
  esac
  curl -s -o /tmp/sql-try.$$ -w '%{http_code}' -X POST "$BASE/V4.0/sql" -H 'Content-Type: application/json' \
    -A "$UA" "${auth[@]+"${auth[@]}"}" "$@" -d "$body"
  printf '\t'; cat /tmp/sql-try.$$; rm -f /tmp/sql-try.$$
}
q() { jq -n --arg d "$1" --arg s "$2" '{dataset:$d, sql:$s}'; }

PASS=0; FAIL=0
expect() { # name expected_status actual_line [jq-expr-that-must-be-true]
  name="$1"; want="$2"; line="$3"; expr="${4:-}"
  got="${line%%$'\t'*}"; body="${line#*$'\t'}"
  if [ "$got" != "$want" ]; then
    FAIL=$((FAIL+1)); printf 'FAIL  %s  (want %s, got %s)  %s\n' "$name" "$want" "$got" "$(printf '%s' "$body" | head -c 160)"; return
  fi
  if [ -n "$expr" ] && ! printf '%s' "$body" | jq -e "$expr" >/dev/null 2>&1; then
    FAIL=$((FAIL+1)); printf 'FAIL  %s  (status ok, but body check failed: %s)  %s\n' "$name" "$expr" "$(printf '%s' "$body" | head -c 160)"; return
  fi
  PASS=$((PASS+1)); printf 'ok    %s\n' "$name"
}

check() {
  if [ "${1:-}" = "--off" ]; then
    expect "SQL off: route does not exist" 404 "$(post tester "$(q sic 'select 1')")"
    printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"; [ "$FAIL" = 0 ]; return
  fi
  [ -f "$DIR/tokens.env" ] || { echo "run: scripts/sql-try.sh setup, then start"; exit 2; }
  curl -s -o /dev/null "$BASE/health" || { echo "server not reachable at $BASE (scripts/sql-try.sh start)"; exit 2; }

  want() { # name, "codes", regex every code must match, [regex at least one must match]
    name="$1"; got="$2"; each="$3"; some="${4:-}"
    if printf '%s' "$got" | tr ' ' '\n' | grep -v '^$' | grep -qvE "^($each)$"; then FAIL=$((FAIL+1)); echo "FAIL  $name  (got: $got)"; return; fi
    if [ -n "$some" ] && ! printf '%s' "$got" | tr ' ' '\n' | grep -qE "^($some)$"; then FAIL=$((FAIL+1)); echo "FAIL  $name  (got: $got)"; return; fi
    PASS=$((PASS+1)); echo "ok    $name"
  }
  echo "== access =="
  # SQL goes through the normal rate limiter too, so each anonymous call comes from a fresh
  # source address (X-Forwarded-For) to get a fresh draconian burst
  xff() { echo "X-Forwarded-For: 10.$((RANDOM % 250)).$((RANDOM % 250)).$((RANDOM % 250))"; }
  expect "no credentials -> 401"                         401 "$(post - "$(q sic 'select 1')" -H "$(xff)")"
  expect "wrong token -> 401"                            401 "$(post raw:tester:not-the-token "$(q sic 'select 1')")"
  expect "unknown profile -> 401"                        401 "$(post raw:nobody:x "$(q sic 'select 1')")"
  expect "forged Origin/Referer -> still 401"            401 "$(post - "$(q sic 'select 1')" -H 'Origin: https://mediumroast.io' -H 'Referer: https://mediumroast.io/' -H "$(xff)")"
  expect "profile without SQL -> 403"                    403 "$(post no-sql "$(q sic 'select 1')")"
  expect "sic-only profile on edgar -> 403"              403 "$(post sic-only "$(q edgar 'select 1')")"
  expect "sic-only profile on sic -> 200"                200 "$(post sic-only "$(q sic 'select 1 as one')")" '.data.rows[0].one == 1'
  expect "unknown dataset -> 400"                        400 "$(post tester "$(q nope 'select 1')")"
  expect "empty sql -> 400"                              400 "$(post tester "$(q sic '  ')")"

  echo "== it queries real data =="
  expect "sic: count rows"                               200 "$(post tester "$(q sic 'select count(*) as n from sic_data')")" '.data.rows[0].n > 0'
  expect "sic: lists every loaded system table"          200 "$(post tester "$(q sic "select table_name from information_schema.tables where table_schema = 'public'")")" '.data.row_count >= 1'
  expect "edgar: count rows"                             200 "$(post tester "$(q edgar 'select count(*) as n from edgar_catalog')")" '.data.rows[0].n > 0'
  expect "response says experimental"                    200 "$(post tester "$(q sic 'select 1')")" '[.data.limitations[].code] | index("experimental") != null'
  expect "bad SQL -> 400 with DataFusion's message"      400 "$(post tester "$(q sic 'selec 1')")" '.message | length > 0'

  echo "== vector columns are hidden =="
  expect "select * has no vector_ column"                200 "$(post tester "$(q sic 'select * from sic_data limit 1')")" '[.data.rows[0] | keys[] | select(startswith("vector_"))] | length == 0'
  expect "naming a vector column fails"                  400 "$(post tester "$(q sic 'select vector_all_minilm_l6_v2 from sic_data limit 1')")"
  expect "information_schema shows no vector_ column"    200 "$(post tester "$(q sic "select count(*) as n from information_schema.columns where column_name like 'vector%'")")" '.data.rows[0].n == 0'

  echo "== read-only, one statement =="
  for s in "insert into sic_data select * from sic_data limit 1" "create table x as select 1" "drop table sic_data" \
           "create external table e (a int) stored as csv location '/etc/passwd'" "copy sic_data to '/tmp/out.csv'" \
           "set datafusion.execution.batch_size = 1" "select 1; select 2" "select * from '/etc/passwd'"; do
    expect "refused: $s" 400 "$(post tester "$(q sic "$s")")"
  done
  expect "table still intact afterwards"                 200 "$(post tester "$(q sic 'select count(*) as n from sic_data')")" '.data.rows[0].n > 0'

  echo "== limits (server started with default 50, max 200 rows, 5 s, 2 concurrent) =="
  expect "default row cap (50) with truncation notice"   200 "$(post tester "$(q sic 'select * from generate_series(1, 1000)')")" '.data.row_count == 50 and .data.truncated == true'
  expect "explicit limit honoured"                       200 "$(post tester "$(jq -n '{dataset:"sic",sql:"select * from generate_series(1, 1000)",limit:7}')")" '.data.row_count == 7'
  expect "limit above ceiling is clamped to 200"         200 "$(post tester "$(jq -n '{dataset:"sic",sql:"select * from generate_series(1, 1000)",limit:100000}')")" '.data.row_count == 200 and .data.limit == 200'
  slow='select count(*) from generate_series(1, 5000000000) a cross join generate_series(1, 5000000000) b'
  t0=$(date +%s)
  expect "runaway query -> 504 at the timeout"           504 "$(post tester "$(q sic "$slow")")"
  t1=$(date +%s); [ $((t1 - t0)) -le 9 ] && { PASS=$((PASS+1)); echo "ok    ...and it was cancelled promptly ($((t1 - t0)) s)"; } || { FAIL=$((FAIL+1)); echo "FAIL  timeout took $((t1 - t0)) s"; }
  expect "memory hog -> 422 (pool is 128 MB)"            422 "$(post tester "$(q sic "select string_agg(cast(value as varchar), ',') as s from generate_series(1, 300000000)")")" '.message | test("memory")'
  echo "   (firing 6 slow queries at once; the server allows 2 at a time)"
  rm -f /tmp/sql-try-par.*
  for i in 1 2 3 4 5 6; do ( post tester "$(q sic "$slow")" | cut -f1 > /tmp/sql-try-par.$i ) & done; wait
  codes=$(cat /tmp/sql-try-par.* | sort | uniq -c | tr -s ' ' | tr '\n' ';'); rm -f /tmp/sql-try-par.*
  if printf '%s' "$codes" | grep -q '429'; then PASS=$((PASS+1)); echo "ok    concurrency cap refuses the excess ($codes)"; else FAIL=$((FAIL+1)); echo "FAIL  expected some 429s, got: $codes"; fi
  expect "server still answers after the abuse"          200 "$(post tester "$(q sic 'select 1')")"

  echo "== per-profile SQL limits, and the normal limits still apply to SQL =="
  expect "sql-small: 100 rows requested, profile cap is 5"   200 "$(post sql-small "$(jq -n '{dataset:"sic",sql:"select * from generate_series(1, 1000)",limit:100}')")" '.data.row_count == 5 and .data.limit == 5 and .data.truncated == true'
  t0=$(date +%s)
  expect "sql-small: its 2 s timeout, not the server's 5 s"  504 "$(post sql-small "$(q sic "$slow")")"
  t1=$(date +%s); [ $((t1 - t0)) -le 4 ] && { PASS=$((PASS+1)); echo "ok    ...cancelled in $((t1 - t0)) s"; } || { FAIL=$((FAIL+1)); echo "FAIL  profile timeout took $((t1 - t0)) s"; }
  rm -f /tmp/sql-try-par.*
  for i in 1 2 3; do ( post sql-small "$(q sic "$slow")" | cut -f1 > /tmp/sql-try-par.$i ) & done; wait
  codes=$(cat /tmp/sql-try-par.* | sort | uniq -c | tr -s ' ' | tr '\n' ';'); rm -f /tmp/sql-try-par.*
  if printf '%s' "$codes" | grep -q '429'; then PASS=$((PASS+1)); echo "ok    sql-small: concurrency 1 refuses the extra queries ($codes)"; else FAIL=$((FAIL+1)); echo "FAIL  expected 429s from the profile's concurrency limit, got: $codes"; fi
  rpm=""; for i in $(seq 1 12); do rpm="$rpm $(post sql-rpm "$(q sic 'select 1')" | cut -f1)"; done
  want "sql-rpm: 20 requests/min is its own SQL limit" "$rpm" '200|429' 429
  anonc=""; fx="$(xff)"; for i in 1 2 3; do anonc="$anonc $(post - "$(q sic 'select 1')" -H 'Origin: https://mediumroast.io' -H "$fx" | cut -f1)"; done
  want "anonymous + forged Origin on SQL: no bypass, limited like anyone (401, then 429)" "$anonc" '401|429' 429
  want "wrong credential on SQL still 401 (never silently anonymous)" "$(post raw:tester:wrong "$(q sic 'select 1')" -H "$(xff)" | cut -f1)" 401

  echo "== failed logins are throttled =="
  for i in $(seq 1 12); do post raw:tester:wrong "$(q sic 'select 1')" > /dev/null; done
  expect "after 10 failures: 429 for bad credentials"    429 "$(post raw:tester:wrong "$(q sic 'select 1')")"
  expect "...but the right credential still works"       200 "$(post tester "$(q sic 'select 1')")"

  echo "== profiles and rate limits on the lookup routes =="
  # a fresh source address per run, so earlier runs' buckets do not interfere (the server
  # keys on X-Forwarded-For; locally nothing else sets it)
  newip() { xff="10.$((RANDOM % 250)).$((RANDOM % 250)).$((RANDOM % 250))"; }
  newip
  L="$BASE/V4.0/na/sic/code/7372"
  look() { curl -s -o /dev/null -w '%{http_code}' -H "X-Forwarded-For: $xff" "$@" "$L"; }
  codes() { n="$1"; shift; for _ in $(seq 1 "$n"); do look "$@"; printf ' '; done; }
  newip; g=$(look -A 'curl/8.4.0'); g2=$(look -A 'curl/8.4.0')
  if [ "$g" = 200 ] && [ "$g2" = 429 ]; then PASS=$((PASS+1)); echo "ok    anonymous, generic User-Agent: draconian (one request, then 429)"; else FAIL=$((FAIL+1)); echo "FAIL  anonymous draconian: got $g $g2"; fi
  newip
  want "self-identifying User-Agent: normal tier (5 in a row)" "$(codes 5 -A 'sql-try/1.0 (contact@example.com)')" 200
  newip
  want "profile with no rate_limit grant: normal tier even with a generic User-Agent" "$(codes 4 -A 'curl/8.4.0' -u "no-sql:$(tok no-sql)")" 200
  newip
  want "'unlimited' profile (bypass): 25 requests, none limited" "$(codes 25 -A 'curl/8.4.0' -u "unlimited:$(tok unlimited)")" 200
  newip
  want "'capped' profile (20/min): limited, with its own bucket" "$(codes 12 -A 'curl/8.4.0' -u "capped:$(tok capped)")" '200|429' 429
  newip
  want "wrong credential on a lookup route -> 401, not silently anonymous" "$(look -A 'curl/8.4.0' -u 'capped:wrong')" 401

  echo "== documentation =="
  curl -s "$BASE/openapi.json" -A "$UA" > /tmp/sql-try-openapi.$$
  jq -e '.paths["/V4.0/sql"].post.tags | index("experimental")' /tmp/sql-try-openapi.$$ >/dev/null && { PASS=$((PASS+1)); echo "ok    OpenAPI: operation is tagged experimental"; } || { FAIL=$((FAIL+1)); echo "FAIL  OpenAPI tag"; }
  jq -e '.components.securitySchemes.basic_auth.scheme == "basic"' /tmp/sql-try-openapi.$$ >/dev/null && { PASS=$((PASS+1)); echo "ok    OpenAPI: HTTP Basic security scheme declared"; } || { FAIL=$((FAIL+1)); echo "FAIL  OpenAPI security scheme"; }
  spec() { # name, jq expression that must be true over the spec
    if jq -e "$2" /tmp/sql-try-openapi.$$ >/dev/null 2>&1; then PASS=$((PASS+1)); echo "ok    OpenAPI: $1"; else FAIL=$((FAIL+1)); echo "FAIL  OpenAPI: $1"; fi
  }
  spec "every operation except /health documents 429 (rate limit)"          '[.paths | to_entries[] | select(.key != "/health") | .value[] | select(.responses | has("429") | not)] | length == 0'
  spec "every operation except /health documents 401 (wrong credential)"   '[.paths | to_entries[] | select(.key != "/health") | .value[] | select(.responses | has("401") | not)] | length == 0'
  spec "every tag in use is declared, with a description"                   '([.paths[][] | .tags[]?] | unique) as $used | ([.tags[]? | select((.description // "") != "") | .name]) as $declared | ($used - $declared) | length == 0'
  spec "the description explains the access ladder and the rate limit"      '.info.description | (contains("User-Agent") and contains("Retry-After") and contains("429"))'
  spec "the description marks the SQL endpoint experimental"                '.info.description | (ascii_downcase | contains("experimental"))'
  spec "the licence is filled in"                                           '(.info.license.name // "") != ""'
  spec "the V4-only request bodies have examples (match, map, sql)"         '[.components.schemas.MatchRequest, .components.schemas.MapRequest, .components.schemas.SqlRequest] | all(has("example"))'
  rm -f /tmp/sql-try-openapi.$$

  printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"; [ "$FAIL" = 0 ]
}

case "${1:-}" in
  setup) setup;;
  start) shift; start "$@";;
  check) shift; check "$@";;
  q) shift; ds="${1:?dataset}"; sql="${2:?sql}"; who="${3:-tester}"
     out=$(post "$who" "$(q "$ds" "$sql")"); echo "HTTP ${out%%$'\t'*}"; printf '%s' "${out#*$'\t'}" | jq '.data // .' ;;
  tables) for ds in sic edgar; do echo "== $ds =="
     out=$(post tester "$(q "$ds" "select table_name, column_name, data_type from information_schema.columns where table_schema = 'public' order by table_name, ordinal_position")")
     printf '%s' "${out#*$'\t'}" | jq -r '.data.rows[]? | "\(.table_name)\t\(.column_name)\t\(.data_type)"'; done;;
  *) sed -n '2,14p' "$0";;
esac
