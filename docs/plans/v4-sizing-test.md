# V4 sizing test: two larger replicas, or four smaller ones?

Status: **Done (2026-10-11). Run on the real cluster in three rounds; results and the decision (20 x 1000m) are recorded at the end of this document.**
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

- Up to 32 replicas, a CPU limit up to 4000m per pod and a memory limit up to 16Gi are accepted; `COMPANY_DNS_REPLICAS` follows the replica count.
- `--processes` sets the load generator's worker processes. The summary shows the generator's own CPU use per run and flags runs where it used 80% or more of its processes: there the generator, not the server, may have been the limit.
- `--max-concurrency` (default 256) guards the nodes that production shares.
- The scheduler decides which node each pod lands on (the Deployment only prefers to spread pods). The summary gives the pods per node for each configuration (for example `2 + 1`), and `results.json` has the pod-to-node map. A deliberate split by node size needs node labels and node affinity in the manifest; that is a deployment decision, not a test switch.
- Two things to watch at four cores per pod: embeddings are serialized per pod (one at a time, so N pods run at most N embeddings at once), and query partitions are capped at 4. If `3x4000m` does not beat `6x2000m` on embeddings, the cores of the large pods are not being used.

### Round three: pod count and repeated lookups

- Results of the larger-replica round: at equal total CPU, embedding throughput scaled with the *number* of pods (3x4000m 76 requests/s, 6x2000m 140, 12x1000m 231) because an embedding runs one at a time per pod; lookups were CPU-bound and shape-insensitive (about 1200 requests/s on 12 cores).
- To find where more 1-core pods stop helping: `--configs 12x1000m/1Gi,16x1000m/1Gi,20x1000m/1Gi,24x1000m/1Gi --mixes lookups,repeated`. The `repeated` mix draws from a small pool, so it shows what repeated asks cost.
- The per-IP rate limits are settings now (`COMPANY_DNS_RATE_LIMIT_*`, `v4/README.md`); with many replicas keep the burst well above the replica count.

### Results and decision (hackathon sizing)

Measured on the two worker nodes, one run per cell; the nodes also carry other workloads, so differences under about 20% are noise.

| configuration (12 cores unless stated) | embedding req/s (p95 <= 1 s) | lookups req/s at N=256 | lookups p95 |
|---|---|---|---|
| 3 x 4000m/4Gi | 76 | 1196 | 697 ms |
| 6 x 2000m/2Gi | 140 | 1230 | 739 ms |
| 12 x 1000m/1Gi | 231 | 1262 | 560 ms |
| 16 x 1000m/1Gi (16 cores) | not run | 1600 (repeated lookups 1987) | 479 ms |
| 20 x 1000m/1Gi (20 cores) | not run | 1873 (repeated lookups 2301) | 421 ms |

- Embeddings run one at a time per pod, so their throughput follows the number of pods, not their size. Lookups are CPU-bound at about 94 requests/s per core of limit and kept scaling to 20 pods.
- Memory peaked at about 250 MiB per pod; throttling at 1000m was about 1%; the load generator was never the limit; production restarted 0 times.
- **Decision:** staging runs 20 x 1000m/1Gi (`k8s/staging/deployment.yaml`), with requests at half the CPU limit so the other workloads on the nodes are not crowded out, `COMPANY_DNS_REPLICAS=20`, and a per-IP quota of 6000 a minute with a burst of 600 (30 per pod).
- Not yet measured at 20 pods: embedding throughput (the 12-pod rate per pod, about 19 requests/s, would give roughly 380), the rate limiter's behaviour across 20 pods (`docs/v4-bringup.md`, step 6.3), and a rolling update of 20 pods (`maxSurge` is 4).
