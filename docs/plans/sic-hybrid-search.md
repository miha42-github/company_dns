# SIC hybrid search: fusing Keyword + Semantic across every system (RRF)

Status: **Built (2026-10-04)** - endpoint, Combined tab, tests and the
evaluation harness are in; not committed. First scoped 2026-10-01 against a
single SIC table, rewritten the same week after global keyword/semantic
search, four live systems (US SIC, Japan SIC, EU NACE, ISIC Rev. 4) and the
37-concept calibration landed. Section 9 records what was built and the
three places the build differs from this plan.
Owner: michael.hay@mediumroast.io
Scope: a new fused/ranked search over **all registered systems at once**,
exposed as its own endpoint (`/V4.0/global/sic/hybrid/{query}`) and its own
tab, labelled **Combined**, in the Industry Classification Explorer. Out of scope:
changing how Keyword, Semantic or Compare work, any non-SIC data source,
real BM25 text scoring.
Related: this is item 3 ("Hybrid global") of `sic-global-search.md`; the
per-system calibration question in that doc is deliberately not solved here
(decision 2).

---

## 1. Why this needs nothing exotic

DataFusion already has everything Reciprocal Rank Fusion (RRF) needs as
plain SQL, no custom UDF:

- **CTEs** (`WITH kw AS (...), sem AS (...)`).
- **Ranking**: `RANK() OVER (ORDER BY ...)`, a built-in window function.
- **Combining**: `FULL OUTER JOIN` + arithmetic.
- **Vector distance**: `array_distance(...)`, a *stock* DataFusion array
  function already used in `similarity.rs` and `global.rs`.
- **Multi-system fan-out**: the dynamic `UNION ALL` over
  `SicCatalog.systems` that `global.rs` already builds.

The one real gap is the keyword side. `find_by_description_global` is a
flat `ILIKE '%term%'` filter with no relevance signal, so every match ties
and the server returns them unordered (capped at 50). `strpos(lower(class_desc),
lower(query))` (built in; earlier match = better) is a cheap proxy that needs
no UDF. A real UDF would only be needed for BM25/TF-IDF, which this doc does
not scope.

## 2. Decisions (2026-10-04)

1. **Single-engine hits are allowed.** A hit found by only one engine keeps
   a nonzero RRF score and can outrank a mediocre both-engine hit. That is
   standard RRF and wanted: an exact-term keyword match is often what the
   user typed, and semantic-only hits are the point of embeddings.
2. **Fuse over the merged global lists first.** Rank keyword matches
   and semantic neighbours across all systems together, then fuse. Per-system
   ranks (which would sidestep the cross-system score offsets measured in
   `sic-global-search.md`: ISIC about -0.06 and NACE about -0.04 against US)
   are a follow-up *only if measurement says they help*, not an assumption.
3. **Global only.** One endpoint, `/V4.0/global/sic/hybrid/{query}`. No
   `/V4.0/na/...` variant and no V3 alias (V3 never had this capability).
4. **A new tab labelled "Combined", placed first**: Combined | Compare |
   Keyword | Semantic. It is not a third Compare column (changed from the
   2026-10-01 plan); Compare stays Keyword | Semantic as it is.
   *Naming trap:* the existing Compare tab's code still uses the id
   `combined` everywhere (`icModeCombined`, `selectIcExplorerMode('combined')`,
   `icCombined*`, `.ic-combined-*`). The new tab's code and ids must be
   `hybrid` (`icModeHybrid`, `icHybrid*`) so the two cannot be confused; only
   the visible label is "Combined". The in-app help should say plainly that
   Combined shows one fused ranking and Compare shows the two result lists
   side by side.
5. **Paginate in the browser.** The endpoint is called once with `k=50` (its
   cap) and the tab pages the 50 results client-side; no server pagination
   (that stays V4.1.0).
6. **When keyword finds nothing**, show the one-line note "No keyword
   matches; showing semantic results".
7. **Filtering is per system only** (the same checkbox-and-count sidebar as
   Semantic); no Both / Keyword-only / Semantic-only engine facet.
8. **The evaluation script moves into the repo** as a regression check
   (section 5).

## 3. Evidence: offline check on the 37-concept set (2026-10-04)

