# Rate-limit probe: `mini`

290,429 requests in 60 s from one address: 6,579 let through, 283,850 limited (`429`), 0 errors.

| | observed | configured |
|---|---|---|
| burst: let through before the first `429` | 421 | 600.0 |
| sustained, let through per second (median after the first 10 s) | 100.0 | 100.0 |
| sustained, per minute | 6000 | 6000.0 |
| `Retry-After` (seconds) | 1 to 1 (median 1.0) | |

The effective sustained rate is **100%** of the configured one.

**The most one address can get through** is therefore about the sustained rate above, after the burst. A service shared by many addresses gives each its own allowance, up to what the pods can carry.
