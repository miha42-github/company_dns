# IC-data similarity search: local test service + minimal web UI

Status: **Built and running** (`experiments/ic-similarity-service/`) —
§§1-4 and §§6-8 below describe what was actually built, not just a
proposal anymore. §5 (similarity-score UX) is still open — analysis
written, nothing decided or implemented yet.
Owner: michael.hay@mediumroast.io
Scope: a small, local, throwaway RESTful service plus a minimal web UI
for manually testing semantic similarity search over the IC (SIC/NACE)
data — specifically `all-MiniLM-L6-v2`, per `go-duckdb-rewrite.md` §7.8
(§7.7's original two-model, low+high-dim pick got superseded after
building and using this very service — see §7.8). This is the natural
next step after §7.4-§7.7's spike work: everything so far has been benchmarks and
scripts with printed output; this is the first time the pieces (data
load, query-time embedding, similarity ranking, an actual API) get
wired together into something you can type a query into and look at
results for.

**Not the rewrite itself** — same posture as `experiments/`: disposable,
exploratory, local-only. If it's useful enough to keep, that's a
separate decision from building it.

---

## 1. What this needs to do

Given a free-text query (e.g. `"growing wheat"`, `"software company"`),
return the top-k most semantically similar IC/SIC rows, ranked by cosine
similarity, using whichever of the two decided models the user selects.
That's the whole feature. Everything else in this plan is in service of
making that testable and inspectable, not adding scope.

## 2. Stack: proposing Rust + DataFusion + `fastembed-rs` + Axum

This continues directly from `experiments/df-spike` and
`experiments/embed-bench` rather than starting fresh — same language,
same data-access approach, same embedding library already validated
against real data. Concretely:

