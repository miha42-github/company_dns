# Ceiling test: studio

**Best sustained: 666 requests/s** at 512 requests in flight (p95 817 ms, error rate 0.00%).

Peak throughput 733 requests/s at 1536 in flight (p95 1983 ms).

The ramp ended without a stop condition (the last level was reached).

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 256 | 623 | 88.9 | 433.7 | 672.4 | 0 | 0.00% | 0 | 0.29 |  |
| 512 | 666 | 154.7 | 817.3 | 1645.7 | 0 | 0.00% | 0 | 0.36 |  |
| 768 | 706 | 271.2 | 1101.8 | 1604.5 | 0 | 0.00% | 0 | 0.42 |  |
| 1024 | 696 | 322.4 | 1519.8 | 1960.2 | 0 | 0.00% | 0 | 0.46 |  |
| 1536 | 733 | 492.2 | 1982.8 | 2320.4 | 0 | 0.00% | 0 | 0.55 |  |
| 2048 | 722 | 780.9 | 2717.6 | 3645.6 | 0 | 0.00% | 0 | 0.57 |  |
| 3072 | 707 | 1257.8 | 3523.6 | 4242.4 | 0 | 0.00% | 0 | 0.74 |  |
