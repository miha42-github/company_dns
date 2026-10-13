# Soak test: PASS

Target https://company-dns-staging.mediumroast.io from `studio-lan`, started 2026-10-13T15:53:34Z; mix `lookups`; 120 windows of 60.0 s.

| | |
|---|---|
| requests | 431153 |
| errors | 0 (0.00%) |
| rate limited (`429`) | 0 |
| windows that missed the bar | 0 of 120 (error rate above 1.00%, p95 above 2000 ms, or a wrong canary) |
| canary answers correct | 600 of 600 |

## By step

| step | concurrency | windows | requests/s (median) | p50 ms | p95 ms (median) | worst p95 ms | errors | 429s |
|---|---|---|---|---|---|---|---|---|
| step 1/1 | 4 | 5 | 57.4 | 8.7 | 95.9 | 98.9 | 0 | 0 |
| hold | 16 | 115 | 60.0 | 10.0 | 96.2 | 100.4 | 0 | 0 |

## Drift while holding

First quarter of the hold: median p95 95.2 ms, 60.0 requests/s. Last quarter: median p95 96.4 ms, 60.0 requests/s. A steady climb in p95, or a fall in requests/s, at the same load is what a slow leak looks like.

Files: windows.csv, windows.jsonl, canaries.jsonl, meta.json (Python 3.14.8, macOS-26.5.1-arm64-arm-64bit-Mach-O).