Before writing any Rust, the planned method was simulated in Python on the
same four feather files and the same MiniLM model the server uses. This is
the *method*, not the SQL: semantic = global top-50 by raw similarity;
keyword = `ILIKE '%q%'` on `class_desc` across all four systems, ranked by
match position with ties sharing a rank (SQL `RANK()`); fused with RRF K=60;
fused-score ties broken by semantic rank. The 37 concepts and their
equivalent classes in each system are the calibration set (hand-picked from
class text; the `ISIC` picks mirror the NACE ones). Scripts live in the
session scratchpad (`hybrid_eval.py`, `hybrid_diag.py`) and move into
the repo as the regression harness described in section 5.

Metrics, over the single merged list: **any@k** = a correct row from *any*
of the four systems is in the top k; **MRR** = mean of 1/(rank of the first
correct row); **pair@10** = of the 148 concept x system pairs, the share
whose correct row is in the top 10 (hard ceiling: 10 slots for 4 systems).
Three query forms, because keyword behaves very differently on each:
a short phrase ("coal mining"), a long natural sentence, and a single term
("coal").

| query form (keyword finds anything for) | method | any@1 | any@3 | any@10 | MRR | pair@10 |
|---|---|---|---|---|---|---|
| **short phrase** (21 / 37) | semantic | .73 | .95 | 1.00 | .84 | .70 |
| | keyword | .16 | .49 | .49 | .32 | .25 |
| | **hybrid** | .68 | .92 | .97 | .81 | .70 |
| **long sentence** (0 / 37) | semantic | .62 | .81 | .92 | .73 | .60 |
| | keyword | 0 | 0 | 0 | 0 | 0 |
| | **hybrid** | .62 | .81 | .92 | .73 | .60 |
| **single term** (36 / 37) | semantic | .59 | .76 | .86 | .70 | .57 |
| | keyword | .08 | .73 | .92 | .44 | .61 |
| | **hybrid** | **.70** | **.95** | **1.00** | **.82** | **.72** |

What it says:

- **Single terms are where hybrid wins**, clearly: any@10 .86 -> 1.00,
  MRR .70 -> .82. It rescues semantic misses outright ("librar": semantic
  rank 127, hybrid rank 2; "repair of motor": 29 -> 1; "clothing": 21 -> 1;
  "ship": 7 -> 1).
- **Long sentences**: the keyword side finds nothing (a full sentence is
  never a substring of a class name), so hybrid degrades to exactly
  semantic. Safe, but it means long natural-language queries gain nothing.
- **Short phrases**: hybrid is slightly *below* semantic (any@1 .73 -> .68).
  Of the six losses, four are the first correct row moving from rank 1 to
  2. I checked those four: each time the row that moved ahead is a
  plausible match that is simply not in the hand-picked answer key (coal
  mining -> "Coal Mining Services"; hospital -> "Specialty Hospitals, Except
  Psychiatric"; gym -> "Gymnasiums (sports hall)"; telecommunications ->
  "Other telecommunications activities"), lifted by a keyword match. So this
  is largely the answer key being incomplete, not worse results; the honest
  reading is "no measurable gain on phrases". The other two losses (trucking
  3 -> 4, warehouse 7 -> 15) were not examined.
- **Substring noise is real**: "car" matches 80 class names ("carpet",
  "cards"), which pushes the right row from 1 to 4. Short, ambiguous terms
  will do this.
- **Tuning knobs did not matter.** RRF K=20 vs 60, a 100-wide semantic pool
  vs 50, preferring whole-word matches, and breaking keyword ties by
  description length all moved results by 0-0.05 and none beat the plain
  design (`strpos` rank, K=60, pool 50). So ship the simple version; do not
  add those.

Caveats: 37 concepts, one author's picks (the same limits as the
calibration run); simulated in Python, so the first SQL implementation must
reproduce these numbers to within noise before it is trusted; the semantic
side still carries the cross-system score offsets (decision 2).

## 4. Design

### 4.1 New module: `crates/sic/src/hybrid.rs`

Built from the start over `SicCatalog.systems`, like `global.rs`. Joins on
`unique_key` (`<module>-<section>-<division>-<group>-<class>`), **not**
`class_id`: a class id such as `0111` exists in US SIC, ISIC and Japan SIC,
so a `class_id` join would fuse unrelated rows.

```rust
#[derive(Serialize, Clone)]
pub struct HybridHit {
    pub rank: usize,
    pub rrf_score: f64,
    pub source_type: String,           // "US SIC" | "Japan SIC" | "EU NACE" | "ISIC"
    pub unique_key: String,
    pub section_desc: String,
    pub division_desc: String,
    pub group_desc: String,
    pub class_desc: String,
    pub keyword_rank: Option<usize>,   // None = did not surface via keyword
    pub semantic_rank: Option<usize>,  // None = did not surface via semantic
    pub similarity: Option<f32>,       // raw cosine, only when semantic_rank is Some
}

impl SicCatalog {
    pub async fn search_hybrid_global(&self, model_id: &str, query: &str,
                                      query_vector: &[f32], k: usize) -> Result<Vec<HybridHit>>
}
```

