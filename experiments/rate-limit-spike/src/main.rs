mod secret_ua;
mod tiered_limit;
mod trusted_origin;
mod user_agent;

use std::net::SocketAddr;

use axum::{extract::State, middleware, routing::get, Router};
use tiered_limit::TieredLimiterState;
use tower_governor::{governor::GovernorConfigBuilder, GovernorLayer};

/// Real implementation would read `MEDIUMROAST_SHARED_SECRET` (§3.5)
/// from its own K8s Secret and fail closed (no bypass) if it's unset
/// in production - unlike a hash, this *is* the raw secret, because
/// §3.5's rolling HMAC design needs it to recompute the expected token
/// fresh every request. This spike falls back to a fixed test secret
/// so the bypass is exercisable without any env var setup - never the
/// shape of the real deploy, just a convenience for `cargo run`.
fn load_trusted_ua_secret() -> Option<String> {
    if let Ok(secret) = std::env::var("MEDIUMROAST_SHARED_SECRET") {
        return Some(secret);
    }
    const SPIKE_TEST_SECRET: &str = "mr-io-spike-test-secret-do-not-use-in-prod";
    println!(
        "MEDIUMROAST_SHARED_SECRET not set - using spike test secret \
         \"{SPIKE_TEST_SECRET}\" for the §3.5 rolling-token bypass demo. \
         Compute today's token with: \
         printf '%s' \"$(date -u +%Y-%m-%dT%HZ)\" | openssl dgst -sha256 -hmac \"{SPIKE_TEST_SECRET}\""
    );
    Some(SPIKE_TEST_SECRET.to_string())
}

async fn ping() -> &'static str {
    "pong"
}

/// Smoke-tests `docs/plans/v4-security-hardening.md` §4's step 1:
/// confirm `tower_governor` 0.8's `axum` feature actually builds and
/// 429s against this workspace's real axum 0.8 / tower 0.5 versions,
/// not just crates.io's declared semver ranges. NOT the design being
/// promoted - see README "Why governor directly, not GovernorLayer".
async fn basic_governed() -> &'static str {
    "governed-pong"
}

async fn tiered_status(State(state): State<TieredLimiterState>) -> &'static str {
    let _ = state;
    "tiered-pong"
}

fn build_router() -> Router {
    let governor_conf = GovernorConfigBuilder::default()
        .per_second(2)
        .burst_size(3)
        .finish()
        .expect("valid governor config");

    let basic_router = Router::new()
        .route("/basic", get(basic_governed))
        .layer(GovernorLayer::new(governor_conf));

    let tiered_state = TieredLimiterState::new(load_trusted_ua_secret());
    let tiered_router = Router::new()
        .route("/ping", get(ping))
        .route("/tiered", get(tiered_status))
        .layer(middleware::from_fn_with_state(
            tiered_state.clone(),
            tiered_limit::tiered_rate_limit,
        ))
        .with_state(tiered_state);

    Router::new().merge(basic_router).merge(tiered_router)
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let app = build_router();
    let addr: SocketAddr = "127.0.0.1:4100".parse()?;
    println!("rate-limit-spike listening on http://{addr}");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .await?;
    Ok(())
}
