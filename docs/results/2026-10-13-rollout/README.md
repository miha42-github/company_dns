# Rollout under load, 13 October 2026

The first run of soak scenario 2 ([`docs/soak-scenarios.md`](../../soak-scenarios.md)): a steady 60 requests/s of lookups for two hours from a machine on the cluster's network while the deployment was changed between image tags `10132026-7a8c8ac` (new) and `10112026-85feab8` (previous).
Analysis: [`docs/performance-report.md`](../../performance-report.md), section 4.

- `summary.md`, `windows.csv`, `meta.json`: the soak's own output (120 one-minute windows).
- `events.txt`: the marks made while changing the deployment (the build node's clock); `events.md`: what `soak_analyze.py events` made of them.
- `watch.csv`: the pods seen from the cluster side every 15 s (`perf_tests/pod_watch.py`): pods, ready, terminating, restarts, memory, CPU used, throttling.
- Not committed because of size: `pods.jsonl` (per-pod detail, 2.7 MB) and `canaries.jsonl` (600 known-answer checks, all correct); the maintainers keep them.
