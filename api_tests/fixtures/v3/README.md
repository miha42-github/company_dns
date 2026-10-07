# V3 fixtures

Real responses from the production V3 service (`https://company-dns.mediumroast.io`), captured on 2026-10-07 with a
self-identifying `User-Agent` (`company_dns-parity-capture/1.0`), one request at a time with a pause, as agreed for the
parity run (`docs/plans/v4-release-to-staging.md`, question Q1). They are the ground truth the V4 `/V3.0/` and `/V2.0/`
paths are compared with: file names say what was asked (`eu_class_2591` is `GET /V3.0/eu/sic/class/25.91`).

V3's no-match answers are an HTML 404 page, not JSON, so they are not stored; V4 answers a no-match with a JSON 404 envelope
(an intentional difference).

Re-capture only on purpose: these files are what V3 said then, and the tests treat them as fixed.
