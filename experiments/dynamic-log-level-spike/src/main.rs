mod configmap_sim;
mod watch;

use std::time::Duration;

use axum::{routing::get, Router};
use configmap_sim::SimulatedConfigMapMount;
use tower_http::trace::TraceLayer;
use tracing_subscriber::{prelude::*, reload, EnvFilter};

async fn probe() -> &'static str {
    tracing::debug!("probe: this is a DEBUG-level line");
    tracing::info!("probe: this is an INFO-level line");
    tracing::warn!("probe: this is a WARN-level line");
    "probed - check stdout for which levels appeared"
}

async fn reload_count() -> String {
    watch::RELOAD_COUNT
        .load(std::sync::atomic::Ordering::SeqCst)
        .to_string()
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // §4.2: the reloadable filter, set up once at startup. Starts at
    // "warn" deliberately - same starting point v4-dynamic-log-level.md
    // §4.3 describes, so the live test can prove DEBUG lines are truly
    // absent before the first reload and truly present after.
    let (filter, reload_handle) = reload::Layer::new(EnvFilter::new("warn"));
    tracing_subscriber::registry()
        .with(filter)
        .with(tracing_subscriber::fmt::layer())
        .init();

    // §4.5: a real simulated ConfigMap mount (configmap_sim.rs),
    // starting at the same "warn" the filter above starts at.
    let mount_dir = std::env::temp_dir().join("dynamic-log-level-spike-configmap");
    let _ = std::fs::remove_dir_all(&mount_dir); // clean slate on each run
    let mount = SimulatedConfigMapMount::create(mount_dir.clone(), "log-level", "warn")?;
    println!(
        "Simulated ConfigMap mount at {:?} (key path: {:?})",
        mount_dir,
        mount.key_path()
    );

    // §4.4: pick the watch strategy via env var so both can be
    // exercised live without recompiling. Default: poll - see
    // docs/plans/v4-dynamic-log-level.md §4.4's leaning, this spike's
    // job is to confirm or overturn that leaning with real evidence.
    let strategy = std::env::var("WATCH_STRATEGY").unwrap_or_else(|_| "poll".to_string());
    match strategy.as_str() {
        "notify" => {
            println!("Using WATCH_STRATEGY=notify");
            watch::spawn_notify_watch(mount.key_path(), reload_handle);
        }
        "poll" => {
            println!("Using WATCH_STRATEGY=poll");
            watch::spawn_polling_watch(mount.key_path(), reload_handle, Duration::from_secs(2));
        }
        other => anyhow::bail!("unknown WATCH_STRATEGY: {other}"),
    }

    // A tiny CLI helper for the live test to trigger a ConfigMap
    // "edit" without needing a real cluster - writes through the same
    // SimulatedConfigMapMount::update path a second process could also
    // call, but simplest as an HTTP trigger here.
    let mount_dir_for_route = mount_dir.clone();
    let app = Router::new()
        .route("/probe", get(probe))
        .route("/reload-count", get(reload_count))
        .route(
            "/simulate-configmap-edit/{level}",
            get(
                move |axum::extract::Path(level): axum::extract::Path<String>| {
                    let mount_dir = mount_dir_for_route.clone();
                    async move {
                        let mount = SimulatedConfigMapMount {
                            mount_dir,
                            key: "log-level".to_string(),
                        };
                        match mount.update(&level) {
                            Ok(_) => format!("simulated ConfigMap edit -> {level:?}"),
                            Err(e) => format!("failed: {e}"),
                        }
                    }
                },
            ),
        )
        .layer(TraceLayer::new_for_http());

    let addr: std::net::SocketAddr = "127.0.0.1:4300".parse()?;
    println!("dynamic-log-level-spike listening on http://{addr}");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
