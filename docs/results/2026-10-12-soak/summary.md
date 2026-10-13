# Soak test: PASS

Target https://company-dns-staging.mediumroast.io from `remote-tester`, started 2026-10-12T03:10:26Z; mix `lookups`; 1440 windows of 60.0 s.

| | |
|---|---|
| requests | 5181863 |
| errors | 0 (0.00%) |
| rate limited (`429`) | 0 |
| windows that missed the bar | 0 of 1440 (error rate above 1.00%, p95 above 2000 ms, or a wrong canary) |
| canary answers correct | 7200 of 7200 |

## By step

| step | concurrency | windows | requests/s (median) | p50 ms | p95 ms (median) | worst p95 ms | errors | 429s |
|---|---|---|---|---|---|---|---|---|
| step 1/4 | 4 | 10 | 56.3 | 26.5 | 115.5 | 117.2 | 0 | 0 |
| step 2/4 | 8 | 10 | 60.0 | 27.0 | 117.3 | 120.1 | 0 | 0 |
| step 3/4 | 16 | 10 | 60.0 | 28.8 | 116.9 | 118.6 | 0 | 0 |
| step 4/4 | 32 | 10 | 60.3 | 28.9 | 112.0 | 116.5 | 0 | 0 |
| hold | 16 | 1400 | 60.0 | 28.3 | 116.8 | 125.8 | 0 | 0 |

## Drift while holding

First quarter of the hold: median p95 116.2 ms, 60.0 requests/s. Last quarter: median p95 117.3 ms, 60.0 requests/s. A steady climb in p95, or a fall in requests/s, at the same load is what a slow leak looks like.

Files: windows.csv, windows.jsonl, canaries.jsonl, meta.json (Python 3.11.0, Linux-6.8.0-139-generic-x86_64-with-glibc2.39).
