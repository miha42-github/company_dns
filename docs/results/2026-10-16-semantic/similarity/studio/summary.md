# Ceiling test: studio

**Best sustained: 274 requests/s** at 192 requests in flight (p95 735 ms, error rate 0.00%).

Peak throughput 274 requests/s at 192 in flight (p95 735 ms).

The ramp ended without a stop condition (the last level was reached).

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 192 | 274 | 106.6 | 735.4 | 982.2 | 0 | 0.00% | 0 | 0.17 |  |
| 384 | 272 | 366.8 | 1202.7 | 1403.3 | 0 | 0.00% | 0 | 0.21 |  |
| 768 | 274 | 902.8 | 1726.4 | 1989.2 | 0 | 0.00% | 0 | 0.27 |  |
