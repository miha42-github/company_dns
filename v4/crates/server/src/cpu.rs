//! Startup preflight: which processor this is, and whether the ONNX Runtime this build uses can run on it.
//!
//! The embedding model runs on the ONNX Runtime (docs/plans/v4-release-to-staging.md, item I). A build links it one of two ways:
//!
//! - `ort-download` (the default for `cargo run`): pyke's prebuilt binaries, which need AVX2 on x86-64. Without it the process dies
//!   with an illegal-instruction signal, which a container shows as an unexplained crash loop.
//! - `ort-dynamic` (the Docker image): Microsoft's `libonnxruntime`, loaded from `ORT_DYLIB_PATH`. It picks its kernels at run time
//!   (AVX2, AVX-512 or plain SSE on x86-64, NEON on arm64), so it runs on 2013 Xeons and on new machines alike. The risk there is the
//!   wrong library for the machine (an x86-64 `.so` on an arm64 node, or a path that is not set), which this checks.
//!
//! The checks log one line describing the CPU and the runtime, and fail with a message that says what to do instead of crashing.

use std::path::Path;

/// ELF `e_machine` values for the two architectures V4 ships for.
pub const EM_X86_64: u16 = 62;
pub const EM_AARCH64: u16 = 183;

/// The ELF machine type in a file header, if it is an ELF file.
pub fn elf_machine(header: &[u8]) -> Option<u16> {
    if header.len() < 20 || &header[0..4] != b"\x7fELF" {
        return None;
    }
    let bytes = [header[18], header[19]];
    Some(if header[5] == 2 { u16::from_be_bytes(bytes) } else { u16::from_le_bytes(bytes) })
}

/// The ELF machine a library must have to run in a process of this architecture.
pub fn expected_machine(arch: &str) -> Option<u16> {
    match arch {
        "x86_64" => Some(EM_X86_64),
        "aarch64" => Some(EM_AARCH64),
        _ => None,
    }
}

fn machine_name(m: u16) -> String {
    match m {
        EM_X86_64 => "x86-64 (amd64)".into(),
        EM_AARCH64 => "aarch64 (arm64)".into(),
        other => format!("ELF machine {other}"),
    }
}

/// The CPU features that matter for the ONNX Runtime, as detected at run time.
pub fn features() -> Vec<(&'static str, bool)> {
    #[cfg(target_arch = "x86_64")]
    {
        vec![
            ("sse4.2", std::is_x86_feature_detected!("sse4.2")),
            ("avx", std::is_x86_feature_detected!("avx")),
            ("avx2", std::is_x86_feature_detected!("avx2")),
            ("fma", std::is_x86_feature_detected!("fma")),
            ("avx512f", std::is_x86_feature_detected!("avx512f")),
        ]
    }
    #[cfg(target_arch = "aarch64")]
    {
        vec![("neon", std::arch::is_aarch64_feature_detected!("neon"))]
    }
    #[cfg(not(any(target_arch = "x86_64", target_arch = "aarch64")))]
    {
        vec![]
    }
}

