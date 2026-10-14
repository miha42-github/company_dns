# Soak test: PASS

Target https://company-dns-staging.mediumroast.io from `studio-lan`, started 2026-10-14T01:57:39Z; mix `lookups`; 66 windows of 60.0 s.

| | |
|---|---|
| requests | 236830 |
| errors | 0 (0.00%) |
| rate limited (`429`) | 0 |
| windows that missed the bar | 0 of 66 (error rate above 1.00%, p95 above 2000 ms, or a wrong canary) |
| canary answers correct | 330 of 330 |

## By step

| step | concurrency | windows | requests/s (median) | p50 ms | p95 ms (median) | worst p95 ms | errors | 429s |
|---|---|---|---|---|---|---|---|---|
| step 1/1 | 4 | 5 | 57.4 | 8.4 | 91.5 | 93.9 | 0 | 0 |
| hold | 16 | 61 | 60.0 | 9.5 | 93.2 | 97.6 | 0 | 0 |

## Drift while holding

First quarter of the hold: median p95 93.9 ms, 60.0 requests/s. Last quarter: median p95 92.9 ms, 60.0 requests/s. A steady climb in p95, or a fall in requests/s, at the same load is what a slow leak looks like.

Files: windows.csv, windows.jsonl, canaries.jsonl, meta.json (Python 3.14.8, macOS-26.5.1-arm64-arm-64bit-Mach-O).
