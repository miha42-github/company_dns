//! Tiered rate limiting - `docs/plans/v4-security-hardening.md` §3.2,
//! built on `experiments/rate-limit-spike/`'s proven design: two
//! independent `governor` keyed rate limiters (one per tier) selected
//! per-request by `user_agent::classify` (a self-identifying
//! `User-Agent` gets the normal tier, anything else the draconian one),
//! checked only after the trusted-origin bypass (§3.4) has had a chance
//! to skip the limiter. The rolling shared-secret `User-Agent` bypass
//! (§3.5) was removed 2026-10-05: authenticated callers are the profiles
//! mechanism's job (`docs/plans/v4-sql-endpoint.md` §5a), not a secret
//! hidden in the `User-Agent`.
//!
//! `tower_governor::GovernorLayer` is deliberately NOT used here - it
//! only supports one fixed quota per layer instance, with no
//! per-request hook to pick a different quota based on a header
//! (confirmed in the spike, `experiments/rate-limit-spike/README.md`
//! "Why governor directly, not GovernorLayer"). This module owns
//! `governor::RateLimiter::keyed(quota)` instances directly instead.

use std::net::{IpAddr, SocketAddr};
use std::num::NonZeroU32;
use std::sync::Arc;
use std::time::Duration;

use axum::{
    body::Body,
    extract::{ConnectInfo, State},
    http::{header, HeaderMap, Request},
    middleware::Next,
    response::{IntoResponse, Response},
};
use governor::{clock::Clock, DefaultKeyedRateLimiter, Quota, RateLimiter};

use crate::envelope::too_many_requests;
use crate::trusted_origin;
use crate::user_agent::{classify, Tier};

/// This deployment runs a fixed 4 replicas behind a Service/Ingress
/// that load-balances across them (`k8s/prod/deployment.yaml`'s
/// `replicas: 4`, itself a deliberate ceiling per
/// `docs/plans/performance-improvements.md` item 3 - don't raise
/// either number without revisiting the other). `governor`'s rate
/// limiter state is in-process, not shared across pods
/// (`docs/plans/v4-security-hardening.md` §6's "in-memory vs. shared
/// quota storage" - accepted for now, same limitation V3's `slowapi`
/// config would have had if it were actually wired up). Dividing the
/// intended aggregate quota by the replica count here means a client
/// hitting different pods on different requests still sees roughly
/// the intended fleet-wide ceiling, instead of each pod independently
/// granting the full quota (which would let the *effective* ceiling
/// drift to `REPLICA_COUNT`x the intended one). This drifts back out
/// of sync if `replicas` changes without updating this constant too.
const REPLICA_COUNT: u32 = 4;

/// docs/plans/v4-security-hardening.md §3.2: intended fleet-wide
/// aggregate quotas, adopting V3's own never-enforced `RATE_LIMITS`
/// baseline shape (`lib/rate_limiter.py:22-37`) for the normal tier.
/// Divided by `REPLICA_COUNT` below to get the actual per-pod quota.
const NORMAL_QUOTA_PER_MINUTE: u32 = 200;
const NORMAL_BURST: u32 = 20;
const DRACONIAN_QUOTA_PER_MINUTE: u32 = 5;
const DRACONIAN_BURST: u32 = 1;

fn per_pod(aggregate: u32) -> NonZeroU32 {
    // Integer division rounds down; NonZeroU32 floors at 1 rather than
    // ever landing on a 0/min quota that would silently block every
    // request in that tier.
    NonZeroU32::new((aggregate / REPLICA_COUNT).max(1)).expect("max(1) is never zero")
}

#[derive(Clone)]
pub struct TieredLimiterState {
    normal: Arc<DefaultKeyedRateLimiter<IpAddr>>,
    draconian: Arc<DefaultKeyedRateLimiter<IpAddr>>,
}

impl TieredLimiterState {
    pub fn new() -> Self {
        let normal_quota =
            Quota::per_minute(per_pod(NORMAL_QUOTA_PER_MINUTE)).allow_burst(per_pod(NORMAL_BURST));
        let draconian_quota = Quota::per_minute(per_pod(DRACONIAN_QUOTA_PER_MINUTE))
            .allow_burst(per_pod(DRACONIAN_BURST));
        Self {
            normal: Arc::new(RateLimiter::keyed(normal_quota)),
            draconian: Arc::new(RateLimiter::keyed(draconian_quota)),
        }
    }

    /// §6's "governor keyed-limiter eviction" open question: without
    /// this, a long-running server accumulates one bucket per distinct
    /// IP per tier forever. Spawned once at startup (`main.rs`), never
    /// awaited - runs for the life of the process.
    pub fn spawn_periodic_sweep(&self, interval: Duration) {
        let normal = Arc::clone(&self.normal);
        let draconian = Arc::clone(&self.draconian);
        tokio::spawn(async move {
            let mut ticker = tokio::time::interval(interval);
            loop {
                ticker.tick().await;
                normal.retain_recent();
                draconian.retain_recent();
            }
        });
    }
}

