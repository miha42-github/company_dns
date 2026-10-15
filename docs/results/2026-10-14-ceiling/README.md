# Ceiling test, 14 October 2026

`perf_tests/ceiling.py` run from three machines at the same time against the 20-pod staging service (image `10142026-4446caf`) as a profile with no rate limit, with `pod_watch.py` on the cluster side for staging and for production. Analysis: [`docs/performance-report.md`](../../performance-report.md), section 5a.

- `merged/`: the three machines combined (`levels.csv`, `summary.md`) and the pods' side per step (`cluster.md`); `studio/`, `mini/`, `laptop/`: each machine's own levels.
- `watch-staging/watch.csv`, `watch-prod/watch.csv`: the pods every 5 seconds (the large per-pod files are not committed).
