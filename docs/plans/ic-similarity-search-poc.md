# IC-data similarity search: local test service + minimal web UI

Status: **Draft — planning only, no code written yet.** A working
draft, same convention as
[`docs/plans/go-duckdb-rewrite.md`](go-duckdb-rewrite.md) — most of this
is a proposal to react to, not a locked decision.
Owner: michael.hay@mediumroast.io
Scope: a small, local, throwaway RESTful service plus a minimal web UI
for manually testing semantic similarity search over the IC (SIC/NACE)
data — specifically the two embedding models decided in
`go-duckdb-rewrite.md` §7.7 (`all-MiniLM-L6-v2` low-dim,
`all-mpnet-base-v2` high-dim). This is the natural next step after
§7.4-§7.7's spike work: everything so far has been benchmarks and
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

## 5. Open questions / decision points (not resolved here)

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

## 6. Explicitly out of scope

- Not a preview of the rewrite's actual API shape — this is a
  single-purpose test tool, not an API design exercise.
- No write path, no persistence beyond the one input file, no user
  accounts, no deployment story beyond "runs on localhost."
- No UK/Japan SIC or EU NACE support yet, even though §7.6 suggested the
  schema likely generalizes — US SIC only, matching the one file that
  exists.

## 7. Proposed project layout

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

## 8. Next steps

1. React to this plan — anything to cut, add, or change before building
   it.
2. Decide the §5 open questions that actually block starting (mainly:
   DataFusion UDF vs. plain-loop ranking, and where this lives).
3. Build it, run it locally, use it to sanity-check the model decision
   from `go-duckdb-rewrite.md` §7.7 by actually typing queries in,  not
   just reading precision/recall numbers off a table.
