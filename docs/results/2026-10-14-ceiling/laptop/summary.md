# Ceiling test: studio

**Best sustained: 585 requests/s** at 512 requests in flight (p95 876 ms, error rate 0.00%).

Peak throughput 700 requests/s at 2048 in flight (p95 2720 ms).

The ramp ended without a stop condition (the last level was reached).

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 256 | 513 | 126.2 | 470.6 | 693.2 | 0 | 0.00% | 0 | 0.2 |  |
| 512 | 585 | 184.2 | 875.9 | 1682.3 | 0 | 0.00% | 0 | 0.29 |  |
| 768 | 644 | 316.8 | 1140.1 | 1626.9 | 0 | 0.00% | 0 | 0.37 |  |
| 1024 | 659 | 351.4 | 1550.9 | 1979.1 | 0 | 0.00% | 0 | 0.4 |  |
| 1536 | 687 | 527.0 | 2039.1 | 2303.4 | 0 | 0.00% | 0 | 0.54 |  |
| 2048 | 700 | 815.3 | 2720.2 | 3668.2 | 0 | 0.00% | 0 | 0.66 |  |
| 3072 | 674 | 1332.7 | 3623.1 | 4346.6 | 0 | 0.00% | 0 | 0.8 |  |
