Company firmographics and industry-classification (SIC) lookup service: V3.0-compatible endpoints under `/V3.0/` and `/V4.0/`, plus V4-only search, Industry Match and an experimental SQL endpoint.

## Access and rate limits

Every request is rate limited per caller, and how much you get depends on how you identify yourself:

| You send | You get |
|---|---|
| nothing, or a generic `User-Agent` (`curl/...`, `python-requests/...`) | the strictest limit |
| a self-identifying `User-Agent` with a contact, for example `YourApp/1.0 (contact@example.com)` | the standard limit |
| HTTP Basic Auth for a profile your operator issued | whatever that profile is granted: no limit or a quota of its own, and optionally SQL |

The limits are **per client IP address** (per profile for a profile with its own quota), counted across all of the service's replicas, as a number of requests per minute plus a short burst allowance. The operator sets the numbers, so they differ between deployments; the built-in defaults are **200 a minute (burst 20)** for the standard limit and **5 a minute (burst 1)** for the strictest. Ask your operator for the figures of the deployment you use. A burst larger than the allowance is answered with `429`s even when your average is low, so spread requests out and cache answers on your side.

Over the limit you get `429` with a `Retry-After` header (seconds to wait). A wrong Basic credential is a `401`; it is never treated as anonymous. The `Origin` and `Referer` headers are not identity. `/health`, `/docs` and `/redoc` are not rate limited.

Details: [Security](https://github.com/miha42-github/company_dns/blob/main/v4/README.md#security) and [Profiles](https://github.com/miha42-github/company_dns/blob/main/v4/README.md#profiles-authenticated-access).

## Response shape

Every answer is `{code, message, module, data, dependencies}`. Every answer also carries a top-level **`total`**: how many results `data` holds (a list gives its length, a dictionary that already counts its results (V3's `total`, EDGAR's `totalCompanies`, the SQL endpoint's `row_count`) that count, any other single record 1, no match or an error 0), so you can read the count without looking inside `data`. On the `/V3.0/`, `/V2.0/` and `/v2/` paths this is the one addition to V3's exact envelope (`data` itself is unchanged, and a client that reads only the fields V3 had is unaffected).

## Experimental

`POST /V4.0/sql` (group `experimental`) is **experimental**: it is off unless the operator enables it, needs a profile granted SQL access, and may change or be removed without notice. It appears here only on servers where it is enabled. See [Experimental: SQL endpoint](https://github.com/miha42-github/company_dns/blob/main/v4/README.md#experimental-sql-endpoint).
