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
don't).

### 5.6 §5.5's band labels have their own conflation problem

**Built per §5.5, then flagged as wrong** (not just imprecise — actively
misleading, same severity as §5.4 option 2). The implementation used
qualitative labels ("Weak" / "Below Average" / "Above Average" /
"Strong" / "Excellent") derived from where a score falls in the
corpus-wide pairwise similarity distribution. The problem: that
distribution is computed across **all** ~1M pairs in the corpus,
overwhelmingly *unrelated* ones — any two randomly-picked SIC codes are
usually unrelated, so the corpus-wide median (0.355) mostly reflects
"typical score between two unrelated codes," not "typical score for a
real search match." Labeling a result "Below Average" because it sits
under that median doesn't mean the result is a weak match — the
"average" it's being compared to is dragged down by irrelevant pairs
that never appear in an actual result set at all. **The label describes
the model's behavior across the whole corpus; it reads to a user as a
verdict on the one result in front of them.** Those are different
things, and the wording collapses them into one number.

Concretely, this means a genuinely good match could easily be labeled
"Below Average" simply because the corpus-wide baseline it's compared
against isn't the right reference class — the right question isn't "how
does this score compare to two random SIC codes," it's closer to "is
this a real match, or is this what the model returns even when nothing
good exists for this query" (§5.3's problem, actually — the noise-floor
question, not a grading-curve question).

**Two candidate directions for a third measure, not mutually
exclusive:**

1. **Reframe the existing percentile as an explicitly-scoped statistical
   fact, not a grade.** Drop "Below Average" / "Above Average" /
   "Strong" entirely — that vocabulary reads as a report card on the
   result. Replace with language that can't be misread as a verdict:
   e.g. `"Higher than 73% of all corpus pairs"` or a compact `P73`
   badge, with the "vs. entire corpus, including unrelated pairs" scope
   stated plainly (the calibration footnote already exists; the *label
   itself* needs the scope too, not just a footnote most people won't
   read closely).
2. **A genuinely new measure, not a rewording of the same one** —
   something that actually answers "is this a real match," which
   corpus-wide percentile doesn't. Two candidates:
   - **Per-row, noise-floor proximity**: how far above the empirically-
     measured "typical unrelated pair" baseline (§5.1's 5th percentile,
     ~0.154) does this score sit? Framed as a binary/tri-state
     confidence cue, not a grade — e.g. "clearly above typical noise"
     vs. "near typical noise level — treat with caution" for scores
     close to that floor. This is the same underlying number as
     §5.5's bar, but phrased as a caution flag about trustworthiness
     rather than a performance rating.
   - **Per-query, not per-row**: whether there's a **clear leader** in
     this particular result set — e.g. flag when result #1's score is
     meaningfully separated from #2's vs. when the top few results are
     close together (several similarly-plausible candidates, no
     standout). This tells a tester something rank order alone doesn't:
     whether the model is confidently pointing at one answer or
     shrugging across several. Shown once per search, not per row —
     doesn't repeat the min-max-rescale trap (§5.4 option 2) because
     it's a single summary judgment about the *result set*, not a
     per-row rescaled score.

Leaning toward **combining 1 and the noise-floor variant of 2**: reworded
percentile badge (removes the misleading grade language) plus a
separate, distinctly-styled noise-floor caution flag (answers the
actual question a "Below Average" label was trying and failing to
answer). The per-query "clear leader" idea is worth keeping in the
option set but feels like a second iteration, not required to fix the
immediate problem.

**Not re-implemented yet** — this section updates the analysis based on
your feedback; the running service still shows §5.5's flawed band
labels until there's agreement on the direction above.

### 5.7 What the literature actually says — and why §5.5/§5.6 were both still too statistical

Fair pushback: §5.5 and §5.6 were still designing for someone comfortable
with percentiles and distributions. A business user with little-to-no
stats background is the actual audience worth designing for. Searched
for how this is handled elsewhere rather than guessing — findings below,
converging from independent sources (search UX, vector-search product
writing, and peer-reviewed recommender-systems HCI research), not just
one opinion.

**1. The dominant, most consistent finding: don't show relevance/
similarity scores as numbers to end users at all.** Search UX guidance
(Coveo, and general search-results-design writing) is blunt about
this — users don't need to know their relevance scores, since the score
is mostly noise to someone not aware of what factors drove the ranking;
relevance should be communicated **through result order and content
presentation**, not a number. This is also just observably how Google,
Bing, and most consumer search products actually behave — no user-facing
relevance score, ever, just an ordered list. That's a strong, converging
signal that the entire "show a number or percentage" framing §5.5 and
§5.6 were refining may be solving the wrong problem for a business
audience.

