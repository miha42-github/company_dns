//! Where the `.feather` data files live - one convention shared by the
//! server and the `ingest-edgar` tool (`docs/plans/v4-deployment.md` §3.2).
//!
//! * `COMPANY_DNS_DATA_DIR` names one directory holding every data file
//!   under its standard name (`us_flat_embedded.feather`,
//!   `edgar_10x_catalog.feather`, ...). In the container image this is the
//!   directory the files are copied into; a volume mounted there replaces
//!   them. For now, in development, point it at the repo's top-level `tmp/`.
//! * A per-file variable (`SIC_DATA_PATH`, `EDGAR_CATALOG_PATH`, ...) still
//!   wins over the directory for that one file.
//! * With neither set, the default is the repo-root `tmp/` found from this
//!   source tree at compile time, so the result no longer depends on which
//!   directory the process happened to be started from (the old default was
//!   `../../tmp/...` relative to the working directory, and silently
//!   resolved to the wrong place from any other directory).

use std::path::PathBuf;

pub const DATA_DIR_ENV: &str = "COMPANY_DNS_DATA_DIR";

/// Standard file name of the EDGAR 10-x catalog inside the data directory.
pub const EDGAR_CATALOG_FILE: &str = "edgar_10x_catalog.feather";

/// The data directory: `COMPANY_DNS_DATA_DIR` if set and non-empty,
/// otherwise the repo-root `tmp/` this source tree sits in.
pub fn data_dir() -> PathBuf {
    match std::env::var(DATA_DIR_ENV) {
        Ok(dir) if !dir.trim().is_empty() => PathBuf::from(dir),
        _ => PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tmp"),
    }
}

/// The path for one data file: the per-file variable `env_var` if set and
/// non-empty, otherwise `file_name` inside [`data_dir`].
pub fn resolve(env_var: &str, file_name: &str) -> PathBuf {
    resolve_in(std::env::var(env_var).ok(), &data_dir(), file_name)
}

/// The pure part of [`resolve`], so it can be tested without touching the
/// process environment.
pub(crate) fn resolve_in(override_path: Option<String>, dir: &std::path::Path, file_name: &str) -> PathBuf {
    match override_path {
        Some(p) if !p.trim().is_empty() => PathBuf::from(p),
        _ => dir.join(file_name),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    #[test]
    fn per_file_override_beats_the_directory() {
        let dir = Path::new("/data");
        assert_eq!(resolve_in(None, dir, "a.feather"), Path::new("/data/a.feather"));
        assert_eq!(resolve_in(Some("".into()), dir, "a.feather"), Path::new("/data/a.feather"));
        assert_eq!(resolve_in(Some("  ".into()), dir, "a.feather"), Path::new("/data/a.feather"));
        assert_eq!(resolve_in(Some("/x/b.feather".into()), dir, "a.feather"), Path::new("/x/b.feather"));
    }

    #[test]
    fn the_default_directory_does_not_depend_on_the_working_directory() {
        // Compile-time anchored: absolute, and ends at the repo-level tmp/.
        let d = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tmp");
        assert!(d.is_absolute());
        assert!(d.ends_with("../../../tmp"));
    }
}
