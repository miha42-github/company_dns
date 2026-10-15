# Ceiling test, 3 machines merged

**Best sustained: 1931 requests/s** at 512 requests in flight (p95 876 ms, error rate 0.00%).

Peak throughput 2145 requests/s at 2048 in flight (p95 2722 ms).

The ramp ended without a stop condition (the last level was reached).

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 256 | 1756 | 126.2 | 470.6 | 693.2 | 0 | 0.00% | 0 | 0.8 |  |
| 512 | 1931 | 184.2 | 875.9 | 1682.3 | 0 | 0.00% | 0 | 1.02 |  |
| 768 | 2066 | 316.8 | 1140.1 | 1626.9 | 0 | 0.00% | 0 | 1.22 |  |
| 1024 | 2061 | 351.4 | 1550.9 | 1979.1 | 0 | 0.00% | 0 | 1.31 |  |
| 1536 | 2144 | 527.0 | 2039.1 | 2320.4 | 0 | 0.00% | 0 | 1.63 |  |
| 2048 | 2145 | 815.3 | 2722.0 | 3668.2 | 0 | 0.00% | 0 | 1.79 |  |
| 3072 | 2080 | 1332.7 | 3623.1 | 4346.6 | 0 | 0.00% | 0 | 2.22 |  |
