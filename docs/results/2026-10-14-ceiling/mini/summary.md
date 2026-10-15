# Ceiling test: studio

**Best sustained: 679 requests/s** at 512 requests in flight (p95 802 ms, error rate 0.00%).

Peak throughput 724 requests/s at 1536 in flight (p95 1994 ms).

The ramp ended without a stop condition (the last level was reached).

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 256 | 620 | 90.6 | 435.5 | 671.1 | 0 | 0.00% | 0 | 0.31 |  |
| 512 | 679 | 150.0 | 801.5 | 1630.0 | 0 | 0.00% | 0 | 0.37 |  |
| 768 | 716 | 266.4 | 1098.7 | 1608.6 | 0 | 0.00% | 0 | 0.43 |  |
| 1024 | 706 | 314.7 | 1524.0 | 1941.2 | 0 | 0.00% | 0 | 0.45 |  |
| 1536 | 724 | 498.4 | 1994.3 | 2314.3 | 0 | 0.00% | 0 | 0.54 |  |
| 2048 | 723 | 781.0 | 2722.0 | 3637.8 | 0 | 0.00% | 0 | 0.56 |  |
| 3072 | 700 | 1286.2 | 3565.9 | 4328.4 | 0 | 0.00% | 0 | 0.68 |  |
