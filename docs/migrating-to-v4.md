# Moving from V3 to V4.0.0-pre

V4 answers V3's URLs, so most integrations need no change. This note says what is the same, what differs, and what to test. V3 is still the live service; V4 is a pre-release on a staging environment
([v4/README.md](../v4/README.md)). The authoritative list of intentional differences is [`docs/results/differences.json`](results/differences.json).

## The same

- **Paths.** Every V3 lookup is served at its original `/V3.0/` path, and the limited `/V2.0/` set (and `/v2/`), in **V3's exact response shape**: field names, messages, module strings, a dictionary keyed by code. 16 of the 19 captured V3
  production responses for EU NACE, ISIC and Japan SIC are identical; the rest differ only in data (below).
- **Envelope.** `{code, message, module, data, dependencies}`.
- **Access.** The public lookups need no credentials.

## Added (nothing to change unless you want it)

- **`/V4.0/...`** paths: a list of matches with their parents, instead of a dictionary keyed by code. New work should use them.
- **A top-level `total`** on every answer, including the V3 and V2 paths: the count of results in `data`. It is additive: `data` is unchanged. A client that compares whole responses to a recording should ignore it.
- Semantic and hybrid industry-code search; the Industry Match endpoint; an experimental SQL endpoint (off unless enabled); `/docs`, `/redoc`, `/openapi.json`; the web UI at `/ui/` (the bare `/` redirects to it).
- Profiles (HTTP Basic) for callers who need their own limits.

## Different

| Area | V3 | V4 | Why |
|---|---|---|---|
| Errors and no-match | an HTML page for a 404 | a JSON envelope with `total: 0` | machine-readable errors |
| Rate limiting | by endpoint type | per client address by how you identify yourself, plus profiles; the numbers are settings of the deployment | fair sharing with an identifying `User-Agent` ([using-the-api.md](using-the-api.md)) |
| Japan SIC | 13 entries for "food" (a partial extract) | 18, upper-case names, from the corrected full file | the corrected classification |
| EDGAR company list | a larger list | 10-K and 10-Q filers of the last eight completed quarters | a rolling window by design |
| Merged firmographics (`/V4.0/...`) | one flat 41-field record | `{edgar, wikipedia, ...}`; the `/V3.0/` path keeps V3's flat shape except the fields from ArcGIS geocoding (coordinates, map links), which V4 does not produce | no geocoding |
| Tickers | `["NASDAQ", "AAPL"]` (exchange mixed in) | `["AAPL"]`, the exchange in `exchanges` | a formatting defect fixed |
| Wikipedia messages | end with "(v2 backend)" | the same without the suffix, plus `performance.cache_hit` and `dependencies.data` | the suffix misnamed the implementation |
| `dependencies` block | V3's | V4's | |

## Not carried forward

- UK SIC (`/V3.0/uk/...`) and the legacy `/v1/` Wikipedia and merged variants (the `wptools` backend).
- Running your own copy: the image is `company_dns_v4`, it listens on port **4000** (V3: 8000), and it takes its settings from environment variables ([v4/README.md](../v4/README.md#settings-reference)).

## Data

The classification data and its terms are in the root README, "Data sources and terms". **ISIC may be removed** if the UN's permission is not given; the US SIC, EU NACE and Japan SIC data are not affected.

## What to test in your client

1. Run your existing calls against V4's `/V3.0/` paths and compare. Ignore the top-level `total`. Expect the data differences above (Japan SIC especially).
2. Check that you treat a `404` as "no match" and that your error handling reads JSON, not HTML.
3. Send an identifying `User-Agent`, honour `Retry-After` on `429`, and cache answers ([using-the-api.md](using-the-api.md)).
4. If you ran V3 yourself: update the image, the port and the settings; `COMPANY_DNS_REPLICAS` must equal the number of copies you run.
5. For new code, try the `/V4.0/` shape.

The comparison tooling used for the project's own checks is in [`api_tests/`](../api_tests/) and [`perf_tests/`](../perf_tests/).
