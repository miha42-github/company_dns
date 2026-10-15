# Plans index

One line per plan, with where it stands. "Done" means built and merged; "superseded" names what replaced it. Plans are working documents: they record decisions and the reasoning at the time.
The current work is at the top.

## Current (V4.0.0-pre)

| Plan | Status | What it is |
|---|---|---|
| [v4-production-cutover.md](v4-production-cutover.md) | plan, nothing executed | moving V4 to production (blue/green), V3 retired and kept as source |
| [v4-documentation-update.md](v4-documentation-update.md) | in progress | the documents for the pre-release: READMEs, data terms, guides, hygiene |
| [ingress-source-address-fix.md](ingress-source-address-fix.md) | to be done by the cluster administrator | the ingress hides callers' addresses, so the per-address limit is shared by everyone; the fix (`externalTrafficPolicy: Local`), its checks and rollback |
| [git-history-cleanup.md](git-history-cleanup.md) | not done (a runbook for the owner) | rewriting the Git history to remove internal names |
| [v4-sizing-test.md](v4-sizing-test.md) | done | replica shapes compared on the cluster; the decision (20 x 1000m) |
| [v4-staging-rollout.md](v4-staging-rollout.md) | done for staging | Kubernetes, manifests and scripting for the staging environment (its script parts are superseded by v4-staging-scripts) |
| [v4-staging-scripts.md](v4-staging-scripts.md) | done | the deploy and secret-sealing scripts and their conventions |
| [v4-release-to-staging.md](v4-release-to-staging.md) | largely done | the steps from "feature complete" to running on staging |
| [v4-results-report.md](v4-results-report.md) | to be extended | V3 versus V4, the clean-run comparison; the performance report will combine it with the cluster and soak results |
| [v4-deployment.md](v4-deployment.md) | partly done | image, secrets, environments and the cluster (the design behind the staging work) |
| [v4-initial-release-roadmap.md](v4-initial-release-roadmap.md) | tracking checklist | the path to an initial release |
| [onprem-k8s-migration.md](onprem-k8s-migration.md) | done | the move from Azure to the on-prem cluster; also the cluster's DNS and certificate notes |

## V4 features (built)

| Plan | Status |
|---|---|
| [v4-server-prototype.md](v4-server-prototype.md) | done: the server, US SIC and EDGAR with V3-parity endpoints |
| [v4-openapi-docs.md](v4-openapi-docs.md) | done: `/docs`, `/redoc`, `/openapi.json` and the `/V3.0/` aliases |
| [v4-security-hardening.md](v4-security-hardening.md) | done: rate limiting, the User-Agent gate, request hygiene |
| [v4-dynamic-log-level.md](v4-dynamic-log-level.md) | done: the log level changes without a restart |
| [v4-sql-endpoint.md](v4-sql-endpoint.md) | phase 1 built, experimental |
| [sic-global-search.md](sic-global-search.md), [sic-hybrid-search.md](sic-hybrid-search.md) | done: search across every classification system |
| [company-sic-match.md](company-sic-match.md) | draft: Industry Match, a first tab built, a simpler design proposed |
| [v4-server-pagination.md](v4-server-pagination.md) | deferred to V4.1.0 |
| [v4-data-gaps.md](v4-data-gaps.md) | the data package work (the US SIC file and its division narrative) |
| [company-dns-ux.md](company-dns-ux.md) | decisions made on the information architecture and framework |

## Background and history

| Plan | Status |
|---|---|
| [go-duckdb-rewrite.md](go-duckdb-rewrite.md), [edgar-backend.md](edgar-backend.md) | decided: Rust and DataFusion; EDGAR through `edgarkit` |
| [ic-similarity-search-poc.md](ic-similarity-search-poc.md) | done: the similarity-search proof of concept |
| [v4-amd64-build-and-compare.md](v4-amd64-build-and-compare.md) | done: the amd64 build and the V3 comparison |
| [v4-container-packaging.md](v4-container-packaging.md) | superseded by v4-deployment |
| [performance-improvements.md](performance-improvements.md) | done: the V3.3.0 performance pass |
