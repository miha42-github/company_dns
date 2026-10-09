# V4 dynamic log level: structured logging that can go from WARN to DEBUG without a restart

Status: **Built (2026-09-30) — promoted into `v4/crates/server/`, live-
verified against the real running server, not just the spike.** New
module `logging.rs` (`init()` sets up `tracing_subscriber::registry()`
with a `reload::Layer<EnvFilter>` + `fmt::layer()`;
`spawn_config_watch()` polls the ConfigMap-mounted file per §4.4's
polling choice, shipped — not `notify` — since polling needs no
platform-specific filesystem-event backend at all, sidestepping the
still-open macOS-vs-Linux question entirely rather than resolving it).
Every `println!`/`eprintln!` in `main.rs` converted to `tracing::info!`/
`tracing::warn!` (§4.1). `main.rs` calls `logging::init()` as the very
first thing in `main()`, before anything else logs. Full workspace
`cargo build`/`cargo test` clean (26/26 passing, zero regressions),
`cargo clippy` clean on the new code. **Live-verified against the real
server with real feather data** (not synthetic routes): started at
`RUST_LOG=warn`, confirmed startup/request-trace output absent; edited
the watched file to `"debug"`, confirmed reload fired within one poll
interval and `tower_http::trace::on_request`/`on_response` — §1's
"silently dropped" finding — became visible, proving both the
diagnosis and the fix on the real binary. **One real finding from this
live run, not anticipated by the design**: a blanket `"debug"` also
floods the log with every dependency's own internal DEBUG output
(observed: DataFusion's `datafusion_datasource::source: Batch
splitting enabled for partition N...`, one line per partition, on
every SIC query) — confirms §6's "exact `EnvFilter` directive
granularity" open question is a real, not hypothetical, operational
concern. A targeted directive
(`company_dns_server=debug,tower_http=debug`) was live-verified to
give clean, relevant DEBUG output with none of that noise — this is
the form worth documenting as the recommended incident-response value,
not a bare `"debug"`. **Not done**: no K8s manifest work yet — V4 has
no deployment manifest of its own at all yet (`docs/plans/v4-deployment.md`
§1.4), and the live production `k8s/prod/deployment.yaml` is V3's
(Python/uvicorn) — wiring the ConfigMap mount described in §4.5 belongs
with whichever V4 manifest `v4-deployment.md` §3.8/§5 produces, not
bolted onto V3's manifest for a Rust-only env var it would never read.
**The macOS-vs-Local-Linux caveat from the spike still stands** — this
promotion re-verified the mechanism on the real server binary, but
still on macOS; `v4-deployment.md` §3.6's platform-parity suite (run at
the staging gate, once it exists) is still where the real Linux/
`microk8s` confirmation happens. Prior spike-stage summary (kept for
history): `experiments/dynamic-log-level-spike/` confirmed the design
live, including that watching the ConfigMap mount's *parent directory*
with `notify` also correctly catches kubelet's atomic `..data` symlink
swap (an alternative not shipped, per the polling choice above). Full
writeup: `experiments/dynamic-log-level-spike/README.md`.
Owner: michael.hay@mediumroast.io
Scope: give `v4/crates/server/` a real structured-logging setup for the
first time (it currently has none — see §1), with the ability to raise
or lower the active log level on a live process, without a pod
restart. Out of scope: fixing V3's own broken `LOG_LEVEL` handling
(§0 explains why), anything related to IP blocking/Traefik access logs
(that thread is being handled outside company_dns entirely — see §0).

---

## 0. Why this doc

Raised directly, while investigating a suspected scanning/attack
pattern against the production V3 deployment (a "side detour" from the
rate-limiting/container-packaging work): pulling V3's app logs with
`LOG_LEVEL=DEBUG` set on the Deployment produced **zero** DEBUG-level
output, even for a controlled test request confirmed to have tripped
`lib/security_middleware.py`'s block logic (a real `403` was returned).
Direct in-pod testing (importing `lib.logging_config` fresh inside the
running container and calling `logger.debug(...)` by hand) reproduced
the same silence. Root cause not chased further — **decided
explicitly**: V3 is being replaced by V4, so debugging a logging bug in
code that's going away isn't worth the time. What *is* worth carrying
forward: **V4 needs this to actually work**, and needs it in a form
that doesn't repeat V3's implicit assumption that changing the log
level means restarting the process (V3's approach was already just an
env var read once at import time — even if it worked, it would have
required a rolling restart to change, same as V4's `MEDIUMROAST_SHARED_SECRET`
pattern from `v4-security-hardening.md` §3.5, but log-level toggling
during a live incident is exactly the case where waiting for a rollout
is the wrong tradeoff).

Separately in that same investigation: the Orbi router log showed
heavy internet-wide scanning traffic against the exposed IP, but with
no working access-log trail (V3's app logs empty at DEBUG, Traefik's
access log confirmed off entirely) there was no way to tell which of
it reached company_dns's application logic versus bounced off Traefik
with no matching Host/SNI. That thread is **not** this doc's problem —
Traefik's access log is being turned on separately (an ops/Helm change,
not a company_dns code change), and the network-edge blocking problem
is being solved with a dedicated device (a Firewalla Orange, sitting
between the cable modem and the router) rather than anything in this
codebase. This doc is scoped narrowly: make sure that when V4 replaces
V3, "turn on verbose logging to investigate something live" actually
works, on the first try, without guessing at env-var plumbing during
an incident the way this investigation just did.

## 1. Current state (audited 2026-09-30)

**V4 has no structured logging at all today.** Grepped
`v4/crates/server/src/main.rs`: every diagnostic message is a raw
`println!`/`eprintln!` call (startup messages, the EDGAR-catalog-load
warning, the port/listen banner) — no log levels, no structured
fields, nothing filterable, nothing that could be turned up or down
short of editing source and rebuilding.

**A `tracing`-based layer is already half-wired in, and currently
inert.** `docs/plans/v4-security-hardening.md` §3.3/§5 added
`TraceLayer::new_for_http()` (from `tower-http`) to `main.rs`.
`tower-http`'s `trace` feature is built on the `tracing` crate — but
`v4/Cargo.toml` has no direct dependency on `tracing` or
`tracing-subscriber`, and nothing in `main.rs` ever calls anything
like `tracing_subscriber::fmt().init()`. That means `TraceLayer` has
been emitting `tracing` events into a process with **no subscriber
listening** since the day it was added — every request/response
`tracing` event it generates is silently dropped. This isn't a new
problem to design around; it's a real, already-shipped gap this doc's
work will also close as a side effect of doing the setup properly.

**No log-level configuration surface exists in V4 at all** — unlike
V3's (broken) `LOG_LEVEL` env var, V4 doesn't even have the equivalent
knob to be broken. Starting from nothing.

## 2. Decisions from the conversation that started this doc

- **Trigger mechanism: Kubernetes-native, not an HTTP admin endpoint or
  a Unix signal.** A ConfigMap mounted as a file into the pod,
  watched for changes; editing the ConfigMap (`kubectl edit`/`patch`)
  updates the mounted file, the process notices and reloads its filter
  in place. Chosen specifically to avoid adding a new network-facing
  attack surface to the running service (the HTTP-endpoint option) and
  to avoid the awkwardness of `kubectl exec ... kill -USR1` across 4
  replicas individually (the signal option) — this fits how K8s
  configuration is normally changed, and one `kubectl` command reaches
  all replicas via the same mounted ConfigMap.
- **V3's own broken `LOG_LEVEL` handling will not be investigated
  further.** Explicitly decided — not worth the time given V4 is
  replacing it. `lib/logging_config.py` stays as-is.
- **Plan doc first, then a small `experiments/` spike** — matching how
  `v4-security-hardening.md` and `v4-container-packaging.md` both
  started in this same session, rather than prototyping directly.

## 3. Crate research (verified live against crates.io, 2026-09-30)

| Crate | Version | Role | Notes |
|---|---|---|---|
| `tracing` | 0.1.44 | The actual logging/instrumentation calls (`tracing::info!`, `tracing::debug!`, etc.), replacing `println!`/`eprintln!` | Already a transitive dependency via `tower-http`'s `trace` feature — this doc makes it a direct one so `main.rs` and the rest of the server crate can use it directly, not just `tower-http` internally. |
| `tracing-subscriber` | 0.3.23 | The actual log processor: formats and emits events, and is where the dynamic-level mechanism lives | `env-filter` feature (confirmed present in 0.3.23's published feature list) gives `EnvFilter`, which parses the same directive syntax as the `RUST_LOG` convention (`"warn"`, `"company_dns_server=debug,tower_http=info"`, etc.) — a good fit for a human editing a ConfigMap by hand. `reload` (confirmed via docs.rs, not assumed) is **not** a separate cargo feature — `reload::Layer`/`Handle` are available under the `std` feature, which is already in `default`. |
| `notify` | 8.2.0 | Filesystem-change notification, for watching the mounted ConfigMap file | Candidate for the trigger mechanism — see §4's open question about K8s ConfigMap mounts' symlink-swap semantics, which may make simple polling a better fit than event-driven watching. |

**The actual reload mechanism** (confirmed via docs.rs, not assumed):
`tracing_subscriber::reload::Layer::new(filter)` returns both the
wrapped layer (registered once at startup) and a `Handle`; calling
`handle.modify(|filter| *filter = EnvFilter::new(new_level))` swaps the
active filter on a live process, no restart, no new connections
dropped, nothing about the running `axum::serve(...)` loop disturbed.

## 4. Design

### 4.1 Replace `println!`/`eprintln!` with `tracing` macros

Straightforward, mechanical: `println!("Loading US SIC data from
{sic_path}...")` becomes `tracing::info!("Loading US SIC data from
{sic_path}...")`, `eprintln!` for the EDGAR-catalog-load warning
becomes `tracing::warn!`, etc. Also gives `TraceLayer`'s own
request/response events (already being generated, currently dropped)
somewhere to actually go once a subscriber exists.

### 4.2 The reloadable filter, set up once at startup

```rust
let (filter, reload_handle) = tracing_subscriber::reload::Layer::new(
    EnvFilter::new(initial_level), // from an env var at startup - see §4.3
);
tracing_subscriber::registry()
    .with(filter)
    .with(tracing_subscriber::fmt::layer())
    .init();
```
`reload_handle` then gets stored somewhere the file-watcher (§4.4) can
reach it — likely a `tokio::spawn`'d background task holding it
directly, mirroring how `rate_limit.rs::spawn_periodic_sweep` already
runs a long-lived background task in this same codebase
(`v4-security-hardening.md` §5).

### 4.3 Startup default vs. runtime override

The ConfigMap-mounted file supplies the *current* level; an env var
(e.g. `RUST_LOG`, the `tracing` ecosystem's own conventional name —
reusing it rather than inventing a company_dns-specific one) supplies
the level to start with *before* the file's first read, and the
fallback if the file is ever missing/unreadable/malformed. Startup
should never fail or block waiting on the ConfigMap mount to be ready.

### 4.4 Watching the mounted file — the real open design question

K8s ConfigMap volume mounts don't update the mounted file in place —
they atomically repoint a `..data` symlink to a new timestamped
directory each time the ConfigMap changes, with the visible file being
a symlink through that indirection. A naive `notify` watch on the
literal file path can miss this (the file's *content* doesn't change
in a way inotify sees as a normal write; the symlink target changes
instead) — this is a well-known gotcha with this exact combination,
not this doc's own speculation, and needs confirming against the real
mount behavior in the spike rather than assumed either way.
**Leaning toward simple periodic polling** (read the file every few
seconds, compare against the last-seen value, call `handle.modify(...)`
only on an actual change) over event-driven watching — the use case is
a human toggling a level during an incident, not something needing
sub-second reaction time, and polling sidesteps the symlink-swap
semantics question entirely at the cost of a few seconds of latency.
`notify`'s inclusion in §3 is a fallback if the spike shows watching
the parent directory (rather than the file itself) handles the
symlink swap cleanly and polling turns out to have its own rough edges
(e.g. torn reads mid-swap).

### 4.5 The ConfigMap itself

A small ConfigMap in the `company-dns` namespace, one key (e.g.
`log-level`, value `"warn"` or `"company_dns_server=debug"` — an
`EnvFilter` directive string), mounted as a file into the existing
Deployment (`k8s/prod/deployment.yaml` gains a `volumes`/`volumeMounts`
entry). Changing the level going forward is `kubectl -n company-dns
edit configmap company-dns-log-level` (or a `kubectl patch`
one-liner) — no rollout, no `kubectl set env`, no waiting on
`maxSurge`/`maxUnavailable` the way the `MEDIUMROAST_SHARED_SECRET`
rotation path does.

## 5. Research spike — **done** (`experiments/dynamic-log-level-spike/`, 2026-09-30)

Following the same `experiments/` pattern as the rate-limiting and
(implicitly) other V4 work this session:

1. **Done.** Minimal Axum app wiring up `tracing_subscriber::reload::
   Layer` + `EnvFilter`. Live-verified `Handle::reload(...)` actually
   changes what gets logged on a live, already-`axum::serve`-ing
   process — real requests before and after, not a unit test — and
   confirmed correct across **repeated** sequential reloads (warn →
   debug → warn → info), not just a single before/after pair.
2. **Done — answered, not left open.** §4.4's concern confirmed real:
   a naive watch on the ConfigMap key file's own path is the failure
   mode this doc worried about, reproduced by hand via
   `configmap_sim.rs` (kubelet's actual `AtomicWriter` mechanism,
   since no real cluster was reachable from this environment to test
   against directly). Watching the **parent directory** instead
   correctly catches the atomic `..data` symlink swap — live-verified,
   not assumed. The polling fallback was independently confirmed
   working too. **Caveat**: tested on macOS (FSEvents), not the real
   Linux/microk8s target (inotify) — carried to §6, not glossed over.
3. **Done.** `TraceLayer`'s events started appearing automatically the
   moment a real subscriber existed — confirms both §1's diagnosis
   (they were being silently dropped) and that this work fixes it as a
   side effect.
4. **Done**, end to end: started at `warn`, confirmed DEBUG-level
   `/probe` output absent; simulated a ConfigMap edit to `debug` via
   the exact mechanism a real `kubectl edit configmap` would trigger;
   confirmed DEBUG output now present, process never restarted.

## 6. Open questions

- **Resolved by live-verification during promotion, 2026-09-30 — a
  real concern, not hypothetical.** A bare `"debug"` was confirmed live
  to flood the log with every dependency's own internal DEBUG output
  (DataFusion's `datafusion_datasource::source: Batch splitting
  enabled for partition N...`, one line per partition, on every SIC
  query). A targeted directive —
  **`company_dns_server=debug,tower_http=debug`** — was live-verified
  to give clean, relevant output with none of that noise. **This is
  the value worth documenting as the recommended incident-response
  setting** (e.g. in `v4/README.md`'s "## Security" section, or a
  runbook), not a bare `"debug"` — still worth someone mid-incident
  having the right string handy rather than discovering this the hard
  way, even though the mechanism itself now handles either input fine.
- **Confirm the `notify`/parent-directory approach on the real Linux
  target, not just the spike's macOS result.** FSEvents (macOS) and
  inotify (Linux) have their own, different edge cases; "worked on
  macOS" is real evidence the design is sound, not proof it's correct
  on `microk8s`. One test run against the actual on-prem hosts (or a
  Linux container standing in for them) before treating this as
  settled — if it doesn't hold, the polling fallback is already
  confirmed working as a drop-in replacement.
- **Which strategy to actually ship, `notify` or polling** — both
  confirmed working in the spike; the choice is a judgment call
  (slightly faster/platform-dependent vs. simpler/platform-agnostic),
  not a correctness question. Leaning polling for the reasons in
  §4.4, pending the Linux confirmation above.
- **Polling interval, if polling is what ships** — needs to
  balance "changes take effect reasonably fast during an incident"
  against "don't stat a file needlessly often." Not sized yet (the
  spike used 2s purely for a fast feedback loop while testing).
- **Does this want to eventually cover the `experiments/rate-limit-spike/`-
  derived modules too** (`user_agent.rs`, `trusted_origin.rs`,
  `secret_ua.rs`, `rate_limit.rs` currently use `eprintln!`/`println!`
  in a couple of places, e.g. `main.rs`'s `load_shared_secret()`
  warning) — likely yes, as part of §4.1's mechanical replacement pass,
  but not scoped in detail here.
- **Should the ConfigMap-driven level ever get exposed read-only
  somewhere** (e.g. in the `/health` response, so `kubectl get
  configmap` isn't the only way to confirm what's currently active)?
  Minor polish, not required for the core feature.

## 7. Explicitly out of scope for this doc

- **V3's broken `LOG_LEVEL` handling** — decided directly (§0/§2): not
  being chased further.
- **Traefik's access log** — being turned on separately as an ops/Helm
  change (`docs/plans/v4-security-hardening.md`'s incident-response
  thread), not a company_dns code change.
- **Network-edge IP blocking** (Orbi/Firewalla/Spectrum modem) —
  hardware/network infrastructure decisions entirely outside this
  codebase's scope, being handled with a dedicated device.