Draft SQL (per-system `SELECT`s joined by `UNION ALL`, generated in a loop
exactly like `global.rs`; `{t}` = system table, `{label}` = `source_type`):

```sql
WITH kw_src AS (
  SELECT arrow_cast('{label}','LargeUtf8') AS source_type, unique_key,
         section_desc, division_desc, group_desc, class_desc,
         strpos(lower(class_desc), lower('{q}')) AS match_pos
  FROM {t} WHERE class_desc ILIKE '%{q}%'
  -- UNION ALL ... one SELECT per registered system
),
kw AS (SELECT *, RANK() OVER (ORDER BY match_pos ASC) AS kw_rank FROM kw_src),
sem_src AS (
  SELECT * FROM (
    SELECT arrow_cast('{label}','LargeUtf8') AS source_type, unique_key,
           section_desc, division_desc, group_desc, class_desc,
           array_distance({vec_col}, arrow_cast({lit}, 'FixedSizeList({dim}, Float32)')) AS distance
    FROM {t} ORDER BY distance ASC LIMIT {pool}
  ) -- UNION ALL ... one per system, each limited to its own top {pool}
),
sem AS (
  SELECT *, RANK() OVER (ORDER BY distance ASC) AS sem_rank
  FROM (SELECT * FROM sem_src ORDER BY distance ASC LIMIT {pool})   -- merged global top {pool}
)
SELECT COALESCE(kw.source_type, sem.source_type)   AS source_type,
       COALESCE(kw.unique_key,  sem.unique_key)    AS unique_key,
       COALESCE(kw.section_desc, sem.section_desc) AS section_desc,
       -- ... division_desc, group_desc, class_desc likewise
       kw.kw_rank, sem.sem_rank,
       1.0 - (sem.distance * sem.distance) / 2.0   AS similarity,
       COALESCE(1.0/({RRF_K} + kw.kw_rank), 0) + COALESCE(1.0/({RRF_K} + sem.sem_rank), 0) AS rrf_score
FROM kw FULL OUTER JOIN sem ON kw.unique_key = sem.unique_key
ORDER BY rrf_score DESC, sem.sem_rank ASC NULLS LAST, unique_key ASC
LIMIT {k}
```

Notes and risks:

- `RRF_K = 60` and `CANDIDATE_POOL = 50` are named constants. K=60 is the
  standard from the original RRF paper; section 3 shows 20 and a pool of 100
  change nothing worth having.
- The pool stays at 50 even when `k` is smaller, so fusion has something to
  rerank; `k` is clamped 1-50 like the other endpoints.
- Tie-break in the final `ORDER BY` is deliberate and measured: equal fused
  scores fall back to the better semantic rank, then to `unique_key`, so
  results are deterministic.
- `source_type` must be `arrow_cast(..., 'LargeUtf8')` (the string-literal
  gotcha already hit in `global.rs`).
- Escaping: the query is spliced into SQL as a quoted literal exactly as
  `global.rs` does (single quotes doubled); the `ILIKE` pattern should also
  escape `%`/`_` in the user's text (not currently done in the existing
  keyword path either; fix both together or note it).
- Verify against DataFusion 55 that the `FULL OUTER JOIN ... ON` with the
  `COALESCE` projection behaves; `USING` would be tidier but is not
  required. This is the one SQL shape not yet proven here.

### 4.2 `crates/sic/src/lib.rs`

`pub mod hybrid; pub use hybrid::HybridHit;`, same pattern as `global`.

### 4.3 `crates/server/src/main.rs`

New route `GET /V4.0/global/sic/hybrid/{query}`, handler `sic_hybrid_global`
copying `sic_similarity_global`'s shape: embed the query via
`state.embedders`, call `state.sic.search_hybrid_global(...)`. Same `k` /
`model` params, V4-only. Registered with `utoipa` like its siblings and
shown in `/docs`. Envelope message follows the existing style ("N hybrid SIC
entries for [query] across all systems").

### 4.4 UI: the Combined tab (`v4/crates/server/static/`)

Tab order: **Combined** | Compare | Keyword | Semantic. It follows the
Semantic tab's layout (full-size cards, left sidebar with per-system facets
and counts via the existing `IC_SOURCES` registry) and reuses what the
Compare work already built. Code and ids are `hybrid` (see decision 4).

