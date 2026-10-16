# Ceiling test, 3 machines merged

**Best sustained: 310 requests/s** at 48 requests in flight (p95 421 ms, error rate 0.00%).

Peak throughput 338 requests/s at 384 in flight (p95 3553 ms).

Stopped: p95 6049 ms is above 5000 ms

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 48 | 310 | 125.4 | 421.1 | 621.8 | 0 | 0.00% | 0 | 0.24 |  |
| 96 | 324 | 174.6 | 1159.5 | 2255.9 | 0 | 0.00% | 0 | 0.27 |  |
| 192 | 328 | 273.0 | 2292.8 | 5141.2 | 0 | 0.00% | 0 | 0.34 |  |
| 384 | 338 | 817.3 | 3552.7 | 5376.0 | 0 | 0.00% | 0 | 0.45 |  |
| 768 | 330 | 1962.1 | 6048.8 | 7565.2 | 0 | 0.00% | 0 | 0.65 |  |
