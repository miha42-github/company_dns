//! Dynamic log level - `docs/plans/v4-dynamic-log-level.md`. Real
//! structured logging (`tracing`, replacing `println!`/`eprintln!` -
//! §4.1) with a level that can be raised or lowered on a live process
//! via a K8s ConfigMap-mounted file, no restart. Promoted from
//! `experiments/dynamic-log-level-spike/`, shipping the **polling**
//! strategy that spike confirmed working (§4.4's own leaning): it
//! sidesteps K8s ConfigMap mounts' symlink-swap semantics entirely (no
//! platform-specific filesystem-event backend to trust - the spike's
//! `notify`-based parent-directory-watch variant was also confirmed
//! working, but only on macOS; polling needed nothing backend-specific
//! to prove), and the use case (a human toggling a level during an
//! incident) doesn't need sub-second reaction time.

use std::path::PathBuf;
use std::time::Duration;

use tracing_subscriber::{prelude::*, reload, EnvFilter, Registry};

pub type ReloadHandle = reload::Handle<EnvFilter, Registry>;

/// §4.3: env var supplies the starting level before the ConfigMap
/// mount's first read, and the fallback if the mount is ever missing,
/// unreadable, or malformed. `RUST_LOG` - the `tracing` ecosystem's
/// own conventional name, not a company_dns-specific one, so it also
/// works the way anyone familiar with `tracing`-based Rust services
/// already expects.
const STARTUP_ENV_VAR: &str = "RUST_LOG";
const DEFAULT_LEVEL: &str = "warn";

/// §4.5: the ConfigMap-mounted file's path, itself overridable (e.g.
/// for local `cargo run`, where no mount exists at all - startup must
/// never fail or block waiting on it, per §4.3). Must NOT be mounted
/// via K8s `subPath` in the deployment manifest - `subPath` bind-mounts
/// the individual file at container creation and never updates when
/// the ConfigMap changes, which would silently defeat the entire
/// point of this module. The whole ConfigMap must be mounted as a
/// directory, with this path pointing at the key's file inside it.
const CONFIG_PATH_ENV_VAR: &str = "LOG_LEVEL_CONFIG_PATH";
const DEFAULT_CONFIG_PATH: &str = "/etc/company-dns-log-level/log-level";

/// Sets up the real subscriber - replacing the total absence of one
/// this doc's §1 found (`TraceLayer`'s own request/response events
/// were being generated and silently dropped, with no subscriber to
/// consume them) - with a reloadable filter. Call once, at the very
/// start of `main()`, before anything else logs.
pub fn init() -> ReloadHandle {
    let startup_level =
        std::env::var(STARTUP_ENV_VAR).unwrap_or_else(|_| DEFAULT_LEVEL.to_string());
    let (filter, handle) = reload::Layer::new(EnvFilter::new(&startup_level));
    tracing_subscriber::registry()
        .with(filter)
        .with(tracing_subscriber::fmt::layer())
        .init();
    handle
}

/// §4.4/§4.5: polls the ConfigMap-mounted file every `interval`,
/// reloading the active filter only when the content actually
/// changes. Spawned once at startup, never awaited - runs for the
/// life of the process, mirroring `rate_limit.rs`'s
/// `spawn_periodic_sweep` in this same crate. A missing or unreadable
/// mount is not an error worth logging repeatedly (§4.3's "never fail
/// or block" extends to "never spam" here too) - the startup level
/// simply stays in effect until the mount, if one ever appears,
/// becomes readable.
pub fn spawn_config_watch(handle: ReloadHandle, interval: Duration) {
    let config_path: PathBuf = std::env::var(CONFIG_PATH_ENV_VAR)
        .unwrap_or_else(|_| DEFAULT_CONFIG_PATH.to_string())
        .into();
    tokio::spawn(async move {
        let mut last_value = tokio::fs::read_to_string(&config_path).await.ok();
        let mut ticker = tokio::time::interval(interval);
        loop {
            ticker.tick().await;
            let Ok(current) = tokio::fs::read_to_string(&config_path).await else {
                continue;
            };
            if Some(&current) != last_value.as_ref() {
                let new_level = current.trim();
                match handle.reload(EnvFilter::new(new_level)) {
                    Ok(_) => {
                        tracing::info!(new_level, path = %config_path.display(), "log level reloaded");
                    }
                    Err(error) => {
                        tracing::warn!(%error, new_level, "failed to reload log level");
                    }
                }
                last_value = Some(current);
            }
        }
    });
}
