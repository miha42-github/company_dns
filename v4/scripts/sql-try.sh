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
# Everything private lives in v4/.local/sql/ (gitignored): the profiles file the
# server reads (token HASHES only) and tokens.env (the tokens themselves, for
# this script's curl calls). Nothing here is a real credential.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$HERE/.local/sql"
BASE="${BASE:-http://localhost:${PORT:-4000}}"
UA='sql-try/1.0 (company_dns local testing)'

need() { command -v "$1" >/dev/null || { echo "needs $1"; exit 2; }; }
need curl; need jq; need openssl; need shasum

setup() {
  mkdir -p "$DIR"; chmod 700 "$DIR"
  if [ -f "$DIR/profiles.json" ]; then echo "already set up: $DIR (delete it to start over)"; return; fi
  t1=$(openssl rand -hex 32); t2=$(openssl rand -hex 32); t3=$(openssl rand -hex 32)
  h() { printf '%s' "$1" | shasum -a 256 | cut -d' ' -f1; }
  cat > "$DIR/profiles.json" <<EOF
{"profiles": {
  "tester":   {"secret_sha256": "$(h "$t1")", "sql": {"datasets": ["sic", "edgar"]}},
  "sic-only": {"secret_sha256": "$(h "$t2")", "sql": {"datasets": ["sic"]}},
  "no-sql":   {"secret_sha256": "$(h "$t3")"}
}}
EOF
  printf 'TESTER_TOKEN=%s\nSICONLY_TOKEN=%s\nNOSQL_TOKEN=%s\n' "$t1" "$t2" "$t3" > "$DIR/tokens.env"
  chmod 600 "$DIR/profiles.json" "$DIR/tokens.env"
  echo "created $DIR (profiles: tester, sic-only, no-sql)"
}

tok() { # profile -> token
  # shellcheck disable=SC1091
  . "$DIR/tokens.env"
  case "$1" in tester) echo "$TESTER_TOKEN";; sic-only) echo "$SICONLY_TOKEN";; no-sql) echo "$NOSQL_TOKEN";; *) echo "";; esac
}

start() {
  [ -f "$DIR/profiles.json" ] || setup
  cd "$HERE" || exit 1
  if [ "${1:-}" = "--off" ]; then
    echo "starting with SQL OFF (flag unset)"
    exec env -u COMPANY_DNS_SQL_ENABLED cargo run -p company-dns-server
  fi
  echo "starting with SQL ON, small limits so they are easy to hit:"
  echo "  default 50 rows, max 200 rows, 5 s timeout, 128 MB, 2 concurrent, parallelism 2"
  exec env COMPANY_DNS_SQL_ENABLED=true COMPANY_DNS_PROFILES_FILE="$DIR/profiles.json" \
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

  echo "== access =="
  expect "no credentials -> 401"                         401 "$(post - "$(q sic 'select 1')")"
  expect "wrong token -> 401"                            401 "$(post raw:tester:not-the-token "$(q sic 'select 1')")"
  expect "unknown profile -> 401"                        401 "$(post raw:nobody:x "$(q sic 'select 1')")"
  expect "forged Origin/Referer -> still 401"            401 "$(post - "$(q sic 'select 1')" -H 'Origin: https://mediumroast.io' -H 'Referer: https://mediumroast.io/')"
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

  echo "== failed logins are throttled =="
  for i in $(seq 1 12); do post raw:tester:wrong "$(q sic 'select 1')" > /dev/null; done
  expect "after 10 failures: 429 for bad credentials"    429 "$(post raw:tester:wrong "$(q sic 'select 1')")"
  expect "...but the right credential still works"       200 "$(post tester "$(q sic 'select 1')")"

  echo "== documentation =="
  curl -s "$BASE/openapi.json" -A "$UA" > /tmp/sql-try-openapi.$$
  jq -e '.paths["/V4.0/sql"].post.tags | index("experimental")' /tmp/sql-try-openapi.$$ >/dev/null && { PASS=$((PASS+1)); echo "ok    OpenAPI: operation is tagged experimental"; } || { FAIL=$((FAIL+1)); echo "FAIL  OpenAPI tag"; }
  jq -e '.components.securitySchemes.basic_auth.scheme == "basic"' /tmp/sql-try-openapi.$$ >/dev/null && { PASS=$((PASS+1)); echo "ok    OpenAPI: HTTP Basic security scheme declared"; } || { FAIL=$((FAIL+1)); echo "FAIL  OpenAPI security scheme"; }
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
