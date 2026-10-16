# Ceiling test: mini

**Best sustained: 105 requests/s** at 48 requests in flight (p95 421 ms, error rate 0.00%).

Peak throughput 114 requests/s at 384 in flight (p95 3471 ms).

Stopped: p95 5846 ms is above 5000 ms

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 48 | 105 | 111.1 | 421.1 | 618.3 | 0 | 0.00% | 0 | 0.08 |  |
| 96 | 112 | 156.7 | 1112.4 | 2194.2 | 0 | 0.00% | 0 | 0.1 |  |
| 192 | 111 | 235.5 | 2292.8 | 5141.2 | 0 | 0.00% | 0 | 0.11 |  |
| 384 | 114 | 744.4 | 3470.6 | 5089.4 | 0 | 0.00% | 0 | 0.14 |  |
| 768 | 111 | 1917.4 | 5846.3 | 7482.6 | 0 | 0.00% | 0 | 0.19 |  |
