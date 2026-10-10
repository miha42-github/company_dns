# Building V4 on amd64 and comparing it with V3

Runbook for plan step 6 (`v4-release-to-staging.md`). Run it on one of the idle amd64 nodes, then repeat on the second node. Written
for `main` once the data-supply change is merged (see step 1). Everything is a command you run on the node, except step 2, which is run from the Mac.

## 0. What the node needs

| Need | Check |
|---|---|
| Nothing special about the CPU, but check what you have: the image loads Microsoft's official ONNX Runtime (`ORT_MODE=dynamic`, the default), which runs on CPUs without AVX2 such as `cafe-1`'s 2 x Xeon E5-2650 v2. (`--ort download` selects pyke's prebuilt runtime instead, which needs AVX2 and exits at start with `WARNING: This CPU does not support AVX2` without it. See plan item I.) | `v4/scripts/cpu-check.sh` (prints architecture and AVX2/NEON, and which builds fit; the server logs the same `CPU: ...` line at start) |
| Docker Engine 24 or newer **with the `buildx` and `compose` plugins** (Ubuntu's own `docker.io` package ships without them: `sudo apt-get install -y docker-buildx docker-compose-v2`) | `docker version && docker buildx version && docker compose version` |
| `git`, `python3` (3.9+, standard library only for the test tools), `rsync`, `curl` | `git --version && python3 --version` |
| 20 GB free disk (build cache, images) | `df -h /var/lib/docker` |
| 16 GB of memory for the build (fat-LTO link; the nodes have far more) | `free -g` |
| Outbound HTTPS to `github.com`, `ghcr.io`, `cdn.pyke.io` (the Rust build downloads the ONNX runtime), `index.crates.io`, `static.crates.io`, `deb.debian.org`, `pypi.org`, `sec.gov` (the image build ingests the EDGAR catalog, as V3's does), `wikipedia.org`, `wikidata.org` | `curl -sI https://cdn.pyke.io \| head -1` |
| Read access to the V3 image on `ghcr.io` (needed only if the package is private) | `docker login ghcr.io` with a token that has `read:packages` |

Nothing else is needed for V3: the comparison pulls the same image production runs. Do not rebuild V3 from source for this; its `makedb.py` downloads
the SEC and SIC source data during the image build and takes much longer, and a rebuilt V3 is not the V3 that production serves.

## 1. Get the code

Use `main` once the PR that added this runbook is merged (it brings the Dockerfile's data-supply stages, `fetch_data.py`, `data-manifest.json`, the compose files and the profile helper). Before that, use its branch.
There is no release tag yet; it will be cut after the comparison.

```bash
git clone git@github.com:miha42-github/company_dns.git && cd company_dns
git checkout main           # or the branch of the data-supply PR, until it is merged
ls v4/data-manifest.json v4/scripts/fetch_data.py v4/docker-compose.compare.yml v4/docker-compose.perf.yml    # all four must exist
```

## 2. Stage the two inputs that are not in git (run from the Mac, not the node)

The build takes the four SIC feather files and the embedding model from two directories (`--build-context data=...` and `--build-context model=...`). **The EDGAR catalog is not staged:** like V3's `makedb.py`, the image build makes it by running `ingest-edgar` against sec.gov (about 15 seconds), so the node only needs sec.gov reachable. (Alternatively the SIC files can be fetched from a URL, see the note after step 3.)

```bash
NODE=user@node-hostname            # your node
ssh $NODE 'mkdir -p ~/company-dns-inputs/data ~/company-dns-inputs/model'
cd /Users/mihay42/dev/company_dns/tmp
rsync -av us_flat_embedded.feather japan_rev13_flat_embedded.feather nace_rev2_flat_embedded.feather \
          isic_rev4_flat_embedded.feather  $NODE:company-dns-inputs/data/
rsync -av /Users/mihay42/dev/company_dns/.claude/worktrees/repo-overview-ed2879/v4/.fastembed_cache/ $NODE:company-dns-inputs/model/
```

(The model directory must contain `models--Qdrant--all-MiniLM-L6-v2-onnx`. If the worktree has been cleaned, run the server once on the Mac to recreate it.)

Check the SIC files on the node against the pinned manifest (the build checks this too, but failing here is quicker), so both architectures run identical data:

```bash
cd ~/company_dns
python3 v4/scripts/fetch_data.py --source dir:$HOME/company-dns-inputs/data --out /tmp/sic-check && rm -rf /tmp/sic-check
```

A `HASH MISMATCH` means the files differ from `v4/data-manifest.json`, the pin for this release; stop and find out why (a newer delivery needs its hash updated on purpose, after `check_ic_feather.py` passes).

## 3. Build both images (native amd64, no `--platform`)

```bash
export DATA_DIR=~/company-dns-inputs/data MODEL_DIR=~/company-dns-inputs/model
time v4/scripts/docker-build.sh -t company-dns-v4:amd64-lean  -p release-lean
time v4/scripts/docker-build.sh -t company-dns-v4:amd64-small -p release-small
```

Expected: the manifest check and the data gate print `verified` and `PASS` lines early in the log; a 5 to 15 minute Rust build each (slower on a cold cache); then `Ingesting 8 quarters (2024Q4 to 2026Q3)` and `EDGAR catalog: 72813 rows` (the row count moves a little if the SEC's index has changed). The EDGAR layer is cached by date, so a rebuild on another day re-ingests. If the build stops with
`MISSING data file ...` or a `FAIL` from `check_ic_feather.py`, the input is wrong, not the build. Do not use `--lto off` here: that switch exists for small
Docker VMs and its output must never be benchmarked or published.

**Other ways to supply the data (stubs, not needed for this run):** `v4/scripts/docker-build.sh --data-source url:https://HOST/DIR/` fetches the four SIC files over HTTP(S) instead of reading `DATA_DIR`
(put a header line such as `Authorization: Bearer ...` in a file and export `DATA_AUTH_FILE=that-file`; it is passed as a BuildKit secret). `--edgar data` uses a frozen `edgar_10x_catalog.feather` from `DATA_DIR`
instead of ingesting, which is the way to compare two builds on exactly the same EDGAR data.

## 4. Smoke test each image (starts with no network, then runs the offline test layers)

```bash
v4/scripts/docker-smoke.sh company-dns-v4:amd64-lean  4100
v4/scripts/docker-smoke.sh company-dns-v4:amd64-small 4100
```

Pass looks like `healthy with no network`, `OK (skipped=3)` and `== done`.

## 5. Record the amd64 sizes

```bash
for t in lean small; do
  echo "$t binary bytes: $(docker run --rm --entrypoint sh company-dns-v4:amd64-$t -c 'stat -c %s /app/company-dns-server')"
done
docker images company-dns-v4 --format '{{.Tag}}\t{{.Size}}'
```

The arm64 numbers to compare with (Mac, 2026-10-09): lean binary 104,429,784 bytes and image 684 MB; small binary 74,217,624 bytes and image 599 MB.

## 6. Bring up V3 and V4 side by side

Do these in order; each has a check that tells you it worked.

**6.1 Make the throwaway no-rate-limit profile for V4** (needed: V4's rate limiter allows a generic User-Agent 5 requests a minute and an identified caller 200 a minute, so a load run
without it measures the limiter, not the server; V3 has no limiter in force). Nothing here is a real secret and nothing is committed.

```bash
export PERF_SECRETS_DIR=$HOME/perf-secrets
v4/scripts/perf-profile.sh "$PERF_SECRETS_DIR"        # writes credentials, rules.json and token (mode 600)
export AUTH="perf:$(cat $PERF_SECRETS_DIR/token)"       # the value the test tools take as --auth
```

**6.2 Pull V3** (the image production runs; see `k8s/prod/deployment.yaml`). The image carries its own database, so nothing is staged for it.

```bash
docker pull ghcr.io/miha42-github/company_dns/company_dns:09272026-1
```

If the pull is denied, the package is private: `docker login ghcr.io` with a token that has `read:packages`, then pull again.

**6.3 Start both** at the production pods' limits (500m CPU, 1Gi). Two compose files: the comparison file and the overlay that gives V4 the profile.

```bash
export V4_IMAGE=company-dns-v4:amd64-lean              # or company-dns-v4:amd64-small for the second pass
C="docker compose -f v4/docker-compose.compare.yml -f v4/docker-compose.perf.yml"
$C --profile v3 --profile v4 up -d
$C --profile v3 --profile v4 ps                        # both "running"
```

Checks (give V3 up to a minute to start):

```bash
curl -s  localhost:8000/health                                                   # V3
curl -s -A "company_dns-check/1 (you@example.com)" localhost:4000/health         # V4 (a generic curl User-Agent would be rate limited)
curl -s -o /dev/null -w "V4 profile: HTTP %{http_code}\n" -u "$AUTH" localhost:4000/V3.0/na/sic/description/oil     # expect 200
docker logs compare-v4 2>&1 | grep -iE "Loaded|WARN|ERROR" | head                # expect the data files loaded and no 'section_full_desc' warning
docker logs compare-v3 2>&1 | tail -3
```

If V3 does not come up: `docker logs compare-v3`. If V4 does not come up: `docker logs compare-v4`; a missing file or model is named in the first lines.

### 6a. Functional parity, both up at once (no production traffic, so it can be as chatty as you like)

```bash
python3 api_tests/parity_report.py --v3 http://localhost:8000 --v4 http://localhost:4000 --repeats 3 --pause 0.2 \
        --auth "$AUTH" --json perf_tests/results/amd64-parity-lean.json
API_TESTS_NETWORK=1 python3 api_tests/run.py --base-url http://localhost:4000 --profile perf --token "$(cat $PERF_SECRETS_DIR/token)" \
        --network --report api_tests/baselines/amd64-lean-suite.json
python3 api_tests/compare.py api_tests/baselines/step4-unthinned-suite.json api_tests/baselines/amd64-lean-suite.json   # no regressions expected
```

Expected: the parity report ends `Verdicts: {'IDENTICAL': 16, 'SAME SHAPE': 6, 'DIFFERENT': 3}` (the three are the intentional ones: Japan description search, EDGAR `ciks` scope, merged firmographics; V3 here is
the Sep 26 image, so EDGAR filing dates can differ a little). On the node the suite skips L5 (it starts its own server from a local binary, and there is none), so `compare.py` lists the 31 L5 tests as `REMOVED`; that is expected. The two SQL contract checks skip or adapt when SQL is off (the production default, and how this container runs): the route must then be absent from the spec and answer 404.

### 6b. Performance, one service at a time, equal limits

Never run V3 and V4 passes at the same time. Record the node's load beside every result (`uptime`).

```bash
$C --profile v4 down; $C --profile v3 up -d          # V3 only, 500m / 1Gi
uptime; python3 perf_tests/baseline.py --base-url http://localhost:8000 --repeat 3 --out perf_tests/results/amd64-v3-limited.json
$C --profile v3 down; $C --profile v4 up -d          # V4 only, same limits
uptime; python3 perf_tests/baseline.py --base-url http://localhost:4000 --auth "$AUTH" --repeat 3 --out perf_tests/results/amd64-v4-lean-limited.json
python3 perf_tests/compare.py perf_tests/results/amd64-v3-limited.json perf_tests/results/amd64-v4-lean-limited.json
```

Check the V4 report has no `429`: `grep -c 429 perf_tests/results/amd64-v4-lean-limited.json` should print `0`. (`baseline.py` now sends an identifying User-Agent by default and accepts `--auth`; V3 ignores both.)

Cold then warm: the first pass right after `up -d` is the cold run (V4's Wikipedia and EDGAR in-memory caches are empty); run the same command again without restarting for the warm run and
save it under a `-warm` name. Headroom run (what these large machines can do): `down`, then `LIMIT_CPUS=16 LIMIT_MEM=64g` exported before `up -d`, repeat both passes, name the files `-headroom`.
Then the same again with `V4_IMAGE=company-dns-v4:amd64-small` for the lean-or-small choice.

### 6c. Reading the results

`perf_tests/compare.py` flags `REGRESSION` and `IMPROVED` per endpoint. Trust the flags on the local routes (`health`, `sic_lookup`, `edgar_ciks`) and read the Wikipedia and merged rows as noisy (the upstream
services dominate them). Production pods may be running on these nodes: if a production pod restarts or its latency stays well above normal during a run, stop and look.

## 7. Repeat on the second node, then send back

Repeat sections 2 to 6 on the other node; a large difference between the two nodes is a measurement problem to understand before trusting either. Bring back:

- `perf_tests/results/amd64-*.json`, `api_tests/baselines/amd64-lean-suite.json`, and `docker logs compare-v4` / `compare-v3` for any run that misbehaved
- the five size numbers from step 5 and the `time` lines from step 3
- `uptime` before each pass, and the output of `docker version` and `nproc; free -g`

## 8. Clean up

```bash
$C --profile v3 --profile v4 down
rm -rf "$PERF_SECRETS_DIR"                                          # the throwaway profile
docker rmi company-dns-v4:amd64-lean company-dns-v4:amd64-small   # optional; keep them if you will repeat
docker builder prune -af                                           # frees the Rust build cache
```
