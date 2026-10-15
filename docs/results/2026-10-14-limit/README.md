# Rate-limit probe, 14 October 2026

`perf_tests/limit_probe.py` run flat out for 60 seconds from two machines at the same time (the Studio and the laptop, each on its own address), against staging configured at 6,000 a minute with a burst of 600 per address. Analysis: [`docs/performance-report.md`](../../performance-report.md), section 5b.

- `studio/` and `laptop/`: `summary.md` and `per_second.json` (let through, limited and failed per second) of each machine.
- The Mac mini ran the probe too, but its DNS was wrong at the time: all 96 requests failed, so it is not included. Its trusted-origin check failed the same way.
