# V3 versus V4: the clean-run comparison and the results report

Plan for the evidence that closes step 6 of `v4-release-to-staging.md`. Written 2026-10-10 before any of it is built. The owner's framing:
caches are part of the design (V4 has them, and V3 has them in places), so there is no cache-off test; the question is whether V4 **regressed in
function beyond what was designed** and whether it **improved or regressed in performance, concurrency included**. The deliverable is a repeatable
clean run for each image, and a tool that turns the results into pictures (PNG or JPG) that show where V4 gained, where it did not, and why.

## 1. The two claims, and what would support them

| Claim | It is supported when | Evidence (data source) | Pictures |
|---|---|---|---|
| **Function: no regression beyond what was designed** | Every V3 route is served by V4 or excluded by a recorded decision; every difference in the 25 parity requests is on the intentional-differences list with its reason; the V4 test suite passes with no unexplained failure | the two OpenAPI specs (V3 and V4, fetched live), `parity_report.py` JSON, the `api_tests` report, the differences list in `v4-release-to-staging.md` | F1 route coverage, F2 parity verdicts, F3 differences ledger, F4 test results by layer, F5 what V4 adds |
| **Performance: improved or not regressed, concurrency included** | For every route in the matrix, at the production limits and with headroom, V4's median and p95 are no worse than V3's beyond run-to-run noise, with the gains attributed to something measured | the clean-run matrix below (`perf_tests` result JSON plus resource samples) | P1 latency cold, P2 latency warm, P3 concurrency scaling, P4 throughput and CPU, P5 resources and footprint, P6 reliability, P7 why |

