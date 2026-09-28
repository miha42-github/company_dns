//! Staged, not built (`docs/plans/v4-server-prototype.md` §8.1). This
//! is the module boundary for a future Wikipedia client, shaped after
//! `lib/wikipedia_v2.py`'s already-validated approach (narrowed field
//! requests, real identifying User-Agent, `maxlag`/429/503 handling -
//! `go-duckdb-rewrite.md` §5.4) - not a real HTTP client yet. Wired to
//! the same general cache mechanism `company-dns-edgar` uses
//! (`company-dns-cache`), with its own instance and its own key shape
//! (page title/QID, a `String`, not a CIK), matching what
//! `experiments/edgar-cache-spike/`'s Test 5 already proved works.

use company_dns_cache::{new_cache, FallbackCache};
use std::sync::Arc;
use std::time::Duration;

pub const DEFAULT_CACHE_CAPACITY: u64 = 10_000;
pub const DEFAULT_TTL: Duration = Duration::from_secs(60 * 60);

pub struct WikipediaClient {
    #[allow(dead_code)]
    cache: FallbackCache<String, Arc<serde_json::Value>>,
}

#[derive(Debug, thiserror::Error)]
pub enum WikipediaError {
    #[error("not yet implemented - see docs/plans/v4-server-prototype.md sec8.1")]
    NotImplemented,
}

impl WikipediaClient {
    pub fn new() -> Self {
        Self {
            cache: new_cache(DEFAULT_CACHE_CAPACITY, DEFAULT_TTL),
        }
    }

    /// Mirrors `lib/wikipedia_v2.py`'s `get_firmographics(company_name)`
    /// shape. Returns a typed "not implemented" error rather than a
    /// silent 404 or a fabricated result - the point of staging this
    /// now is that the shape is right when real work starts, not that
    /// this prototype ships a working Wikipedia client.
    pub async fn get_firmographics(
        &self,
        _company_name: &str,
    ) -> Result<Arc<serde_json::Value>, WikipediaError> {
        Err(WikipediaError::NotImplemented)
    }
}

impl Default for WikipediaClient {
    fn default() -> Self {
        Self::new()
    }
}
