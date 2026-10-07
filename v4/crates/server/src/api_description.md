Company firmographics and industry-classification (SIC) lookup service: V3.0-compatible endpoints under `/V3.0/` and `/V4.0/`, plus V4-only search, Industry Match and an experimental SQL endpoint.

## Access and rate limits

Every request is rate limited per caller, and how much you get depends on how you identify yourself:

| You send | You get |
|---|---|
| nothing, or a generic `User-Agent` (`curl/...`, `python-requests/...`) | the strictest limit |
| a self-identifying `User-Agent` with a contact, for example `YourApp/1.0 (contact@example.com)` | the standard limit |
| HTTP Basic Auth for a profile your operator issued | whatever that profile is granted: no limit or a quota of its own, and optionally SQL |

Over the limit you get `429` with a `Retry-After` header (seconds to wait). A wrong Basic credential is a `401`; it is never treated as anonymous. The `Origin` and `Referer` headers are not identity. `/health`, `/docs` and `/redoc` are not rate limited.

Details: [Security](https://github.com/miha42-github/company_dns/blob/main/v4/README.md#security) and [Profiles](https://github.com/miha42-github/company_dns/blob/main/v4/README.md#profiles-authenticated-access).

## Experimental

`POST /V4.0/sql` (group `experimental`) is **experimental**: it is off unless the operator enables it, needs a profile granted SQL access, and may change or be removed without notice. It appears here only on servers where it is enabled. See [Experimental: SQL endpoint](https://github.com/miha42-github/company_dns/blob/main/v4/README.md#experimental-sql-endpoint).
