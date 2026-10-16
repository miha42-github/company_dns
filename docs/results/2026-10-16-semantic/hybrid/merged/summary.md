# Ceiling test, 3 machines merged

**No step stayed within p95 of 1 s and an error rate of 1%.**

Peak throughput 207 requests/s at 768 in flight (p95 7327 ms).

Stopped: p95 7327 ms is above 5000 ms

3 machine(s). Latencies of a merged run are the worst machine's (an upper bound), not recomputed over all requests.

| in flight | requests/s | p50 ms | p95 ms | p99 ms | errors | error rate | 429s | generator cores | |
|---|---|---|---|---|---|---|---|---|---|
| 192 | 206 | 318.1 | 2610.1 | 3165.3 | 0 | 0.00% | 0 | 0.26 |  |
| 384 | 206 | 1666.8 | 4802.3 | 5507.1 | 0 | 0.00% | 0 | 0.41 |  |
| 768 | 207 | 3763.2 | 7327.0 | 8554.7 | 0 | 0.00% | 0 | 0.58 |  |
