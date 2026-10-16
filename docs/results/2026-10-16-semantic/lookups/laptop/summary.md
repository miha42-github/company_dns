# Ceiling test: laptop

**Best sustained: 630 requests/s** at 512 requests in flight (p95 756 ms, error rate 0.00%).

Peak throughput 706 requests/s at 1536 in flight (p95 1818 ms).

The ramp ended without a stop condition (the last level was reached).

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 256 | 556 | 114.3 | 431.9 | 704.5 | 0 | 0.00% | 0 | 0.29 |  |
| 512 | 630 | 200.4 | 756.0 | 1098.5 | 0 | 0.00% | 0 | 0.38 |  |
| 768 | 649 | 243.3 | 1507.4 | 2127.8 | 0 | 0.00% | 0 | 0.46 |  |
| 1024 | 660 | 274.8 | 1839.1 | 2850.2 | 0 | 0.00% | 0 | 0.53 |  |
| 1536 | 706 | 572.6 | 1817.5 | 2282.8 | 0 | 0.00% | 0 | 0.65 |  |
| 2048 | 702 | 817.2 | 2857.0 | 3706.1 | 0 | 0.00% | 0 | 0.77 |  |
| 3072 | 688 | 1365.8 | 3689.2 | 4242.2 | 4 | 0.02% | 0 | 0.96 |  |
