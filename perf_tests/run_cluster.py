"""Size the staging replicas: run the same load against several replica configurations on the real cluster and compare. (Standard library only.)

    python3 perf_tests/run_cluster.py                                   # 2x500m/1Gi (today), 2x1000m/2Gi, 4x500m/1Gi: embedding and lookup mixes
    python3 perf_tests/run_cluster.py --configs 2x1000m/2Gi,4x500m/1Gi --mixes embedding --concurrency 16 32 --duration 40
    python3 perf_tests/run_cluster.py --dry-run                         # the plan, and the preflight, changing nothing

A configuration is REPLICAS x CPU-LIMIT / MEMORY-LIMIT per replica: `2x1000m/2Gi` is two pods of one core and 2 GiB, the same total as
`4x500m/1Gi` (four half-core pods), which is what production's V3 runs per pod. For each configuration it patches the staging Deployment (replicas,
resources and COMPANY_DNS_REPLICAS, in one rollout), waits for it, runs the closed-loop load of `load.py` at each concurrency for each mix, and
records throughput, latency percentiles, errors, and from inside the pods the CPU-throttling counters and memory. It ALWAYS puts the Deployment back
as it found it, even if interrupted. The Deployment manifest in the repository is never touched.

Run it on the build node (it needs kubectl and the staging-test token, `~/company_dns-staging-secrets/tokens`), through Traefik's LAN address with the
real host name, so it measures the real path: Traefik, TLS, the Service, the pods.

Courtesy to production, which shares these nodes: only the staging namespace is ever changed (and nothing is deleted); production's pods must be
Ready before it starts and their restart count is checked between every run (any change stops the test and restores staging); concurrency is capped
(--max-concurrency, default 128); and it pauses between runs. Run it when production is quiet. See docs/plans/v4-sizing-test.md.
"""
import argparse
import json
import os
import re
import resource
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402

NAMESPACE = "company-dns-staging"
PROD_NAMESPACE = "company-dns"
DEPLOYMENT = "company-dns"
CONTAINER = "company-dns"
HOST = "company-dns-staging.mediumroast.io"
TEST_PROFILE = "staging-test"
SELECTOR = "app.kubernetes.io/name=company-dns"
DEFAULT_CONFIGS = "2x500m/1Gi,2x1000m/2Gi,4x500m/1Gi"


class Aborted(Exception):
    pass


# ---------------------------------------------------------------- configurations
def parse_config(text: str) -> dict:
    """`2x1000m/2Gi` -> replicas 2, a CPU limit of 1000 millicores and a memory limit of 2 GiB per replica."""
    m = re.fullmatch(r"(\d+)x(\d+)m/(\d+)(Mi|Gi)", text.strip())
    if not m:
        raise ValueError(f"{text!r} is not REPLICASxCPUm/MEMORY, for example 2x1000m/2Gi")
    replicas, cpu, mem, unit = int(m[1]), int(m[2]), int(m[3]), m[4]
    if not 1 <= replicas <= 32:
        raise ValueError(f"{text!r}: replicas must be 1 to 32")
    if not 100 <= cpu <= 4000:
        raise ValueError(f"{text!r}: the CPU limit must be 100m to 4000m")
    mem_mi = mem * (1024 if unit == "Gi" else 1)
    if not 256 <= mem_mi <= 16384:
        raise ValueError(f"{text!r}: the memory limit must be 256Mi to 16Gi")
    return {"name": f"{replicas}x{cpu}m/{mem}{unit}", "replicas": replicas, "cpu_m": cpu, "mem_mi": mem_mi}


def resources_for(cfg: dict) -> dict:
    """Limits as given; requests in the ratio the manifest uses (CPU 1 to 5, memory 1 to 4), so scheduling is comparable between configurations."""
    return {"requests": {"cpu": f"{max(50, cfg['cpu_m'] // 5)}m", "memory": f"{max(128, cfg['mem_mi'] // 4)}Mi"},
            "limits": {"cpu": f"{cfg['cpu_m']}m", "memory": f"{cfg['mem_mi']}Mi"}}


def patch_for(replicas: int, resources: dict, replicas_env: str) -> dict:
    return {"spec": {"replicas": replicas, "template": {"spec": {"containers": [
        {"name": CONTAINER, "resources": resources, "env": [{"name": "COMPANY_DNS_REPLICAS", "value": replicas_env}]}]}}}}


