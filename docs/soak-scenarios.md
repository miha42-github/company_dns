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

### The results (13 and 14 October)

The second session (scenario 2b, 14 October, image `10142026-4446caf`) ran the three remaining changes on the graceful-shutdown build: all PASS, 0 errors, stopped pods left in 5 to 10 seconds (median 5, against 30 before). See [performance-report.md](performance-report.md), section 4b. What follows is the note on the first run.

#### The first run (13 October)

The first run passed for the rollback, the roll forward and one deleted pod; the three later changes were not reached because the steps started late (the first change came 48 minutes in, not 15). Results and the one finding (pods take the full 30 seconds to stop, because the server has no graceful shutdown) are in [performance-report.md](performance-report.md), section 4. Run the remaining three changes (two pods at once, restart all, scale down and up) in a shorter session, 10 minutes apart, with `pod_watch.py --interval 5` so a brief dip in ready pods is not missed. A mark made after the soak has ended (a note) is shown as NOT JUDGED and does not count against the run.

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

## Scenario 5: the rate limit, CORS and the ceiling (about 90 minutes, three machines)

Three machines on three different addresses (for example a Mac Studio, a Mac mini and a laptop) can show what a single address gets through the limiter, whether each address has its own allowance, and, with all three as load generators,
where the pods buckle. **Run it at an agreed time, never in the event window.** Staging shares the cluster's nodes and ingress with production: the pods are CPU-limited so they cannot take more than their own limit, but the ingress is shared, which is why production is watched too.

**Part A: the limit, from each address (about 10 minutes).** On each machine, with a start time a few minutes ahead (`date -u -v+3M +%Y-%m-%dT%H:%M:%SZ` on a Mac prints one; give every machine the same):

```bash
python3.14 perf_tests/limit_probe.py --start-at <time> --seconds 60 --expect-per-minute 6000 --expect-burst 600 --label <machine>
```

Each prints the **burst** (let through before the first `429`), the **sustained rate** after it, and how they compare with the configured 6,000 a minute and burst 600. Add the three sustained rates for the aggregate that three addresses get together: about three times one address,
because the allowance is per address. Many addresses at the full rate would reach what the pods carry (about 1,900 lookups a second) with about twenty.

**The trusted-origin bypass.** `python3.14 perf_tests/limit_probe.py --origin https://mediumroast.io --seconds 10` shows a caller that sends `Origin: https://mediumroast.io` (or a `Referer` from it) is **never limited on lookups**. That is by design (the first-party sites are not limited), but the header is set by the client, so anyone can send it.
The pods' capacity is then the only limit for such a caller. The SQL route ignores the header.

**Part B: CORS (a few minutes, `curl` from any machine).** Lookups answer any origin (the response echoes the caller's origin); the credentialed SQL route answers only the first-party origins and allows no other. Expected, for a foreign origin `https://partner.example` and a first-party one `https://app.mediumroast.io`:

- a preflight (`-X OPTIONS` with `Access-Control-Request-Method: POST`) to `/V4.0/sql` from the foreign origin: **no** `access-control-allow-origin` header; from the first-party origin: the header echoes it;
- a lookup (`/V4.0/na/sic/code/3571`) with the foreign `Origin`: `access-control-allow-origin: https://partner.example`, and its preflight (`Access-Control-Request-Method: GET`) allows it too.

**Part C: the ceiling (about 40 minutes).** Needs credentials with no rate limit (the `staging-test` profile) as `LOAD_AUTH` on each machine. On the build node run `pod_watch.py` for staging **and** for production (`--namespace company-dns`), 5 s apart, started 3 minutes before and stopped 3 minutes after.
On each machine, at the same agreed time:

```bash
python3.14 perf_tests/ceiling.py run --machines 3 --start-at <time> --label <machine> --out ./tmp/ceiling-<machine>
```

The levels are the **total** requests in flight across the three machines (256 to 3,072), and each machine sends a third of each. A machine stops its own ramp at the first step where the service buckles (error rate above 2%, p95 above 5 s, or throughput fallen 15% below its peak for two steps).
**Stop all three at once** (`Ctrl-c`) if the production watcher shows a pod not ready or restarting. Then merge, and join the cluster side:

```bash
python3.14 perf_tests/ceiling.py merge ./tmp/ceiling-studio ./tmp/ceiling-mini ./tmp/ceiling-laptop --out ./tmp/ceiling-merged
```

```bash
python3.14 perf_tests/ceiling.py report --run ./tmp/ceiling-merged --watch ./tmp/watch-staging
```

The merged summary gives the **best sustained** rate (p95 within 1 s, error rate within 1%), the peak, and the step where it buckled; the report beside it gives, per step, the pods' CPU, throttling, memory, restarts and ready pods. Repeat with `--mix embedding --levels 48 96 192 384 768 1536` for the embedding searches, which were never measured at 20 pods.

## Optional: the limit biting (about 1 hour)

(`perf_tests/limit_probe.py`, scenario 5, now measures this directly.) A short soak with no credentials at a rate above the per-address quota (`--rps` above the quota's rate), to see that `429`s are clean (`Retry-After` present, no `5xx`) and the service recovers when the load drops. The `429`s are counted apart from errors and
the run is expected to *miss the bar* only because of them; read the summary's `429` counts and the watch output.
