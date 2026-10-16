# Ceiling test: studio

**Best sustained: 687 requests/s** at 512 requests in flight (p95 725 ms, error rate 0.00%).

Peak throughput 726 requests/s at 1536 in flight (p95 1805 ms).

The ramp ended without a stop condition (the last level was reached).

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 256 | 650 | 89.5 | 399.0 | 680.4 | 0 | 0.00% | 0 | 0.33 |  |
| 512 | 687 | 176.8 | 725.1 | 1067.0 | 0 | 0.00% | 0 | 0.4 |  |
| 768 | 682 | 219.0 | 1557.6 | 2101.3 | 0 | 0.00% | 0 | 0.43 |  |
| 1024 | 691 | 249.7 | 1840.3 | 2826.7 | 0 | 0.00% | 0 | 0.47 |  |
| 1536 | 726 | 546.6 | 1805.4 | 2295.0 | 0 | 0.00% | 0 | 0.54 |  |
| 2048 | 716 | 803.1 | 2828.0 | 3669.0 | 0 | 0.00% | 0 | 0.63 |  |
| 3072 | 694 | 1351.4 | 3691.4 | 4257.7 | 4 | 0.02% | 0 | 0.71 |  |