# ---------------------------------------------------------------- the cluster
class Cluster:
    def __init__(self):
        if subprocess.run(["which", "kubectl"], capture_output=True).returncode == 0:
            self.kubectl = ["kubectl"]
        elif subprocess.run(["which", "microk8s"], capture_output=True).returncode == 0:
            self.kubectl = ["microk8s", "kubectl"]
        else:
            self.kubectl = None

    def run(self, *args, namespace: str | None = NAMESPACE, stdin: str | None = None, check: bool = True) -> str:
        cmd = self.kubectl + (["-n", namespace] if namespace else []) + list(args)
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
        if check and r.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd)} failed: {r.stderr.strip()[:300]}")
        return r.stdout

    def deployment(self, namespace: str = NAMESPACE) -> dict:
        return json.loads(self.run("get", "deployment", DEPLOYMENT, "-o", "json", namespace=namespace))

    def pods(self, namespace: str = NAMESPACE, selector: str = SELECTOR) -> list[dict]:
        return json.loads(self.run("get", "pods", "-l", selector, "-o", "json", namespace=namespace))["items"]

    def restarts(self, namespace: str) -> int:
        return sum(c.get("restartCount", 0) for p in self.pods(namespace) for c in p["status"].get("containerStatuses", []))

    def ready(self, namespace: str) -> tuple[int, int]:
        d = self.deployment(namespace)
        return d["status"].get("readyReplicas", 0) or 0, d["spec"]["replicas"]

    def lb_ip(self) -> str:
        return self.run("get", "ingress", DEPLOYMENT, "-o", "jsonpath={.status.loadBalancer.ingress[0].ip}", check=False).strip()

    def placement(self) -> dict:
        """Pod name -> the node it runs on (what the scheduler chose; the Deployment only prefers to spread pods)."""
        return {p["metadata"]["name"]: p["spec"].get("nodeName", "") for p in self.pods()}

    def apply_patch(self, patch: dict) -> None:
        self.run("patch", "deployment", DEPLOYMENT, "--type", "strategic", "-p", json.dumps(patch))
        self.run("rollout", "status", f"deployment/{DEPLOYMENT}", "--timeout=300s")

    def wait_ready(self, timeout: float = 300.0) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            ready, want = self.ready(NAMESPACE)
            if ready == want and len(self.pods()) == want:
                return
            time.sleep(2)
        raise RuntimeError("the staging pods did not become ready in time")

    def cgroup(self) -> dict:
        """Per pod, from inside it: CPU usage and throttling since it started, and memory. Missing numbers are None (an older kernel, or no exec)."""
        out = {}
        for p in self.pods():
            name = p["metadata"]["name"]
            stat = {}
            for key, path in (("cpu", "/sys/fs/cgroup/cpu.stat"), ("mem_peak", "/sys/fs/cgroup/memory.peak"), ("mem", "/sys/fs/cgroup/memory.current")):
                try:
                    stat[key] = self.run("exec", name, "--", "cat", path, check=True)
                except RuntimeError:
                    stat[key] = None
            out[name] = parse_cgroup(stat)
        return out


