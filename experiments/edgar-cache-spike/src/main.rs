// Spike for docs/plans/go-duckdb-rewrite.md sec5.1's general caching
// mechanism, wired to the real EDGAR live-fallback path (edgarkit,
// per ../edgar-spike/ and docs/plans/edgar-backend.md). Checked
// edgarkit itself for anything cache-shaped first - docs.rs search for
// "cache" against the crate returns zero hits - confirming it has none
// and this caching layer genuinely belongs on top of it (and later,
// on top of Wikipedia's client), not inside it.

use edgarkit::{Edgar, EdgarError, FilingOperations, Submission};
use moka::future::Cache;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

const USER_AGENT: &str = "Mediumroast, Inc. edgar-cache-spike hello@mediumroast.io";

// Real, stable CIKs, used throughout.
const IBM: u64 = 51143;
const APPLE: u64 = 320193;
const MSFT: u64 = 789019;

/// The general mechanism decided in go-duckdb-rewrite.md sec5.1: one
/// generic TTL+LRU cache type (moka), instantiated separately per data
/// source with its own key shape and config - not two bespoke caches.
/// EDGAR's instance below keys by CIK (u64); Test 5 demonstrates the
/// same type reused with a completely different key/value shape,
/// standing in for what a real Wikipedia instance (sec5.4, its own,
/// separate future spike) would look like.
type FallbackCache<K, V> = Cache<K, V>;

fn new_cache<K, V>(max_capacity: u64, ttl: Duration) -> FallbackCache<K, V>
where
    K: std::hash::Hash + Eq + Send + Sync + 'static,
    V: Clone + Send + Sync + 'static,
{
    Cache::builder()
        .max_capacity(max_capacity)
        .time_to_live(ttl)
        .build()
}

/// Cache-aside firmographics fetch: on a miss, calls edgarkit's live
/// `submissions()` (the same call ../edgar-spike/'s company_test makes)
/// and stores the result; on a hit, returns the cached value with no
/// network call at all. `fetch_count` increments only inside the
/// closure moka actually runs - i.e., only on a real miss - so the
/// tests below can prove a hit didn't touch the network, not just that
/// it returned quickly.
async fn get_firmographics_cached(
    edgar: &Edgar,
    cache: &FallbackCache<u64, Arc<Submission>>,
    cik: u64,
    fetch_count: &AtomicUsize,
) -> Result<Arc<Submission>, Arc<EdgarError>> {
    let cik_padded = format!("{cik:010}");
    cache
        .try_get_with(cik, async {
            fetch_count.fetch_add(1, Ordering::SeqCst);
            let submission = edgar.submissions(&cik_padded).await?;
            Ok::<_, EdgarError>(Arc::new(submission))
        })
        .await
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let edgar = Edgar::new(USER_AGENT)?;

    miss_then_hit_test(&edgar).await?;
    concurrent_single_flight_test(&edgar).await;
    ttl_expiry_test(&edgar).await;
    lru_eviction_test(&edgar).await;
    generic_type_test().await;

    Ok(())
}

/// Same CIK, twice: first call must go to the network, second must
/// come straight from the cache.
async fn miss_then_hit_test(edgar: &Edgar) -> Result<(), Box<dyn std::error::Error>> {
    println!("=== Test 1: miss then hit ===");
    let cache = new_cache(100, Duration::from_secs(300));
    let fetches = AtomicUsize::new(0);

    let t0 = Instant::now();
    let s1 = get_firmographics_cached(edgar, &cache, IBM, &fetches)
        .await
        .map_err(|e| e.to_string())?;
    let miss_elapsed = t0.elapsed();

    let t1 = Instant::now();
    let s2 = get_firmographics_cached(edgar, &cache, IBM, &fetches)
        .await
        .map_err(|e| e.to_string())?;
    let hit_elapsed = t1.elapsed();

    println!("first call (miss):  {miss_elapsed:?}, name={}", s1.name);
    println!("second call (hit):  {hit_elapsed:?}, name={}", s2.name);
    println!(
        "real network fetches so far: {}",
        fetches.load(Ordering::SeqCst)
    );
    println!(
        "hit was ~{:.0}x faster than the miss",
        miss_elapsed.as_secs_f64() / hit_elapsed.as_secs_f64().max(0.000_001)
    );
    println!();
    Ok(())
}