fn has(features: &[(&'static str, bool)], name: &str) -> bool {
    features.iter().any(|(n, on)| *n == name && *on)
}

/// What the runtime choice means for this machine. `dynamic` is whether the build loads `libonnxruntime` at run time; `lib` is the
/// first bytes of that library when it could be read (`None` when the path is unset or unreadable, with `lib_problem` saying why).
/// `elf` is whether libraries on this OS are ELF files (Linux), so a file that is not one is refused.
pub fn verdict(arch: &str, features: &[(&'static str, bool)], dynamic: bool, lib: Option<&[u8]>, lib_problem: Option<&str>, elf: bool) -> Result<(), String> {
    if dynamic {
        if let Some(problem) = lib_problem {
            return Err(format!(
                "this build loads the ONNX Runtime at run time but {problem}. The Docker image sets ORT_DYLIB_PATH=/opt/onnxruntime/lib/libonnxruntime.so; \
                 outside it, point ORT_DYLIB_PATH at Microsoft's libonnxruntime for this machine ({arch})."
            ));
        }
        if let (Some(bytes), Some(want)) = (lib, expected_machine(arch)) {
            match elf_machine(bytes) {
                None if elf => {
                    return Err("ORT_DYLIB_PATH does not point at an ONNX Runtime shared library (the file is not an ELF library). \
                                Check the path; the Docker image uses /opt/onnxruntime/lib/libonnxruntime.so.".to_string());
                }
                Some(got) if got != want => {
                    return Err(format!(
                        "the ONNX Runtime library is built for {} but this machine is {}. Use the library for {arch} (the image build picks it from the target platform; \
                         rebuild with --platform for this machine).",
                        machine_name(got),
                        machine_name(want)
                    ));
                }
                _ => {}
            }
        }
        return Ok(());
    }
    // pyke's prebuilt runtime: x86-64 needs AVX2; arm64 always has NEON.
    if arch == "x86_64" && !has(features, "avx2") {
        return Err("this build uses pyke's prebuilt ONNX Runtime, which needs a CPU with AVX2, and this CPU has none (it would die with an illegal instruction). \
                    Use the Docker image (it loads Microsoft's ONNX Runtime, which runs without AVX2), or build with `--no-default-features --features ort-dynamic` \
                    and set ORT_DYLIB_PATH.".to_string());
    }
    if arch == "aarch64" && !has(features, "neon") {
        return Err("this arm64 CPU reports no NEON, which the ONNX Runtime needs.".to_string());
    }
    Ok(())
}

/// Log the CPU and runtime in one line and refuse to start when the runtime cannot run here.
pub fn preflight() -> anyhow::Result<()> {
    let arch = std::env::consts::ARCH;
    let feats = features();
    let dynamic = cfg!(feature = "ort-dynamic");
    let (lib_head, lib_problem, lib_path) = if dynamic {
        match std::env::var("ORT_DYLIB_PATH") {
            Ok(p) if !p.trim().is_empty() => match read_head(Path::new(&p)) {
                Ok(h) => (Some(h), None, Some(p)),
                Err(e) => (None, Some(format!("ORT_DYLIB_PATH={p} cannot be read ({e})")), Some(p)),
            },
            _ => (None, Some("ORT_DYLIB_PATH is not set".to_string()), None),
        }
    } else {
        (None, None, None)
    };
    tracing::info!(
        "CPU: {arch}, features [{}]; ONNX Runtime: {}{}",
        feats.iter().map(|(n, on)| format!("{n}={}", if *on { "yes" } else { "no" })).collect::<Vec<_>>().join(" "),
        if dynamic { "loaded at run time (Microsoft's libonnxruntime)" } else { "pyke's prebuilt binaries" },
        lib_path.map(|p| format!(" from {p}")).unwrap_or_default(),
    );
    verdict(arch, &feats, dynamic, lib_head.as_deref(), lib_problem.as_deref(), cfg!(target_os = "linux")).map_err(|m| anyhow::anyhow!("preflight failed: {m}"))
}

fn read_head(path: &Path) -> std::io::Result<Vec<u8>> {
    use std::io::Read;
    let mut buf = vec![0u8; 64];
    let n = std::fs::File::open(path)?.read(&mut buf)?;
    buf.truncate(n);
    Ok(buf)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn elf(machine: u16, big_endian: bool) -> Vec<u8> {
        let mut h = vec![0u8; 64];
        h[0..4].copy_from_slice(b"\x7fELF");
        h[4] = 2; // 64-bit
        h[5] = if big_endian { 2 } else { 1 };
        let m = if big_endian { machine.to_be_bytes() } else { machine.to_le_bytes() };
        h[18] = m[0];
        h[19] = m[1];
        h
    }

    fn feats(avx2: bool, neon: bool) -> Vec<(&'static str, bool)> {
        vec![("avx2", avx2), ("neon", neon)]
    }

    #[test]
    fn reads_the_machine_from_an_elf_header() {
        assert_eq!(elf_machine(&elf(EM_X86_64, false)), Some(62));
        assert_eq!(elf_machine(&elf(EM_AARCH64, false)), Some(183));
        assert_eq!(elf_machine(&elf(EM_AARCH64, true)), Some(183));
        assert_eq!(elf_machine(b"not an elf file at all, just text"), None);
        assert_eq!(elf_machine(&[0x7f, b'E', b'L', b'F']), None, "too short");
    }

    #[test]
    fn pykes_runtime_needs_avx2_on_x86_64_only() {
        let err = verdict("x86_64", &feats(false, false), false, None, None, true).unwrap_err();
        assert!(err.contains("AVX2") && err.contains("ort-dynamic"), "{err}");
        assert!(verdict("x86_64", &feats(true, false), false, None, None, true).is_ok());
        assert!(verdict("aarch64", &feats(false, true), false, None, None, true).is_ok(), "arm64 does not need AVX2");
        assert!(verdict("aarch64", &feats(false, false), false, None, None, true).is_err());
    }

    #[test]
    fn the_dynamic_runtime_runs_without_avx2() {
        assert!(verdict("x86_64", &feats(false, false), true, Some(&elf(EM_X86_64, false)), None, true).is_ok());
    }

    #[test]
    fn a_library_for_the_wrong_architecture_is_refused_with_both_named() {
        let err = verdict("aarch64", &feats(false, true), true, Some(&elf(EM_X86_64, false)), None, true).unwrap_err();
        assert!(err.contains("x86-64") && err.contains("aarch64"), "{err}");
        let err = verdict("x86_64", &feats(true, false), true, Some(&elf(EM_AARCH64, false)), None, true).unwrap_err();
        assert!(err.contains("aarch64") && err.contains("x86-64"), "{err}");
    }

    #[test]
    fn a_missing_library_path_says_what_to_set() {
        let err = verdict("x86_64", &feats(true, false), true, None, Some("ORT_DYLIB_PATH is not set"), true).unwrap_err();
        assert!(err.contains("ORT_DYLIB_PATH"), "{err}");
    }

    #[test]
    fn a_file_that_is_not_a_library_is_refused_on_linux_only() {
        let junk = b"this is text, not a shared library at all, so not an ELF file....";
        let err = verdict("x86_64", &feats(true, false), true, Some(junk), None, true).unwrap_err();
        assert!(err.contains("ORT_DYLIB_PATH"), "{err}");
    }
}
