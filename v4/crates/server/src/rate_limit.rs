//! Tiered rate limiting - `docs/plans/v4-security-hardening.md` §3.2,
//! built on `experiments/rate-limit-spike/`'s proven design: two
//! independent `governor` keyed rate limiters (one per tier) selected
//! per-request by `user_agent::classify` (a self-identifying
//! `User-Agent` gets the normal tier, anything else the draconian one),
//! checked only after the trusted-origin bypass (§3.4) has had a chance
//! to skip the limiter. The rolling shared-secret `User-Agent` bypass
//! (§3.5) was removed 2026-10-05. Authenticated callers are the profiles
//! mechanism's job (`access.rs`, `docs/plans/v4-sql-endpoint.md` §5a):
//! HTTP Basic Auth identifies a profile, and its `rate_limit` grant is
//! either no limit at all or a quota of its own, replacing the tiers. A
//! profile with no grant is an identified caller and gets the normal tier;
//! a wrong credential is a 401, never silently anonymous.
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
use governor::{clock::Clock, DefaultDirectRateLimiter, DefaultKeyedRateLimiter, Quota, RateLimiter};
use std::collections::HashMap;

use crate::access::{Access, Identity, RateLimitGrant};
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

pub(crate) fn per_pod(aggregate: u32) -> NonZeroU32 {
    // Integer division rounds down; NonZeroU32 floors at 1 rather than
    // ever landing on a 0/min quota that would silently block every
    // request in that tier.
    NonZeroU32::new((aggregate / REPLICA_COUNT).max(1)).expect("max(1) is never zero")
}

#[derive(Clone)]
pub struct TieredLimiterState {
    normal: Arc<DefaultKeyedRateLimiter<IpAddr>>,
    draconian: Arc<DefaultKeyedRateLimiter<IpAddr>>,
    /// Whether a trusted `Origin`/`Referer` skips the limiter. True for the lookup routes;
    /// false for the SQL route, where a client-set header must never be a bypass.
    trust_origin: bool,
    /// Profiles; `None` when no profiles file is configured (everyone is anonymous).
    access: Option<Arc<Access>>,
    /// One bucket per profile whose `rate_limit` grant is a quota (keyed by profile, not IP).
    profile_quotas: Arc<HashMap<String, DefaultDirectRateLimiter>>,
}

impl TieredLimiterState {
    pub fn new(access: Option<Arc<Access>>) -> Self {
        let normal_quota =
            Quota::per_minute(per_pod(NORMAL_QUOTA_PER_MINUTE)).allow_burst(per_pod(NORMAL_BURST));
        let draconian_quota = Quota::per_minute(per_pod(DRACONIAN_QUOTA_PER_MINUTE))
            .allow_burst(per_pod(DRACONIAN_BURST));
        let mut profile_quotas = HashMap::new();
        if let Some(access) = &access {
            for (id, grant) in access.profiles().rate_limit_grants() {
                if let RateLimitGrant::Quota { per_minute, burst } = grant {
                    // fleet-wide numbers, divided across replicas like the tiers
                    let quota = Quota::per_minute(per_pod(per_minute)).allow_burst(per_pod(burst));
                    profile_quotas.insert(id.to_string(), RateLimiter::direct(quota));
                }
            }
        }
        Self {
            normal: Arc::new(RateLimiter::keyed(normal_quota)),
            draconian: Arc::new(RateLimiter::keyed(draconian_quota)),
            trust_origin: true,
            access,
            profile_quotas: Arc::new(profile_quotas),
        }
    }

