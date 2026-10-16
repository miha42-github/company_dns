# Ceiling test: laptop

**No step stayed within p95 of 1 s and an error rate of 1%.**

Peak throughput 70 requests/s at 768 in flight (p95 7260 ms).

Stopped: p95 7260 ms is above 5000 ms

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 192 | 69 | 309.1 | 2610.1 | 3165.3 | 0 | 0.00% | 0 | 0.09 |  |
| 384 | 69 | 1421.9 | 4777.8 | 5507.1 | 0 | 0.00% | 0 | 0.15 |  |
| 768 | 70 | 3647.7 | 7260.4 | 8387.2 | 0 | 0.00% | 0 | 0.24 |  |