- **Fetch**: `icFetchHybrid(query, 50)` mirroring `icFetchSimilar`, one
  request per query. The tab auto-runs the active query on switch (same
  behaviour as Semantic/Compare).
- **Pagination (browser-side)**: all 50 results are held in memory; the tab
  shows 10 at a time with the same page buttons as the Keyword tab (the
  Keyword tab has no visible page-size control, so neither does this one). System facets filter the full set first, then the
  result is paged; facet counts and "Showing N-M of T" always reflect the
  full set, never just the visible page (the lesson from the Compare
  keyword bug).
- **Card header**: code, system pill, and in the middle slot **engine
  badges** instead of the semantic "Score" pill: `Keyword #3 · Semantic #1`,
  or `Keyword only` / `Semantic only`. The fused number itself is not shown
  as a percentage: RRF scores live in about 0.01-0.033, which reads badly as
  "Score". Show the fused rank order, with `rrf_score` and the raw similarity
  in a tooltip and in the JSON.
- **Why this needs its own tab** (the reason it is not a Compare column):
  the provenance badges and a full card are too much for a compact 10-row
  column.
- **Facets**: per-system checkboxes with counts, as Semantic. No engine
  facet (decision 7).
- **View JSON**: the same `showJsonModal`; payload is the semantic one plus
  `keyword_rank`, `semantic_rank`, `rrf_score`, `engines`.
- **No-keyword-match note**: when no result has a keyword rank, show the
  one-line note "No keyword matches; showing semantic results" (decision 6),
  because the results are then identical to the Semantic tab and users
  should know why.
- **Help/About text** and the Home Industry Classification panel get a
  short description of the Combined tab and how it differs from Compare.
- No change to Compare, to Keyword or to Semantic.

## 5. Testing and acceptance

1. Rust unit tests for the SQL builder (dynamic across 1 and N systems),
   in the style of the existing `global.rs` tests, plus the escaping.
2. Server test that the endpoint returns the documented fields and a 200
   with the same shape for every system.
3. **Reproduce section 3 on the real server**: run the 37 concepts x 3 forms
   through the new endpoint and confirm the table above to within noise
   (in particular single-term any@10 near 1.00 and long sentences identical
   to semantic). That check, not the Rust unit tests, is the proof the SQL
   does what the simulation did. It is done by the evaluation harness below.