| Piece | Proposal | Why |
|---|---|---|
| Language/runtime | Rust | Continues the stack `df-spike`/`embed-bench` already validated against real Mediumroast data — not a new decision, just using what's already been tested. `go-duckdb-rewrite.md` §6 hasn't formally locked in Go vs. Rust yet; this service is a real (if small) data point toward that decision, not a commitment that preempts it. |
| Data access | DataFusion, reading `tmp/us_flat_embedded.feather` directly | Same `read_arrow` approach `df-spike` already proved works cleanly against this exact file (§7.3/§7.4) — no new integration risk. |
| Query-time embedding | `fastembed-rs`, both decided models loaded at startup | Same crate/pattern `embed-bench` already benchmarked (§7.5) — known load times (~70-150ms) and per-query latency (~2.5-7ms). |
| Similarity ranking | DataFusion's `cosine_distance` (or equivalent) over the in-memory table, **not** a hand-rolled loop | Deliberately exercises the actual DataFusion vector-search path floated in §4.6/§6.3 as a real alternative to SQLite/DuckDB for vector search — this service is a good low-stakes place to find out if that's as easy in practice as it looked in research. Falling back to a plain Rust loop over `Vec<f32>` (trivial at 1,005 rows) is the fallback if the UDF path turns out to be more friction than it's worth — noted as an explicit decision point in §5. |
| Web framework | [Axum](https://github.com/tokio-rs/axum) | Minimal, idiomatic on top of the `tokio` runtime DataFusion already pulls in as a dependency — no extra async-runtime question to resolve. Deliberately not evaluating this against `actix-web`/others per §6's "Go-specific (or Rust-equivalent) open questions" — that's a real decision for the actual rewrite, overkill for a throwaway test tool. |
| Frontend | Static HTML/CSS/vanilla JS, no build step | See §4 — deliberately not reusing `html/`'s Alpine.js SPA machinery. |

## 3. API surface

Small, three endpoints:

```
GET /health
  -> 200 OK, liveness only

GET /api/models
  -> [{ "id": "all_minilm_l6_v2", "label": "all-MiniLM-L6-v2 (384-dim, fast)", "dim": 384 },
      { "id": "all_mpnet_base_v2", "label": "all-mpnet-base-v2 (768-dim, higher quality)", "dim": 768 }]
  -> lets the UI populate a model dropdown without hardcoding it twice

GET /api/similar?q={text}&model={all_minilm_l6_v2|all_mpnet_base_v2}&k={1-50, default 10}
  -> [{
       "rank": 1,
       "similarity": 0.87,
       "unique_key": "us-A-01-011-0111",
       "section_desc": "Agriculture, Forestry, And Fishing",
       "division_desc": "Agricultural Production Crops",
       "group_desc": "Cash Grains",
       "class_desc": "Wheat",
       "subclass_desc": ""
     }, ...]
  -> embeds `q` at request time with the selected model, ranks the
     1,005-row corpus by cosine similarity against that model's
     precomputed vector column, returns the top k
```

No auth, no rate limiting, no pagination beyond `k` — matches "super
simple," and this never leaves localhost.

## 4. Web UI: inspired by, not copied from, `html/`

`html/` is a real, capable SPA (787-line `index.html`, 2046-line
`styles.css`, Alpine.js components, ~3,800 lines total across its core
files) — appropriate for the production service it serves, wrong tool
for a throwaway test harness. Proposing something around 1-2% of that
size:

- **One static `index.html`**, no framework, no build step — a search
  input, a model `<select>` (populated from `/api/models`), a `k`
  input, a submit button, and a results area.
- **Vanilla JS `fetch()`** against `/api/similar`, rendering results as
  a plain table: rank, similarity (as a percentage), and the SIC
  hierarchy path (`section_desc > division_desc > group_desc >
  class_desc[ > subclass_desc]`), matching how `experiments/df-spike`'s
  queries already display this data.
- **Visual language borrowed directly from `html/styles.css`'s `:root`
  custom properties** — the dark theme (`--color-bg-primary: #0F0D0E`,
  `--color-text-primary: #ca703f`, etc.), base typography, and border/
  spacing tokens — copied as a small, self-contained CSS block, not the
  full 2,046-line stylesheet. Enough to look like it belongs next to the
  real UI without dragging in unrelated component styles (pagination,
  modals, tab navigation) this tool doesn't need.
- **No Alpine.js, no `api-service.js`/`explorer-base.js` reuse** — those
  exist to support multi-tab, cached, paginated exploration across five
  classification systems; this tool does one thing against one
  in-memory table.

Rough shape:

```
┌─────────────────────────────────────────────┐
│  IC Similarity Search (test tool)            │
│                                               │
│  [ growing wheat            ] [MiniLM ▾] [10▾] [Search] │
│                                               │
│  #  sim    path                              │
│  1  0.87   Agriculture > ... > Cash Grains > Wheat │
│  2  0.81   Agriculture > ... > Cash Grains > Corn  │
│  ...                                         │
└─────────────────────────────────────────────┘
```

## 5. Representing similarity in the UI

Raised after actually using the service (see
[`go-duckdb-rewrite.md` §7.8](go-duckdb-rewrite.md)): the raw cosine
similarity number is real, correct, and genuinely hard to read at face
value. Worth writing out clearly, since this determines what the UI
should actually show, not just how it should be styled.

### 5.1 The core problem: it isn't a 0–100% scale, even though it looks like one

Cosine similarity ranges mathematically from −1 to +1, so displaying it
as a percentage (`similarity × 100`) is a defensible thing to *compute*
— but it invites reading it the way a percentage normally works: "48.6%"
reads as "under half similar," a mediocre-sounding number, even when
it's the single best match in the entire corpus. Measured, not assumed
— computed the actual pairwise cosine similarity across all 1,005×1,005
combinations in the IC corpus (`all-MiniLM-L6-v2` vectors):

| Statistic | Value |
|---|---|
| Minimum | −0.075 |
| 1st percentile | 0.092 |
| 5th percentile | 0.154 |
| Median | 0.355 |
| 95th percentile | 0.608 |
| 99th percentile | 0.776 |
| Maximum (excluding self-pairs) | 0.998 |

The entire *practical* range this model produces sits mostly between
about 0.09 and 0.78 — a **48.6% top match is actually a strong result**,
sitting well above the median of everything in the corpus. Nothing in
the raw number communicates that; "48.6%" just looks unconvincing next
to an intuitive 0–100% mental model.

### 5.2 Negative similarity: real, but rare and barely negative

Directly relevant to what was asked: yes, negative cosine similarity is
mathematically possible and does occur in this corpus — but only in
**0.015% of all pairs** (about 152 out of ~1,009,020), and the most
negative value observed is only **−0.075**, nowhere close to −1. In
practice, real natural-language sentence embeddings cluster into a
comparatively narrow cone of the vector space rather than spreading
across the full hypersphere, so genuinely negative similarity between
two ordinary English phrases is unusual — it tends to show up only for
near-nonsensical or adversarial inputs, not typical queries. **Not worth
over-engineering the UI around** (e.g. a whole "what does negative mean"
explainer), but worth not assuming it can't happen either — a `0.0%`
floor on display, or handling it same as any low positive score, is
enough; no special-casing required.

### 5.3 There's no natural "not a match" floor either

Tested directly: a deliberately nonsense query
(`"xyzzy quantum flibbertigibbet nonsense"`) still returned a top match
at **12.9% similarity** — not near-zero, not negative. Sentence
embedding models generally place *all* reasonably-formed text somewhere
in a shared region of the space; there's no reliable zero-point that
means "unrelated." A naive reading of "12.9%" might strike a user as
"plausible, if weak" — it's actually noise. This is the flip side of
§5.1's problem: low scores don't reliably mean "no match" any more than
a middling score reliably means "decent match."

### 5.4 Options considered

1. **Show the raw score as-is, relabeled.** Cheapest change: stop
   calling it "similarity %" (which invites the 0–100% reading) and
   call it something like "match score," still 0.00–1.00 or ×100 as a
   number. Doesn't fix the interpretation problem, just stops implying a
   false precision — a half-measure.
2. **Min-max rescale within each query's own returned results** (worst
   shown → 0%, best shown → 100%). **Actively misleading, ruled out**:
   a mediocre top result (raw 0.35) would display identically to a
   genuinely excellent one (raw 0.85) — both "100%." For a *test* tool
   whose entire purpose is judging whether the model finds good matches,
   this is exactly the wrong failure mode: it makes every query look
   equally confident regardless of whether the results are actually
   good.
