#!/usr/bin/env python3
"""Watch the pods of a deployment from the cluster side while a soak test runs: the numbers an outside client cannot see (standard library only).

    python3 perf_tests/pod_watch.py --out ./watch                 # staging, every 30 s until Ctrl-C
    python3 perf_tests/pod_watch.py --out ./watch --hours 3 --interval 60
    python3 perf_tests/pod_watch.py --namespace company-dns --out ./watch   # a read-only look at another namespace (for example production)

Run it on a machine that reaches the cluster (the build node), next to the soak. Every interval it reads the pod list and, from inside each pod, its cgroup (CPU used, CPU
throttling, memory), and appends a row to watch.csv (one row for all the pods, UTC time, so it lines up with the soak's windows) and a line per pod to pods.jsonl.
It only ever reads: `kubectl get pods` and, per pod, one `kubectl exec ... cat` of the cgroup files. It never changes, restarts or deletes anything.

Start it a few minutes BEFORE the soak and stop it a few minutes AFTER: the pods' CPU is low while idle and clearly higher while the soak runs, so `soak_analyze.py events` can see when the load started and ended
and line the soak's windows up with these rows, without anyone comparing clocks.

Mark what you do (on the machine this runs on: the same clock), in a text file, one line each (`events.txt`):    echo "$(date -u +%FT%TZ) rolling update to <tag>" >> events.txt
`soak_analyze.py events` then shows the soak windows and the pods around each mark.
"""
import argparse
import csv
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_cluster as rc  # noqa: E402

CSV_FIELDS = ["time_utc", "pods", "ready", "terminating", "not_ready", "restarts_total", "new_restarts", "oom_killed", "mem_mib_median", "mem_mib_max", "cpu_cores_used",
              "throttled_share", "nodes", "unreadable"]
CGROUP_CMD = ["sh", "-c", "cat /sys/fs/cgroup/cpu.stat; echo ---; cat /sys/fs/cgroup/memory.current"]


def parse_cgroup_text(text: str) -> dict:
    """The two cgroup reads of one exec: `cpu.stat` lines, a `---` line, then memory.current. Missing or odd numbers are None."""
    cpu_part, _, mem_part = (text or "").partition("---")
    stat = {}
    for line in cpu_part.splitlines():
        k, _, v = line.partition(" ")
        if v.strip().isdigit():
            stat[k] = int(v.strip())
    mem = mem_part.strip()
    return {"usage_us": stat.get("usage_usec"), "periods": stat.get("nr_periods"), "throttled": stat.get("nr_throttled"),
            "mem_mib": round(int(mem) / 1048576, 1) if mem.isdigit() else None}


def pod_state(p: dict) -> dict:
    """What matters of one pod from `get pods -o json`: ready, terminating, restarts, last termination reason, node."""
    statuses = p["status"].get("containerStatuses", [])
    last = [c.get("lastState", {}).get("terminated", {}).get("reason") for c in statuses]
    return {"name": p["metadata"]["name"], "phase": p["status"].get("phase"), "terminating": bool(p["metadata"].get("deletionTimestamp")),
            "ready": bool(statuses) and all(c.get("ready") for c in statuses), "restarts": sum(c.get("restartCount", 0) for c in statuses),
            "oom": any(r == "OOMKilled" for r in last), "node": p["spec"].get("nodeName", "")}


def combine(now_iso: str, states: list[dict], cg: dict, prev: dict | None, seconds: float, prev_restarts: int | None) -> tuple[dict, dict]:
    """One CSV row from the pod states and cgroup reads; `prev` is the previous cgroup reads by pod name. Returns (row, this sample's cgroup reads for the next call).
    CPU used and throttled share are deltas over pods present in both samples (a pod that came or went in between has no delta)."""
    restarts = sum(s["restarts"] for s in states)
    mems = [cg[s["name"]]["mem_mib"] for s in states if cg.get(s["name"]) and cg[s["name"]]["mem_mib"] is not None]
    used = periods = throttled = 0
    common = 0
    for s in states:
        a, b = (prev or {}).get(s["name"]), cg.get(s["name"])
        if a and b and None not in (a["usage_us"], b["usage_us"]) and b["usage_us"] >= a["usage_us"]:
            used += b["usage_us"] - a["usage_us"]
            common += 1
            if None not in (a["periods"], b["periods"], a["throttled"], b["throttled"]):
                periods += b["periods"] - a["periods"]
                throttled += b["throttled"] - a["throttled"]
    row = {"time_utc": now_iso, "pods": len(states), "ready": sum(1 for s in states if s["ready"] and not s["terminating"]), "terminating": sum(1 for s in states if s["terminating"]),
           "not_ready": sum(1 for s in states if not s["ready"] and not s["terminating"]), "restarts_total": restarts,
           "new_restarts": (restarts - prev_restarts) if prev_restarts is not None and restarts >= prev_restarts else 0, "oom_killed": sum(1 for s in states if s["oom"]),
           "mem_mib_median": round(statistics.median(mems), 1) if mems else None, "mem_mib_max": max(mems) if mems else None,
           "cpu_cores_used": round(used / 1e6 / seconds, 2) if common and seconds else None,
           "throttled_share": round(throttled / periods, 3) if periods else None, "nodes": len({s["node"] for s in states if s["node"]}),
           "unreadable": sum(1 for s in states if not s["terminating"] and not cg.get(s["name"])) }
    return row, cg


