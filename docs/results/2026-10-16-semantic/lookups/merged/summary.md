# Ceiling test, 3 machines merged

**Best sustained: 2002 requests/s** at 512 requests in flight (p95 756 ms, error rate 0.00%).

Peak throughput 2153 requests/s at 1536 in flight (p95 1818 ms).

The ramp ended without a stop condition (the last level was reached).

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 256 | 1843 | 114.3 | 431.9 | 704.5 | 0 | 0.00% | 0 | 0.93 |  |
| 512 | 2002 | 200.4 | 756.0 | 1098.5 | 0 | 0.00% | 0 | 1.15 |  |
| 768 | 2027 | 243.3 | 1557.6 | 2127.8 | 0 | 0.00% | 0 | 1.3 |  |
| 1024 | 2052 | 274.8 | 1840.3 | 2850.2 | 0 | 0.00% | 0 | 1.45 |  |
| 1536 | 2153 | 572.6 | 1817.5 | 2306.2 | 0 | 0.00% | 0 | 1.7 |  |
| 2048 | 2132 | 817.2 | 2857.0 | 3706.1 | 0 | 0.00% | 0 | 1.98 |  |
| 3072 | 2074 | 1365.8 | 3698.1 | 4287.4 | 14 | 0.02% | 0 | 2.38 |  |
