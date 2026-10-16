# Ceiling test: studio

**No step stayed within p95 of 1 s and an error rate of 1%.**

Peak throughput 70 requests/s at 768 in flight (p95 7254 ms).

Stopped: p95 7254 ms is above 5000 ms

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 192 | 69 | 311.5 | 2606.0 | 3068.7 | 0 | 0.00% | 0 | 0.08 |  |
| 384 | 68 | 1666.8 | 4666.4 | 5463.5 | 0 | 0.00% | 0 | 0.12 |  |
| 768 | 70 | 3602.4 | 7254.5 | 8303.0 | 0 | 0.00% | 0 | 0.16 |  |
