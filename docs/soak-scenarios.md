# Soak scenarios after the first 24 hours

The first soak ([soak-test.md](soak-test.md); results in [performance-report.md](performance-report.md)) proved stability for one steady workload: lookups at 60 requests/s from outside the network for 24 hours.
These are the next scenarios, in order, each with who does what, the commands, and what counts as a pass. The tools: `perf_tests/soak.py` (the load and the known-answer checks, run by a remote tester),
`perf_tests/pod_watch.py` (the pods seen from the cluster: readiness, restarts, memory, CPU throttling; run on the build node) and `perf_tests/soak_analyze.py` (merge sites; judge events).

**Never during an event, and never against a cluster someone else is changing.** Staging shares its nodes with other services: keep to the steady rates below.

## Scenario 2: rollout under load (about 2 hours)

**Question:** does anything fail while the deployment changes under a steady load? This is what cutover day is made of, and the bring-up guide's rolling-update, rollback and restart checks at 20 pods have not been run.

**Two people.** The *tester* (remote) only starts the soak. The *maintainer* (on the build node) runs the watcher and makes the changes, noting the time of each.

**Before starting.** Staging healthy at 20 pods (`./scripts/build-and-deploy-v4.sh --status`). Deploy the **next** image (`NEXT`, for example `main` with the latest fixes) beforehand with the normal script, so `NEXT` is running and the previous revision is the one the cluster remembers
(`--rollback` needs it). Note both tags. No one else deploys to staging during the test.

### Start

Tester, from outside the network (a steady 60 requests/s, a short ramp, two hours):

```bash
python3 perf_tests/soak.py --label your-name-where --hours 2 --steps 4 --step-minutes 5 --hold-concurrency 16 --rps 60 --out ./soak-rollout
```

Maintainer, on the build node, in the repository root, at about the same moment:

```bash
python3 perf_tests/pod_watch.py --interval 15 --hours 2.25 --out ./watch-rollout &
mark() { echo "$(date -u +%FT%TZ) $*" >> events.txt; }      # the same clock as the soak (UTC)
```

Let it run for 15 minutes untouched: that is the baseline.

### The changes (about 15 minutes apart; mark each one just before you run it)

| After | Mark and run | What it tests |
|---|---|---|
| 15 min | `mark "rollback to previous revision"`; `./scripts/build-and-deploy-v4.sh --rollback` | a rolling update backwards (the rollback you would do on cutover day) |
| 30 min | `mark "roll forward to NEXT"`; `./scripts/build-and-deploy-v4.sh --no-build NEXT` | a rolling update forwards |
| 45 min | `mark "delete one pod"`; `kubectl -n company-dns-staging delete pod <one pod name>` | a pod lost without warning |
| 60 min | `mark "delete two pods"`; `kubectl -n company-dns-staging delete pod <name> <name>` (on different nodes if you can see them) | two lost at once |
| 75 min | `mark "restart all pods"`; `kubectl -n company-dns-staging rollout restart deployment/company-dns` | a restart after a ConfigMap or setting change |
| 90 min | `mark "scale down to 16"`; `kubectl -n company-dns-staging scale deployment/company-dns --replicas=16`; wait 5 minutes; `mark "scale up to 20"`; `kubectl -n company-dns-staging scale deployment/company-dns --replicas=20` | losing and regaining capacity (the rate limit's per-pod share is briefly off, since `COMPANY_DNS_REPLICAS` stays 20) |

Take the pod names from `kubectl -n company-dns-staging get pods`. Do not drain or cordon a node: it carries other services.

### Stop and judge

The soak ends by itself after two hours (the tester can also press `Ctrl-C`); stop the watcher (`kill %1`). The tester sends the whole `soak-rollout` directory. Then:

```bash
python3 perf_tests/soak_analyze.py events --soak ./soak-rollout --events ./events.txt --watch ./watch-rollout --span 5
```

It judges each marked change over the next five minutes: **PASS** means no request errors, every known-answer check right, and p95 within 1.5 times the quiet baseline; otherwise **REVIEW** with the reason and the soak windows.
The same table shows, from the cluster, the fewest ready pods, the most terminating, new restarts and peak memory.

### Pass

- Every event PASS; zero errors and zero wrong answers over the whole run.
- Ready pods never below 18 at a pod kill, and back to 20 within a few minutes; no unplanned restarts (`new_restarts` 0 outside the changes you made), no out-of-memory kill, peak memory per pod well under the 1 GiB limit.

### If an event is REVIEW

- **Errors or resets at a pod kill or rollout** are most likely requests to a pod that is going away (keep-alive connections, or the pod leaving the load balancer after it stops accepting). The first things to try, in `k8s/staging/deployment.yaml`: a `preStop` delay of about 10 seconds
  and a termination grace period that covers it, then repeat the scenario.
- **Slow p95 but no errors** during a rollout: the new pods were taking traffic before they were warm; check the readiness probe's delay.
- Anything else: keep the directory and the watch output, and read the event's windows in `events.md`.

## Scenario 3: breadth, from several places (12 to 24 hours)

**Question:** is it stable under a wider mix, from more than one caller? Mostly lookups on both the V4 and the V3 paths, with a few embedding searches (the "bleed over" from the hackathon), from two or three locations at once, each with its own address (per-IP limits are independent).

Each tester, at the same time:

```bash
python3 perf_tests/soak.py --label name-where --hours 12 --mix breadth --embedding-share 0.05 --rps 60 --out ./soak-breadth
```

The maintainer runs `pod_watch.py` for the same period (`--interval 60`), then merges the sites:

```bash
python3 perf_tests/soak_analyze.py merge ./site-a ./site-b ./site-c --out ./soak-breadth-merged
```

**Pass:** every site passes (the merged summary says so), no restarts or out-of-memory kills in the watch, memory flat (no climb across the hours; embedding searches hold the model in memory, so watch for growth), and no `429`s at 60 requests/s per site.

## Scenario 4: the same soak on production, after the cutover (24 to 72 hours)

The first soak's command, aimed at the production address (`--url`), with V3 standing by and `pod_watch.py --namespace company-dns` watching read-only. Compare with the staging baseline: p95 within noise of 116 ms from the same tester, no errors.
This is the soak of the production cutover plan ([plans/v4-production-cutover.md](plans/v4-production-cutover.md), WP7).

## Optional: the limit biting (about 1 hour)

A short soak with no credentials at a rate above the per-address quota (`--rps` above the quota's rate), to see that `429`s are clean (`Retry-After` present, no `5xx`) and the service recovers when the load drops. The `429`s are counted apart from errors and
the run is expected to *miss the bar* only because of them; read the summary's `429` counts and the watch output.
