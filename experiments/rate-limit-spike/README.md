# rate-limit-spike

Proves `docs/plans/v4-security-hardening.md` §4's design before it's
promoted into `v4/crates/server/`: tiered rate limiting keyed on
whether a request's `User-Agent` looks self-identifying (§3.1/§3.2),
a trusted-origin bypass for the local dev site and mediumroast.io
(§3.4), and a rolling shared-secret `User-Agent` bypass for
mediumroast.io specifically (§3.5) — against the real crate versions
this workspace uses (axum 0.8, `governor` 0.10.4, `tower_governor`
0.8.0, `sha2` 0.11.0, `hmac` 0.13.0, `chrono` 0.4.45), not just
crates.io's declared semver compatibility.

## What this proves

1. **`tower_governor` 0.8's `axum` feature actually builds and 429s**
   against this exact axum 0.8 / tower 0.5 combination (`src/main.rs`'s
   `/basic` route, `GovernorLayer::new(...)`, 2/sec burst 3). Live
   test: 6 requests fired back-to-back → `200 200 200 429 429 429`.
2. **The tiered design (§3.2) works and the two tiers are isolated per
   IP**, not sharing one bucket. `/ping`'s custom `tiered_rate_limit`
   middleware (`src/tiered_limit.rs`) checks one of two independent
   `governor::DefaultKeyedRateLimiter<IpAddr>` instances depending on
   `user_agent::classify()`'s verdict. Live tests, same client IP
   throughout:
   - Draconian tier (curl's own default `User-Agent: curl/8.7.1`,
     quota 5/min burst 1): first request already consumed by an
     earlier `curl -v` call in the same session, so the flood of 8
     that followed was 8/8 `429` — matches burst=1 exactly.
   - Normal tier (`User-Agent: rate-limit-spike-test/1.0
     (hi@example.com)`, quota 200/min burst 20), fired on the **same
     IP** right after the draconian bucket above was already
     exhausted: 25 requests fired back-to-back →
     `200` × 20, then `429` × 5 — proves the normal-tier bucket isn't
     affected by the draconian-tier bucket being empty; they're
     genuinely separate quotas per key, not one shared bucket
     re-classified per request.
   - 429 response (`curl -i`):
     ```
     HTTP/1.1 429 Too Many Requests
     content-type: application/json
     retry-after: 3

     {"code":429,"data":null,"dependencies":{"modules":{}},
      "message":"Rate limit exceeded. Set a self-identifying
      User-Agent header (e.g. \"YourApp/1.0 (contact@example.com)\")
      for a higher limit.","module":"rate_limit"}
     ```
     Confirms `NotUntil::wait_time_from(...)` (`governor::clock::Clock`
     trait, imported explicitly - not in scope by default) gives a
     real, non-zero `Retry-After` value, and the body can be shaped
     like V4's real `ApiEnvelope` (`v4/crates/server/src/envelope.rs`)
     without needing anything from `governor` beyond the wait duration.