4. **Evaluation harness in the repo** (decision 8), `experiments/sic-hybrid-eval/`
   (next to the existing spike folders), made self-contained so it does not
   depend on session scratch files:
   - `concepts.json`: the 37 concepts with their short / long / single-term
     query forms and the equivalent class ids in each of the four systems
     (the calibration picks, made explicit instead of embedded in a script).
   - `eval.py` with two modes: `--simulate` (the Python method from section 3,
     reading the feather files and embedding with the pinned MiniLM revision)
     and `--server URL` (calls `/V4.0/global/sic/hybrid/...` plus the existing
     keyword and similarity endpoints and scores the merged lists the same
     way). Prints the section 3 table.
   - Regression thresholds (single-term hybrid any@10 >= .95, hybrid MRR on
     single terms >= semantic MRR, long-sentence hybrid identical to semantic)
     so it can fail a build; a README that records the environment it needs
     (pyarrow + numpy + sentence-transformers, which on this machine live in
     two different Python installs, so a one-step dump of the vectors to
     `.npy` is part of the script's setup).
   - Needs a self-identifying User-Agent when it calls the server (the rate
     limiter returns 429 to anonymous ones).
5. Browser verification of the new tab in light of the Compare lessons:
   facet counts reflect the full result set, not the displayed slice; the
   View JSON modal matches the other tabs for the same record; both themes.

## 6. Explicitly out of scope

- Real text-relevance scoring (BM25/TF-IDF) via a UDF. Section 3 suggests
  the `strpos` proxy is enough for this data; revisit only on evidence.
- Per-system rank fusion (decision 2): a measured follow-up, not part of
  this.
- Changing `find_by_description_global` / `search_similar_global`
  themselves; hybrid is additive.
- Pagination (V4.1.0, `v4-server-pagination.md`): the endpoint is
  `k`-limited (1-50) like its siblings.
- Any non-SIC hybrid search (EDGAR, Wikipedia, firmographics).
- Shipping ISIC: the UN licence gate in `sic-global-search.md` applies to
  hybrid results exactly as to any other, and ISIC rows appear in them.

## 7. Dependencies and order of work

No new data and no new crates. It depends only on what is already built:
`SicCatalog.systems`, `global.rs`'s per-system SQL pattern, the embedders,
and the Explorer tab and `IC_SOURCES` machinery. Suggested order: SQL +
`hybrid.rs` and a throwaway test, then the endpoint, then reproduce
section 3, then the tab, then docs.

## 8. Open items (not decisions yet)

- A minimum query length or ambiguity guard for the keyword side ("car"
  matched 80 rows). Not applied because whole-word and length tie-breaks did
  not help; left as an observation.

## 9. As built (2026-10-04)

* **Rust** - `crates/sic/src/hybrid.rs` (`search_hybrid_global`, `HybridHit`,
  `RRF_K = 60`, `CANDIDATE_POOL = 50`), exported from `lib.rs`;
  `GET /V4.0/global/sic/hybrid/{query}` in `main.rs` (`sic_hybrid_global`,
  `k` clamped 1-50, `model` as the other endpoints, listed in `/docs`). Six
  unit tests in `hybrid.rs`, four of which execute the real fused SQL in
  DataFusion on tiny in-memory systems (both-engine, keyword-only and
  semantic-only hits; the same class id in two systems staying two hits;
  keyword ties sharing a rank; literal `%`/`_`; blank query; `k`). The
  `FULL OUTER JOIN ... ON` + `COALESCE` shape the plan flagged as unproven
  works in DataFusion 55 as drafted. `cargo test --workspace` and clippy
  clean.
* **Eval harness** - `experiments/sic-hybrid-eval/` (`concepts.json`,
  `eval.py`, README). `simulate` reproduces section 3 exactly; `server`
  scores the live endpoints and reproduces it (single terms hybrid any@10
  1.00 vs semantic .86, MRR .82 vs .70; long sentences identical; short
  phrases hybrid MRR .80 vs semantic .84). Both exit 0 against the current
  data.
* **UI** - **Combined** tab first (Combined | Compare | Keyword | Semantic)
  and the **default**: the explorer opens on it, the Home page's Industry
  Classification panel preselects its pill, and a `?q=` deep link opens it
  with the query run (the Keyword search still runs in the background so
  the Keyword tab is populated when switched to); code
  and ids are `hybrid`. Semantic's layout and per-system facets; engine
  badges (`Keyword #3 - Semantic #1` / `Keyword only - #3` / `Semantic only -
  #1`) with the fused score and raw similarity in the tooltip; View JSON
  adds `rank`, `rrf_score`, `keyword_rank`, `semantic_rank`, `engines`;
  one request with `k=50`, paged in the browser at a fixed 10,
  facet counts and "Showing a-b of N" over the full filtered set; the
  "No keyword matches; showing semantic results" note; help text and the
  in-app API list updated.

### Where the build differs from the plan

1. **The keyword predicate is `strpos(lower(class_desc), lower(q)) > 0`, not
   `ILIKE '%q%'`.** Same matches for normal text, but `%` and `_` in the
   user's query are literal, so they cannot act as wildcards. The existing
   `find_by_description_global` (Keyword and Compare) still has that wildcard
   quirk; it was not changed.
2. **The page number is not kept in the URL.** The plan said to mirror the
   Keyword tab, but the Keyword tab's `page`/`perPage` parameters belong to
   that tab and the explorer does not store which tab is active in the URL
   (a reload lands on Keyword), so a Combined page number in the URL would
   restore nothing useful. Paging resets on a new search or filter change.
3. **No engine facet and no `rrf` percentage**, as decided. (A "Per page"
   select was added and then removed at the owner's request: the Keyword tab
   has no visible page-size control, only a fixed 10, and none was asked for.)

### Observations from using it

* Fused-score ties are common (every keyword rank-1 and the semantic #1 both
  score 1/61). The tie-break is the better semantic rank, then `unique_key`.
  On "librar" this puts a semantic-only #1 ("Liquor Stores") above the
  four keyword-only library classes that tie with it. Preferring the keyword
  rank on a tie was tried on the 37 concepts: single terms +0.03 any@1,
  short phrases -0.03, MRR .82 -> .83 and .81 -> .79, i.e. noise in opposite
  directions, so the plan's tie-break was kept.
* Identical rows in two systems (NACE 02.40 and ISIC 0240 share their text)
  tie exactly and can swap places between the Semantic and Combined tabs;
  nothing is different about the results.
* ISIC rows appear in Combined results; the UN licence gate in
  `sic-global-search.md` applies.
