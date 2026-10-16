# Ceiling test: mini

**Best sustained: 274 requests/s** at 192 requests in flight (p95 740 ms, error rate 0.00%).

Peak throughput 274 requests/s at 192 in flight (p95 740 ms).

The ramp ended without a stop condition (the last level was reached).

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 192 | 274 | 110.5 | 739.9 | 988.1 | 0 | 0.00% | 0 | 0.16 |  |
| 384 | 274 | 364.0 | 1211.6 | 1403.3 | 0 | 0.00% | 0 | 0.21 |  |
| 768 | 273 | 895.5 | 1728.9 | 1985.5 | 0 | 0.00% | 0 | 0.26 |  |
