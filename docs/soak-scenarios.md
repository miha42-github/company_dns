# Soak scenarios after the first 24 hours

The first soak ([soak-test.md](soak-test.md); results in [performance-report.md](performance-report.md)) proved stability for one steady workload: lookups at 60 requests/s from outside the network for 24 hours.
These are the next scenarios, in order, each with who does what, the commands, and what counts as a pass. The tools: `perf_tests/soak.py` (the load and the known-answer checks, run by a remote tester),
`perf_tests/pod_watch.py` (the pods seen from the cluster: readiness, restarts, memory, CPU throttling; run on the build node) and `perf_tests/soak_analyze.py` (merge sites; judge events).

**Never during an event, and never against a cluster someone else is changing.** Staging shares its nodes with other services: keep to the steady rates below.

## From a machine on the same network (for example a Mac Studio beside the cluster)

The soak can run from any machine, including one on the cluster's own network, with `pod_watch.py` on the build node. What that does and does not show:

- **It shows** how the cluster behaves: stability, and what happens to requests during a rollout, a restart or a lost pod. That is what scenario 2 is about, and a nearby client sees it with less network noise.
- **It does not show** the public path (the internet, then the router's port forward, then the ingress), or what a distant client sees; latencies are lower. The first 24-hour soak, run remotely, covers the public path; keep a remote tester for the runs where that matters (scenario 4 especially).

**Reaching the server.** The router does not loop traffic from the network back to its own public address, and the public name may not resolve to the cluster from inside. First check from that machine: `curl -sI <service-url>/health` should answer within a second or two. If it fails or hangs, give the soak the ingress address directly:

```bash
python3 perf_tests/soak.py ... --connect-to <ingress-address>      # the address `kubectl -n company-dns-staging get ingress` shows
```

The connection goes to that address, but the certificate and the routing still use the service's name, so TLS validates as normal. The address is not written into the results.

**Also.** Keep the machine awake (on macOS run it as `caffeinate -i python3 perf_tests/soak.py ...`; Python 3.10 or newer). The per-address limits apply to that machine's address, as for any single caller, so `--rps 60` stays under them.
**Clocks are not compared.** The two machines' clocks are not trusted to agree, and nobody needs to check them. Instead the watcher runs for a few minutes *before* the soak starts and a few minutes *after* it ends: the pods' CPU is low while idle and clearly higher while the soak runs, so the start and the end of the load show in the watch. `soak_analyze.py events` finds them and shifts the soak's times onto the watcher's clock (the clock your marks are made on, the build node's) by itself, and says what it did.
For scenario 3, a machine on the network and a remote tester are two different addresses, which is what that scenario wants.

## Scenario 2: rollout under load (about 2 hours)

**Question:** does anything fail while the deployment changes under a steady load? This is what cutover day is made of, and the bring-up guide's rolling-update, rollback and restart checks at 20 pods have not been run.

**One or two people, two machines.** The soak runs on one machine (a remote tester, or the machine beside the cluster: see above); the watcher and the changes run on the build node, where the time of each change is noted.

**Before starting.** Staging healthy at 20 pods (`./scripts/build-and-deploy-v4.sh --status`). Deploy the **next** image (`NEXT`, for example `main` with the latest fixes) beforehand with the normal script, so `NEXT` is running and the previous revision is the one the cluster remembers
(`--rollback` needs it). Note both tags. No one else deploys to staging during the test.

### Start

On the soak machine (a steady 60 requests/s, a short ramp, two hours; add `--connect-to <ingress-address>` if the service's name does not resolve to the cluster from there):

```bash
python3 perf_tests/soak.py --label your-name-where --hours 2 --steps 4 --step-minutes 5 --hold-concurrency 16 --rps 60 --out ./soak-rollout
```

Maintainer, on the build node, in the repository root, **first**:

```bash
python3 perf_tests/pod_watch.py --interval 15 --out ./watch-rollout &      # runs until you stop it
mark() { echo "$(date -u +%FT%TZ) $*" >> events.txt; }      # marks use the build node's clock, the watcher's clock
```

Let the watcher run **idle for at least 3 minutes**, then start the soak on the soak machine. The idle stretch is what lets the tool see where the load begins. Then let the soak run for 15 minutes untouched: that is the baseline.

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

The soak ends by itself after two hours (`Ctrl-C` also ends it cleanly). **Leave the watcher running for at least 3 more minutes**, then stop it (`kill %1`): that idle stretch shows where the load ended. Bring the whole `soak-rollout` directory to the build node (or the other way round). Then:

```bash
python3 perf_tests/soak_analyze.py events --soak ./soak-rollout --events ./events.txt --watch ./watch-rollout --span 5
```

It first lines the soak's timeline up with the watcher's from the load's start and end in the watch, and prints how (`--offset SECONDS` sets it by hand; `--no-align` trusts the clocks). It judges each marked change over the next five minutes: **PASS** means no request errors, every known-answer check right, and p95 within 1.5 times the quiet baseline; otherwise **REVIEW** with the reason and the soak windows.
The same table shows, from the cluster, the fewest ready pods, the most terminating, new restarts and peak memory.

### Pass

- Every event PASS; zero errors and zero wrong answers over the whole run.
- Ready pods never below 18 at a pod kill, and back to 20 within a few minutes; no unplanned restarts (`new_restarts` 0 outside the changes you made), no out-of-memory kill, peak memory per pod well under the 1 GiB limit.

### If an event is REVIEW

- **Errors or resets at a pod kill or rollout** are most likely requests to a pod that is going away (keep-alive connections, or the pod leaving the load balancer after it stops accepting). The first things to try, in `k8s/staging/deployment.yaml`: a `preStop` delay of about 10 seconds
  and a termination grace period that covers it, then repeat the scenario.
- **Slow p95 but no errors** during a rollout: the new pods were taking traffic before they were warm; check the readiness probe's delay.
- Anything else: keep the directory and the watch output, and read the event's windows in `events.md`.

## Scenario 2b: the remaining changes, on the graceful-shutdown build (about 70 minutes)

**Question:** the three changes the first run did not reach (two pods lost at once, a restart of all pods, scaling down and up), and: do pods now leave quickly? The first run found that every stopped pod stayed in `Terminating` for the whole 30 s because the server ignored the stop signal;
the server now keeps serving 5 s after the signal, drains, and exits (`v4/crates/server/src/shutdown.rs`). Run this on an image that includes that change.

**Pass:** every event PASS (no errors, every canary right, p95 within 1.5 times the baseline), no unplanned restarts, ready pods back to 20 after each change, and **stopped pods leave in about 6 to 10 seconds** (`soak_analyze.py terminating`; the median should be well under 15 s, against 30 s before).
The watcher samples every 5 s here so short states show.

The steps are the same as scenario 2 with these differences: rebuild first so the new image is running; the watcher uses `--interval 5`; the soak runs 66 minutes (`--hours 1.1`); the changes are 10 minutes apart, starting 10 minutes in:

| After | Mark | Change |
|---|---|---|
| 10 min | `delete one pod` | one pod deleted (this is the measurement of the graceful shutdown) |
| 20 min | `delete two pods` | one pod on each node deleted at once |
| 30 min | `restart all pods` | `kubectl -n company-dns-staging rollout restart deployment/company-dns` |
| 40 min | `scale down to 16` | `kubectl -n company-dns-staging scale deployment/company-dns --replicas=16` |
| 50 min | `scale up to 20` | `kubectl -n company-dns-staging scale deployment/company-dns --replicas=20` |

After the soak ends and 3 quiet minutes have passed, stop the watcher, and judge with `soak_analyze.py events ...` as before, then:

```bash
python3.14 perf_tests/soak_analyze.py terminating --watch ./tmp/watch-rollout
```

## Scenario 3: breadth, from several places (12 to 24 hours)

**Question:** is it stable under a wider mix, from more than one caller? Mostly lookups on both the V4 and the V3 paths, with a few embedding searches (the "bleed over" from the hackathon), from two or three locations at once, each with its own address (per-IP limits are independent).

Each tester, at the same time:

```bash
python3 perf_tests/soak.py --label name-where --hours 12 --mix breadth --embedding-share 0.05 --rps 60 --out ./soak-breadth
```

The maintainer starts `pod_watch.py` (`--interval 60`) a few minutes before the soaks begin and stops it a few minutes after the last one ends, then merges the sites (the merge needs no clock alignment):

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
