# Ceiling test: studio

**Best sustained: 106 requests/s** at 48 requests in flight (p95 401 ms, error rate 0.00%).

Peak throughput 114 requests/s at 384 in flight (p95 3408 ms).

Stopped: p95 6049 ms is above 5000 ms

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 48 | 106 | 110.5 | 401.4 | 608.3 | 0 | 0.00% | 0 | 0.08 |  |
| 96 | 107 | 163.5 | 1155.9 | 2255.9 | 0 | 0.00% | 0 | 0.08 |  |
| 192 | 110 | 253.4 | 2229.0 | 4222.4 | 0 | 0.00% | 0 | 0.1 |  |
| 384 | 114 | 773.0 | 3407.9 | 4974.3 | 0 | 0.00% | 0 | 0.14 |  |
| 768 | 110 | 1961.2 | 6048.8 | 7563.1 | 0 | 0.00% | 0 | 0.2 |  |
