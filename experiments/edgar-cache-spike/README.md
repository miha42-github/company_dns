# edgar-cache-spike

Builds the general caching mechanism
[`docs/plans/go-duckdb-rewrite.md`](../../docs/plans/go-duckdb-rewrite.md)
§5.1 decided on (process-local, in-process, TTL+LRU via `moka`, one
generic type shared by EDGAR and Wikipedia rather than two bespoke
caches) and wires it to the real EDGAR live-fallback path — `edgarkit`'s
`submissions()` call, the same one [`../edgar-spike/`](../edgar-spike/)
validated can rebuild `get_firmographics()`'s full output shape.

**Checked whether `edgarkit` has anything cache-shaped first**: a
docs.rs full-text search of the crate for `"cache"` returns zero hits.
It has none — confirming the caching layer genuinely belongs on top of
`edgarkit` (and later, on top of Wikipedia's client, once that exists),
not inside it, exactly as `edgar-backend.md` §4 anticipated.

## Running it

```bash
cargo run
```

Hits real `data.sec.gov` — no local data needed. Makes a handful of
real requests across three real CIKs (IBM, Apple, Microsoft), well
under `edgarkit`'s own 10 req/s rate limit.

## What it found (2026-09-28)

Five tests, each proving one piece of §5.1's spec against real data and
a real (if synthetic) concurrent workload, not just reading `moka`'s
own docs:

**1. Miss then hit** — same CIK, called twice: **544ms** (real network
call) vs. **11.75µs** (cache hit) — **~46,000x faster**, and a real
fetch counter (incremented only inside the closure `moka` actually
runs, not just measured by wall-clock speed) confirms exactly one real
network call happened across both.

**2. Concurrent single-flight** — 5 concurrent requests for the *same*,
not-yet-cached CIK: only **1** real network fetch, not 5. This isn't
something a naive "check cache, fetch on miss, insert" implementation
gets for free — that shape has a real cache-stampede bug under
concurrent load (N simultaneous misses on the same key racing to fetch
independently). `moka`'s `try_get_with` is single-flight by design: the
first caller's future runs, the other 4 wait on it and share the
result. Worth calling out as a real advantage over hand-rolling this,
not just a convenience.

**3. TTL expiry** — fetched once (1 real fetch), immediately re-fetched
within a 2-second TTL (stayed at 1), then slept past the TTL and
re-fetched again (correctly went to 2). Staleness bounding works as
specified.

**4. LRU eviction** — a capacity-2 cache warmed with two entries (IBM,
Apple — 2 real fetches, `cache.entry_count() == 2`), then a third,
distinct entry added (Microsoft — 3 real fetches, entry count stays at
2, something got evicted to make room). Re-requesting the first entry
(IBM) afterward triggered a **4th** real fetch — not just "IBM was
theoretically evictable," but a real, confirmed miss proving it
actually was evicted. `cache.run_pending_tasks().await` was needed
after each insert to make eviction happen synchronously for this test
(`moka`'s maintenance is normally async/eventual) — worth knowing if
the real implementation ever needs deterministic behavior in tests.

**5. Generic type, different shape** — instantiated the exact same
`Cache<K, V>` type with `K = String` (a stand-in for Wikipedia's page
title/QID) and a different value type, not a real Wikipedia fetch
(`go-duckdb-rewrite.md` §5.4 is its own, separate future spike). Proves
the *type* from §5.1 is genuinely generic across data sources, not
EDGAR-specific — the "one mechanism, not two bespoke ones" decision
holds up in code, not just in the planning doc's prose.

## Bottom line for go-duckdb-rewrite.md §5.1 / edgar-backend.md

This is the piece that finally answers the standing question about
`edgarkit`: not just "can it fetch and shape the right data"
(`edgar-spike`) or "does the resulting data load into DataFusion"
(`edgar-index-query`), but "does the whole EDGAR live-fallback path —
cache-aside, TTL, LRU, concurrent-safe — actually work end to end, on
top of `edgarkit`, the way §5.1 designed it to." Yes, on all five counts,
against real SEC data. Nothing here required `edgarkit` to cooperate in
any special way — the cache sits entirely outside it, confirming §5.1's
"general mechanism on top of the fetch client" framing was right, and
`edgarkit`'s total absence of caching functionality is a non-issue
rather than a gap to work around.
