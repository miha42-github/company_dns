# Rate-limit probe: `studio` (run at the same time as the laptop's; see docs/performance-report.md, section 5b)

300,258 requests in 60 s from one address: 9,518 let through, 290,740 limited (`429`), 0 errors.

| | observed | configured |
|---|---|---|
| burst: let through before the first `429` | 707 | 600.0 |
| sustained, let through per second (median after the first 10 s) | 139.0 | 100.0 |
| sustained, per minute | 8340 | 6000.0 |
| `Retry-After` (seconds) | 1 to 1 (median 1.0) | |

The effective sustained rate is **139%** of the configured one.

**The most one address can get through** is therefore about the sustained rate above, after the burst. A service shared by many addresses gives each its own allowance, up to what the pods can carry.
