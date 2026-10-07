# API tests

Functional tests for the V3 and V4 APIs, in the layers described in `docs/plans/v4-release-to-staging.md` (step 3). Standard library
only, so a laptop or a CI runner runs them unchanged. This is the first layer of the suite; the performance tests stay in `perf_tests/`.

```sh
python3 api_tests/run.py                                   # a server on http://localhost:4000
python3 api_tests/run.py --base-url https://staging-company-dns.mediumroast.io --profile ID --token TOKEN
python3 api_tests/run.py --network                         # also the tests that make the server call Wikipedia and SEC
python3 -m unittest discover -s api_tests -v               # the same, without the wrapper
```

A server that is not running makes the tests skip with the reason, not fail. On a local server the client sends an `Origin: http://localhost`
header, which the rate limiter trusts; against any other server use a profile (`--profile` and `--token`).

| File | What it covers |
|---|---|
| `test_non_us_sic.py` | The 15 per-system EU NACE, ISIC and Japan lookups in both shapes (L1 contract), their parity with V3's real answers (L3), the V3-shaped US aliases, the V2.0 aliases against their `/V3.0/` twins, and that the spec lists all of it |
| `fixtures/v3/` | Responses captured from production V3 on 2026-10-07: the ground truth for parity (see its README) |
| `common.py`, `run.py` | The HTTP helper, the fixtures loader and the runner |

Still to come in this suite: L0 smoke and L1 contract for every route, L2 data readiness, L4 V4-only functions (search, Industry Match, SQL and
profiles), L5 limits and abuse; the SQL battery in `v4/scripts/sql-try.sh` moves here.