3. **Calibrate against the model's own measured background
   distribution** (§5.1's table, which already exists — no new
   computation needed) — e.g. map the 5th percentile (0.154, "typical
   noise") to the low end and the 95th–99th percentile (0.61–0.78,
   "typical strong match") to the high end of a visual scale, and
   display the raw score with that calibration as context (a bar/gauge,
   or a qualitative band like "Strong / Moderate / Weak" derived from
   those same percentile cutoffs) rather than a bare, misleadingly
   precise percentage.
4. **Rank-only, no score at all.** Sidesteps the whole problem by not
   showing a number that invites over-interpretation. Loses real
   signal, though — for a *test* tool specifically, seeing whether
   result #1 and result #5 are close together or far apart (i.e., how
   sharply the model discriminates on this particular query) is useful
   information a bare rank list throws away.

### 5.5 Leaning toward: raw score *and* a calibrated visual cue, not one or the other

Given this tool's actual purpose — letting a person judge whether the
model is finding good matches, not presenting a polished consumer
feature — the right answer is probably **both pieces of information at
once**, not picking one:

- Keep showing the **raw score**, for the technically-minded person
  actually using this tool. Don't hide real data from someone testing
  a search algorithm.
- Add a **calibrated bar/gauge next to it**, anchored to §5.1's already-
  measured percentile data (5th/95th, or similar) rather than to a
  generic 0–100% assumption or to the current result set's own min/max
  (§5.4 option 2, ruled out). This turns an opaque, misleadingly-precise
  number into something visually honest about "is this actually a good
  match by this model's own standards" without lying about confidence.
- Worth visually de-emphasizing (not hiding) results that fall below
  the calibrated "typical noise" threshold (~0.15 for `all-MiniLM-L6-
  v2`, per §5.1) — not a hard cutoff, since §5.3 showed even nonsense
  queries can land above it, but a visual signal that "this is getting
  into noise territory" is more honest than presenting all k results as
  equally credible.
