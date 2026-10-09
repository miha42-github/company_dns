//! The actual design being spiked: two `governor` keyed rate limiters
//! (one per tier) selected per-request by `user_agent::classify`, since
//! `tower_governor::GovernorLayer` only supports one fixed quota per
//! layer instance - see README "Why governor directly, not
//! GovernorLayer" and `docs/plans/v4-security-hardening.md` §3.2.

use std::net::IpAddr;
use std::sync::Arc;

use axum::{
    body::Body,
    extract::{ConnectInfo, State},
    http::{header, HeaderValue, Request, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
};
use governor::{clock::Clock, DefaultKeyedRateLimiter, Quota, RateLimiter};
use std::num::NonZeroU32;

use crate::secret_ua;
use crate::trusted_origin;
use crate::user_agent::{classify, Tier};

#[derive(Clone)]
pub struct TieredLimiterState {
    normal: Arc<DefaultKeyedRateLimiter<IpAddr>>,
    draconian: Arc<DefaultKeyedRateLimiter<IpAddr>>,
    /// §3.5: the raw shared secret used to recompute the expected
    /// rolling HMAC token each request - `None` disables the check
    /// entirely (fails closed, no bypass, never "no check needed").
    trusted_ua_secret: Option<String>,
}

impl TieredLimiterState {
    /// `docs/plans/v4-security-hardening.md` §3.2's illustrative
    /// numbers: normal tier borrows V3's own never-enforced
    /// `RATE_LIMITS` baseline shape (`lib/rate_limiter.py:22-37`, a
    /// couple hundred/minute), draconian is an order of magnitude
    /// tighter - single digits/minute, burst 1, so a real integration
    /// notices immediately without being an outright hard block.
    pub fn new(trusted_ua_secret: Option<String>) -> Self {
        let normal_quota = Quota::per_minute(NonZeroU32::new(200).unwrap())
            .allow_burst(NonZeroU32::new(20).unwrap());
        let draconian_quota =
            Quota::per_minute(NonZeroU32::new(5).unwrap()).allow_burst(NonZeroU32::new(1).unwrap());
        Self {
            normal: Arc::new(RateLimiter::keyed(normal_quota)),
            draconian: Arc::new(RateLimiter::keyed(draconian_quota)),
            trusted_ua_secret,
        }
    }
}

fn too_many_requests(retry_after_secs: u64) -> Response {
    let body = serde_json::json!({
        "code": 429,
        "message": "Rate limit exceeded. Set a self-identifying User-Agent header (e.g. \"YourApp/1.0 (contact@example.com)\") for a higher limit.",
        "module": "rate_limit",
        "data": null,
        "dependencies": { "modules": {} }
    });
    let mut resp = (StatusCode::TOO_MANY_REQUESTS, axum::Json(body)).into_response();
    if let Ok(val) = HeaderValue::from_str(&retry_after_secs.to_string()) {
        resp.headers_mut().insert(header::RETRY_AFTER, val);
    }
    resp
}

/// §3.5/§3.6 first: a trusted first-party origin (local dev site,
/// mediumroast.io) OR a matching shared-secret `User-Agent`
/// (mediumroast.io only, additive - covers server-to-server calls with
/// no `Origin`/`Referer` at all) skips the limiter entirely, before
/// either tier's quota is ever touched. Otherwise picks a tier from
/// the request's `User-Agent` header, checks the matching keyed
/// limiter for the caller's IP (from `ConnectInfo`, requires
/// `into_make_service_with_connect_info::<SocketAddr>()` - see README
/// §4.4 on `PeerIpKeyExtractor` vs `SmartIpKeyExtractor`, not yet
/// decided which this should use in the real implementation), and
/// either forwards the request or returns a 429 with `Retry-After`.
pub async fn tiered_rate_limit(
    State(state): State<TieredLimiterState>,
    ConnectInfo(addr): ConnectInfo<std::net::SocketAddr>,
    request: Request<Body>,
    next: Next,
) -> Response {
    let origin = request
        .headers()
        .get(header::ORIGIN)
        .and_then(|v| v.to_str().ok());
    let referer = request
        .headers()
        .get(header::REFERER)
        .and_then(|v| v.to_str().ok());
    let ua = request
        .headers()
        .get(header::USER_AGENT)
        .and_then(|v| v.to_str().ok());

    if trusted_origin::is_trusted(origin, referer) {
        return next.run(request).await;
    }
    if secret_ua::is_trusted(ua, state.trusted_ua_secret.as_deref(), chrono::Utc::now()) {
        return next.run(request).await;
    }

    let tier = classify(ua);
    let limiter = match tier {
        Tier::Normal => &state.normal,
        Tier::Draconian => &state.draconian,
    };
    let ip = addr.ip();
    match limiter.check_key(&ip) {
        Ok(_) => next.run(request).await,
        Err(not_until) => {
            let wait = not_until.wait_time_from(governor::clock::DefaultClock::default().now());
            too_many_requests(wait.as_secs().max(1))
        }
    }
}
