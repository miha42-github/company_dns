# Ceiling test: mini

**No step stayed within p95 of 1 s and an error rate of 1%.**

Peak throughput 97 requests/s at 768 in flight (p95 4957 ms).

The ramp ended without a stop condition (the last level was reached).

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 192 | 94 | 318.2 | 1987.3 | 2418.3 | 0 | 0.00% | 0 | 0.1 |  |
| 384 | 96 | 1162.1 | 3167.9 | 3547.2 | 0 | 0.00% | 0 | 0.13 |  |
| 768 | 97 | 2551.0 | 4956.9 | 5877.7 | 0 | 0.00% | 0 | 0.19 |  |
