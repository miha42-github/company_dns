//! Simulates exactly how kubelet mounts and updates a ConfigMap volume,
//! for `docs/plans/v4-dynamic-log-level.md` §4.4/§5.2. No real K8s
//! cluster is reachable from this spike's environment, so this
//! reproduces the documented mechanism (kubelet's `AtomicWriter`)
//! directly with `std::fs`, rather than skipping the question or
//! assuming a `notify` watch "should" work.
//!
//! Layout kubelet actually creates:
//! ```text
//! <mount-dir>/
//!   ..data -> ..2024_01_01_00_00_00.123456789          (symlink)
//!   ..2024_01_01_00_00_00.123456789/
//!     log-level                                         (real file)
//!   log-level -> ..data/log-level                        (symlink)
//! ```
//! An update creates a NEW timestamped directory with the new content,
//! then atomically renames a freshly-created `..data_tmp` symlink over
//! `..data` (`rename()` on the same filesystem is atomic on Unix) -
//! the mounted `log-level` path itself is never written to directly;
//! only the `..data` symlink's target ever changes. This is exactly
//! the shape that can defeat a naive single-file `notify` watch.

use std::fs;
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

pub struct SimulatedConfigMapMount {
    pub mount_dir: PathBuf,
    pub key: String,
}

impl SimulatedConfigMapMount {
    /// Creates the initial mount, exactly matching kubelet's first-sync
    /// layout, with `key` (e.g. `"log-level"`) containing `initial_value`.
    pub fn create(mount_dir: PathBuf, key: &str, initial_value: &str) -> anyhow::Result<Self> {
        fs::create_dir_all(&mount_dir)?;
        let mount = Self {
            mount_dir,
            key: key.to_string(),
        };
        mount.write_generation(initial_value, true)?;
        Ok(mount)
    }

    /// The path the application actually reads/watches - stable across
    /// every update, same as what a real container sees.
    pub fn key_path(&self) -> PathBuf {
        self.mount_dir.join(&self.key)
    }

    /// Simulates `kubectl edit configmap` landing and kubelet re-syncing
    /// the mount: a brand new timestamped directory, a brand new
    /// `..data` symlink, atomically swapped in. Never touches the
    /// existing `..data` symlink or the timestamped directory it still
    /// points at until the swap itself.
    pub fn update(&self, new_value: &str) -> anyhow::Result<()> {
        self.write_generation(new_value, false)
    }

    fn write_generation(&self, value: &str, first: bool) -> anyhow::Result<()> {
        let now = SystemTime::now().duration_since(UNIX_EPOCH)?;
        let gen_name = format!("..{}_{}", now.as_secs(), now.subsec_nanos());
        let gen_dir = self.mount_dir.join(&gen_name);
        fs::create_dir(&gen_dir)?;
        fs::write(gen_dir.join(&self.key), value)?;

        let data_tmp = self.mount_dir.join("..data_tmp");
        let _ = fs::remove_file(&data_tmp); // stale leftover, ignore if absent
        symlink(&gen_name, &data_tmp)?;
        fs::rename(&data_tmp, self.mount_dir.join("..data"))?; // the atomic swap

        let key_link = self.key_path();
        if first {
            symlink(format!("..data/{}", self.key), &key_link)?;
        }
        // else: key_link already points through ..data, untouched -
        // exactly the property that can defeat a naive file watch.
        Ok(())
    }
}

/// Reads the current value by following the full symlink chain, the
/// way any normal file read would (no special-casing needed on the
/// reader's side - the indirection is transparent to `fs::read`).
/// Used by the tests below; `watch.rs`'s own watchers do their own
/// equivalent read inline.
#[allow(dead_code)]
pub fn read_current(key_path: &Path) -> anyhow::Result<String> {
    Ok(fs::read_to_string(key_path)?.trim().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn simulated_mount_reads_transparently_through_symlinks() {
        let dir = tempdir();
        let mount = SimulatedConfigMapMount::create(dir.clone(), "log-level", "warn").unwrap();
        assert_eq!(read_current(&mount.key_path()).unwrap(), "warn");
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn update_swaps_content_without_touching_the_stable_path() {
        let dir = tempdir();
        let mount = SimulatedConfigMapMount::create(dir.clone(), "log-level", "warn").unwrap();
        let stable_path = mount.key_path();
        assert!(stable_path.is_symlink());

        mount.update("debug").unwrap();
        assert_eq!(read_current(&stable_path).unwrap(), "debug");
        // The stable path is still a symlink (to ..data, unchanged
        // itself) - only ..data's own target moved.
        assert!(stable_path.is_symlink());
        std::fs::remove_dir_all(&dir).ok();
    }

    fn tempdir() -> PathBuf {
        let d = std::env::temp_dir().join(format!(
            "configmap-sim-test-{}-{:?}",
            std::process::id(),
            SystemTime::now()
        ));
        std::fs::create_dir_all(&d).unwrap();
        d
    }
}
