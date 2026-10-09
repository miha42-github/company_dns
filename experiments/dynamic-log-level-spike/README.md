# dynamic-log-level-spike

Proves `docs/plans/v4-dynamic-log-level.md` §5's design before it's
promoted into `v4/crates/server/`: a `tracing`-based logging setup
whose level can be raised or lowered on a live process, driven by a
K8s ConfigMap mount, with no restart.

## What this proves

1. **The reload mechanism itself works.** `tracing_subscriber::reload::
   Layer` + `EnvFilter`, exactly as `docs/plans/v4-dynamic-log-level.md`
   §4.2 specifies. Live test: started at `"warn"`, hit `/probe`
   (emits one DEBUG + one INFO + one WARN line) — only WARN appeared.
   Reloaded to `"debug"` via `Handle::reload(...)`, hit `/probe` again
   — all three appeared. Confirmed working for **repeated** sequential
   reloads too (warn → debug → warn → info, each one correctly
   reflected on the next request, not stuck or cumulative).
2. **§1's finding about `TraceLayer` being inert is confirmed, and the
   fix is confirmed too.** Once a real subscriber existed,
   `tower_http::trace::on_request`/`on_response` events started
   appearing in the output automatically — same `TraceLayer` call V4's
   real `main.rs` already has, previously producing nothing because
   nothing was listening.
3. **§4.4's open question is answered, with real evidence, not
   assumption: watching the ConfigMap mount's *parent directory* with
   `notify` correctly catches the atomic `..data` symlink swap.**
   `configmap_sim.rs` reproduces kubelet's actual `AtomicWriter`
   mechanism by hand (`std::fs`, no real cluster needed, since none was
   reachable from this environment) — a brand new timestamped
   directory, a temp symlink, an atomic `rename()` over the existing
   `..data` symlink, exactly as documented. Naively watching the *file
   path itself* was the specific failure mode §4.4 worried about (the
   file's own directory entry never changes, only `..data`'s target
   does); watching the parent directory instead sees the rename event
   and works. Live-verified end to end via the `/simulate-configmap-edit/{level}`
   route (which calls the exact same `SimulatedConfigMapMount::update`
   a second real process editing a real ConfigMap would trigger).
4. **The polling fallback also works**, confirmed independently with
   the same live test sequence, `WATCH_STRATEGY=poll` instead of
   `WATCH_STRATEGY=notify`.

## A caveat this spike could NOT resolve

Tested on **macOS**, whose `notify` backend is FSEvents. The real
target (`microk8s` on the on-prem Linux hosts) uses `notify`'s inotify
backend, which has its own, different edge cases around renames and
watched-file lifecycle (a well-known category of inotify quirk,
distinct from FSEvents' own). Watching the parent directory is the
generally-recommended pattern specifically because it sidesteps most
inotify rename gotchas too (this is the same technique several
real-world K8s config-reloader sidecars use), and this spike's result
is a genuine, real, working proof of the *design* — but the exact
before-promotion confirmation should include one real test run on the
actual Linux target (or a Linux container standing in for it), not
just this macOS result. Flagged in the plan doc's open questions
rather than glossed over.

## Why polling is still the recommendation despite `notify` working

`notify` worked cleanly here, but §4.4 in the plan doc already leaned
toward polling for a good reason unrelated to whether it *works*: this
is a human-triggered incident-response toggle, not something needing
sub-second reactivity, and polling has zero dependency on
platform-specific filesystem-event semantics (no FSEvents-vs-inotify
question at all). This spike proves **both are real, viable options**
— the final choice is a judgment call between "slightly faster,
platform-event-dependent" (`notify`) and "trivially simple, platform-
agnostic, a few seconds slower" (polling), not a question of whether
either one actually functions.

## Running it

```bash
cargo run --release
# separate terminal, notify strategy:
WATCH_STRATEGY=notify cargo run --release
# or polling (default):
cargo run --release

curl http://127.0.0.1:4300/probe                              # logs at current level
curl http://127.0.0.1:4300/simulate-configmap-edit/debug       # simulates `kubectl edit configmap`
curl http://127.0.0.1:4300/probe                               # logs again - compare
curl http://127.0.0.1:4300/reload-count                        # how many reloads have actually fired
```

```bash
cargo test    # 2/2: configmap_sim's symlink-swap-simulation tests
```
