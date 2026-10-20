# Soak test: PASS

Target https://company-dns.mediumroast.io from `soak-48`, started 2026-10-17T23:37:22Z; mix `lookups`; 2880 windows of 60.0 s.

| | |
|---|---|
| requests | 10365156 |
| errors | 0 (0.00%) |
| rate limited (`429`) | 0 |
| windows that missed the bar | 0 of 2880 (error rate above 1.00%, p95 above 2000 ms, or a wrong canary) |
| canary answers correct | 14400 of 14400 |

## By step

| step | concurrency | windows | requests/s (median) | p50 ms | p95 ms (median) | worst p95 ms | errors | 429s |
|---|---|---|---|---|---|---|---|---|
| step 1/4 | 4 | 10 | 56.5 | 25.8 | 113.8 | 114.7 | 0 | 0 |
| step 2/4 | 8 | 10 | 60.0 | 26.5 | 113.6 | 121.0 | 0 | 0 |
| step 3/4 | 16 | 10 | 60.0 | 28.2 | 111.0 | 116.6 | 0 | 0 |
| step 4/4 | 32 | 10 | 60.3 | 28.4 | 110.6 | 112.1 | 0 | 0 |
| hold | 16 | 2840 | 60.0 | 27.9 | 113.9 | 331.8 | 0 | 0 |

## Drift while holding

First quarter of the hold: median p95 113.2 ms, 60.0 requests/s. Last quarter: median p95 114.3 ms, 60.0 requests/s. A steady climb in p95, or a fall in requests/s, at the same load is what a slow leak looks like.

Files: windows.csv, windows.jsonl, canaries.jsonl, meta.json (Python 3.11.0, Linux-6.8.0-139-generic-x86_64-with-glibc2.39).
