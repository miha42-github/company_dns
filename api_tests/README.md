# API tests

Functional tests for the V4 API (and, through fixtures, its parity with V3), in the layers of `docs/plans/v4-release-to-staging.md`
step 3. Standard library only, so a laptop or a CI runner runs them unchanged. Performance tests stay in `perf_tests/`.

```sh
python3 api_tests/run.py                                   # everything, against a server on http://localhost:4000
python3 api_tests/run.py --layers L0,L1                    # just the fast layers
python3 api_tests/run.py --base-url https://staging-company-dns.mediumroast.io --profile ID --token TOKEN
python3 api_tests/run.py --network                         # also the tests that make the server call Wikipedia and SEC
python3 api_tests/run.py --report results/v4.json          # a JSON report stamped with the commit
python3 api_tests/compare.py before.json after.json        # what changed between two runs; exits 1 on a regression
python3 -m unittest discover -s api_tests -v               # the same, without the wrapper
```

A server that is not running makes the tests skip with the reason, not fail. On a local server the client sends an `Origin: http://localhost`
header, which the rate limiter trusts; against any other server use a profile (`--profile` and `--token`). L5 starts its own server (needs a built
`v4/target/{debug,release-lean,release-small,release}/company-dns-server`, or `V4_BINARY`) and is skipped without one.

| Layer | File | What it covers |
|---|---|---|
| L0 smoke | `test_smoke.py` | health, the spec, the documentation pages (and that `/redoc` loads nothing from a third party), one lookup per family, Industry Match |
| L1 contract | `test_contract.py`, `test_non_us_sic.py` | **every route in the live spec** (a table that fails if a route has no entry): a match is a 200 envelope, a no-match a documented 404, every error including the framework's own is the JSON envelope, 400s for bad input, and the spec documents what the server returns |
| L2 data readiness | `test_data_readiness.py` | each classification system loaded and complete, hierarchies, the embedding model, the EDGAR catalog spanning its quarters, merged firmographics finding EDGAR data |
| L3 parity with V3 | `test_non_us_sic.py`, `test_edgar_wikipedia_parity.py` | V4's `/V3.0/` and `/V2.0/` answers against V3's real responses (`fixtures/v3/`). Four known gaps are `expectedFailure` tests that document what is not V3-shaped yet |
| L4 V4-only functions | `test_v4_functions.py` | global keyword, semantic and hybrid search, the tokeniser check, Industry Match (match, chunks, map) |
| L5 limits and profiles | `test_limits_and_profiles.py`, `server.py` | access and profiles, the User-Agent ladder and profile rate limits, the SQL endpoint's read-only guard, row, time and memory caps, per-profile limits, throttling. Starts its own server with throwaway credentials and small limits; never run against someone else's server |

`fixtures/v3/` holds responses captured from production V3 on 2026-10-07 (see its README). `v4/scripts/sql-try.sh` stays as the developer's
local playground; its `check` battery and L5 cover the same behaviour.
