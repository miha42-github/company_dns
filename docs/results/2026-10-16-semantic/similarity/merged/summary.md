# Ceiling test, 3 machines merged

**Best sustained: 801 requests/s** at 192 requests in flight (p95 759 ms, error rate 0.00%).

Peak throughput 815 requests/s at 768 in flight (p95 1746 ms).

The ramp ended without a stop condition (the last level was reached).

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 192 | 801 | 137.4 | 759.0 | 1010.3 | 0 | 0.00% | 0 | 0.52 |  |
| 384 | 807 | 409.4 | 1221.1 | 1447.4 | 0 | 0.00% | 0 | 0.66 |  |
| 768 | 815 | 949.3 | 1746.1 | 1997.7 | 0 | 0.00% | 0 | 0.88 |  |
