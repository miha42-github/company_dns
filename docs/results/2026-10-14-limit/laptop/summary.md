# Rate-limit probe: `laptop`

123,241 requests in 60 s from one address: 3,643 let through, 119,598 limited (`429`), 0 errors.

| | observed | configured |
|---|---|---|
| burst: let through before the first `429` | 518 | 600.0 |
| sustained, let through per second (median after the first 10 s) | 60.5 | 100.0 |
| sustained, per minute | 3630 | 6000.0 |
| `Retry-After` (seconds) | 1 to 1 (median 1.0) | |

The effective sustained rate is **60%** of the configured one. Each pod holds its share separately, so uneven spreading of requests across the pods lowers it.

**The most one address can get through** is therefore about the sustained rate above, after the burst. A service shared by many addresses gives each its own allowance, up to what the pods can carry.
