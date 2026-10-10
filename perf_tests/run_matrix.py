#!/usr/bin/env python3
"""Clean-run comparison matrix for V3 and V4 images (docs/plans/v4-results-report.md, sections 2 and 3). Standard library only; run it on the node.

    python3 perf_tests/run_matrix.py --out perf_tests/results/matrix-$(date +%F)-$(hostname) \
        --v3-image ghcr.io/miha42-github/company_dns/company_dns:09272026-1 \
        --lean-image company-dns-v4:amd64-lean --small-image company-dns-v4:amd64-small \
        [--images v3,lean,small] [--regimes limited,headroom] [--repeats 3] [--extras] [--dry-run]

For every (regime, repeat, image) it starts the image from nothing, with the production settings (caches on, nothing switched off), and measures, in this order:
time to healthy; a COLD sequential pass (one route at a time, the container restarted before each so a route never benefits from another's cached results); a WARM sequential pass (same sequence, no restart); a concurrency pass (N = 1, 4, 8, 16). Container CPU and memory are
sampled every second throughout. Then the container is removed. Images take turns in a rotated order across repeats so drift on the node is spread evenly. One
service runs at a time. A finished run is skipped on restart (`--resume` is the default), so an interrupted matrix continues where it stopped.

Layout written under --out (read by report_data.load_matrix):
    manifest.json
    raw/<regime>/<image>/run<k>/{sequential-cold.json, sequential-warm.json, concurrency.json, container.json, resources.csv}
    specs/{v3,v4}-openapi.json    parity/<image>.json    suite/<image>.json      (with --extras)

V4 is called with a throwaway profile that has no rate limit (v4/scripts/perf-profile.sh) so the limiter is not what is measured; V3 has none in force.
Courtesy rules for a node that also runs production pods: it waits while the load average is above --max-load and records the production pod restart count
before and after every run (a change is written to the manifest, not hidden).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
COMPOSE = [REPO / "v4" / "docker-compose.compare.yml", REPO / "v4" / "docker-compose.perf.yml"]
UA = "company_dns-matrix/1.0 (+https://github.com/miha42-github/company_dns)"

# image name -> (compose profile, port, container name, which --*-image option names it)
IMAGES = {
    "v3": ("v3", 8000, "compare-v3"),
    "lean": ("v4", 4000, "compare-v4"),
    "small": ("v4", 4000, "compare-v4"),
}
REGIMES = {"limited": ("0.5", "1g"), "headroom": ("16", "64g")}  # CPUs and memory; "limited" is the production pods' limits


# ------------------------------------------------------------------ pure helpers (unit-tested)
def rotate(items: list[str], k: int) -> list[str]:
    """The same items starting k places along, so every image gets every position across repeats."""
    if not items:
        return []
    k %= len(items)
    return items[k:] + items[:k]


def plan(images: list[str], regimes: list[str], repeats: int) -> list[tuple[str, int, str]]:
    """(regime, repeat, image) in execution order: regime by regime, repeat by repeat, images rotated each repeat."""
    return [(reg, k, img) for reg in regimes for k in range(1, repeats + 1) for img in rotate(images, k - 1)]


def run_dir(out: Path, regime: str, image: str, k: int) -> Path:
    return out / "raw" / regime / image / f"run{k}"


def run_done(d: Path) -> bool:
    return all((d / n).exists() for n in ("sequential-cold.json", "sequential-warm.json", "concurrency.json", "container.json"))


_UNITS = {"b": 1 / 1048576, "kib": 1 / 1024, "kb": 1 / 1024, "mib": 1.0, "mb": 1.0, "gib": 1024.0, "gb": 1024.0}


def parse_stats(line: str) -> tuple[float, float] | None:
    """`docker stats --format '{{.CPUPerc}},{{.MemUsage}}'` -> (cpu percent, memory MiB). None for a line that is not a sample."""
    m = re.match(r"\s*([\d.]+)%\s*,\s*([\d.]+)\s*([A-Za-z]+)\s*/", line)
    if not m or m.group(3).lower() not in _UNITS:
        return None
    return float(m.group(1)), float(m.group(2)) * _UNITS[m.group(3).lower()]


def baseline_command(py: str, url: str, out: Path, *, auth: str | None, label: str, kind: str, repeat: int, timeout: int, levels: list[int],
                     endpoint: str | None = None) -> list[str]:
    """The baseline.py invocation for one phase: kind is 'cold', 'warm' or 'concurrency'; `endpoint` limits a sequential pass to one route."""
    cmd = [py, str(HERE / "baseline.py"), "--base-url", url, "--timeout", str(timeout), "--image-label", label, "--out", str(out)]
    if auth:
        cmd += ["--auth", auth]
    if kind in ("cold", "warm"):
        cmd += ["--skip-concurrency"]
        if endpoint:
            cmd += ["--endpoints", endpoint]
    else:
        cmd += ["--skip-sequential", "--repeat", str(repeat), "--concurrency", *map(str, levels)]
    return cmd


def merge_sequential(reports: list[dict]) -> dict:
    """One report from several single-route passes: the first one's header with every pass's sequential results in order."""
    merged = dict(reports[0])
    merged["sequential_results"] = [r for rep in reports for r in rep.get("sequential_results", [])]
    return merged


def endpoint_keys() -> list[str]:
    """The route keys baseline.py measures, in its own order (from `baseline.py --list`)."""
    out = sh([sys.executable, str(HERE / "baseline.py"), "--list"]).stdout
    keys: list[str] = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] not in keys and not line.startswith(" ") and parts[2] != "calls":
            keys.append(parts[0])
    return keys


# ------------------------------------------------------------------ talking to the host
def sh(cmd, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def compose(env: dict, *args: str) -> subprocess.CompletedProcess:
    base = ["docker", "compose"] + [x for f in COMPOSE for x in ("-f", str(f))]
    return subprocess.run(base + list(args), capture_output=True, text=True, env={**os.environ, **env})


def http_get(url: str, auth: str | None = None, timeout: int = 10):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if auth:
        import base64
        req.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def wait_healthy(url: str, limit: int = 240) -> float | None:
    t0 = time.time()
    while time.time() - t0 < limit:
        try:
            if http_get(url + "/health", timeout=3)[0] == 200:
                return time.time() - t0
        except Exception:
            pass
        time.sleep(0.5)
    return None


def restart_clean(container: str, url: str) -> float | None:
    """Restart the container (clearing V4's in-memory caches, and giving V3 the same treatment) and wait until it is healthy again."""
    sh(["docker", "restart", container], timeout=120)
    return wait_healthy(url)


def prod_restarts() -> int | None:
    """Total restart count of the production pods, if kubectl can see them (None otherwise)."""
    if not shutil.which("kubectl"):
        return None
    r = sh(["kubectl", "-n", "company-dns", "get", "pods", "-o", "jsonpath={range .items[*]}{.status.containerStatuses[*].restartCount}{\"\\n\"}{end}"], timeout=10)
    if r.returncode != 0:
        return None
    try:
        return sum(int(x) for line in r.stdout.splitlines() for x in line.split() if x.isdigit())
    except ValueError:
        return None


class Sampler(threading.Thread):
    """Samples `docker stats` for one container about once a second until stopped."""

    def __init__(self, container: str):
        super().__init__(daemon=True)
        self.container, self.rows, self.stop_flag, self.t0 = container, [], threading.Event(), time.time()

    def run(self):
        while not self.stop_flag.is_set():
            r = sh(["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}},{{.MemUsage}}", self.container])
            s = parse_stats(r.stdout.strip()) if r.returncode == 0 else None
            if s:
                self.rows.append((time.time() - self.t0, s[0], s[1]))
            self.stop_flag.wait(0.2)

    def write(self, path: Path):
        path.write_text("t_seconds,cpu_percent,mem_mib\n" + "".join(f"{t:.1f},{c:.2f},{m:.1f}\n" for t, c, m in self.rows))


def wait_for_quiet_node(max_load: float, max_wait: int) -> float:
    t0 = time.time()
    while True:
        load = os.getloadavg()[0]
        if load <= max_load or time.time() - t0 > max_wait:
            return load
        print(f"   node load {load:.2f} is above {max_load}; waiting...", flush=True)
        time.sleep(15)


# ------------------------------------------------------------------ one run
def do_run(a, regime: str, image: str, k: int, manifest: dict) -> None:
    profile, port, container = IMAGES[image]
    cpus, mem = REGIMES[regime]
    d = run_dir(a.out, regime, image, k)
    if run_done(d) and not a.force:
        print(f"== {regime} / {image} / run{k}: already done, skipping")
        return
    d.mkdir(parents=True, exist_ok=True)
    env = {"V3_IMAGE": a.v3_image, "V4_IMAGE": a.lean_image if image == "lean" else a.small_image,
           "LIMIT_CPUS": cpus, "LIMIT_MEM": mem, "PERF_SECRETS_DIR": str(a.secrets)}
    label = {"v3": f"V3 {a.v3_image.rsplit(':', 1)[-1]}", "lean": f"V4 lean ({env['V4_IMAGE']})", "small": f"V4 small ({env['V4_IMAGE']})"}[image]
    url = f"http://localhost:{port}"
    auth = None if image == "v3" else a.auth
    endpoints = endpoint_keys()
    print(f"== {regime} / {image} / run{k}: starting {label} at {cpus} CPU, {mem}", flush=True)

    compose(env, "--profile", "v3", "--profile", "v4", "down", "-v", "--remove-orphans")
    load = wait_for_quiet_node(a.max_load, a.max_wait)
    before = prod_restarts()
    up = compose(env, "--profile", profile, "up", "-d")
    if up.returncode != 0:
        raise SystemExit(f"could not start {image}: {up.stderr.strip()[:400]}")
    t_healthy = wait_healthy(url)
    if t_healthy is None:
        logs = sh(["docker", "logs", "--tail", "20", container])
        raise SystemExit(f"{image} did not become healthy in time:\n{logs.stdout}{logs.stderr}")
    sampler = Sampler(container)
    sampler.start()
    try:
        def phase(kind: str, out: Path, endpoint: str | None = None) -> dict:
            cmd = baseline_command(sys.executable, url, out, auth=auth, label=f"{label} {kind}", kind=kind, repeat=a.repeat_batches,
                                   timeout=a.timeout, levels=a.concurrency, endpoint=endpoint)
            r = subprocess.run(cmd, capture_output=True, text=True)
            with open(d / f"{kind}.log", "a") as log:
                log.write(r.stdout + r.stderr)
            if r.returncode != 0:
                raise SystemExit(f"baseline.py failed in the {kind} pass ({endpoint or 'all routes'}) of {image}; see {d / (kind + '.log')}")
            return json.loads(out.read_text())

        # COLD: one route at a time, restarting the container before each, so no route benefits from another's cached results.
        print("   cold pass (one route at a time, restarting between)", flush=True)
        parts = []
        for ep in endpoints:
            if restart_clean(container, url) is None:
                raise SystemExit(f"{image} did not come back healthy after a restart")
            parts.append(phase("cold", d / f"cold-{ep}.json", ep))
        (d / "sequential-cold.json").write_text(json.dumps(merge_sequential(parts)))
        for ep in endpoints:
            (d / f"cold-{ep}.json").unlink()
        # WARM: the whole sequence again with the caches filled by the cold pass, no restart. CONCURRENCY follows.
        print("   warm pass", flush=True)
        phase("warm", d / "sequential-warm.json")
        print("   concurrency pass", flush=True)
        phase("concurrency", d / "concurrency.json")
    finally:
        sampler.stop_flag.set()
        sampler.join(timeout=15)
        sampler.write(d / "resources.csv")
        insp = sh(["docker", "inspect", container])
        info = json.loads(insp.stdout)[0] if insp.returncode == 0 and insp.stdout.strip() else {}
        compose(env, "--profile", "v3", "--profile", "v4", "down", "-v", "--remove-orphans")
    after = prod_restarts()
    (d / "container.json").write_text(json.dumps({
        "regime": regime, "image": image, "label": label, "image_ref": info.get("Config", {}).get("Image"), "image_id": info.get("Image"),
        "limits": {"cpus": cpus, "memory": mem}, "time_to_healthy_s": round(t_healthy, 2), "load_at_start": round(load, 2),
        "prod_restarts_before": before, "prod_restarts_after": after, "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }, indent=2))
    if before is not None and after is not None and after != before:
        manifest.setdefault("warnings", []).append(f"production pod restarts changed during {regime}/{image}/run{k}: {before} -> {after}")
        print("   WARNING: a production pod restarted during this run", flush=True)
    print(f"   done (healthy in {t_healthy:.1f}s, {len(sampler.rows)} resource samples)", flush=True)


# ------------------------------------------------------------------ extras: specs, parity, suite
def do_extras(a, manifest: dict) -> None:
    print("== extras: specs, parity and the suite (V3 and the lean image up together, production limits)")
    env = {"V3_IMAGE": a.v3_image, "V4_IMAGE": a.lean_image, "LIMIT_CPUS": REGIMES["limited"][0], "LIMIT_MEM": REGIMES["limited"][1],
           "PERF_SECRETS_DIR": str(a.secrets)}
    compose(env, "--profile", "v3", "--profile", "v4", "down", "-v", "--remove-orphans")
    compose(env, "--profile", "v3", "--profile", "v4", "up", "-d")
    try:
        if wait_healthy("http://localhost:8000") is None or wait_healthy("http://localhost:4000") is None:
            raise SystemExit("extras: a service did not become healthy")
        (a.out / "specs").mkdir(parents=True, exist_ok=True)
        for name, url, auth in (("v3", "http://localhost:8000", None), ("v4", "http://localhost:4000", a.auth)):
            (a.out / "specs" / f"{name}-openapi.json").write_bytes(http_get(url + "/openapi.json", auth, timeout=30)[1])
        (a.out / "parity").mkdir(exist_ok=True)
        (a.out / "suite").mkdir(exist_ok=True)
        sh([sys.executable, str(REPO / "api_tests" / "parity_report.py"), "--v3", "http://localhost:8000", "--v4", "http://localhost:4000",
            "--repeats", "3", "--pause", "0.2", "--auth", a.auth, "--json", str(a.out / "parity" / "lean.json")])
        user, token = a.auth.split(":", 1)
        sh([sys.executable, str(REPO / "api_tests" / "run.py"), "--base-url", "http://localhost:4000", "--profile", user, "--token", token,
            "--network", "--report", str(a.out / "suite" / "lean.json")], env={**os.environ, "API_TESTS_NETWORK": "1"})
    finally:
        compose(env, "--profile", "v3", "--profile", "v4", "down", "-v", "--remove-orphans")


def host_facts() -> dict:
    cc = sh([str(REPO / "v4" / "scripts" / "cpu-check.sh")])
    mem = None
    if Path("/proc/meminfo").exists():
        mem = next((int(l.split()[1]) // 1024 for l in Path("/proc/meminfo").read_text().splitlines() if l.startswith("MemTotal")), None)
    git = sh(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"]).stdout.strip()
    dirty = bool(sh(["git", "-C", str(REPO), "status", "--porcelain"]).stdout.strip())
    return {"hostname": platform.node(), "system": f"{platform.system()} {platform.machine()}", "cpus": os.cpu_count(), "memory_mib": mem,
            "load_average": os.getloadavg(), "cpu_check": cc.stdout, "docker": sh(["docker", "version", "--format", "{{.Server.Version}}"]).stdout.strip(),
            "git_commit": git, "git_dirty": dirty}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--images", default="v3,lean,small")
    p.add_argument("--regimes", default="limited,headroom")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--v3-image", default="ghcr.io/miha42-github/company_dns/company_dns:09272026-1")
    p.add_argument("--lean-image", default="company-dns-v4:amd64-lean")
    p.add_argument("--small-image", default="company-dns-v4:amd64-small")
    p.add_argument("--secrets", type=Path, default=Path.home() / "perf-secrets", help="directory made by v4/scripts/perf-profile.sh (created if missing)")
    p.add_argument("--concurrency", type=int, nargs="+", default=[1, 4, 8, 16])
    p.add_argument("--repeat-batches", type=int, default=3, help="batches per concurrency level inside one run")
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--max-load", type=float, default=2.0, help="wait while the node's 1-minute load average is above this")
    p.add_argument("--max-wait", type=int, default=600)
    p.add_argument("--extras", action="store_true", help="also fetch both OpenAPI specs and run the parity report and the suite")
    p.add_argument("--force", action="store_true", help="redo runs that are already finished")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    images = [x.strip() for x in a.images.split(",") if x.strip()]
    regimes = [x.strip() for x in a.regimes.split(",") if x.strip()]
    bad = [x for x in images if x not in IMAGES] + [x for x in regimes if x not in REGIMES]
    if bad:
        p.error(f"unknown image or regime: {bad}")
    steps = plan(images, regimes, a.repeats)
    print(f"{len(steps)} runs: " + ", ".join(f"{r}/{i}/run{k}" for r, k, i in steps))
    if a.dry_run:
        return 0
    a.out.mkdir(parents=True, exist_ok=True)
    if not (a.secrets / "token").exists():
        print(f"== creating the throwaway no-rate-limit profile in {a.secrets}")
        subprocess.run([str(REPO / "v4" / "scripts" / "perf-profile.sh"), str(a.secrets)], check=True, capture_output=True)
    a.auth = "perf:" + (a.secrets / "token").read_text().strip()
    manifest = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "host": host_facts(), "plan": [list(s) for s in steps],
                "images": {"v3": a.v3_image, "lean": a.lean_image, "small": a.small_image}, "regimes": REGIMES,
                "concurrency": a.concurrency, "repeat_batches": a.repeat_batches, "timeout_s": a.timeout}
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    try:
        for regime, k, image in steps:
            do_run(a, regime, image, k, manifest)
        if a.extras:
            do_extras(a, manifest)
    finally:
        manifest["ended"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (a.out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"== finished; results in {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
