# V4 security hardening: rate limiting, inbound User-Agent gate, request hygiene

Status: **Built (2026-09-29) — promoted into `v4/crates/server/`, live-
verified against the real server, not just the spike.** New modules
`user_agent.rs`, `trusted_origin.rs`, `secret_ua.rs`, `rate_limit.rs`
(ported from `experiments/rate-limit-spike/` with two real production
adjustments — see below); `envelope.rs` gained `too_many_requests()`;
`main.rs` splits the router into a rate-limited `data_router` and an
unlayered `health_router` (`OpenApiRouter::merge` after `.layer(...)`,
matching the exact "layer wraps what's already there" ordering §3.1a
described), added `TimeoutLayer`/`RequestBodyLimitLayer`/`TraceLayer`,
a `.fallback(...)` handler, and switched to
`into_make_service_with_connect_info::<SocketAddr>()`. Full workspace
`cargo build`/`cargo test` clean (21/21 new tests passing, zero
regressions elsewhere), `cargo clippy` clean on the new code. Two real
findings from reading `k8s/prod/*.yaml` before implementing (asked for
up front, not guessed): (1) **the deployment already runs 4 replicas**
(`deployment.yaml`'s `replicas: 4`) behind a `ClusterIP` Service, so
`governor`'s per-pod in-memory quota isn't a future hypothetical — the
§3.2 quotas below are the *fleet-wide* target, divided by 4 for the
actual per-pod `Quota` (`rate_limit.rs`'s `REPLICA_COUNT`/`per_pod`);
(2) **`/health` needed the same exemption as `/docs`** (§3.1a) since it
wasn't originally covered — `k8s/prod/deployment.yaml`'s liveness/
readiness probes hit it every 10s per pod, and would have been
draconian-tiered and 429'd, which would make Kubernetes think a
healthy pod is failing and kill it. Also confirmed via the same
manifests that this deployment sits behind Traefik
(`k8s/prod/ingress.yaml`) as its sole external edge with a
`ClusterIP`-only Service, settling §6's `PeerIpKeyExtractor` vs.
`SmartIpKeyExtractor` question in favor of reading `X-Forwarded-For`
(rightmost entry — the trusted proxy's own append, not a
client-spoofable leading entry). Also fixed, unplanned but necessary:
the server was binding `127.0.0.1` only, unreachable from outside its
own pod's loopback in the confirmed K8s topology — switched to
`0.0.0.0`. Live-verified end to end against the real running server
with real feather data (not the spike's toy routes): `/health`/`/docs`
un-rate-limited under flood; a data route drops a curl-UA'd client into
the draconian tier (burst 1) and a well-formed-UA'd client into the
normal tier (burst 5, both post-÷4 numbers); a trusted `Origin` and an
independently-`openssl`-computed rolling secret token both bypass the
limiter entirely on an already-exhausted IP; `X-Forwarded-For` buckets
distinct claimed IPs independently and ignores a spoofed leading entry
in favor of the real (rightmost) one; an unmatched route returns the
new envelope-shaped 404. Prior spike-stage summary (kept for history):
`experiments/rate-limit-spike/` confirms:
`tower_governor` 0.8's `axum` feature builds and 429s against this
workspace's real axum 0.8/tower 0.5 versions; the tiered design (§3.2)
resolved in favor of a custom `governor`-backed middleware over
`GovernorLayer` (which only supports one fixed quota per instance, no
per-request tiering hook); the two tiers' buckets are genuinely
isolated per IP (verified live: exhausting the draconian-tier bucket
on an IP didn't touch that same IP's normal-tier bucket); `NotUntil::
wait_time_from(...)` gives a real `Retry-After` value; §3.1's
classifier is stateless and unit-tested (7/7). Two new findings from
the spike, not previously flagged: (1) Swagger UI's "Try it out" at
`/docs` sends a browser User-Agent, which has no `@`/`http` contact
signal and would hit the draconian tier — needs a decision before
promotion (exempt `/docs`/`/redoc`/`/openapi.json` from the gate, or
accept throttled interactive doc-browsing); (2) `governor`'s keyed
limiters need a periodic `retain_recent` sweep in a long-running
server, or memory grows with distinct-IP cardinality — not needed for
a short-lived spike, needed for the real implementation. Full writeup:
`experiments/rate-limit-spike/README.md`. **Decided (2026-09-28):**
`/docs`/`/redoc`/`/openapi.json` are exempt from the gate entirely
(§3.1a) — the gate protects the data endpoints, not documentation
browsing. **Also decided:** the local dev site and the production
mediumroast.io site get a trusted-origin bypass, not just the normal
tier (§3.4) — spiked and live-verified
(`experiments/rate-limit-spike/`'s `trusted_origin` module). **Also
decided (raised directly, refined once from an initial static-secret
draft to the rolling design below):** mediumroast.io additionally
proves trust via a `User-Agent` that rotates every hour — 
`HMAC-SHA256(shared_secret, current UTC date+hour)`, computed
independently by both sides from a secret they both hold (company_dns
in its own K8s Secret, mediumroast.io in its own Sealed Secret) —
additive to, not a replacement for, the origin check, and the only
signal that works for server-to-server calls with no `Origin`/
`Referer` at all. A captured token is only valid for about the two
hours it's checked against, unlike the flat static-secret draft it
replaced. Spiked and live-verified end to end
(`experiments/rate-limit-spike/`'s `secret_ua` module) — including
against a token computed by an independent `openssl` invocation, not
just the spike's own Rust code checking itself. See also
[`v4-deployment.md`](v4-deployment.md) for how
`MEDIUMROAST_SHARED_SECRET` actually gets deployed (runtime K8s Secret,
not baked into the image — that doc covers why).
Owner: michael.hay@mediumroast.io
Scope: bring `v4/crates/server/` up to, and in the rate-limiting case
*past*, V3's actual (not documented) security posture: per-client rate
limiting, a required inbound `User-Agent` — checked statelessly for
both presence and EDGAR-style self-identifying shape, no registry of
callers kept — with draconian limits for callers that fail the check
(mirrors the courtesy V4 already extends *outbound*
to EDGAR/Wikipedia — `crates/edgar/src/lib.rs:12`,
`crates/wikipedia/src/lib.rs:39` — applied instead to V4's own inbound
callers), and the handful of cheap `tower-http` hygiene layers (timeout,
body-size limit, trace, a JSON-shaped fallback for unmatched routes)
V4 doesn't have yet. Out of scope for this doc: CORS policy (currently
`CorsLayer::permissive()`, §7 explains why it's deliberately left alone
here), IP allow/deny-listing, WAF-style path/query blocking (V3's
`security_middleware.py` pattern list — §7).

---

## 0. Why this doc

Raised directly: *"I'm not sure that these made it into this new
version AND we also need to boost the basic security posture... require
a user agent setting -- similar to EDGAR -- and have fairly draconian
rate limits when not set."* The premise needed checking rather than
assuming — V3's rate limiting turned out to be **dead code**, not a bar
V4 already clears (§1.1). This doc is the audit plus the plan to fix
it.

## 1. Current state (audited 2026-09-28, file:line cited)

### 1.1 V3 (`company_dns.py`, `lib/*.py`)

**Rate limiting exists in the codebase and does nothing.**
- `lib/rate_limiter.py:14-19` — a `slowapi.Limiter` is constructed
  (`default_limits=["500/minute"]`, IP-keyed).
- `lib/rate_limiter.py:22-37` — `RATE_LIMITS`: per-category limits
  (docs 1000/min, sic 200/min, firmographics 100/min, edgar_detail
  50/min, search 150/min).
- `lib/rate_limiter.py:40-69` — `get_rate_limit_for_path(path)`, which
  maps a path to one of those limits. **Grep confirms this function is
  never called anywhere** — dead code.
- `company_dns.py:27,125,126` wires `app.state.limiter` and a
  `RateLimitExceeded` exception handler, but **no route carries an
  `@limiter.limit(...)` decorator, and `SlowAPIMiddleware` (imported at
  `lib/rate_limiter.py:9`) is never added via `app.add_middleware`**.
  Inspected `slowapi`'s own source (`slowapi/extension.py`):
  rate-limit checks only fire from one of those two integration points.
  Neither exists here, so `RateLimitExceeded` can never be raised — the
  500/minute default and all per-category limits are inert. `slowapi`
  is a `requirements.txt` dependency doing nothing at runtime.

**No inbound User-Agent check.** `lib/edgar.py:85,102-106` and
`lib/wikipedia_v2.py:103,109` set an *outbound* User-Agent for EDGAR/
Wikipedia calls (EDGAR's own fair-use courtesy). Nothing inspects the
inbound `User-Agent` header of requests arriving at company_dns itself.

**404 handling discards the useful message** (previously found, cited
here with exact lines): `company_dns.py:129-159`'s
`not_found_handler` passes `exc.detail` through for every status code
*except* 404 (lines 133-136 vs. 138-146) — for 404 specifically it
always serves a static `html/404.html`, discarding whatever
`HTTPException(status_code=404, detail=return_msg)` was raised (the
`return_msg` built at `company_dns.py:37-48`, e.g. V3's restored
corporate-suffix hint text). A second, independent 404 path exists in
`lib/security_middleware.py:150-175` for requests outside its
path-prefix whitelist.

**What V3 actually has that works:** `lib/security_middleware.py`
blocks ~40 known-malicious path substrings (`BLOCKED_PATTERNS:20-51`)
and suspicious query params (`BLOCKED_QUERY_PARAMS:54-67`) with a 403,
and enforces a path-prefix whitelist (`VALID_PREFIXES:70-79`). CORS is
`allow_origins=["*"]` + `allow_credentials=True`
(`company_dns.py:109-116` — spec-questionable but that's existing
behavior, not this doc's problem to fix). No CSP/HSTS/security headers,
no explicit body-size limit, no explicit timeout (bare
`uvicorn.run(..., host, port)`, `company_dns.py:605-611`). Client IP is
logged (`lib/logging_config.py:30-90`) but not scored or banned.

### 1.2 V4 (`v4/crates/server/src/main.rs`, current, pre-this-doc)

**No rate limiting of any kind.** `v4/Cargo.toml:40` enables only
`tower-http`'s `fs`/`cors` features; no rate-limit crate appears in
`v4/crates/server/Cargo.toml` or anywhere in `v4/crates/**/*.rs`
(grepped).

**No inbound User-Agent check.** Same shape as V3: outbound-only, set
at `main.rs:83-84` from `company_dns_edgar::USER_AGENT` /
`company_dns_wikipedia::USER_AGENT` (`crates/edgar/src/lib.rs:12`,
`crates/wikipedia/src/lib.rs:39`). Nothing inspects inbound
`User-Agent`.

**404 handling is actually *better* than V3 for matched routes, worse
for unmatched ones.** A resource-not-found within a matched route (no
SIC match, no EDGAR match, Wikipedia's restored hint text) already
returns a real `ApiEnvelope` JSON body with the specific message, via
`envelope.rs:57-62`'s `not_found()` — V3's bug (discarding `detail` for
404s) does **not** exist in V4; this was already fixed when the
Wikipedia hint was restored (`main.rs:729-739`). What V4 is missing:
**no `.fallback(...)` handler is registered** (grepped, zero matches)
— an unmatched path (typo'd URL, wrong method) falls through to Axum's
bare built-in 404 (empty body, no `ApiEnvelope` shape), inconsistent
with every other response this API returns.

**No other `tower-http` hygiene layers.** Only layer applied is
`CorsLayer::permissive()` (`main.rs:146`). No `TimeoutLayer`, no
`RequestBodyLimitLayer`, no `TraceLayer` — confirmed absent from both
the enabled Cargo features (`fs`, `cors` only) and `main.rs`. Relies
entirely on Axum/Hyper/Tokio defaults (`axum::serve(listener, app)`,
`main.rs:157`, no timeout/limit config).

### 1.3 Net assessment

This is not "V3 has protections V4 lacks" — it's "neither has working
rate limiting or an inbound User-Agent gate; V4 already fixed the 404
hint-discarding bug that V3 still has; both are missing basic
`tower-http` hygiene (timeout, body limit, a JSON fallback)." V4 gets
to leapfrog V3 here, not just match it.

## 2. Crate research (verified live against crates.io, 2026-09-28)

| Crate | Version | Role | Compatibility check |
|---|---|---|---|
| `tower_governor` | 0.8.0 | GCRA rate-limiting `tower::Layer`, built on `governor` | Optional `axum` feature requires `^0.8` — matches this workspace's axum 0.8 (upgraded in `v4-openapi-docs.md` §2). `tower ^0.5.1`, `http ^1.0.0` — both already satisfied by this workspace's existing `tower-http` 0.6 pin. Verified via `crates.io/api/v1/crates/tower_governor/0.8.0/dependencies`, not assumed. |
| `governor` | 0.10.4 | GCRA token-bucket algorithm `tower_governor` wraps | Pulled in transitively; no direct dependency needed unless the tiering design (§3.2) requires calling it directly. |
| `tower-http` (already a dependency) | 0.6.7 | `TimeoutLayer`, `RequestBodyLimitLayer`, `TraceLayer` | Features confirmed present in 0.6.7's feature list: `limit`, `timeout`, `trace` (not currently enabled — `v4/Cargo.toml:40` only has `fs`, `cors`). |

`tower_governor`'s own `PeerIpKeyExtractor` needs
`.into_make_service_with_connect_info::<SocketAddr>()` (not plain
`.into_make_service()`) to see the real peer IP; its
`SmartIpKeyExtractor` instead reads `x-forwarded-for` /
`x-real-ip` / `forwarded` first, falling back to peer IP — the better
default if this server ever sits behind a proxy/load balancer, worth
confirming against actual deployment topology before picking one
(§6, open question).

**Design gap `tower_governor` doesn't solve by itself:** its
`GovernorLayer` applies one fixed quota (burst + replenishment) to
every request matching a key — it has no built-in notion of "a
different quota depending on whether this request has a User-Agent
header." That tiering has to be built as a thin layer on top (§3.2).

## 3. Design

### 3.1 Required inbound User-Agent — stateless format check, not just presence

**Decision: presence *and* shape, both stateless.** A request must
send a non-empty `User-Agent` header that also looks like
self-identification, not just any non-empty string. The check is a
pure function of the header value alone — no registry of known
callers, no persisted history of who's been seen before, nothing
stored across requests. That's the distinction from EDGAR's own
convention worth keeping: EDGAR's fair-use ask is a *format*
("AppName contact@domain" — a human name plus a way to reach them),
not a *database* of pre-registered clients, and a format-only check is
what V4 can enforce with zero added state.

Concretely: reject (route into the draconian tier, §3.2) a
`User-Agent` that is missing, empty, or matches either of two cheap,
stateless signals:
- **Default library/tool strings.** The out-of-the-box User-Agent of
  common HTTP clients that nobody hand-sets on purpose — `curl/*`,
  `python-requests/*`, `Go-http-client/*`, `okhttp/*`, `axios/*`,
  `PostmanRuntime/*`, `Mozilla/5.0` with nothing else attached, etc.
  Prefix/substring match against a short fixed list (analogous in
  spirit to V3's `BLOCKED_PATTERNS` list, `lib/security_middleware.py:20-51`,
  but classifying rather than 403-blocking).
- **No contact signal.** No `@` (email-shaped) and no `http`/`https`
  substring (URL-shaped) anywhere in the header value. This is the
  actual EDGAR-style bar: *some* way to reach the operator of whatever
  is calling, not a specific registered identity.

Both checks run against the header string only, per-request, and
produce nothing durable — no allowlist, no first-seen timestamp, no
per-UA counters beyond the rate limiter's own short-lived quota window
(§3.2). A client that starts sending a well-formed `User-Agent`
tomorrow gets the normal tier tomorrow; nothing about today's requests
is remembered against it.

### 3.1a `/docs`, `/redoc`, `/openapi.json` are exempt from the gate

**Decided:** the introspection routes added in `v4-openapi-docs.md`
are mounted outside the rate-limit middleware entirely — not just
routed into a lenient tier. Rationale unchanged from the spike finding
that raised this (previous status line): the gate exists to protect
the firmographics/SIC data endpoints from unidentified scraping;
Swagger UI's "Try it out" sends a plain browser User-Agent with no
`@`/`http` contact signal, so leaving these three routes inside the
gate would throttle a human reading documentation, which was never the
target. Mechanically: apply the rate-limit middleware layer only to
the `OpenApiRouter`'s data routes, and `.merge(...)` the
`SwaggerUi`/`Redoc` routers in afterward, unlayered — the same
ordering `main.rs` already uses to add `CorsLayer` after those merges
(`main.rs:143-146`), just one step earlier in the chain.

### 3.2 Tiered rate limiting

Two `governor` quotas, chosen per-request by User-Agent presence,
*after* the trusted-origin/secret-UA bypass in §3.4/§3.5 has already
let a request through:

- **Normal tier** (User-Agent present): adopt V3's own never-enforced
  `RATE_LIMITS` numbers as the live baseline (`lib/rate_limiter.py:22-37`)
  — they were already sized per-category by whoever wrote them, just
  never wired up. A single global quota to start (V4's routes aren't
  categorized by cost the way V3's dead code implies) — sizing detail
  in the spike, §4.
- **Draconian tier** (User-Agent missing, empty, or failing the §3.1
  format check): an order of magnitude
  tighter — e.g. single-digit requests/minute — deliberately harsh
  enough that a real integration notices immediately and sets a
  User-Agent, while not being an outright hard block (matches "have
  fairly draconian rate limits when not set," not "reject when not
  set").

**Resolved by the spike (`experiments/rate-limit-spike/`, §4): option
(b).** Because `tower_governor::GovernorLayer` takes one fixed config
per instance, a custom `axum::middleware::from_fn_with_state` wrapping
two independent `governor::RateLimiter::keyed(quota)` instances (one
per tier) and picking which to check per request turned out to be less
code than fighting the layer's one-config-per-instance shape with a
router split, and was proven live: the two tiers' buckets are genuinely
isolated per IP (exhausting the draconian-tier bucket for an IP didn't
touch that same IP's normal-tier bucket).

429 responses use V4's existing `ApiEnvelope` shape (via `envelope.rs`)
for consistency with every other error path, and set `Retry-After` from
`NotUntil::wait_time_from(clock.now())` — confirmed working in the
spike (`governor::clock::Clock` must be explicitly imported for
`.now()` to resolve; not obvious from the type signature alone).

### 3.3 Request hygiene (`tower-http`, cheap, low-risk)

Enable `limit`, `timeout`, `trace` features in `v4/Cargo.toml:40`, add:
- `TimeoutLayer` — bound worst-case request time (pick a number
  generous enough for the slowest real endpoint — Wikipedia
  firmographics with a cold cache was ~870ms median in the last perf
  run, `docs/plans/v4-server-prototype.md` §7; a few seconds of margin
  is plenty).
- `RequestBodyLimitLayer` — this API is all GET with no request bodies
  today, but a small cap (e.g. a few KB) costs nothing and forecloses
  a class of abuse if that ever changes.
- `TraceLayer::new_for_http()` — request/response logging, the Rust
  analogue of V3's `lib/logging_config.py` request logger; useful for
  the same reason V3 wanted it (visibility into what's hitting the
  server), and useful for debugging the rate limiter itself once it's
  live.
- A `.fallback(...)` handler returning `envelope::not_found("router",
  "...")` for unmatched routes, closing the one real gap found in
  §1.2's 404 audit.

### 3.4 Trusted-origin bypass: local dev site + mediumroast.io

> **Note (2026-10-05):** `Origin`/`Referer` are client-set headers, so any
> caller that sends `Origin: https://mediumroast.io` is treated as trusted and
> skips the limiter on every data route. Acceptable for cheap lookups, but it
> is not proof of identity, which is why the SQL endpoint ignores these headers
> and requires a credential ([`v4-sql-endpoint.md`](v4-sql-endpoint.md) §5a).
> Whether to tighten this for the lookup routes is an open question for this
> document.

**Decided:** two first-party callers — the local development website
and the production mediumroast.io site — should not be rate-limited at
all, not merely placed in the normal tier. Both are browser-driven, so
they can't be identified by User-Agent (a browser's UA has no contact
signal, same reason `/docs` needed its own exemption, §3.1a) — they're
identified by the `Origin` header instead (falling back to `Referer`
when `Origin` is absent, which browsers omit on some same-origin
requests): a request whose `Origin`/`Referer` host is `localhost` /
`127.0.0.1` / `::1` (any port — local dev servers move around) or
`mediumroast.io` / any `*.mediumroast.io` subdomain skips the rate
limiter entirely, checked *before* §3.2's tiering (so it never
consumes either tier's quota). Matching happens once, per request,
against the header string alone — same stateless shape as §3.1's
User-Agent check, no registry of trusted callers beyond this short
fixed host list.

**Known weakness, addressed by §3.5 for mediumroast.io specifically:**
`Origin`/`Referer` are attacker-controlled headers —
`curl -H "Origin: https://mediumroast.io"` gets the bypass as easily as
the real site does. Accepted as-is for the local dev site (low stakes,
developer-only), but mediumroast.io is production and gets a second,
much stronger signal on top — §3.5.

Mechanically: a stateless `is_trusted_origin(origin_or_referer: &str)
-> bool` function (spiked as `trusted_origin.rs`, §4), checked as the
first thing in the rate-limit middleware, short-circuiting straight to
`next.run(request).await` on a match — `true` here is one of two ways
into the bypass, the other being §3.5's secret User-Agent.

### 3.5 Rolling shared-secret User-Agent for mediumroast.io (additive to §3.4's origin check)

> **Note (2026-10-05): superseded in plan.** The experimental SQL endpoint
> ([`v4-sql-endpoint.md`](v4-sql-endpoint.md) §5a) replaces this scheme with
> one profiles file (a section per profile: a token hash and per-feature grants
> such as rate-limit bypass and SQL), delivered as a mounted secret file, with
> HTTP Basic Auth as the credential. Only the *secret carried in the User-Agent*
> (the rolling HMAC below) is superseded: nothing on the mediumroast.io side was
> built against it, so there is no legacy path, and when the profiles module is
> built. **Removed from the code 2026-10-05:** `secret_ua.rs`,
> `MEDIUMROAST_SHARED_SECRET` and the `hmac` dependency are gone, with tests
> showing an HMAC-looking User-Agent is now an ordinary draconian-tier caller.
> **§3.1's
> self-identifying `User-Agent` requirement and §3.2's normal/draconian tiering
> stay**: they are the "identify yourself for a better experience" rung. The
> ladder is anonymous (draconian), self-identifying `User-Agent` (normal), then
> Basic-Auth profile (lower or no rate limit plus enhanced access such as SQL).
> Kept below as the record of what was decided and built first.

**Decided (raised directly, superseding an earlier static-secret-hash
draft):** mediumroast.io's calls to company_dns carry a second trust
signal beyond `Origin` — a `User-Agent` value that changes every hour,
derived from a shared secret both sides hold plus a time-based salt,
rather than a fixed token sent as-is. Trust becomes
`is_trusted_origin(...) OR is_trusted_secret_ua(...)` — **additive**, a
second independent path to the same bypass, not a replacement for the
origin check and not an AND with it. This matters for a case §3.4
alone can't cover: if mediumroast.io's *own backend* calls company_dns
server-to-server (not from the end user's browser), there is no
`Origin`/`Referer` header at all — only the secret UA proves trust in
that path.

**Mechanism: `HMAC-SHA256(shared_secret, salt)`, where `salt` is the
current UTC date+hour** (e.g. `"2026-09-29T14Z"`), hex-encoded and sent
as the entire `User-Agent` value. Both company_dns and mediumroast.io
hold the same shared secret — an agreed-upon string, mediumroast.io's
copy in its own Kubernetes Sealed Secret (injected via Dockerfile
`ARG`/`ENV` or `.env` into that service's container), company_dns's
copy in its own K8s Secret, sourced via an env var
(`MEDIUMROAST_SHARED_SECRET`) — and each independently computes the
salt from its own clock, no coordination needed beyond both using UTC.
company_dns recomputes the expected token for the current hour *and*
the previous hour (tolerates a request landing right at an hour
boundary where the two clocks briefly disagree) and compares with a
constant-time comparison. A match is trusted regardless of `Origin`; a
non-match falls through to §3.4's origin check and then §3.2's normal
tiering same as any other request — an unrecognized `User-Agent` is
not itself suspicious, it's just not this specific bypass. HMAC (not a
plain `secret + salt` concatenation before hashing) specifically
because it's the standard, well-analyzed construction for exactly this
job — combining a key and a message safely — rather than relying on
SHA-256's own collision/extension properties to make an ad hoc
concatenation behave correctly.

**Real tradeoff versus the static-secret-hash draft this replaces:**
company_dns now has to hold the *raw* shared secret, not just a
one-way hash of it — computing `HMAC(secret, salt)` for a fresh salt
every hour requires the secret itself; a stored hash of it can't be
un-hashed to derive the key. What's gained in exchange: a captured
`User-Agent` value — from a log, a proxy, browser history if this were
ever browser-exposed — is only valid for about the two hours it's
checked against, not forever. The static design had no such expiry
once someone came to possess the value; this one self-rotates hourly
with zero coordination or stored state beyond the one long-lived
shared secret both sides already need to keep safe.

Rotation: unlike the static-hash draft, rotating the shared secret now
requires updating it on **both** sides at effectively the same time
(mediumroast.io's Sealed Secret and company_dns's
`MEDIUMROAST_SHARED_SECRET`) — a coordinated deploy, not a
one-sided company_dns config update. Worth a short runbook note when
this is promoted (§5), not designed in this doc.

**How `MEDIUMROAST_SHARED_SECRET` actually reaches a deployed
company_dns instance is covered in
[`v4-deployment.md`](v4-deployment.md)**, not here —
that doc audits a proposal to inject it at image-build time via a
BuildKit/GitHub-Actions secret, and recommends against that
specifically for this secret (keeping it a runtime K8s Secret env var,
as designed above) while reserving the build-secret mechanism for
whatever genuine build-time secret needs company_dns's container image
turns out to have. This doc's design above (rolling HMAC, both sides
hold the raw secret, coordinated rotation) is unchanged by that
discussion — only *how the value gets configured* is covered there.

## 4. Research spike — **done** (`experiments/rate-limit-spike/`, 2026-09-28)

Small standalone spike, following this project's established pattern
of proving a design against the real crate before promoting it into
`v4/crates/server/`. Full writeup in the spike's own README; summary:

1. **Done.** Minimal Axum 0.8 app with `tower_governor::GovernorLayer`
   (`/basic` route, default-shaped config) — confirmed it builds and
   returns 429s under load against this workspace's exact dependency
   versions: 6 requests fired back-to-back → `200 200 200 429 429 429`
   against a 2/sec-burst-3 quota.
2. **Done.** Prototyped the tiering design from §3.2 — resolved in
   favor of (b), the custom middleware, per §3.2's update above.
   Verified live with real curl traffic (not just unit tests): curl's
   own default `User-Agent` hits the draconian tier and is throttled
   almost immediately (burst 1); a well-formed User-Agent on the same
   client IP, sent right after exhausting that IP's draconian bucket,
   still got 20 successful requests before its own 429s — proving the
   two tiers' quotas are properly isolated per key, not one bucket
   being reclassified per request.
3. **Done.** `NotUntil::wait_time_from(clock.now())`
   (`governor::clock::Clock` imported explicitly) gives the `Duration`
   for `Retry-After`; live-verified a real `retry-after: 3` header and
   an `ApiEnvelope`-shaped 429 JSON body (`experiments/rate-limit-
   spike/README.md`'s live-test transcript).
4. **Still open** — genuinely depends on real deployment topology
   (reverse proxy/load balancer in front or not), which this spike
   can't answer on its own. Carried to §6.
5. **Done.** Prototyped §3.4's `is_trusted_origin` bypass —
   `trusted_origin.rs`, unit-tested against `localhost`/`127.0.0.1`
   (any port), `mediumroast.io` and a subdomain, and confirmed rejected
   for a lookalike host (`mediumroast.io.evil.example`) that merely
   contains the trusted suffix as a substring — a naive
   `.contains("mediumroast.io")` check would have passed that; the
   real check parses the header as a URL and compares the *host*
   exactly or as a proper subdomain. Live-verified: a request carrying
   `Origin: http://localhost:5173` skips the rate limiter entirely even
   after both tiers' quotas for that IP were already exhausted.
6. **Done.** Prototyped §3.5's rolling shared-secret `User-Agent`
   bypass — `secret_ua.rs`: `HMAC-SHA256(secret, UTC date+hour salt)`,
   current-hour-or-previous-hour tolerance, hand-rolled constant-time
   comparison. Unit-tested (current-hour match, previous-hour boundary
   tolerance, two-hours-stale rejected, wrong secret rejected, no
   configured secret fails closed, missing/garbage header rejected).
   Live-verified two things at once: (1) the specific case §3.4 can't
   cover — with **no `Origin`/`Referer` header sent at all**, a request
   on an IP whose draconian-tier quota was already exhausted still got
   10/10 successes once it carried a correctly-computed token, and a
   2-hours-stale token stayed correctly blocked; (2) **interop** — the
   token was computed with a completely independent implementation
   (`openssl dgst -sha256 -hmac`, not the spike's own Rust code) and
   still matched the server's own computation exactly, confirming the
   construction is a real, standard, interoperable HMAC and not an
   artifact of one code path agreeing with itself.

**Two findings from the spike not anticipated by this doc**, both
carried to §6/§3.1: interactive "Try it out" calls from `/docs`'s
Swagger UI send a plain browser User-Agent, which fails the §3.1
contact-signal check and would land in the draconian tier; and
`governor`'s keyed limiters need a periodic `retain_recent` sweep in a
long-running server to bound memory by distinct-IP cardinality (not
needed for a spike that runs a few minutes).

## 5. Implementation steps — **done** (2026-09-29)

1. **Done.** `v4/Cargo.toml`: `tower-http` features `limit`, `timeout`,
   `trace` enabled; `tower_governor`, `governor`, `sha2`, `hmac` added
   (`chrono` already pinned, reused as planned).
2. **Done, with two real adjustments found by reading the actual K8s
   manifests before writing code** (both asked about up front, per
   plan): `v4/crates/server/src/main.rs` splits the router into a
   `data_router` (rate-limited: §3.2's tiering, §3.4's trusted-origin
   bypass, §3.5's rolling secret-UA bypass, all in
   `rate_limit.rs::tiered_rate_limit`) and a `health_router` (unlayered
   — `/health` needed the same exemption as `/docs`/`/redoc`/
   `/openapi.json`, §3.1a, not originally scoped for it); added
   `TraceLayer`, `TimeoutLayer` (408, not the deprecated
   `TimeoutLayer::new`), `RequestBodyLimitLayer` (64KB), and a
   `.fallback(...)` handler. `MEDIUMROAST_SHARED_SECRET` is read once
   at startup via `load_shared_secret()` and fails closed (logs a
   warning, leaves the bypass disabled) if unset or empty — no test-
   secret fallback, unlike the spike. Switched to
   `into_make_service_with_connect_info::<SocketAddr>()`. **Also
   switched the bind address from `127.0.0.1` to `0.0.0.0`** — not
   originally in this plan, but the confirmed K8s topology
   (`k8s/prod/deployment.yaml`'s probes, `k8s/prod/service.yaml`'s
   `ClusterIP`) meant the server was previously unreachable from
   outside its own pod's loopback; left unfixed, none of this work
   would have mattered in production.
3. **Done.** `envelope.rs::too_many_requests()` added, same shape as
   `ok()`/`not_found()`/`server_error()` plus a real `Retry-After`
   header set directly on the response.
4. **Skipped, as flagged optional.** `v4-openapi-docs.md`'s spec
   doesn't list the 429 response in `responses(...)` blocks — not
   required for spec validity, left for later polish if wanted.
5. **Done**, against the real running server with real feather data,
   not synthetic routes: draconian tier (curl's default UA, burst 1
   post-÷4) and normal tier (well-formed UA, burst 5 post-÷4) both
   confirmed with real 429s + `Retry-After` + envelope shape;
   `/health`/`/docs` confirmed un-rate-limited under a 10-request
   flood; trusted-`Origin` and an independently-`openssl`-computed
   rolling secret token both confirmed to bypass the limiter entirely
   on an IP whose quota was already exhausted; `X-Forwarded-For`
   confirmed to bucket distinct claimed IPs independently and to use
   the rightmost entry (ignoring a spoofed leading one); unmatched
   route confirmed returning the new envelope-shaped 404. Full
   transcript in this doc's status line above.
6. **Done.** `v4/README.md` gained a "## Security" section (placed
   after "## API docs", matching its style) and the `MEDIUMROAST_SHARED_SECRET`
   env var was added to the existing "## Running it" env-var list.
   mediumroast.io's own integration-code change (computing the rolling
   token as its outbound `User-Agent`) is documented there as *their*
   side of the work, not something this repo's change can do for them.

## 6. Open questions

- **Resolved (2026-09-29), asked directly before implementing.** Exact
  quota numbers: fleet-wide aggregate targets are the spike's
  illustrative numbers (200/min normal, 5/min draconian), confirmed as
  the real starting values rather than guessed. **Also resolved in the
  same conversation**: with `k8s/prod/deployment.yaml`'s `replicas: 4`
  confirmed as the real, current topology (not a future hypothetical —
  see status line above), the per-pod `governor::Quota` is the
  aggregate divided by 4 (`rate_limit.rs`'s `per_pod()`), so the
  fleet-wide ceiling stays close to the intended target instead of
  drifting to ~4x it. This does re-couple the quota constants to
  `REPLICA_COUNT` — documented in `rate_limit.rs` with a comment
  pointing back at `deployment.yaml`'s own "don't raise this without
  revisiting" note, both need updating together if replica count ever
  changes.
- **Resolved (2026-09-29), asked directly before implementing.**
  `PeerIpKeyExtractor` vs `SmartIpKeyExtractor`: confirmed via
  `k8s/prod/ingress.yaml` that this deployment sits behind Traefik as
  its sole external edge, with a `ClusterIP`-only Service
  (`k8s/prod/service.yaml`) unreachable from outside the cluster except
  through that Ingress — so `X-Forwarded-For` (Traefik's own append) is
  trustworthy. Implemented as a hand-rolled equivalent
  (`rate_limit.rs::client_ip`, not `tower_governor`'s own extractor,
  since this module doesn't use `GovernorLayer` at all) reading the
  *rightmost* `X-Forwarded-For` entry, falling back to `X-Real-Ip`,
  falling back to the raw `ConnectInfo` peer address for traffic that
  reaches the pod without going through Traefik.
- Exact default-library-string list and contact-signal regex for §3.1
  — kept as the spike's illustrative list at promotion time; revisit
  against real observed traffic if it proves too broad or too narrow
  once live.
- In-memory vs. shared quota storage: still per-pod, not shared across
  replicas — §5's "divide by replica count" adjustment approximates
  the aggregate but will drift if traffic isn't evenly distributed
  across pods, or if replica count changes without updating
  `REPLICA_COUNT`. A real shared backend (e.g. Redis) would fix this
  properly; not built now, no evidence yet that the approximation is
  insufficient in practice.
- **Resolved (2026-09-29), asked directly before implementing.**
  `governor` keyed-limiter eviction: `TieredLimiterState::
  spawn_periodic_sweep`, called once at startup with a 5-minute
  interval, calls `retain_recent()` on both tiers' limiters in a
  background `tokio::spawn` task for the life of the process.
- **Exact trusted-origin host list (§3.4).** `localhost`/`127.0.0.1`/
  `::1` (any port) and `mediumroast.io`/`*.mediumroast.io` are this
  doc's working list; confirm against the local dev site's actual dev
  server (is it always `localhost`, or does it ever run under a
  different hostname/`.test` domain?) and whether the production site
  serves from `mediumroast.io` itself, a `www.` subdomain, or both,
  before promotion.
- **§3.5's exact shared-secret value and where it's minted.** This doc
  specifies the mechanism (`HMAC-SHA256(secret, UTC date+hour)`,
  constant-time comparison, both sides hold the raw secret) but not the
  actual secret value — that's a coordinated decision between
  company_dns's and mediumroast.io's deploys, not something either side
  mints alone the way the earlier hash-only draft allowed. Needs a
  process for the first exchange and for rotation (§3.5's "Rotation"
  paragraph flags this needs a runbook, not just a config change),
  before promotion.
- **Clock skew tolerance beyond one hour.** §3.5 checks the current and
  previous UTC hour; if either side's clock can genuinely drift more
  than that (unlikely for two cloud-hosted services with NTP, but worth
  confirming rather than assuming), the tolerance window may need to
  widen — a decision for whoever owns mediumroast.io's deployment
  environment, not decidable from company_dns's side alone.
- **Should the local dev site also get a §3.5-style secret**, or stay
  origin-only? Not raised — lower stakes (developer-only, not
  production), and local dev servers don't have a clean place to keep
  a Sealed Secret the way a K8s-deployed site does. Leaving it
  origin-only unless asked otherwise.

## 7. Explicitly out of scope for this doc

- **CORS.** `CorsLayer::permissive()` matches V3's own
  `allow_origins=["*"]` behavior (`company_dns.py:109-116`) — not a
  V4-introduced regression. Tightening it is a product decision (who's
  allowed to call this from a browser) independent of the rate-limiting
  ask that started this doc; worth its own short doc if/when it's
  raised.
- **WAF-style path/query pattern blocking**
  (`lib/security_middleware.py:20-67`'s blocklist). V4's router only
  ever matches the exact paths it registers (`main.rs`'s
  `routes!(...)` calls) plus the new `.fallback(...)` from this doc —
  there's no dynamic file-serving or admin surface for `wp-*`/`.php`/
  `.env`-style probes to hit in the first place, so V3's pattern list
  is defending against a surface V4 structurally doesn't have. Revisit
  only if that stops being true.
- **IP allow/deny-listing beyond what rate limiting provides.** Not
  requested; `governor`'s per-key throttling already bounds abuse from
  a single IP without maintaining a persistent ban list.