"Beyond noise" is defined once, here: a route regresses only if V4's median is more than 10% worse than V3's in the same regime **and** that holds in at least two
of three repeated runs. (This is `compare.py`'s own 10% threshold, made repeat-aware.) Anything else is reported as "no difference".

## 2. The clean run: what "clean, with every performance benefit on" means

One run is one image started from nothing, measured in a fixed order. Nothing is switched off: caches on, gzip on, the production settings.

1. **Stop and remove** every comparison container and network (`down -v`); nothing carried over. Record `uptime`, `nproc`, memory, `cpu-check.sh` output and the image digests.
2. **Start the image** at the chosen resource limits and time it to the first healthy `/health` (time to healthy). Sample container CPU and memory every second from here (`docker stats`).
3. **Cold pass:** the sequential matrix on the ten companies with empty caches. Routes run in an order that does not let one route warm another's cache for the
   cold numbers: each route's cold set runs before any other route touches the same company, or the cold pass restarts the container between routes (decided in step 6 of section 6, once I see how much it costs).
4. **Warm pass:** the same sequence again, no restart (what a server with repeat traffic looks like).
5. **Concurrency pass:** N = 1, 4, 8, 16 concurrent requests per route, three repeats, correctness-checked as `baseline.py` already does.
6. **Stop**, save raw results and resource samples.

**Images measured (one at a time, never together):** V3 `09272026-1` (the production image), V4 `release-lean`, V4 `release-small`.
**Regimes:** (a) the production pods' limits, 500m CPU and 1Gi; (b) headroom, 16 CPUs and 64Gi, which is what the large nodes can do.
**Repeats:** three full clean runs per image per regime, in rotated order (V3, lean, small; then lean, small, V3; then small, V3, lean) so that drift on the node (load, upstream weather) is spread evenly.
**Host:** `cafe-1` first (amd64, the production hardware class), the second node after to check repeatability; the Mac Studio for arm64 later. Results from different hosts are never mixed in one chart.
**V4 access:** the throwaway no-rate-limit profile, so the limiter is not what is measured. V3 has none in force.
**Fixed inputs:** the ten companies in `perf_tests/companies.py`, the identifying User-Agent, a 120 s request timeout (so slow is not mistaken for failed), the same egress for both.

## 3. The harness (runs on the node, standard library only)

`perf_tests/run_matrix.py`. One command runs the whole protocol for the images and regimes asked for, writes everything under
`perf_tests/results/matrix-<date>-<host>/` and is resumable (a finished run is skipped on restart):

```
raw/<regime>/<image>/run<k>/sequential-cold.json, sequential-warm.json, concurrency.json, resources.csv, container.json
specs/v3-openapi.json, specs/v4-openapi.json
parity/<image>.json, suite/v4-<image>.json
manifest.json     # host facts, cpu-check output, image digests, git commit, order of runs, start and end times, tool versions
```

It reuses `baseline.py` for the measuring (so numbers stay comparable with every earlier file), `docker compose` for lifecycle, and `docker stats` for resources.
It refuses to start if another comparison container is running or the node's load average is above a threshold (the courtesy rule for the production pods), and
stops a run cleanly if a production pod restarts.

## 4. The report tool (runs on the Mac, needs matplotlib)

`perf_tests/report_data.py` (standard library, unit-tested) reads a `matrix-*` directory and produces the numbers: per route and regime the median, p95 and the
spread across the three repeats; the regression verdict from section 1; throughput; resource summaries; the route-coverage join. `perf_tests/report.py` draws
them with matplotlib into `docs/results/<date>/*.png` (JPG on request) plus an `index.md` that lists each picture with its takeaway and its conditions.

Every picture: a title that **states the finding** ("V4 answers local lookups 3 to 5 times faster"), a subtitle with the conditions (host, limits, n, date), the same
colour for the same image everywhere, a colour-blind-safe palette, readable at 1600 x 900, and a footer with the image tags, commit and run id. Error bars are the
spread across repeats; a result is never drawn without its n.

| # | Picture | What it shows | Why it is in the set |
|---|---|---|---|
| F1 | Route coverage | every V3 route as served / served as an alias / excluded by decision (UK pair, `/v1/` backends), from the two live specs | the "no function lost" claim |
| F2 | Parity verdicts | the 25 requests as identical / same shape / intentionally different, per route family | shows how close the answers are |
| F3 | Differences ledger | each difference with its reason (corrected Japan data, EDGAR window, merged shape, `tickers` fix...) | every difference is accounted for |
| F4 | Test results | tests by layer (smoke, contract, data, parity, V4-only, limits), passed / skipped / expected failure | the function was exercised |
| F5 | What V4 adds | counts and names of V4-only capabilities (hybrid search, map, match, SQL experimental, lineage fields) | the gain in function |
| P1 | Latency, cold | grouped bars per route, V3 / lean / small, median with p95 whisker, log scale, both regimes | the fair single-request comparison |
| P2 | Latency, warm | same, with the cache effect shown separately and labelled | what a running server sees |
| P3 | Concurrency | wall time and speedup against N per route, per image, both regimes | the concurrency claim |
| P4 | Throughput and CPU | requests per second and CPU at saturation (N = 16) | how much load a pod carries |
| P5 | Footprint | image size, binary size, time to healthy, idle and peak memory | the cost of running it |
| P6 | Reliability | status codes and errors per route and image, timeouts shown explicitly | success rate under load |
| P7 | Why | for each gain, the measured cause (see below) | the "where and why" the owner asked for |

## 5. Why V4 is faster: only causes we measure get claimed

A picture may only attribute a gain to something we have measurements for. Today's status:

| Cause | Status | Evidence |
|---|---|---|
| In-memory result cache (warm repeat of Wikipedia 3.4 ms against 741 ms) | **Measured** | warm versus cold passes |
| gzip on the Wikidata call (704 ms plain, 540 ms gzipped; 305-670 KB down to 47-117 KB) | **Measured** (one call, ten companies) | the gzip A/B, 2026-10-08 |
| Local lookups on DataFusion over feather files against V3's SQLite (`sic_lookup` 49.9 to about 11 ms) | **Measured effect, cause not isolated** | the matrix; a micro-benchmark of one query on each would separate engine from HTTP overhead |
| Rust and tokio against Python and the threadpool (health 4.6 to 2-3 ms, concurrency) | **Measured effect, cause not isolated** | `health` is the control for framework overhead |
| V3's older image timing out (63 timeouts on `09262026-5`) | **Explained by code history** (the Wikipedia v2 cut-over came after that image), image check pending | `git log`, the image grep |
| Cold Wikipedia is level with V3 (735 against 741 ms) | **Measured** | the cold pass |

The "why" picture (P7) states the unmeasured ones as observations ("health, which has no work in it, is 2x faster, so about half the gain is framework overhead"), not as proven causes, and
adds a micro-benchmark if a claim needs it.

## 6. Steps, and who does what

| # | Step | Where | Output |
|---|---|---|---|
| 1 | `report_data.py` with unit tests, developed on the existing result files (V3 t120, V4 cold and warm) | Mac | **Done 2026-10-10**: `perf_tests/report_data.py`, 13 tests |
| 2 | `run_matrix.py` with a dry-run mode and a tiny fixture run on a Mac container | Mac | **Done 2026-10-10**: `perf_tests/run_matrix.py`, 8 tests, and a one-image, one-repeat trial on the Mac that `report_data.load_matrix` reads back. `baseline.py` gained `--skip-sequential` and `--endpoints`. Not yet run with V3 or on an amd64 node |
| 3 | `report.py` and the figure set, drawn first from the existing files and the 2026-10-10 parity and suite runs | Mac | **Done 2026-10-10**: `perf_tests/report.py` (12 pictures, PNG or JPG, `--draft` watermark; titles and phrases computed from the data; a figure whose inputs are missing is skipped and listed in `index.md`), `docs/results/evidence.json` and `differences.json` (each entry with its source), 10 tests. Draft pictures reviewed on a scratch matrix of real files only: V4 lean from the Mac trial, V3 stood in by the old Sep 28 file (layout check, not a comparison). Needs `perf_tests/.venv` (matplotlib, numpy) |
| 4 | Run the matrix on `cafe-1` (about 3 images x 2 regimes x 3 repeats; hours, unattended) | node | `matrix-*` directory |
| 5 | Copy the results back, generate the final figures, review each against its data | Mac | `docs/results/<date>/` |
| 6 | Decide the cold-pass method (restart per route or ordered sets) | Mac trial | **Decided 2026-10-10: restart the container before each route's cold set.** A trial with ordered sets showed merged firmographics at 15.7 ms "cold" because the Wikipedia route had just warmed its cache; with a restart per route it is 796 ms (its true Wikipedia cost) and the warm pass 15.6 ms. |
| 7 | Repeat on the second node; arm64 on the Mac Studio when wanted | nodes | repeatability chart |
| 8 | Update `v4-release-to-staging.md` (step 6 done, the table of numbers) and open the PR | Mac | PR |

## 7. Dependencies and decisions

- **matplotlib (and numpy) is needed on the Mac for `report.py`** and is not installed. Plan: a virtual environment under the repo's `perf_tests/.venv` (gitignored) with `pip install matplotlib`, pinned in `perf_tests/requirements-report.txt`. This downloads packages from PyPI, so it needs the owner's yes before I run it. The harness and `report_data.py` need nothing beyond the standard library, so the node stays as it is.
- Figures are committed (they are the evidence, a few MB); raw matrices are not, only their manifest and a hash.
- Both V4 images are measured (lean and small) because the lean-or-small choice depends on it.
- PNG is the default format; `--jpg` writes JPG for slide decks.
- Open: how many repeats (default 3), whether to include N = 16 (default yes), whether the Mac Studio run is part of this release or later (default later).

## 8. Definition of done

- One command on a node produces the whole matrix; one command on the Mac produces the full figure set and `index.md` from it.
- The function claim is shown by F1 to F5 with no unexplained difference; the performance claim by P1 to P7 with every regression flag either absent or explained.
- Each picture states its conditions, n and image tags; every "why" is marked measured or observed.
- The tools have tests (aggregation, regression rule, coverage join) and the result of running them is in the PR.
- `v4-release-to-staging.md` step 6 and its progress table are updated with the final numbers.
