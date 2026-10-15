# Rate-limit probe after the ingress fix, 15 October 2026

`perf_tests/limit_probe.py` run flat out for 60 seconds from three machines at the same time (the Studio, the Mac mini and the laptop, each on its own address) against staging configured at 6,000 a minute with a burst of 600 per address, after the ingress service was changed to `externalTrafficPolicy: Local`. Analysis: [`docs/performance-report.md`](../../performance-report.md), section 5c; before the fix: [`../2026-10-14-limit/`](../2026-10-14-limit/).

- `studio/`, `mini/`, `laptop/`: `summary.md` and `per_second.json` of each machine.
- `watch/watch.csv`: the pods every 5 seconds during the runs (the per-pod file is not committed).