**2. Where vector-search products specifically do show *something*
beyond rank, the recommended pattern is translated, plain-language
labels — not raw scores, and not statistical framing.** Guidance aimed
at exactly this situation (surfacing embedding-similarity output to
non-technical users) recommends converting raw scores into labels like
"Very Similar," "Likely Match," "Possible Match" — a small, fixed set of
plain phrases, calibrated once against the score ranges, never shown as
percentiles or population comparisons. Also flags something we already
learned the hard way in §7.8: score ranges aren't portable across
models/backends, so whatever calibration is used has to be re-derived
per model, not assumed universal.

**3. Peer-reviewed HCI research on confidence displays in recommender
systems (Shani et al., "Investigating confidence displays for top-N
recommendations," JASIST 2013) gives real, specific caveats worth
weighing, not just "add a confidence indicator":**
   - Confidence displays **don't make it objectively easier for users to
     pick out relevant items** — showing one doesn't improve task
     performance by itself.
   - Users **do appreciate and trust** confidence displays, particularly
     when **relevance is hard to judge from the content alone** — which
     cuts both ways for this tool: an IC classification path is fairly
     self-explanatory text (a business user can often just *read*
     "Agriculture > ... > Cash Grains > Wheat" and judge for themselves
     whether it's sensible for "growing wheat"), so a confidence
     indicator may matter most for the genuinely ambiguous/borderline
     cases, not every row uniformly.
   - **Novice users are measurably less likely to notice, understand, or
     use a confidence display than experienced users.** Directly
     relevant to "a business user who won't know anything or very
     little about stats" — a subtle numeric or percentile-flavored
     signal is likely to be *ignored*, not misread; it needs to be
     obvious and plain, not precise.
   - Separately, general guidance on communicating AI/model uncertainty
     to non-expert users (Nielsen Norman Group's writing on this)
     recommends **hedged natural language** ("here's my best guess...")
     over numbers, and avoiding language that locks a user into treating
     one result as definitively correct.

**What this changes about §5.5/§5.6's direction**: both were still
fundamentally "pick the right number/percentile to show," just disagreeing
about which one. The literature suggests the number itself — reworded,
recalibrated, or not — probably shouldn't be the primary signal for this
audience at all. Revised recommendation:

- **Primary signal: rank order + the result content itself** (the
  classification path), exactly as search UX guidance recommends —
  already what this tool does, don't add anything competing with it.
- **Secondary signal: a small, fixed set of plain-language labels** (no
  more than 3-4), calibrated using the same measured data as before
  (§5.1's percentiles, §5.6's noise-floor idea) but **worded like plain
  task language, not statistics** — e.g. "Strong match" / "Possible
  match" / "Unlikely match" instead of anything percentile- or
  average-flavored. The calibration work already done isn't wasted, just
  the *words* attached to it change.
- **Tertiary, optional: the raw score**, demoted rather than removed —
  available for the technically-curious (which, per this doc's own
  §1, includes whoever is using this tool to judge the model itself,
  not just a hypothetical end user), but small, muted, and not the
  first thing the eye lands on — closer to a tooltip/detail than a
  headline number.
- Worth **not showing a confidence label on every row uniformly** —
  per the Shani et al. finding that confidence displays matter most when
  content alone doesn't make relevance obvious, showing one only where
  it adds information (e.g., borderline cases) rather than as decoration
  on every row is both more literature-aligned and less visual noise.

**Sources**:
[Coveo — Search Best Practices](https://source.coveo.com/2017/09/26/search-best-practices-2/) ·
translated-label guidance from vector-search UX writing (Labelbox/Meilisearch/Zilliz-adjacent
product literature surfaced in this search, not one single canonical article) ·
[Shani et al., "Investigating confidence displays for top-N recommendations," JASIST 2013](https://asistdl.onlinelibrary.wiley.com/doi/abs/10.1002/asi.22934) ·
Nielsen Norman Group's writing on communicating AI uncertainty to end users.

Still not implemented — this is the requested literature search and its
synthesis, one more layer on top of §5.6's proposal, not a final answer
either. Next real decision point: pick the actual 3-4 label words and
their calibration thresholds, and decide whether/how to demote the raw
score in the existing markup.

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
