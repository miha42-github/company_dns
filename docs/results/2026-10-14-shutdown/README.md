# Remaining changes on the graceful-shutdown build, 14 October 2026

Scenario 2b of [`docs/soak-scenarios.md`](../../soak-scenarios.md): 66 minutes of a steady 60 requests/s of lookups from a machine on the cluster's network while one pod, two pods, all pods were replaced and the deployment was scaled to 16 and back.
The image was tag `10142026-4446caf` (commit 4446caf, the merge of the graceful-shutdown change). Analysis: [`docs/performance-report.md`](../../performance-report.md), section 4.

- `summary.md`, `windows.csv`, `meta.json`: the soak's own output (66 one-minute windows).
- `events.txt`: the marks made while changing the deployment; `events.md`: what `soak_analyze.py events` made of them.
- `watch.csv`: the pods seen from the cluster side every 5 s (`perf_tests/pod_watch.py`).
- Not committed because of size: `pods.jsonl` (per-pod detail, 4.6 MB), `canaries.jsonl` and `windows.jsonl`; the maintainers keep them.