/// Five concurrent requests for the *same*, not-yet-cached CIK. A naive
/// check-then-fetch cache would make 5 network calls (a "thundering
/// herd"/cache-stampede). moka's try_get_with is single-flight: only
/// the first caller's future actually runs; the other 4 wait for it and
/// share the result.
async fn concurrent_single_flight_test(edgar: &Edgar) {
    println!("=== Test 2: 5 concurrent requests for the same uncached CIK ===");
    let cache: FallbackCache<u64, Arc<Submission>> = new_cache(100, Duration::from_secs(300));
    let fetches = Arc::new(AtomicUsize::new(0));

    let mut tasks = Vec::new();
    for _ in 0..5 {
        let edgar = edgar.clone();
        let cache = cache.clone();
        let fetches = fetches.clone();
        tasks.push(tokio::spawn(async move {
            get_firmographics_cached(&edgar, &cache, APPLE, &fetches).await
        }));
    }

    let mut ok = 0;
    for t in tasks {
        if matches!(t.await, Ok(Ok(_))) {
            ok += 1;
        }
    }

    println!("5 concurrent requests completed ({ok}/5 ok)");
    println!(
        "real network fetches: {} (1 means moka de-duplicated the other 4, not a coincidence of timing)",
        fetches.load(Ordering::SeqCst)
    );
    println!();
}

/// A short-lived cache: fetch, immediately re-fetch (should stay
/// cached), then sleep past the TTL and re-fetch again (should force a
/// real re-fetch).
async fn ttl_expiry_test(edgar: &Edgar) {
    println!("=== Test 3: TTL expiry forces a re-fetch ===");
    let ttl = Duration::from_secs(2);
    let cache: FallbackCache<u64, Arc<Submission>> = new_cache(100, ttl);
    let fetches = AtomicUsize::new(0);

    get_firmographics_cached(edgar, &cache, MSFT, &fetches)
        .await
        .ok();
    println!(
        "after first fetch:              {} real fetch(es)",
        fetches.load(Ordering::SeqCst)
    );

    get_firmographics_cached(edgar, &cache, MSFT, &fetches)
        .await
        .ok();
    println!(
        "immediate re-fetch (within TTL): {} real fetch(es) (should stay 1)",
        fetches.load(Ordering::SeqCst)
    );

    println!("sleeping {ttl:?} past the TTL...");
    tokio::time::sleep(ttl + Duration::from_millis(500)).await;
    cache.run_pending_tasks().await;

    get_firmographics_cached(edgar, &cache, MSFT, &fetches)
        .await
        .ok();
    println!(
        "re-fetch after TTL expiry:       {} real fetch(es) (should be 2)",
        fetches.load(Ordering::SeqCst)
    );
    println!();
}

/// A capacity-2 cache warmed with two entries, then a third distinct
/// entry added - something has to be evicted to stay within capacity.
/// Re-requesting the first entry afterward should be a miss if it was
/// the one evicted.
async fn lru_eviction_test(edgar: &Edgar) {
    println!("=== Test 4: LRU eviction under a small capacity ===");
    let cache: FallbackCache<u64, Arc<Submission>> = new_cache(2, Duration::from_secs(300));
    let fetches = AtomicUsize::new(0);

    get_firmographics_cached(edgar, &cache, IBM, &fetches)
        .await
        .ok();
    cache.run_pending_tasks().await;
    get_firmographics_cached(edgar, &cache, APPLE, &fetches)
        .await
        .ok();
    cache.run_pending_tasks().await;
    println!(
        "after warming IBM + Apple (capacity 2): {} real fetches, cache size {}",
        fetches.load(Ordering::SeqCst),
        cache.entry_count()
    );

    get_firmographics_cached(edgar, &cache, MSFT, &fetches)
        .await
        .ok();
    cache.run_pending_tasks().await;
    println!(
        "after adding Microsoft (3rd entry):     {} real fetches, cache size {}",
        fetches.load(Ordering::SeqCst),
        cache.entry_count()
    );

    get_firmographics_cached(edgar, &cache, IBM, &fetches)
        .await
        .ok();
    println!(
        "re-requesting IBM:                      {} real fetches total \
        (a 4th fetch here confirms IBM was actually evicted, not just theoretically evictable)",
        fetches.load(Ordering::SeqCst)
    );
    println!();
}

/// Not a real Wikipedia fetch - docs/plans/go-duckdb-rewrite.md sec5.4
/// is its own, separate future spike. Just proves the *type* from
/// sec5.1 is generic enough to reuse for Wikipedia's very different key
/// shape (page title/QID, a String, not a CIK) without writing a
/// second cache implementation - the point of "one general caching
/// mechanism, not two bespoke ones."
async fn generic_type_test() {
    println!("=== Test 5: same cache type, different key/value shape (Wikipedia stand-in) ===");
    let wiki_cache: FallbackCache<String, Arc<String>> = new_cache(50, Duration::from_secs(600));
    let value = wiki_cache
        .try_get_with("International_Business_Machines".to_string(), async {
            Ok::<_, std::convert::Infallible>(Arc::new(
                "(stand-in payload, not a real Wikipedia fetch)".to_string(),
            ))
        })
        .await
        .unwrap();
    println!(
        "Wikipedia-shaped instance: key=String, value={value:?} - \
        same Cache<K, V> type as the EDGAR instance above, just a \
        different instance with its own K/V and config."
    );
    println!();
}
