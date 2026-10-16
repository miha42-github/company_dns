# Ceiling test: laptop

**No step stayed within p95 of 1 s and an error rate of 1%.**

Peak throughput 94 requests/s at 768 in flight (p95 4999 ms).

The ramp ended without a stop condition (the last level was reached).

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 192 | 94 | 354.8 | 1944.6 | 2432.0 | 0 | 0.00% | 0 | 0.12 |  |
| 384 | 94 | 1193.7 | 3201.4 | 3534.7 | 0 | 0.00% | 0 | 0.17 |  |
| 768 | 94 | 2757.5 | 4999.4 | 5793.8 | 0 | 0.00% | 0 | 0.25 |  |
