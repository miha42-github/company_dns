# Ceiling test: laptop

**Best sustained: 99 requests/s** at 48 requests in flight (p95 416 ms, error rate 0.00%).

Peak throughput 110 requests/s at 384 in flight (p95 3553 ms).

Stopped: p95 5902 ms is above 5000 ms

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 48 | 99 | 125.4 | 415.8 | 621.8 | 0 | 0.00% | 0 | 0.08 |  |
| 96 | 104 | 174.6 | 1159.5 | 2209.3 | 0 | 0.00% | 0 | 0.09 |  |
| 192 | 108 | 273.0 | 2246.5 | 4606.8 | 0 | 0.00% | 0 | 0.13 |  |
| 384 | 110 | 817.3 | 3552.7 | 5376.0 | 0 | 0.00% | 0 | 0.17 |  |
| 768 | 109 | 1962.1 | 5901.7 | 7565.2 | 0 | 0.00% | 0 | 0.26 |  |