    /// The same buckets (so SQL requests count against the same per-IP and per-profile
    /// limits as lookups), but a trusted `Origin`/`Referer` is not a bypass. Used for the
    /// SQL route.
    pub fn without_origin_trust(&self) -> Self {
        Self { trust_origin: false, ..self.clone() }
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

    if state.trust_origin && trusted_origin::is_trusted(origin, referer) {
        return next.run(request).await;
    }

    let ip = client_ip(headers, peer);
    let mut identified = false;
    if let Some(access) = &state.access {
        match access.identify(headers, ip) {
            Identity::Anonymous => {}
            Identity::Rejected(response) => return response,
            Identity::Profile { id, profile } => {
                identified = true;
                match profile.rate_limit {
                    Some(RateLimitGrant::Bypass) => return next.run(request).await,
                    Some(RateLimitGrant::Quota { .. }) => {
                        let Some(limiter) = state.profile_quotas.get(&id) else {
                            return next.run(request).await; // unreachable: built from the same profiles
                        };
                        return match limiter.check() {
                            Ok(_) => next.run(request).await,
                            Err(not_until) => {
                                let wait = not_until.wait_time_from(governor::clock::DefaultClock::default().now());
                                too_many_requests(
                                    "rate_limit",
                                    "This profile's rate limit was exceeded.",
                                    wait.as_secs().max(1),
                                )
                                .into_response()
                            }
                        };
                    }
                    None => {} // identified, no grant: the normal tier below
                }
            }
        }
    }

    let tier = if identified { Tier::Normal } else { classify(ua) };
    let limiter = match tier {
        Tier::Normal => &state.normal,
        Tier::Draconian => &state.draconian,
    };
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
    use crate::access::{tests::token_hash, Profiles};
    use axum::http::StatusCode;
    use axum::{extract::ConnectInfo, middleware, routing::get, Router};
    use base64::Engine;
    use tower::ServiceExt;

    /// Profiles: `unlimited` (bypass), `capped` (20/min fleet-wide = 5 per pod), `plain` (no
    /// rate_limit grant). Every token is "tok".
    fn profiles() -> Arc<Access> {
        let h = token_hash("tok");
        Arc::new(Access::new(
            Profiles::parse(&format!(
                r#"{{"profiles": {{
                    "unlimited": {{"secret_sha256": "{h}", "rate_limit": {{"bypass": true}}}},
                    "capped":    {{"secret_sha256": "{h}", "rate_limit": {{"requests_per_minute": 20, "burst": 20}}}},
                    "plain":     {{"secret_sha256": "{h}"}}
                }}}}"#
            ))
            .unwrap(),
        ))
    }

    fn app_with(access: Option<Arc<Access>>) -> Router {
        Router::new()
            .route("/x", get(|| async { "ok" }))
            .layer(middleware::from_fn_with_state(TieredLimiterState::new(access), tiered_rate_limit))
    }

    fn app() -> Router {
        app_with(None)
    }

    fn basic(id: &str, token: &str) -> String {
        format!("Basic {}", base64::engine::general_purpose::STANDARD.encode(format!("{id}:{token}")))
    }

    async fn hit_as(app: &Router, ua: Option<&str>, origin: Option<&str>, auth: Option<String>) -> StatusCode {
        let mut b = Request::builder().uri("/x");
        if let Some(ua) = ua {
            b = b.header(header::USER_AGENT, ua);
        }
        if let Some(o) = origin {
            b = b.header(header::ORIGIN, o);
        }
        if let Some(a) = auth {
            b = b.header(header::AUTHORIZATION, a);
        }
        let mut req = b.body(Body::empty()).unwrap();
        req.extensions_mut().insert(ConnectInfo::<SocketAddr>("10.0.0.1:1".parse().unwrap()));
        app.clone().oneshot(req).await.unwrap().status()
    }

    async fn hit(app: &Router, ua: Option<&str>, origin: Option<&str>) -> StatusCode {
        hit_as(app, ua, origin, None).await
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

    // --- profiles ---

    #[tokio::test]
    async fn a_bypass_profile_is_never_limited() {
        let a = app_with(Some(profiles()));
        for _ in 0..50 {
            assert_eq!(hit_as(&a, None, None, Some(basic("unlimited", "tok"))).await, StatusCode::OK);
        }
    }

    #[tokio::test]
    async fn a_quota_profile_gets_its_own_bucket() {
        let a = app_with(Some(profiles())); // 20/min fleet-wide, 4 replicas: 5 per pod
        let capped = || Some(basic("capped", "tok"));
        for i in 0..5 {
            assert_eq!(hit_as(&a, None, None, capped()).await, StatusCode::OK, "request {i}");
        }
        assert_eq!(hit_as(&a, None, None, capped()).await, StatusCode::TOO_MANY_REQUESTS);
        // the quota is the profile's: anonymous callers and other profiles are unaffected
        assert_eq!(hit(&a, None, None).await, StatusCode::OK);
        assert_eq!(hit_as(&a, None, None, Some(basic("unlimited", "tok"))).await, StatusCode::OK);
    }

    #[tokio::test]
    async fn an_identified_profile_without_a_grant_gets_the_normal_tier() {
        let a = app_with(Some(profiles()));
        // a generic User-Agent would be draconian (1 request); an identified caller is not
        for i in 0..4 {
            assert_eq!(hit_as(&a, Some("curl/8.4.0"), None, Some(basic("plain", "tok"))).await, StatusCode::OK, "request {i}");
        }
    }

    #[tokio::test]
    async fn a_wrong_credential_is_a_401_not_silently_anonymous() {
        let a = app_with(Some(profiles()));
        assert_eq!(hit_as(&a, None, None, Some(basic("capped", "wrong"))).await, StatusCode::UNAUTHORIZED);
        assert_eq!(hit_as(&a, None, None, Some(basic("nobody", "tok"))).await, StatusCode::UNAUTHORIZED);
        assert_eq!(hit_as(&a, None, None, Some("Basic !!!".to_string())).await, StatusCode::UNAUTHORIZED);
    }

    #[tokio::test]
    async fn without_profiles_a_basic_header_is_just_ignored() {
        let a = app_with(None);
        assert_eq!(hit_as(&a, None, None, Some(basic("unlimited", "tok"))).await, StatusCode::OK);
        assert_eq!(hit_as(&a, None, None, Some(basic("unlimited", "tok"))).await, StatusCode::TOO_MANY_REQUESTS, "still the draconian tier");
    }

    #[tokio::test]
    async fn another_authorization_scheme_is_not_ours() {
        let a = app_with(Some(profiles()));
        assert_eq!(hit_as(&a, None, None, Some("Bearer abc".to_string())).await, StatusCode::OK);
        assert_eq!(hit_as(&a, None, None, Some("Bearer abc".to_string())).await, StatusCode::TOO_MANY_REQUESTS, "anonymous, draconian");
    }

    #[tokio::test]
    async fn the_sql_style_layer_ignores_a_forged_origin_and_shares_the_buckets() {
        let state = TieredLimiterState::new(Some(profiles()));
        let lookups = Router::new()
            .route("/x", get(|| async { "ok" }))
            .layer(middleware::from_fn_with_state(state.clone(), tiered_rate_limit));
        let sql = Router::new()
            .route("/x", get(|| async { "ok" }))
            .layer(middleware::from_fn_with_state(state.without_origin_trust(), tiered_rate_limit));
        // the lookup routes honour the Origin; the SQL route does not
        assert_eq!(hit_as(&lookups, None, Some("https://mediumroast.io"), None).await, StatusCode::OK);
        assert_eq!(hit_as(&lookups, None, Some("https://mediumroast.io"), None).await, StatusCode::OK);
        assert_eq!(hit_as(&sql, None, Some("https://mediumroast.io"), None).await, StatusCode::OK, "first draconian request");
        assert_eq!(hit_as(&sql, None, Some("https://mediumroast.io"), None).await, StatusCode::TOO_MANY_REQUESTS, "forged Origin is no bypass on SQL");
        // same bucket: that anonymous request also used up the lookup routes' draconian burst
        assert_eq!(hit(&lookups, None, None).await, StatusCode::TOO_MANY_REQUESTS);
        // a bypass profile is still unlimited on the SQL route's generic limit
        for _ in 0..10 {
            assert_eq!(hit_as(&sql, None, None, Some(basic("unlimited", "tok"))).await, StatusCode::OK);
        }
    }

    #[tokio::test]
    async fn trusted_origin_wins_even_over_a_bad_credential() {
        let a = app_with(Some(profiles()));
        assert_eq!(hit_as(&a, None, Some("https://mediumroast.io"), Some(basic("capped", "wrong"))).await, StatusCode::OK);
    }
}
