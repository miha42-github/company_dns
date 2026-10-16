# Ceiling test, 3 machines merged

**No step stayed within p95 of 1 s and an error rate of 1%.**

Peak throughput 286 requests/s at 768 in flight (p95 4999 ms).

The ramp ended without a stop condition (the last level was reached).

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 192 | 284 | 354.8 | 1987.3 | 2432.0 | 0 | 0.00% | 0 | 0.31 |  |
| 384 | 284 | 1193.7 | 3201.4 | 3581.1 | 0 | 0.00% | 0 | 0.43 |  |
| 768 | 286 | 2757.5 | 4999.4 | 5877.7 | 0 | 0.00% | 0 | 0.65 |  |