class Watcher:
    def __init__(self, cluster: rc.Cluster, namespace: str):
        self.cluster, self.namespace = cluster, namespace

    def pods(self) -> list[dict]:
        return self.cluster.pods(self.namespace)

    def read_cgroup(self, name: str) -> dict | None:
        try:
            return parse_cgroup_text(self.cluster.run("exec", name, "--", *CGROUP_CMD, namespace=self.namespace))
        except RuntimeError:
            return None  # a pod that is starting, stopping or gone

    def sample(self) -> tuple[list[dict], dict]:
        states = [pod_state(p) for p in self.pods()]
        live = [s["name"] for s in states if s["phase"] == "Running" and not s["terminating"]]
        with ThreadPoolExecutor(max_workers=8) as ex:
            reads = list(ex.map(self.read_cgroup, live))
        return states, {n: r for n, r in zip(live, reads) if r}


def run(a, cluster=None, log=print, sleep=time.sleep, now=time.time) -> int:
    cluster = cluster or rc.Cluster()
    if not cluster.kubectl:
        print("kubectl not found (run this on a machine that reaches the cluster, such as the build node)", file=sys.stderr)
        return 2
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    w = Watcher(cluster, a.namespace)
    log(f"watching {a.namespace} every {a.interval:g} s; results in {out}/ (Ctrl-C to stop)")
    end = now() + a.hours * 3600 if a.hours else None
    prev = prev_t = prev_restarts = None
    rows = 0
    try:
        with open(out / "watch.csv", "a", newline="") as fcsv, open(out / "pods.jsonl", "a") as fpods:
            writer = csv.DictWriter(fcsv, fieldnames=CSV_FIELDS)
            if fcsv.tell() == 0:
                writer.writeheader()
            while True:
                t = now()
                try:
                    states, cg = w.sample()
                except RuntimeError as e:  # the cluster did not answer: note it and go on
                    log(f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t))}] could not read the pods: {str(e)[:120]}")
                    states, cg = None, None
                if states is not None:
                    iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
                    row, prev_cg = combine(iso, states, cg, prev, (t - prev_t) if prev_t else 0.0, prev_restarts)
                    writer.writerow(row)
                    fcsv.flush()
                    for s in states:
                        fpods.write(json.dumps({"time_utc": iso, **s, **(cg.get(s["name"]) or {})}) + "\n")
                    fpods.flush()
                    prev, prev_t, prev_restarts = prev_cg, t, row["restarts_total"]
                    rows += 1
                    log(f"[{iso}] pods {row['pods']} ready {row['ready']} terminating {row['terminating']} restarts {row['restarts_total']} (+{row['new_restarts']})  "
                        f"mem max {row['mem_mib_max']} MiB  cpu {row['cpu_cores_used']} cores  throttled {row['throttled_share']}")
                if end and now() >= end:
                    break
                sleep(max(0.0, a.interval - (now() - t)))
    except KeyboardInterrupt:
        log("stopped")
    log(f"{rows} samples in {out}/watch.csv")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--namespace", default=rc.NAMESPACE, help="default: the staging namespace; another one is read-only too")
    ap.add_argument("--interval", type=float, default=30.0, help="seconds between samples")
    ap.add_argument("--hours", type=float, help="stop after this long (default: until Ctrl-C)")
    ap.add_argument("--out", type=Path, default=Path("perf_tests/results") / f"watch-{time.strftime('%Y%m%d-%H%M')}")
    a = ap.parse_args(argv)
    if a.interval < 5:
        print("--interval must be at least 5 seconds", file=sys.stderr)
        return 2
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
