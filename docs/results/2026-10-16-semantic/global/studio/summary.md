# Ceiling test: studio

**No step stayed within p95 of 1 s and an error rate of 1%.**

Peak throughput 96 requests/s at 192 in flight (p95 1930 ms).

The ramp ended without a stop condition (the last level was reached).

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 192 | 96 | 323.8 | 1930.0 | 2369.2 | 0 | 0.00% | 0 | 0.09 |  |
| 384 | 95 | 1152.1 | 3190.1 | 3581.1 | 0 | 0.00% | 0 | 0.13 |  |
| 768 | 95 | 2688.3 | 4993.0 | 5661.3 | 0 | 0.00% | 0 | 0.21 |  |
