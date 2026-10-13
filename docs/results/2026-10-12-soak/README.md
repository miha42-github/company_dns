# 24-hour soak test, 12 to 13 October 2026

Results of `perf_tests/soak.py` run by a remote tester against the staging service (guide: [`docs/soak-test.md`](../../soak-test.md)); analysis in [`docs/performance-report.md`](../../performance-report.md).

- `summary.md`: the run's own summary (verdict PASS).
- `windows.csv`: one row per one-minute window (1,440 rows).
- `meta.json`: the run's settings and the tester's platform.
- Not committed because of size: `windows.jsonl` (the same rows as JSON) and `canaries.jsonl` (7,200 known-answer checks, all correct); they are kept by the maintainers.

The tester's label was replaced with `remote-tester` in these copies; nothing else was changed.
