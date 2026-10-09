//! The general caching mechanism decided in
//! `docs/plans/go-duckdb-rewrite.md` §5.1: one process-local, in-process
//! TTL+LRU cache type (via `moka`), instantiated separately per data
//! source with its own key shape and configuration - not a bespoke
//! cache per backend. Promoted from `experiments/edgar-cache-spike/`,
//! which validated this exact shape against real EDGAR data (miss/hit,
//! concurrent single-flight de-duplication, TTL expiry, LRU eviction,
//! and reuse with a different K/V shape as a Wikipedia stand-in).
//!
//! No EDGAR- or Wikipedia-specific knowledge lives here - callers
//! (`company-dns-edgar`, and later a Wikipedia client) own their own
//! `FallbackCache<K, V>` instance, keyed however makes sense for their
//! data (CIK for EDGAR, page title/QID for Wikipedia).

use moka::future::Cache;
use std::time::Duration;

/// A process-local, TTL+LRU cache. Purely in-memory, gone on
/// restart/redeploy/crash by design - nothing about correctness depends
/// on it surviving a restart (`go-duckdb-rewrite.md` §5.1's "no
/// write-back to the persistent store, ever" decision already
/// established that upstream, for the data this fronts).
pub type FallbackCache<K, V> = Cache<K, V>;

/// Builds a new cache instance. `max_capacity` bounds memory (LRU-style
/// eviction once full); `ttl` bounds staleness (an entry expires and
/// gets re-fetched live after this window, rather than being trusted
/// indefinitely). Both apply together - an entry can be evicted by
/// either running out of room or aging out, whichever comes first.
pub fn new_cache<K, V>(max_capacity: u64, ttl: Duration) -> FallbackCache<K, V>
where
    K: std::hash::Hash + Eq + Send + Sync + 'static,
    V: Clone + Send + Sync + 'static,
{
    Cache::builder()
        .max_capacity(max_capacity)
        .time_to_live(ttl)
        .build()
}