3. **`user_agent::classify()`'s rules (§3.1) are stateless and unit-
   tested** — 7/7 passing (`src/user_agent.rs`'s `tests` module):
   missing/empty header, default-library prefixes (`curl/`,
   `python-requests/`, bare `Mozilla/5.0`, etc.), no `@`/`http` contact
   signal, and the two positive cases (email-shaped, URL-shaped). No
   test or code path stores a header value anywhere past the single
   request it came from.
4. **The trusted-origin bypass (§3.4) actually bypasses, and a
   lookalike host doesn't.** `src/trusted_origin.rs`'s `is_trusted()`
   is checked first in `tiered_rate_limit`, before either tier's
   quota. Unit tests: 6/6 passing (`localhost`/`127.0.0.1`/`[::1]` at
   arbitrary ports, `mediumroast.io` + subdomains, `Referer` fallback
   when `Origin` is absent, `Origin` taking priority over a conflicting
   `Referer`, and three lookalike-rejection cases —
   `mediumroast.io.evil.example`, `notmediumroast.io`, and
   `evil.example/?u=mediumroast.io` — that a naive substring check
   would have wrongly trusted). Live test, same client IP throughout:
   - Exhausted the draconian tier first (curl's own UA, burst 1): 5
     requests → `200 429 429 429 429`.
   - Immediately after, 10 more requests **on the same exhausted IP**,
     same curl UA, but with `Origin: http://localhost:5173` →
     `200` × 10 — the bypass works even though that IP's draconian
     bucket was already empty, proving it's checked *before* the
     tiering, not a third tier that still consumes a bucket.
   - Same again with `Origin: https://mediumroast.io` → `200` × 10.
   - Then `Origin: https://mediumroast.io.evil.example` → `429` — the
     lookalike host is correctly rejected and falls through to the
     still-exhausted draconian tier.
5. **The rolling shared-secret User-Agent bypass (§3.5) works with
   *zero* `Origin`/`Referer` header** — the server-to-server case §3.4
   alone can't cover — **and interoperates with an independent
   implementation**, not just its own Rust code checking itself.
   `src/secret_ua.rs`'s `is_trusted()` computes
   `HMAC-SHA256(secret, current-or-previous UTC date+hour salt)` and
   compares the `User-Agent` header against it with a hand-rolled
   constant-time comparison; company_dns holds the raw shared secret
   (`MEDIUMROAST_SHARED_SECRET` in `src/main.rs`, with a fallback to a
   fixed spike-only test secret when that env var is unset — never the
   shape of a real deploy, just a `cargo run` convenience) since
   computing a fresh HMAC every hour needs the key itself, unlike an
   earlier static-secret-hash draft this design replaced. Unit tests:
   8/8 passing (current-hour match, previous-hour boundary tolerance,
   two-hours-stale rejected, wrong secret rejected, no configured
   secret fails closed, missing/garbage header rejected, salt format).
   Live test, same client IP throughout, **no `Origin` header sent at
   all, token computed with `openssl dgst -sha256 -hmac`, a completely
   separate implementation from this spike's own Rust code**:
   - Exhausted the draconian tier first (curl's own UA): 5 requests →
     `200 429 429 429 429`.
   - 10 more requests on that same exhausted IP, still no `Origin`,
     `User-Agent` set to the `openssl`-computed current-hour token →
     `200` × 10 — confirms the construction is genuinely
     interoperable, not an artifact of one code path agreeing with
     itself.
   - A token computed for 2 hours ago, same secret → `429` (correctly
     rejected as stale, outside the one-hour-back tolerance window).

## Why `governor` directly, not `GovernorLayer`

`tower_governor::GovernorLayer` takes one fixed `GovernorConfig` per
layer instance — it has no per-request hook to pick a different quota
based on a header. `/basic` in this spike proves the crate itself
works; `/ping`'s hand-written `tiered_rate_limit` middleware
(`axum::middleware::from_fn_with_state`) is the actual promotable
design: it owns two `governor::RateLimiter::keyed(quota)` instances
directly and picks one per request. This resolves §3.2's open "(a)
router split vs (b) custom middleware" question in favor of (b) — it
turned out to be the less code, and there was no router-split
mechanism in `axum`/`tower_governor` that made (a) actually simpler
once written out.

## Answering §4's open questions

- **`PeerIpKeyExtractor` vs `SmartIpKeyExtractor` (§4.4, §6):** not
  resolved here — this spike uses raw `ConnectInfo<SocketAddr>`
  (`.into_make_service_with_connect_info::<SocketAddr>()`,
  `src/main.rs`), i.e. the `PeerIpKeyExtractor` equivalent. Still
  genuinely depends on whether the real V4 deployment sits behind a
  reverse proxy/load balancer (`docs/plans/onprem-k8s-migration.md`);
  if so, promotion should read `x-forwarded-for`/`x-real-ip` the way
  `tower_governor::key_extractor::SmartIpKeyExtractor` does (or use
  that extractor's logic directly), not the raw peer IP.
- **`GovernorError`/`NotUntil` shape (§4.3):** confirmed above —
  `RateLimiter::keyed(quota).check_key(&key)` returns
  `Result<_, NotUntil<_>>`; `NotUntil::wait_time_from(clock.now())`
  gives the `Duration` for `Retry-After`. Requires
  `use governor::clock::Clock;` in scope for `.now()` to resolve (not
  obvious from the type signature alone — cost a build iteration in
  this spike, worth remembering when promoting).
- **Exact quota numbers (§6):** kept as illustrative placeholders here
  (200/min burst 20 normal, 5/min burst 1 draconian) — proving the
  *mechanism* was this spike's job, not final sizing.

## What this spike does NOT prove / new findings for the plan doc

- **A real browser's default `User-Agent` classifies as draconian
  too** (`user_agent.rs`'s `browser_ua_without_contact_is_still_
  draconian` test) — it has neither an `@` nor an `http(s)://`
  substring. §3.1 already calls this a deliberate v1 choice ("this
  API's real callers are expected to be programmatic integrations, not
  browsers"), but it has one concrete consequence not previously
  flagged: **Swagger UI's "Try it out" button at `/docs`
  (`docs/plans/v4-openapi-docs.md`) sends the browser's own
  `User-Agent`, so exploring the API interactively through `/docs`
  would hit the draconian tier**, not the normal one. **Decided in the
  plan doc (§3.1a): `/docs`/`/redoc`/`/openapi.json` are mounted
  outside the rate-limit middleware entirely**, not routed through the
  gate at all — not spiked separately since it's the same mechanism as
  §3.4/§3.5's un-layered mounting, not new code to prove.
- **A hand-crafted UA that starts with a default-library prefix but
  appends a real contact string still classifies as draconian** — e.g.
  `curl/8.7.1 (hi@example.com)` (tested live above, via `/tiered`)
  trips the `is_default_library_string` prefix check before the
  contact-signal check ever runs, since `classify()` checks the
  library-prefix list first. This is arguably correct (the "curl/"
  prefix itself is still the un-customized default string shape, and a
  real caller would just set a UA that doesn't start with a known
  library's own default token), but it's a real edge case worth a
  one-line note in §3.1 rather than an unstated implementation detail.
- **No `retain_recent`/eviction wired up.** `governor`'s keyed limiters
  keep one entry per distinct key forever by default; `governor`'s own
  docs recommend periodic cleanup for long-running keyed limiters in
  production. Out of scope for a spike that runs for a few minutes,
  but the real implementation (§5 of the plan) needs either a periodic
  `retain_recent` sweep or an accepted note that memory grows with
  distinct-IP cardinality over the server's lifetime.

## Running it

```bash
cargo run --release   # prints the spike test secret and an `openssl` one-liner for today's token
# separate terminal:
curl -i http://127.0.0.1:4100/ping                                   # curl's own UA -> draconian tier
curl -i -H "User-Agent: myapp/1.0 (me@example.com)" http://127.0.0.1:4100/ping  # normal tier
curl -i -H "Origin: http://localhost:5173" http://127.0.0.1:4100/ping           # trusted-origin bypass
curl -i http://127.0.0.1:4100/basic                                  # tower_governor smoke test

# rolling secret-UA bypass, no Origin needed - compute the current hour's token:
SECRET="mr-io-spike-test-secret-do-not-use-in-prod"
TOKEN=$(printf '%s' "$(date -u +%Y-%m-%dT%HZ)" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')
curl -i -H "User-Agent: $TOKEN" http://127.0.0.1:4100/ping
```

```bash
cargo test    # 21/21: 7 user_agent::classify + 6 trusted_origin::is_trusted + 8 secret_ua::is_trusted
```
