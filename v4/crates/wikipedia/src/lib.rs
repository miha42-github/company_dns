//! Built (2026-09-28), promoted from `experiments/wikipedia-spike/`
//! (`docs/plans/v4-server-prototype.md` sec8.1) - real, tested,
//! diff-verified-against-live-V3-output Wikipedia firmographics, not a
//! stub. Shaped after `lib/wikipedia_v2.py`'s already-validated approach
//! (narrowed field requests, real identifying User-Agent, `maxlag`/429/
//! 503 handling), wired into the same general cache mechanism
//! `company-dns-edgar`'s client uses (`company-dns-cache`), with its own
//! instance and its own key shape (page title/QID, a `String`, not a
//! CIK) - what `experiments/edgar-cache-spike/`'s Test 5 already proved
//! works.
//!
//! The `client`/`infobox`/`firmographics` modules are a promotion of the
//! spike's own modules of the same names, not a rewrite - see that
//! spike's README for the full validation trail: crate evaluation (why
//! this is hand-rolled on `reqwest`, not a general MediaWiki crate), the
//! wptools infobox/claims parsing port, the side-by-side diff against
//! V3's live output across 10 companies, the corporate-suffix hint
//! restoration (V3 computes this hint but a 404-handler bug means it
//! never reaches a client - not reproduced here), the infobox-presence
//! gate that fixed "Alphabet"/"Meta" resolving to the wrong page, and
//! the Wikidata canonical-title fix for redirect aliases.

mod client;
mod firmographics;
mod infobox;

use company_dns_cache::{new_cache, FallbackCache};
use std::sync::Arc;
use std::time::Duration;

pub const DEFAULT_CACHE_CAPACITY: u64 = 10_000;
pub const DEFAULT_TTL: Duration = Duration::from_secs(60 * 60);

/// Matches `lib/wikipedia_v2.py`'s own real, identifying User-Agent
/// convention (its docstring, Finding 5: wptools' hardcoded generic
/// string is indistinguishable from every other wptools consumer's
/// traffic, a real operational risk under Wikimedia's User-Agent
/// policy - https://meta.wikimedia.org/wiki/User-Agent_policy).
pub const USER_AGENT: &str =
    "company_dns/4.0.0 (https://github.com/miha42-github/company_dns; hello@mediumroast.io)";

pub struct WikipediaClient {
    http: reqwest::Client,
    cache: FallbackCache<String, Arc<serde_json::Value>>,
}

#[derive(Debug, thiserror::Error)]
pub enum WikipediaError {
    /// V3-parity: byte-identical to `lib/wikipedia_v2.py`'s
    /// `lookup_error['message']` (`client::hint_message`) when nothing
    /// resolves - the raw name, nor any of V3's three suffix guesses,
    /// nor an infobox on any of them. NOT cached (an `Err` from
    /// `try_get_with`'s closure isn't cached by moka) - deliberate,
    /// matches V3's own behavior of never caching a miss, and avoids
    /// permanently caching a negative for a page that might exist later.
    #[error("{0}")]
    NotFound(String),
    /// A real network/parse failure (not a "this company doesn't
    /// exist" outcome) - distinct from `NotFound` so a caller/handler
    /// can map this to a 5xx instead of a 404.
    #[error("wikipedia request failed: {0}")]
    Request(String),
}

impl WikipediaClient {
    pub fn new(user_agent: &str) -> anyhow::Result<Self> {
        Self::with_cache_config(user_agent, DEFAULT_CACHE_CAPACITY, DEFAULT_TTL)
    }

    pub fn with_cache_config(
        user_agent: &str,
        max_capacity: u64,
        ttl: Duration,
    ) -> anyhow::Result<Self> {
        Ok(Self {
            http: reqwest::Client::builder().user_agent(user_agent).build()?,
            cache: new_cache(max_capacity, ttl),
        })
    }

    /// Mirrors `lib/wikipedia_v2.py`'s `get_firmographics(company_name)`
    /// shape. Cache-aside (`experiments/edgar-cache-spike/`'s pattern,
    /// reused verbatim from `company-dns-edgar`'s client): a cache hit
    /// returns with no network call; a miss runs the full
    /// `client::lookup_firmographics` pipeline (near-exact title first,
    /// then V3's suffix-hint fallback, infobox-gated, canonical-title-
    /// correct for Wikidata) and caches the result on success.
    pub async fn get_firmographics(
        &self,
        company_name: &str,
    ) -> Result<Arc<serde_json::Value>, Arc<WikipediaError>> {
        self.cache
            .try_get_with(company_name.to_string(), async {
                let outcome = client::lookup_firmographics(&self.http, company_name)
                    .await
                    .map_err(|e| WikipediaError::Request(e.to_string()))?;
                match outcome.firmographics {
                    Some(f) => Ok(Arc::new(f)),
                    None => Err(WikipediaError::NotFound(outcome.message)),
                }
            })
            .await
    }
}
