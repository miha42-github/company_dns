# V4 sizing test: two larger replicas, or four smaller ones?

Status: **Tool written and tested against a fake cluster (2026-10-11); not yet run on the real cluster.**
Owner: michael.hay@mediumroast.io
Question: for the same total CPU and memory, is V4 better as a few large replicas or several small ones? V3 production runs 4 replicas of 500m CPU and 1 GiB each; staging runs 2 of the same size.

## What it does

`perf_tests/run_cluster.py` (with the closed-loop generator `perf_tests/load.py`, standard library only, run on the build node) patches the **staging**
Deployment to each configuration in turn (replicas, CPU and memory limits, and `COMPANY_DNS_REPLICAS`, in one rollout), runs the same load against it
through Traefik with the real host name (so the path is the real one: TLS, Traefik, the Service, the pods), and **always puts the Deployment back as it
found it**. The repository's manifest is never edited.

A configuration is `REPLICASxCPU-LIMIT/MEMORY-LIMIT`. The default set compares the same total (2 cores, 4 GiB) two ways, plus today's size as the baseline:

| configuration | total CPU limit | what it answers |
|---|---|---|
| `2x500m/1Gi` | 1 core | today's staging (the baseline) |
| `2x1000m/2Gi` | 2 cores | two larger replicas |
| `4x500m/1Gi` | 2 cores | four of V3's per-pod size: the same total as the line above |

For each, two **mixes** at concurrency 8, 16, 32 and 64 for 30 seconds each (after a 5-second warm-up that is thrown away):
- **`embedding`**: similarity and hybrid search. These embed the query with the ONNX model, which is the CPU-heavy work.
- **`lookups`**: SIC description and code, EDGAR CIKs. The cheap DataFusion routes.
(`mixed` is also available: 70% lookups, 30% embedding.) Every request is different (random words), so no result cache can answer it and the work is real. EDGAR
detail, Wikipedia and merged are excluded on purpose: they call Wikimedia and the SEC, and cache.

Per run it records requests per second, p50, p95 and p99 latency, errors and 429s, and, **read from inside the pods**, the CPU actually used (in cores), the
**share of scheduling periods that were CPU-throttled**, and peak memory. It then names, per configuration, the **best sustained throughput** (the most
requests per second with at most 1% errors and a p95 under one second) and that divided by the cores of limit.

## Why these hypotheses, and what would settle them

Two things in the code suggest that bigger is not automatically better, and the test is designed to show it either way:
1. **One embedding at a time per pod.** `embed_query` runs under a `Mutex<Embedders>` (`main.rs`), so a pod embeds one query at a time. More concurrent embedding
   requests than pods queue. If so, `embedding` throughput should scale with the number of pods more than with the size of each (a larger pod only makes each
   embedding faster, by using more cores inside it).
2. **Threads versus the CPU limit.** Nothing sets the ONNX Runtime's thread count; its default follows the machine's cores, not the container's CPU quota.
   On a many-core node a 500m pod can run many threads against half a core and be throttled. The **throttled share** column shows whether that is happening
   and whether a larger limit relieves it.

The lookups mix tests the opposite case: small, many-way-parallel queries where more, smaller pods spread the work and a few large ones may not use their cores.

## Safety (staging shares two nodes with production)

- Only the namespace `company-dns-staging` is ever changed; nothing is deleted; production is only read (its restart count).
- It refuses to start unless production and staging are fully ready; **any production pod restart during the test stops it and restores staging**.
- Concurrency is capped (`--max-concurrency`, default 128) and it pauses between runs. Run it when production is quiet, and watch
  `kubectl -n company-dns get pods` and the nodes' load while it runs.
- It restores staging in a `finally` block, so an error or Ctrl-C still puts it back. Check afterwards with `./scripts/build-and-deploy-v4.sh --status`
  and `kubectl -n company-dns-staging get deploy company-dns -o jsonpath='{.spec.replicas}'`.
- The token comes from `~/company_dns-staging-secrets/tokens` (the `staging-test` profile, which has no rate limit) and is sent as a Basic header from
  inside the processes, never on a command line.

## Steps

1. **Deploy the current code** (so the test measures what will ship): merge the open PRs, then on the build node
   `git pull && ./scripts/build-and-deploy-v4.sh --suite`.
2. **Preflight and plan**, changing nothing: `python3 perf_tests/run_cluster.py --dry-run`. It checks the cluster, the token and production's readiness and prints
   the number of runs and the time (about 25 minutes for the defaults, with the rollouts).
3. **Run it**: `python3 perf_tests/run_cluster.py`. Results go to `perf_tests/results/cluster-<date>/` (`results.json` and `summary.md`; the directory is gitignored).
4. **Read `summary.md`** with the hypotheses above. Compare, per mix, the configurations with the same total (`2x1000m/2Gi` against `4x500m/1Gi`), the throttled
   share, and the requests per second per core of limit.
5. **Decide** the staging size (and later production's), record the numbers in the plan, and set `replicas`, `resources` and `COMPANY_DNS_REPLICAS` in
   `k8s/staging/deployment.yaml` together (the manifest test pins them to each other).

## What the test does not tell you

- It measures the **staging pods on shared nodes**, so a busy neighbour (production) adds noise: repeat a surprising result, and run when production is quiet.
- Closed-loop load is a capacity measurement, not a model of production traffic (V3 sees bursts and long idle stretches). It answers "how much can each shape
  sustain", not "how many do we need".
- The lookups mix is the cheap routes; the embedding mix is the heavy ones. Real traffic is some blend: `--mixes mixed` approximates one.
- Memory is checked for headroom only (V4 idles near 160 MiB and peaked under 260 MiB in the earlier matrix); it is not the variable under test.
- A bigger change than sizing (a pool of embedders, an explicit ONNX thread count) would be a code change and is out of scope here; the results may argue for it.

## Larger replicas (hackathon sizing)

The first round (2x500m, 4x500m, 2x1000m) showed that half-core pods are heavily CPU-throttled and that fewer, larger pods did better at equal total CPU. To test larger pods:

```bash
python3 perf_tests/run_cluster.py --configs 3x4000m/4Gi,6x2000m/2Gi,12x1000m/1Gi --concurrency 32 64 128 256 --processes 8
```

- The CPU limit may go up to 4000m per pod and the memory limit up to 16Gi; `COMPANY_DNS_REPLICAS` follows the replica count.
- `--processes` sets the load generator's worker processes. The summary shows the generator's own CPU use per run and flags runs where it used 80% or more of its processes: there the generator, not the server, may have been the limit.
- `--max-concurrency` (default 256) guards the nodes that production shares.
- The scheduler decides which node each pod lands on (the Deployment only prefers to spread pods). The summary gives the pods per node for each configuration (for example `2 + 1`), and `results.json` has the pod-to-node map. A deliberate split by node size needs node labels and node affinity in the manifest; that is a deployment decision, not a test switch.
- Two things to watch at four cores per pod: embeddings are serialized per pod (one at a time, so N pods run at most N embeddings at once), and query partitions are capped at 4. If `3x4000m` does not beat `6x2000m` on embeddings, the cores of the large pods are not being used.
