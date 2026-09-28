//! Cache-aside live firmographics fetch - promoted from
//! `experiments/edgar-cache-spike/`, which validated this exact
//! pattern (miss/hit, concurrent single-flight de-duplication, TTL
//! expiry, LRU eviction) against real EDGAR data.

use crate::firmographics::build_firmographics;
use company_dns_cache::{new_cache, FallbackCache};
use edgarkit::{Edgar, EdgarError, FilingOperations};
use std::sync::Arc;
use std::time::Duration;

/// Defaults chosen for a first real prototype, not yet tuned against
/// real traffic - `go-duckdb-rewrite.md` §5.1 flags these as
/// per-instance configuration, not fixed by the cache type itself.
pub const DEFAULT_CACHE_CAPACITY: u64 = 10_000;
pub const DEFAULT_TTL: Duration = Duration::from_secs(60 * 60); // 1 hour

pub struct EdgarClient {
    edgar: Edgar,
    cache: FallbackCache<u64, Arc<serde_json::Value>>,
}

impl EdgarClient {
    pub fn new(user_agent: &str) -> anyhow::Result<Self> {
        Ok(Self::with_cache_config(
            user_agent,
            DEFAULT_CACHE_CAPACITY,
            DEFAULT_TTL,
        )?)
    }

    pub fn with_cache_config(
        user_agent: &str,
        max_capacity: u64,
        ttl: Duration,
    ) -> anyhow::Result<Self> {
        Ok(Self {
            edgar: Edgar::new(user_agent)?,
            cache: new_cache(max_capacity, ttl),
        })
    }

    /// The EDGAR live-fallback path (`docs/plans/go-duckdb-rewrite.md`
    /// §5.3, `docs/plans/edgar-backend.md` §1.2): on a cache miss, calls
    /// `edgarkit`'s live `submissions()` and builds the
    /// `get_firmographics()`-equivalent shape; on a hit, returns the
    /// cached value with no network call. Cache-key is the CIK
    /// (unpadded `u64`), matching `go-duckdb-rewrite.md` §2's
    /// "CIK, not company name" durable-identifier lesson.
    pub async fn get_firmographics(
        &self,
        cik: u64,
    ) -> Result<Arc<serde_json::Value>, Arc<EdgarError>> {
        let cik_padded = format!("{cik:010}");
        self.cache
            .try_get_with(cik, async {
                let submission = self.edgar.submissions(&cik_padded).await?;
                Ok::<_, EdgarError>(Arc::new(build_firmographics(&submission)))
            })
            .await
    }
}
