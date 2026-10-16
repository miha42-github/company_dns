# Ceiling test: mini

**No step stayed within p95 of 1 s and an error rate of 1%.**

Peak throughput 70 requests/s at 384 in flight (p95 4802 ms).

Stopped: p95 7327 ms is above 5000 ms

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 192 | 68 | 318.1 | 2571.6 | 3164.3 | 0 | 0.00% | 0 | 0.09 |  |
| 384 | 70 | 1404.6 | 4802.3 | 5430.0 | 0 | 0.00% | 0 | 0.14 |  |
| 768 | 68 | 3763.2 | 7327.0 | 8554.7 | 0 | 0.00% | 0 | 0.18 |  |