def parse_cgroup(raw: dict) -> dict:
    cpu = {}
    for line in (raw.get("cpu") or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            cpu[parts[0]] = int(parts[1])
    num = lambda v: int(v.strip()) if v and v.strip().isdigit() else None  # noqa: E731
    return {"usage_us": cpu.get("usage_usec"), "periods": cpu.get("nr_periods"), "throttled_periods": cpu.get("nr_throttled"),
            "throttled_us": cpu.get("throttled_usec"), "mem_mib": round(num(raw.get("mem")) / 1048576, 1) if num(raw.get("mem")) else None,
            "mem_peak_mib": round(num(raw.get("mem_peak")) / 1048576, 1) if num(raw.get("mem_peak")) else None}


def cgroup_delta(before: dict, after: dict, seconds: float) -> dict:
    """What the pods did during one run: total CPU used (in cores), the share of scheduling periods that were throttled, peak memory."""
    used = throttled = periods = 0
    mem = []
    for name, b in before.items():
        a = after.get(name)
        if not a or None in (a.get("usage_us"), b.get("usage_us")) or a["usage_us"] < b["usage_us"]:
            continue  # a pod that restarted or has no counters: left out
        used += a["usage_us"] - b["usage_us"]
        if None not in (a.get("throttled_periods"), b.get("throttled_periods"), a.get("periods"), b.get("periods")):
            throttled += a["throttled_periods"] - b["throttled_periods"]
            periods += a["periods"] - b["periods"]
        if a.get("mem_peak_mib") or a.get("mem_mib"):
            mem.append(a.get("mem_peak_mib") or a.get("mem_mib"))
    return {"cpu_cores_used": round(used / 1e6 / seconds, 2) if seconds else None,
            "throttled_share": round(throttled / periods, 3) if periods else None,
            "mem_peak_mib_max": max(mem) if mem else None}


# ---------------------------------------------------------------- the test
def token(secrets_dir: Path) -> str | None:
    f = secrets_dir / "tokens"
    if not f.exists():
        return None
    for line in f.read_text().splitlines():
        if line.startswith(f"{TEST_PROFILE}:"):
            return line.split(":", 1)[1].strip()
    return None


def run_configs(cluster: Cluster, configs: list[dict], mixes: list[str], levels: list[int], duration: float, warmup: float, pause: float,
                target: load.Target, auth: str, log=print, settle: float = 10.0, processes: int = 4) -> dict:
    live = cluster.deployment()
    container = next(c for c in live["spec"]["template"]["spec"]["containers"] if c["name"] == CONTAINER)
    original = {"replicas": live["spec"]["replicas"], "resources": container.get("resources", {}),
                "replicas_env": next((e.get("value") for e in container.get("env", []) if e["name"] == "COMPANY_DNS_REPLICAS"), str(live["spec"]["replicas"]))}
    prod_before = cluster.restarts(PROD_NAMESPACE)
    results = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "original": original, "runs": [], "aborted": None, "placements": {}, "generator_processes": processes}
    try:
        for cfg in configs:
            log(f"== {cfg['name']}: patching the staging Deployment")
            cluster.apply_patch(patch_for(cfg["replicas"], resources_for(cfg), str(cfg["replicas"])))
            cluster.wait_ready()
            time.sleep(settle)
            results["placements"][cfg["name"]] = cluster.placement()
            counts = sorted(Counter(results["placements"][cfg["name"]].values()).values(), reverse=True)
            log(f"   pods per node: {' + '.join(str(c) for c in counts)}")
            for mix in mixes:
                for n in levels:
                    before = cluster.cgroup()
                    t0 = time.monotonic()
                    cpu0 = resource.getrusage(resource.RUSAGE_CHILDREN)
                    r = load.run_level(target, mix, n, duration, warmup, auth, processes=processes)
                    seconds = time.monotonic() - t0
                    cpu1 = resource.getrusage(resource.RUSAGE_CHILDREN)
                    # CPU the load generator itself used (its worker processes), in cores: near `processes` means the generator, not the server, is the limit
                    generator = round((cpu1.ru_utime + cpu1.ru_stime - cpu0.ru_utime - cpu0.ru_stime) / seconds, 2) if seconds else None
                    after = cluster.cgroup()
                    r.update({"config": cfg["name"], "mix": mix, "total_cpu_cores": cfg["replicas"] * cfg["cpu_m"] / 1000.0, "generator_cores": generator,
                              "pods": cgroup_delta(before, after, seconds)})
                    results["runs"].append(r)
                    log(f"   {mix:9s} N={n:<3d} {r['rps']:8.1f} rps  p50 {r['p50_ms']:7.1f}  p95 {r['p95_ms']:7.1f}  p99 {r['p99_ms']:7.1f} ms  "
                        f"errors {r['errors']} 429s {r['rate_limited']}  cpu {r['pods']['cpu_cores_used']} cores  throttled {r['pods']['throttled_share']}")
                    if cluster.restarts(PROD_NAMESPACE) != prod_before:
                        raise Aborted("a production pod restarted during the test: stopping and restoring staging")
                    time.sleep(pause)
    except Aborted as e:
        results["aborted"] = str(e)
        log(f"ABORTED: {e}")
    finally:
        log("== restoring the staging Deployment as it was found")
        cluster.apply_patch(patch_for(original["replicas"], original["resources"], original["replicas_env"]))
        results["restored"] = True
    results["production_restarts_before_after"] = [prod_before, cluster.restarts(PROD_NAMESPACE)]
    return results


# ---------------------------------------------------------------- the summary
def best_sustained(runs: list[dict], max_error_rate: float = 0.01, max_p95_ms: float = 1000.0) -> dict | None:
    good = [r for r in runs if r["error_rate"] <= max_error_rate and r["p95_ms"] <= max_p95_ms]
    return max(good, key=lambda r: r["rps"]) if good else None


