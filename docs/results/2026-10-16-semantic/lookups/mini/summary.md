# Ceiling test: mini

**Best sustained: 684 requests/s** at 512 requests in flight (p95 732 ms, error rate 0.00%).

Peak throughput 721 requests/s at 1536 in flight (p95 1812 ms).

The ramp ended without a stop condition (the last level was reached).

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 256 | 636 | 90.9 | 410.6 | 698.0 | 0 | 0.00% | 0 | 0.31 |  |
| 512 | 684 | 175.9 | 732.2 | 1069.8 | 0 | 0.00% | 0 | 0.37 |  |
| 768 | 696 | 211.9 | 1513.3 | 2102.7 | 0 | 0.00% | 0 | 0.41 |  |
| 1024 | 702 | 241.8 | 1822.9 | 2798.9 | 0 | 0.00% | 0 | 0.45 |  |
| 1536 | 721 | 543.6 | 1812.3 | 2306.2 | 0 | 0.00% | 0 | 0.51 |  |
| 2048 | 714 | 797.1 | 2838.0 | 3686.2 | 0 | 0.00% | 0 | 0.58 |  |
| 3072 | 693 | 1348.6 | 3698.1 | 4287.4 | 6 | 0.03% | 0 | 0.71 |  |
