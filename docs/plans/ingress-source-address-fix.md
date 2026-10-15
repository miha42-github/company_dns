# Ingress hides the callers' addresses: a fix for the MicroK8s cluster

Status: **DONE and verified on 2026-10-15.** `externalTrafficPolicy: Local` is live and durable (Helm values); a probe from three machines on three addresses got 100 requests a second each (300 together, no trade-off). The record is in `docs/plans/onprem-k8s-migration.md` ("The ingress keeps the callers' addresses") and `docs/performance-report.md`, section 5c. What follows is the document as it was handed over; one addition from the work: a pod on a node without a Traefik pod (cert-manager's) cannot use the LAN address under `Local`, so the CoreDNS `hosts` block was repointed to Traefik's ClusterIP first.
Audience: whoever administers the MicroK8s cluster. No knowledge of the application is needed beyond section 1.
No addresses or host names of the lab's machines appear here (the repository is public): `<node-a>`, `<node-b>` and `<traefik-lan-ip>` stand for the two nodes and the ingress address.

---

## Summary

- **The problem.** The `traefik` Service in the `ingress` namespace has `externalTrafficPolicy: Cluster`. Kubernetes then replaces every outside caller's address with a node's address before the request reaches Traefik. The application cannot see who is calling; it sees one of two node addresses.
- **What it breaks.** The service limits each caller by address (6,000 requests a minute, burst 600). Because every caller looks like one of two addresses, **all callers share about two allowances (about 200 requests a second in all)** instead of one allowance each. The pods can carry about 2,100 requests a second. For a public event with hundreds of callers, one busy caller can use up everyone's allowance.
- **The fix.** Set `externalTrafficPolicy: Local` on that Service, so the caller's address is kept. It is one command, reversible with one command. It affects every site behind this ingress, so it should be done at a quiet time, with a before-and-after check (section 5).
- **Deadline.** The load that matters starts on **22 October 2026**. Please make the change, and run the checks in section 5, **by 16 October** if at all possible, to leave time to test again.

## 1. What the application does (the part that matters here)

The service (a lookup API, `company_dns`) runs as 20 pods in the namespace `company-dns-staging`, behind Traefik. Each pod limits callers **by address, per pod**: the configured rate is divided by the number of pods. It reads the caller's address from the **last entry of the `X-Forwarded-For` header, which Traefik adds** (the last entry cannot be forged by the caller). With the ingress hiding the real address, that last entry is a node address.

## 2. Evidence

**The measurement.** Two machines on two different addresses (a Mac Studio and a laptop on the LAN) each sent requests flat out for 60 seconds at the same time, as ordinary identified callers, to a service whose limit is 100 requests a second per address (burst 600):

| | burst (let through before the first `429`) | sustained, let through per second |
|---|---|---|
| machine 1 | 707 | 139 |
| machine 2 | 518 | 60 |
| **together** | 1,225 | **200** (189 to 210 every second) |

If each machine had its own allowance, each would have got about 100 a second. Instead the two together got exactly two allowances, split unevenly (139 and 60), and what one gained the other lost (correlation of the per-second counts: **-0.96**). The limiter was counting them against the same two buckets.
The full data and charts are in `docs/performance-report.md`, section 5b, and `docs/results/2026-10-14-limit/`.

**The cluster facts** (from `kubectl`, 2026-10-14):

```
kubectl get svc -A | grep -i traefik
ingress   traefik   LoadBalancer   <cluster-ip>   <traefik-lan-ip>   80:<port>/TCP,443:<port>/TCP

kubectl -n ingress get svc traefik -o jsonpath='{.spec.externalTrafficPolicy}'
Cluster

kubectl -n ingress get pods -o wide
traefik-xxxxx   1/1   Running   ...   <node-a>
traefik-yyyyy   1/1   Running   ...   <node-b>

kubectl -n metallb-system get ipaddresspool,l2advertisement
default-addresspool   ["<traefik-lan-ip-range>"]        default-advertise-all-pools
```

## 3. Cause

With `externalTrafficPolicy: Cluster`, `kube-proxy` accepts traffic for the load balancer address on any node and may forward it to a Traefik pod on **another** node. To make the reply find its way back, it rewrites the source address (source NAT) to the node's own address. Traefik therefore sees `<node-a>` or `<node-b>` as the caller, and writes that into `X-Forwarded-For`. This is documented Kubernetes behaviour; `externalTrafficPolicy: Local` is the standard way to keep the real source address.

## 4. The fix, and what it changes

```
kubectl -n ingress patch svc traefik -p '{"spec":{"externalTrafficPolicy":"Local"}}'
```

With `Local`, a node delivers load-balancer traffic only to the Traefik pod **on that same node**, with no forwarding and no source NAT, so Traefik sees the real caller. MetalLB (layer 2 mode here) will then announce the address only from a node that has a ready Traefik pod; both nodes have one, so failover between them still works.

**What to expect, and what to check:**

1. **A blip of a few seconds** while MetalLB re-announces the address (possibly from a different node). Every site behind this ingress is affected, not only this service. Choose a quiet moment.
2. **One Traefik pod then takes all the external traffic** (in layer 2 mode only the announcing node receives it), where today the two pods share it. The service's pods carry about 2,100 lookups a second through the current arrangement. After the change, check that a single Traefik pod is not the new limit (step 7 below).
3. **Callers behind one shared address** (a campus, a venue) will still share one allowance. That is how per-address limits work; it is not a fault.
4. **It is a manual change to a Service that something installed.** If Traefik was installed with Helm or an addon, a later upgrade or re-apply may **silently put the policy back to `Cluster`**. Find out how it was installed (step 2) and make the setting durable there.
5. **In-cluster callers** of the load balancer address (cert-manager's self-check goes through it, via a CoreDNS `hosts` entry) reach the Traefik pod on their own node, which exists on both nodes. They should not be affected; the certificate renewals are worth watching afterwards.

## 5. Procedure

Do the steps in order; each has a stop condition.

**1. Back up the Service as it is.**

```
kubectl -n ingress get svc traefik -o yaml > traefik-svc-before.yaml
```

**2. Find out how Traefik was installed** (so the change survives upgrades):

```
helm -n ingress list          # or: microk8s helm -n ingress list
kubectl -n ingress get svc traefik -o jsonpath='{.metadata.labels}'; echo
kubectl -n ingress get ds,deploy
```

If it is a Helm release, the durable form of the change is in its values (`service.spec.externalTrafficPolicy: Local` for the official chart; check the chart in use). If it is an addon or a plain manifest, record the change where that is managed.

**3. Before the change: show the problem with `curl`** (two machines on different addresses, A and B, both on the network the tests use; replace nothing, the URL is public):

On A, use up A's allowance:

```
seq 1 1500 | xargs -P 50 -I{} curl -s -o /dev/null -w "%{http_code}\n" -A "check/1.0 (you@example.org)" https://company-dns-staging.mediumroast.io/V4.0/na/sic/code/3571 | sort | uniq -c
```

Expect a few hundred `200` and many `429`. **Immediately** on B:

```
seq 1 20 | xargs -P 1 -I{} curl -s -o /dev/null -w "%{http_code}\n" -A "check/1.0 (you@example.org)" https://company-dns-staging.mediumroast.io/V4.0/na/sic/code/3571 | sort | uniq -c
```

**Before the fix, B is often limited too** (`429`s), because A and B share a bucket. After the fix B must get 20 `200`s. (With two buckets, roughly half the tries before the fix will not show it: repeat a few times.)

**4. Start an availability watch** on a machine outside the cluster, in `tmux`, to see how long the blip lasts:

```
while true; do echo "$(date -u +%T) $(curl -s -o /dev/null -w '%{http_code} %{time_total}s' --max-time 5 https://company-dns-staging.mediumroast.io/health)"; sleep 0.5; done
```

**5. Make the change.**

```
kubectl -n ingress patch svc traefik -p '{"spec":{"externalTrafficPolicy":"Local"}}'
kubectl -n ingress get svc traefik -o jsonpath='{.spec.externalTrafficPolicy}'; echo
```

The second command must print `Local`. Watch the availability loop. **Stop condition:** if the service is not answering `200` again within about 30 seconds, roll back (below) and report what the loop showed.

**6. After the change: repeat the check of step 3.** B must now get 20 `200`s straight after A has been limited. Also confirm the other sites behind the ingress still answer (open each in a browser, or `curl -I`).

**7. The proper test** (the repository's tools; `git clone` the public repository, Python 3.10 or newer, nothing to install): from **two or three machines on different addresses at the same time**,

```
python3 perf_tests/limit_probe.py --start-at <UTC time a few minutes ahead> --seconds 60 --expect-per-minute 6000 --expect-burst 600 --label <machine> --out ./limit-<machine>
```

**Expected after the fix:** each machine about **100 requests a second** and a burst near 600; about 200 a second in total for two machines (about 300 for three), and **no trade-off between them**. Then check the ingress is not the new bottleneck: repeat the ceiling test (`docs/soak-scenarios.md`, scenario 5, part C) and compare with the earlier **2,145 requests a second** (CPU limited); a clearly lower peak means the single Traefik pod is now the limit (look at `kubectl -n ingress top pods` during the run).

**8. Make it durable and write it down** (step 2's result), and add a short entry to `docs/plans/onprem-k8s-migration.md` next to the CoreDNS note: what was changed, why, the date, and how to undo it.

### Rollback, at any point

```
kubectl -n ingress patch svc traefik -p '{"spec":{"externalTrafficPolicy":"Cluster"}}'
```

(`traefik-svc-before.yaml` records the original Service.)

## 6. Why this and not something else

- **Per-team credentials** (each team gets a profile; the limit follows the profile, not the address) would also work and does not depend on the ingress, but needs credentials issued to every team. It is the fallback if this change cannot be made before the event.
- **Raising the shared limit** to roughly the pods' capacity would stop the limit protecting anything and would not give each caller a fair share.
- **PROXY protocol** (the router passes the address to Traefik) is not available with the router in use.

## 7. References

- `docs/performance-report.md`, section 5b (the measurement) and 5a (the ceiling).
- `docs/soak-scenarios.md`, scenario 5 (the limit probe and the ceiling test).
- Kubernetes: "Using Source IP" (`externalTrafficPolicy`), and MetalLB: "Traffic policies".