def summary(results: dict) -> str:
    lines = ["# Sizing test", "", f"Started {results['started']}. Staging Deployment found as {results['original']['replicas']} replicas; restored: {results.get('restored')}.", ""]
    if results.get("aborted"):
        lines += [f"**ABORTED: {results['aborted']}**", ""]
    for mix in sorted({r["mix"] for r in results["runs"]}):
        lines += [f"## {mix}", "", "| configuration | N | requests/s | p50 ms | p95 ms | p99 ms | errors | 429s | CPU cores used | throttled | peak memory MiB | generator cores |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        runs = [r for r in results["runs"] if r["mix"] == mix]
        for r in runs:
            p = r["pods"]
            lines.append(f"| {r['config']} | {r['concurrency']} | {r['rps']} | {r['p50_ms']} | {r['p95_ms']} | {r['p99_ms']} | {r['errors']} | {r['rate_limited']} | "
                         f"{p['cpu_cores_used']} | {p['throttled_share']} | {p['mem_peak_mib_max']} | {r.get('generator_cores')} |")
        lines += ["", "Best sustained (error rate at most 1% and p95 at most 1 s), by configuration:", "", "| configuration | total CPU limit | best requests/s | at N | p95 ms | requests/s per core of limit |", "|---|---|---|---|---|---|"]
        for cfg in dict.fromkeys(r["config"] for r in runs):
            best = best_sustained([r for r in runs if r["config"] == cfg])
            if best:
                lines.append(f"| {cfg} | {best['total_cpu_cores']} | {best['rps']} | {best['concurrency']} | {best['p95_ms']} | {round(best['rps'] / best['total_cpu_cores'], 1)} |")
            else:
                lines.append(f"| {cfg} | | none met the bar | | | |")
        lines.append("")
    procs = results.get("generator_processes", 4)
    hot = [r for r in results["runs"] if (r.get("generator_cores") or 0) >= 0.8 * procs]
    if hot:
        lines += [f"**The load generator used at least 80% of its {procs} processes in {len(hot)} runs (see the generator cores column): the server may not have been the limit there. Re-run with more --processes or from a bigger machine.**", ""]
    if results.get("placements"):
        lines += ["Pods per node (largest first), by configuration:", ""] + [
            f"- {cfg}: {' + '.join(str(c) for c in sorted(Counter(pods.values()).values(), reverse=True))}" for cfg, pods in results["placements"].items()] + [""]
    lines += ["Production restarts before and after: " + " -> ".join(str(x) for x in results.get("production_restarts_before_after", [])), ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--configs", default=DEFAULT_CONFIGS)
    ap.add_argument("--mixes", default="embedding,lookups")
    ap.add_argument("--concurrency", type=int, nargs="+", default=[8, 16, 32, 64])
    ap.add_argument("--duration", type=float, default=30.0)
    ap.add_argument("--warmup", type=float, default=5.0)
    ap.add_argument("--pause", type=float, default=10.0)
    ap.add_argument("--max-concurrency", type=int, default=256, help="refuse higher concurrency (staging shares nodes with production)")
    ap.add_argument("--processes", type=int, default=4, help="load generator processes (use more for hundreds of concurrent requests)")
    ap.add_argument("--out", type=Path, default=Path("perf_tests/results") / f"cluster-{time.strftime('%Y%m%d-%H%M')}")
    ap.add_argument("--secrets-dir", type=Path, default=Path(os.environ.get("V4_SECRETS_DIR", Path.home() / "company_dns-staging-secrets")))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    configs = [parse_config(c) for c in a.configs.split(",")]
    mixes = [m.strip() for m in a.mixes.split(",")]
    bad = [m for m in mixes if m not in load.MIXES]
    if bad or max(a.concurrency) > a.max_concurrency:
        print(f"unknown mix {bad}" if bad else f"concurrency {max(a.concurrency)} is above --max-concurrency {a.max_concurrency} (staging shares nodes with production)", file=sys.stderr)
        return 2
    cluster = Cluster()
    problems = []
    if not cluster.kubectl:
        problems.append("kubectl not found (run this on the build node)")
    tok = token(a.secrets_dir)
    if not tok:
        problems.append(f"no {TEST_PROFILE} token in {a.secrets_dir}/tokens (made by scripts/seal-secrets-v4.sh)")
    lb = ""
    if cluster.kubectl:
        try:
            ready, want = cluster.ready(PROD_NAMESPACE)
            if ready != want:
                problems.append(f"production is not fully ready ({ready} of {want}): not starting")
            ready, want = cluster.ready(NAMESPACE)
            if ready != want:
                problems.append(f"staging is not fully ready ({ready} of {want})")
            lb = cluster.lb_ip()
            if not lb:
                problems.append("the staging Ingress has no load balancer address")
        except RuntimeError as e:
            problems.append(str(e))
    if problems:
        print("cannot start:\n  - " + "\n  - ".join(problems), file=sys.stderr)
        return 1
    steps = len(configs) * len(mixes) * len(a.concurrency)
    est = steps * (a.duration + a.warmup + a.pause) / 60
    print(f"plan: {', '.join(c['name'] for c in configs)} x mixes {mixes} x concurrency {a.concurrency}: {steps} runs, about {est:.0f} minutes. Staging is restored afterwards.")
    if a.dry_run:
        return 0
    a.out.mkdir(parents=True, exist_ok=True)
    target = load.Target(f"https://{HOST}", connect_to=lb)
    results = run_configs(cluster, configs, mixes, a.concurrency, a.duration, a.warmup, a.pause, target, f"{TEST_PROFILE}:{tok}", processes=a.processes)
    (a.out / "results.json").write_text(json.dumps(results, indent=1))
    text = summary(results)
    (a.out / "summary.md").write_text(text)
    print(text)
    print(f"written to {a.out}/")
    return 1 if results.get("aborted") else 0


if __name__ == "__main__":
    sys.exit(main())
