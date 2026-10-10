#!/usr/bin/env bash
# Report this machine's processor architecture and the features the ONNX Runtime cares about, and say which V4 build fits.
#
#   v4/scripts/cpu-check.sh            # prints a summary; exit 0 = the default Docker image (Microsoft's runtime) runs here
#
# Run it on every node before building or deploying (docs/plans/v4-amd64-build-and-compare.md, section 0). The server does the same
# check itself at start-up (v4/crates/server/src/cpu.rs) and logs a "CPU: ..." line; this script answers the question earlier.
#
# What decides the build:
#   architecture    amd64 (x86-64) or arm64 (aarch64): the image build picks the matching Microsoft library from the target platform.
#   AVX2 (amd64)    pyke's prebuilt runtime (the `ort-download` build, `docker-build.sh --ort download`) needs it; Microsoft's runtime
#                   (the default, `--ort dynamic`) does not: it picks AVX-512, AVX2 or SSE kernels itself at run time.
#   NEON (arm64)    always present on aarch64; reported for completeness.
set -euo pipefail
os="$(uname -s)"; raw="$(uname -m)"
case "$raw" in
  x86_64|amd64) arch=amd64 ;;
  aarch64|arm64) arch=arm64 ;;
  *) arch="$raw" ;;
esac

flags=""; model=""
cpuinfo="${CPUINFO_FILE:-/proc/cpuinfo}"   # overridable so the script can be tested against a recorded CPU
if [ "$os" = "Linux" ] && [ -r "$cpuinfo" ]; then
  model="$(grep -m1 -E "^(model name|Model|Hardware)" "$cpuinfo" | cut -d: -f2- | sed 's/^ *//')"
  flags="$(grep -m1 -E "^(flags|Features)" "$cpuinfo" | cut -d: -f2- | sed 's/^ *//')"
elif [ "$os" = "Darwin" ]; then
  model="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || true)"
  if [ "$arch" = "amd64" ]; then
    flags="$(sysctl -n machdep.cpu.features machdep.cpu.leaf7_features 2>/dev/null | tr 'A-Z' 'a-z' | tr '\n' ' ')"
  elif [ "$(sysctl -n hw.optional.neon 2>/dev/null || echo 0)" = "1" ]; then
    flags="neon asimd"
  fi
fi
have() { case " $flags " in *" $1 "*) return 0 ;; esac; return 1; }
yn() { if have "$1"; then echo yes; else echo no; fi; }

echo "OS / architecture : $os / $arch ($raw)"
[ -z "$model" ] || echo "Processor         : $model"
virt="$(systemd-detect-virt 2>/dev/null || true)"; [ -z "$virt" ] || echo "Virtualization    : $virt  (none = bare metal; a VM can hide CPU features: ask for host passthrough)"
verdict=0
case "$arch" in
  amd64)
    echo "x86-64 features   : sse4_2=$(yn sse4_2) avx=$(yn avx) avx2=$(yn avx2) fma=$(yn fma) avx512f=$(yn avx512f)"
    echo "Default image     : OK  (Microsoft's ONNX Runtime, picks its kernels at run time; needs no AVX2)"
    if have avx2; then
      echo "pyke prebuilt     : OK  (--ort download works: this CPU has AVX2)"
    else
      echo "pyke prebuilt     : NO  (--ort download would die with an illegal instruction: no AVX2). Use the default image."
    fi
    have sse4_2 || { echo "WARNING: no SSE4.2; the ONNX Runtime may not run here"; verdict=1; }
    ;;
  arm64)
    echo "arm64 features    : neon=$( (have neon || have asimd) && echo yes || echo no )"
    echo "Default image     : OK  (Microsoft's aarch64 ONNX Runtime)"
    echo "pyke prebuilt     : OK  (arm64 has no AVX2 requirement)"
    (have neon || have asimd) || { [ "$os" = "Darwin" ] || { echo "WARNING: no NEON/asimd reported"; verdict=1; }; }
    ;;
  *)
    echo "Unsupported architecture '$raw': V4 images are built for amd64 and arm64 only."; verdict=1 ;;
esac
exit $verdict
