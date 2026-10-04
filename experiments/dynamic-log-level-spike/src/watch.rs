//! Two candidate strategies for `docs/plans/v4-dynamic-log-level.md`
//! §4.4 - proving live which one actually notices a K8s-style
//! ConfigMap update (`configmap_sim.rs`'s atomic symlink swap), rather
//! than assuming either way.

use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use notify::{RecursiveMode, Watcher};
use tracing_subscriber::reload::Handle;
use tracing_subscriber::EnvFilter;

/// Counts successful reloads, so the live test can prove the watcher
/// actually fired (not just that the server didn't crash).
pub static RELOAD_COUNT: AtomicU64 = AtomicU64::new(0);

fn apply<L, S>(handle: &Handle<L, S>, new_value: &str)
where
    L: From<EnvFilter> + 'static,
    S: 'static,
{
    match handle.reload(EnvFilter::new(new_value)) {
        Ok(_) => {
            RELOAD_COUNT.fetch_add(1, Ordering::SeqCst);
            eprintln!(
                "[watch] reloaded filter -> {new_value:?} (reload #{})",
                RELOAD_COUNT.load(Ordering::SeqCst)
            );
        }
        Err(e) => eprintln!("[watch] reload failed: {e}"),
    }
}

/// Strategy A: a `notify` watch on the mounted key file's PARENT
/// directory (not the file itself - §4.4's concern is specifically
/// that watching the file path directly can miss a `..data` symlink
/// re-point that never touches the file path's own directory entry).
pub fn spawn_notify_watch<L, S>(key_path: PathBuf, handle: Handle<L, S>)
where
    L: From<EnvFilter> + 'static + Send + Sync,
    S: 'static + Send + Sync,
{
    std::thread::spawn(move || {
        let parent = key_path
            .parent()
            .expect("key path has a parent")
            .to_path_buf();
        let (tx, rx) = std::sync::mpsc::channel();
        let mut watcher = notify::recommended_watcher(move |res| {
            let _ = tx.send(res);
        })
        .expect("failed to create notify watcher");
        watcher
            .watch(&parent, RecursiveMode::NonRecursive)
            .expect("failed to watch parent dir");
        eprintln!("[watch:notify] watching parent dir {parent:?}");

        let mut last_value = std::fs::read_to_string(&key_path).ok();
        for res in rx {
            let Ok(_event) = res else { continue };
            let Ok(current) = std::fs::read_to_string(&key_path) else {
                continue;
            };
            if Some(&current) != last_value.as_ref() {
                apply(&handle, current.trim());
                last_value = Some(current);
            }
        }
    });
}

/// Strategy B: dead-simple polling - read the file every `interval`,
/// compare to the last-seen value, reload only on an actual change.
/// No dependency on filesystem-event semantics at all, so it can't be
/// fooled by the symlink-swap mechanism - it just re-reads through
/// whatever the current symlink chain resolves to, same as any normal
/// file read.
pub fn spawn_polling_watch<L, S>(key_path: PathBuf, handle: Handle<L, S>, interval: Duration)
where
    L: From<EnvFilter> + 'static + Send + Sync,
    S: 'static + Send + Sync,
{
    let handle = Arc::new(handle);
    tokio::spawn(async move {
        let mut last_value = tokio::fs::read_to_string(&key_path).await.ok();
        eprintln!("[watch:poll] polling {key_path:?} every {interval:?}");
        let mut ticker = tokio::time::interval(interval);
        loop {
            ticker.tick().await;
            let Ok(current) = tokio::fs::read_to_string(&key_path).await else {
                continue;
            };
            if Some(&current) != last_value.as_ref() {
                apply(&handle, current.trim());
                last_value = Some(current);
            }
        }
    });
}
