# Semantic-search throughput and the lookups ceiling, 16 October 2026

`perf_tests/ceiling.py` run from three machines at the same time (the Studio, the Mac mini and the laptop) against the 20-pod staging service, as the `staging-test` profile (no rate limit), five runs one after another, with `pod_watch.py` on the cluster side for staging and for production. Analysis: [`docs/performance-report.md`](../../performance-report.md), section 5d; the protocol is scenario 6 in [`docs/soak-scenarios.md`](../../soak-scenarios.md). Pictures: [`../2026-10-16/`](../2026-10-16/).

- `head/`: the three semantic routes together (mix `semantic`, 4:3:3), 48 to 1,536 in flight; it stopped at 768 because p95 passed 5 s.
- `similarity/`, `global/`, `hybrid/`: one route each (US similarity, global similarity, hybrid), 192, 384 and 768 in flight.
- `lookups/`: the lookups ceiling, 256 to 3,072 in flight, through the single Traefik pod.
- In each: `merged/` (the three machines combined: `levels.csv`, `summary.md`, and `cluster.md`, the pods' side per step) and `studio/`, `mini/`, `laptop/` (each machine's own `levels.csv`, `meta.json`, `summary.md`).
- `watch-staging/watch.csv`, `watch-prod/watch.csv`: the pods every 5 seconds (the large per-pod files are not committed). Production was read-only and stayed at 4 pods ready throughout.