- Keep `k` user-adjustable rather than hard-coding a "just show 5"
  default — for a test tool specifically, seeing *where* result quality
  falls off (a cliff after #3? a gentle slope through #10?) is itself
  useful signal, which a fixed top-5 view would hide. A sane default
  (the service already defaults to `k=10`) is fine; artificially
  capping it isn't.

This calibration is specific to **`all-MiniLM-L6-v2` on this IC
corpus** — a different model, or company data once it exists, would
need its own percentile table (§5.1's approach generalizes; the numbers
don't). Nothing here is implemented yet — this section is the analysis
requested, not a design decided in isolation; next step is reacting to
it before building anything.

## 6. Open questions / decision points (not resolved here)

- **DataFusion `cosine_distance` UDF vs. a plain Rust loop for
  ranking.** §2 proposes trying the DataFusion path first since it's
  the more useful validation for the eventual rewrite, but at 1,005
  rows a hand-rolled `Vec<f32>` dot-product loop would also be trivially
  fast and simpler to get right. Worth timeboxing the UDF attempt rather
  than treating it as mandatory — if it's fighting the framework, the
  simple loop is a perfectly good fallback and doesn't compromise what
  this tool is for.
- **Where this lives**: proposing `experiments/ic-similarity-service/`,
  matching the `df-spike`/`embed-bench`/`quality-eval` convention
  (disposable, committed so it's durable across worktrees, not part of
  the actual rewrite). Open to a different location if this is expected
  to have a longer life than the other experiments.
- **Docker**: not in scope for the first version (adds a build step
  before there's anything to test), but flagged from the earlier chat
  discussion as a real, wanted next step once this works locally —
  the existing `Dockerfile`/`svc_ctl.sh` pattern is a reasonable
  template to follow for that, later.
- **Data file location**: reads `tmp/us_flat_embedded.feather` via a
  CLI arg or env var (matching `df-spike`'s pattern), default path
  documented in the README, file itself not committed (gitignored, real
  Mediumroast output) — same handling as every other experiment so far.
- **Company data**: out of scope entirely for now — this tool only
  makes sense against data that actually exists (§7.7 was explicit that
  company-data embeddings aren't available to test yet).

## 7. Explicitly out of scope

- Not a preview of the rewrite's actual API shape — this is a
  single-purpose test tool, not an API design exercise.
- No write path, no persistence beyond the one input file, no user
  accounts, no deployment story beyond "runs on localhost."
- No UK/Japan SIC or EU NACE support yet, even though §7.6 suggested the
  schema likely generalizes — US SIC only, matching the one file that
  exists.

## 8. Proposed project layout

```
experiments/ic-similarity-service/
├── Cargo.toml
├── Cargo.lock
├── README.md               # how to run, what data file it needs, results/notes
├── src/
│   ├── main.rs              # Axum app setup, routes, shared state (loaded table + models)
│   ├── search.rs            # DataFusion table registration + similarity query
│   └── embed.rs             # fastembed-rs model loading + query embedding
└── static/
    ├── index.html
    └── app.js                # inline <style> or a tiny styles.css, TBD when building
```

## 9. Next steps

1. ~~React to this plan...~~ **Done** — built, running, already found
   real things (§7.8's model reversal, the zstd/`array_distance` bugs in
   `ic-similarity-service/README.md`).
2. ~~Decide the §6 open questions...~~ **Done** — DataFusion's SQL
   interface (not the Rust builder API, which had a real bug), lives in
   `experiments/ic-similarity-service/`.
3. ~~Build it, run it locally, use it to sanity-check the model
   decision...~~ **Done, and it worked exactly as hoped** — using it
   directly is what caught the mpnet score-inflation issue that led to
   §7.8.
4. **Now open**: react to §5's similarity-score-representation analysis
   — pick one of §5.4's options (or a variant) and implement it, since
   that's the one piece of this tool still just analysis rather than
   working code.
