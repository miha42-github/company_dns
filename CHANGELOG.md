# Changelog

All notable changes to this project are documented here.

The format is based on Keep a Changelog and this project adheres to Semantic Versioning.

## [V4.0.0-pre] (unreleased)
A rewrite of the service in Rust (`v4/`). It answers V3's URLs and, on its `/V3.0/` and `/V2.0/` paths, V3's answer shapes. V3 remains the live service until V4 is released. Every intentional difference is recorded in `docs/results/differences.json`; the guide for clients is [docs/migrating-to-v4.md](docs/migrating-to-v4.md).

### Added
- Semantic and hybrid industry-code search, and the Industry Match endpoint (`/V4.0/...`).
- An experimental SQL endpoint over the classification and EDGAR data (off unless enabled; profiles and limits in `v4/README.md`).
- Built-in API documentation (`/docs`, `/redoc`, `/openapi.json`) and web UI (`/ui/`); `/` redirects to the UI.
- A top-level `total` on every answer, including the `/V3.0/`, `/V2.0/` and `/v2/` paths: the count of results in `data`. Additive; `data` is unchanged.
- Profiles (HTTP Basic) with their own rate limits, and per-IP rate limits that are settings (`COMPANY_DNS_RATE_LIMIT_*`) and are shared fairly across replicas (`COMPANY_DNS_REPLICAS`).
- A live log level without a restart; a CORS allow-list for the credentialed routes (`COMPANY_DNS_CORS_ORIGINS`).
- Deploy and test tooling: `scripts/build-and-deploy-v4.sh`, `scripts/seal-secrets-v4.sh`, `perf_tests/` (load, cluster sizing, soak), `scripts/check_hygiene.py`.

### Changed
- A trusted `Origin` or `Referer` (mediumroast.io, its subdomains, localhost) no longer skips the rate limit: it gets the standard per-address tier, so the first-party web pages keep working and forging the header earns no more than a contact in the `User-Agent` does. A wrong credential from such an origin is now a `401`.
- Runtime: Rust (axum, DataFusion, ONNX Runtime) instead of Python; the image is self-contained and starts without a network. Faster than V3 on 26 of the 28 checks compared (`docs/results/`).
- Errors are JSON envelopes (V3 returned an HTML page for a 404); the `dependencies` block is V4's.
- Japan SIC answers come from the corrected full classification file; ticker lists hold symbols only; the merged firmographics shape is `{edgar, wikipedia, ...}` on `/V4.0/` paths.
- The EDGAR catalog covers the 10-K and 10-Q filers of the last eight completed quarters.

### Removed
- UK SIC and the `/v1/` Wikipedia backends are not served.

### Data
- Terms for each data source, and a pending permission for ISIC (which may be removed): see the README, "Data sources and terms".

## [3.3.0]
A performance pass across the whole service: the `companies` database full-table-scan fix, blocking I/O moved off the event loop, four replicas, comparison tooling (`perf_tests/baseline.py`, `compare.py`), HTTP connection reuse to SEC EDGAR, and a rewritten Wikipedia backend (`lib/wikipedia_v2.py`, median latency down about 80%). Details and measured numbers: `docs/plans/performance-improvements.md` and the README's history.

## [3.2.0]
The V3.2.0 release brought comprehensive security hardening and modernized the web framework:

1. Security middleware blocking 70+ known attack patterns including WordPress probes, PHP exploits, SQL injection, and XSS attempts
2. IP-based rate limiting (100-1000 req/min by endpoint type) using SlowAPI
3. Structured, severity-based logging with automatic request tracking and performance metrics
4. Complete replacement of Starlette with the FastAPI framework, bringing automatic interactive API docs (Swagger UI at `/docs`, ReDoc at `/redoc`) and Pydantic v2.10.0 request/response validation
5. Python 3.13 support, tested via Homebrew with the `.venv` convention

## [3.1.0]
The V3.1.0 release of `company_dns` brings significant UI improvements to enhance usability and functionality:

1. Renamed sections to "Industry Code Explorer" and "Query Explorer" for consistent terminology
2. Fixed cross-browser compatibility issues affecting Chrome and Safari
3. Improved search results display with horizontal detail layout
4. Added JSON viewer modal for search results with copy capability
5. More compact layout for the Query Explorer to maximize screen real estate
6. Enhanced pagination controls and scroll behavior
7. Added proper DOCTYPE declaration to ensure modern rendering mode

## [3.0.0]
The V3.0.0 release of `company_dns` is a significant update to the service. The primary changes are:

1. Shift from Flask to Starlette with Uvicorn
2. Automated monthly container builds from the main branch using GitHub Actions
3. Simplification of code structure with streamlined Docker and service control script
4. Vastly improved embedded help with a query console to test queries