/// Extracts the real client IP for rate-limit keying. This deployment
/// sits behind Traefik (`k8s/prod/ingress.yaml`) as the sole external
/// edge - the Service is `ClusterIP`-only (`k8s/prod/service.yaml`),
/// unreachable from outside the cluster except through that Ingress -
/// so `X-Forwarded-For` (Traefik's own append, not a client-supplied
/// value it blindly forwards) is trustworthy for external traffic.
/// Takes the *last* (rightmost) entry specifically: that's the one
/// nearest proxy (Traefik) appended based on the TCP peer it actually
/// saw, not whatever a client may have pre-populated the header with
/// to try to spoof an earlier entry. `X-Real-Ip` is a secondary
/// fallback (also Traefik-set), and the raw `ConnectInfo` peer address
/// is the final fallback for traffic that reaches the pod without
/// going through Traefik at all (e.g. `kubectl port-forward`, or
/// direct-to-pod traffic from elsewhere in the cluster - out of scope
/// for this pass, `docs/plans/v4-security-hardening.md` §7).
pub(crate) fn client_ip(headers: &HeaderMap, peer: SocketAddr) -> IpAddr {
    if let Some(xff) = headers.get("x-forwarded-for").and_then(|v| v.to_str().ok()) {
        if let Some(ip) = xff
            .rsplit(',')
            .find_map(|s| s.trim().parse::<IpAddr>().ok())
        {
            return ip;
        }
    }
    if let Some(xri) = headers.get("x-real-ip").and_then(|v| v.to_str().ok()) {
        if let Ok(ip) = xri.trim().parse::<IpAddr>() {
            return ip;
        }
    }
    peer.ip()
}

/// §3.4 first: a trusted first-party origin (local dev site,
/// mediumroast.io) skips the limiter entirely, before either tier's
/// quota is ever touched. Otherwise picks a tier from
/// the request's `User-Agent` header, checks the matching keyed
/// limiter for the caller's IP, and either forwards the request or
/// returns a 429 with `Retry-After`.
pub async fn tiered_rate_limit(
    State(state): State<TieredLimiterState>,
    ConnectInfo(peer): ConnectInfo<SocketAddr>,
    request: Request<Body>,
    next: Next,
) -> Response {
    let headers = request.headers();
    let origin = headers.get(header::ORIGIN).and_then(|v| v.to_str().ok());
    let referer = headers.get(header::REFERER).and_then(|v| v.to_str().ok());
    let ua = headers
        .get(header::USER_AGENT)
        .and_then(|v| v.to_str().ok());

    if trusted_origin::is_trusted(origin, referer) {
        return next.run(request).await;
    }

    let tier = classify(ua);
    let limiter = match tier {
        Tier::Normal => &state.normal,
        Tier::Draconian => &state.draconian,
    };
    let ip = client_ip(headers, peer);
    match limiter.check_key(&ip) {
        Ok(_) => next.run(request).await,
        Err(not_until) => {
            let wait = not_until.wait_time_from(governor::clock::DefaultClock::default().now());
            too_many_requests(
                "rate_limit",
                "Rate limit exceeded. Set a self-identifying User-Agent header \
                 (e.g. \"YourApp/1.0 (contact@example.com)\") for a higher limit.",
                wait.as_secs().max(1),
            )
            .into_response()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{extract::ConnectInfo, middleware, routing::get, Router};
    use axum::http::StatusCode;
    use tower::ServiceExt;

    fn app() -> Router {
        Router::new()
            .route("/x", get(|| async { "ok" }))
            .layer(middleware::from_fn_with_state(TieredLimiterState::new(), tiered_rate_limit))
    }

    async fn hit(app: &Router, ua: Option<&str>, origin: Option<&str>) -> StatusCode {
        let mut b = Request::builder().uri("/x");
        if let Some(ua) = ua {
            b = b.header(header::USER_AGENT, ua);
        }
        if let Some(o) = origin {
            b = b.header(header::ORIGIN, o);
        }
        let mut req = b.body(Body::empty()).unwrap();
        req.extensions_mut().insert(ConnectInfo::<SocketAddr>("10.0.0.1:1".parse().unwrap()));
        app.clone().oneshot(req).await.unwrap().status()
    }

    #[tokio::test]
    async fn no_user_agent_gets_the_draconian_tier() {
        let a = app();
        assert_eq!(hit(&a, None, None).await, StatusCode::OK);
        assert_eq!(hit(&a, None, None).await, StatusCode::TOO_MANY_REQUESTS);
    }

    #[tokio::test]
    async fn self_identifying_user_agent_gets_the_normal_tier() {
        let a = app();
        let ua = Some("YourApp/1.0 (contact@example.com)");
        // far past the draconian burst of 1: the normal tier is a separate, larger bucket
        for i in 0..4 {
            assert_eq!(hit(&a, ua, None).await, StatusCode::OK, "request {i}");
        }
    }

    #[tokio::test]
    async fn the_two_tiers_are_independent_buckets() {
        let a = app();
        assert_eq!(hit(&a, None, None).await, StatusCode::OK);
        assert_eq!(hit(&a, None, None).await, StatusCode::TOO_MANY_REQUESTS);
        assert_eq!(hit(&a, Some("YourApp/1.0 (contact@example.com)"), None).await, StatusCode::OK);
    }

    #[tokio::test]
    async fn an_hmac_looking_user_agent_is_no_longer_a_bypass() {
        let a = app();
        let hex = "a".repeat(64);
        assert_eq!(hit(&a, Some(&hex), None).await, StatusCode::OK);
        assert_eq!(hit(&a, Some(&hex), None).await, StatusCode::TOO_MANY_REQUESTS, "treated as an ordinary draconian caller");
    }

    #[tokio::test]
    async fn trusted_origin_still_skips_the_limiter() {
        let a = app();
        for _ in 0..30 {
            assert_eq!(hit(&a, None, Some("https://mediumroast.io")).await, StatusCode::OK);
        }
    }
}
