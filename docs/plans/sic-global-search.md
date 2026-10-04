# SIC global/unified search (all classification systems at once)

Status: **Keyword and Semantic variants built (2026-10-01).** Japan SIC
data landed (`tmp/japan_rev13_flat_embedded.feather`, same schema as US
SIC's feather file plus five `*_ja` columns and matching embeddings)
the same day this was raised - unblocked almost immediately.
`GET /V4.0/global/sic/description/{query}` (+ `/V3.0/` alias) and
`GET /V4.0/global/sic/similarity/{query}` both ship, fanning out across
every classification system `SicCatalog` has registered at startup (US
SIC + Japan SIC today) and tagging each row with `source_type`
(`crates/sic/src/global.rs`). Every keyword/semantic surface in the UI
- the main Keyword and Semantic tabs, and both of Compare mode's
columns - is wired to the global endpoints with real per-source
filtering, live-verified end to end. Four systems are live (US SIC, Japan SIC, EU NACE, ISIC - see the EU NACE
section for its two upstream data defects). **Hybrid global search is built too** (2026-10-04, `sic-hybrid-search.md`).
Owner: michael.hay@mediumroast.io

---

## What V3 does

`GET /V3.0/global/sic/description/{query_string}` →
`UnifiedSICQueries.search_all_descriptions` (`lib/unified_sic.py:33-110+`).
Instantiates `SICQueries`, `UKSICQueries`, `EuSICQueries`,
`InternationalSICQueries`, `JapanSICQueries` (`lib/unified_sic.py:6-10,
22-31`) and queries each in turn, merging into one
`{results, sources, total}` response. True fan-out-and-merge across 5
systems, not a single query.

## What shipped (keyword variant)

- `SicCatalog` (`crates/sic/src/lib.rs`) now tracks a `systems: Vec<SicSystem>`
  list instead of assuming one table. `open()` registers the primary US
  table as before; a new `register_system(path, table_name,
  source_label)` registers additional ones into the same
  `SessionContext`. `main.rs` calls it for Japan SIC at startup, behind
  `JAPAN_SIC_DATA_PATH` (default `../../tmp/japan_rev13_flat_embedded.feather`),
  warn-and-continue if missing - same optional-load pattern as the
  EDGAR catalog, not a hard startup dependency.
- `crates/sic/src/global.rs`: `find_by_description_global` builds the
  `UNION ALL` SQL dynamically from whichever systems are actually
  registered (never hardcodes "US + Japan" as a pair), `DISTINCT`
  per-system same as the existing single-system lookups, tags each row
  `source_type` via `arrow_cast(..., 'LargeUtf8')` - a plain string
  literal comes back as `Utf8` and panics the `LargeStringArray`
  downcast every other column in this codebase uses, caught live during
  testing, not anticipated in the original design.
- `GET /V4.0/global/sic/description/{query}` + `/V3.0/` alias
  (`main.rs`), both calling the same impl fn, same pattern as every
  other V3-parity pair in this file.
- Frontend: `api-service.js` points `searchIndustryCodes` at the new
  endpoint instead of the US-only one; `global-search-alpine.js`'s
  result transform now reads the server's real `source_type` per row
  instead of hardcoding `'US SIC'`, and branches `additional_data`'s
  shape per system (Japan SIC's `division_code`/`major_group_code`/
  `group_code` fields match a meta-grid template that was already built
  in an earlier UX pass and had nothing populating it until now).
  `index.html`'s Keyword sidebar gets its `Japan SIC` checkbox back,
  wired to Alpine state (`filters`/`filterCounts`) that already existed
  but had no checkbox rendering it.
- Live-verified: `forest` query returns 3 Japan SIC + 3 US SIC matches
  correctly tagged, filter checkboxes independently show/hide each
  system's results with correct counts, View JSON on a Japan SIC result
  shows the right field shape. `cargo test --workspace` and `cargo
  clippy` both clean.
- **Follow-up, same day**: Compare tab's Keyword column
  (`ic-explorer.js`) was still pointed at the old US-only endpoint,
  caught directly ("Is the UI's keyword focused on global?"). Fixed to
  use the same global endpoint, with its facet row upgraded from the
  single "All Results"/"US SIC" mirror (copied from when it really was
  single-system) to real independent US SIC/Japan SIC toggles -
  Semantic's column keeps the single-toggle shape since semantic global
  still isn't built.

## What shipped (semantic variant)

Built the same day, right after keyword - the "shared embedding space"
open question turned out to resolve itself: Japan SIC's feather file
carries the identical `model`/`model_revision` metadata as US SIC's
(confirmed via schema read, not assumed), so it's the same model over
two corpora, not two different embedding spaces that happen to be
comparable. Live-verified directly: a `forest` query's top 10 global
results interleave US SIC and Japan SIC by similarity score (ranks
1,4,7-10 US; 2,3,5,6 Japan) rather than clustering by system - exactly
what you'd expect if the scores really are on the same scale.

- `crates/sic/src/global.rs`: `search_similar_global` fetches each
  registered system's own top-k nearest neighbors first, then merges
  and re-sorts by distance - a standard distributed-top-k argument
  (the globally-best k rows can only come from each shard's own
  locally-best k, so per-shard top-k before merging is both necessary
  and sufficient). `format_float_array_literal` promoted to
  `pub(crate)` in `similarity.rs` so this didn't need its own copy.
- `GET /V4.0/global/sic/similarity/{query}` (`main.rs`) - V4-only, no
  V3 alias, same precedent as single-system Semantic (V3 never had
  this capability, global or otherwise).
- Frontend: `icFetchSimilar` (shared by the main Semantic tab *and*
  Compare mode's Semantic column) points at the new endpoint.
  `icRenderSemanticCard`'s source pill is now dynamic
  (`hit.source_type`) instead of hardcoded `US SIC`. Both Semantic
  sidebars (main tab, Compare column) gained a real `Japan SIC`
  checkbox alongside `US SIC`, replacing the old single-toggle "All
  Results"/"US SIC" mirror - Compare mode's Keyword and Semantic
  columns now share one generic per-source filtering implementation
  (`icCombinedActiveSources`/`icToggleCombinedSource` in
  `ic-explorer.js`) instead of two diverging copies.
- `cargo test --workspace` and `cargo clippy` clean throughout.

## What shipped (EU NACE, 2026-10-02)

`tmp/nace_rev2_flat_embedded.feather` (615 rows; same schema, same
MiniLM model/revision as US and Japan) landed and was registered as a
third system - `EU_NACE_DATA_PATH` (default
`../../tmp/nace_rev2_flat_embedded.feather`), table `sic_data_nace`,
`source_type` "EU NACE". Startup loading of the optional systems is now
one loop in `main.rs` rather than a copy per system. UI: `ic-explorer.js`
gained an `IC_SOURCES` registry that drives every facet row/count (adding
a system = one entry + its checkbox markup, not new filter logic);
`icSemanticLevels` maps each system's own hierarchy levels; the Keyword
tab's Alpine transform has an EU NACE branch feeding the template that
already existed. Keyword/Semantic/Compare all show it, live-verified.

**Upstream data defects in the first NACE file - found, reported, fixed.**
The first file had wrong section labels on 323 of 615 rows (a missing
D/E boundary shifted every section from division 36 up by one letter,
and the wrong text was baked into `unique_key`/`embedding_text`/vectors)
and no group level. Full write-up:
[`research/nace-rev2-feather-defects.md`](research/nace-rev2-feather-defects.md).
It was integrated as-is rather than patched around, then replaced with a
corrected file (same path, no code change needed beyond showing the new
third level) after checking it first: acceptance script PASS; all
structural checks clean (group ids nest under divisions, one description
per group/division, `unique_key` and `embedding_text` follow the
`section > division > group > class` recipe, no `-` inside ids); every
vector re-embeds from its `embedding_text` at cosine 1.000000, unit-norm,
no near-duplicates; retrieval on par with the other systems (self-retrieval
R@1 .894 / R@5 .979 vs US .906/.962, Japan .877/.984; division P@5 .940)
and the original bug is gone (retail now lands in section G, water supply
in E). NACE now shows Section / Division / Group in both the Semantic
card and the Keyword tab. Two observations, neither a file defect: its
pairwise-score distribution (median/p95/p99 .357/.671/.910) has a much
higher top tail than US (.355/.608/.776) because 4-level ALL-CAPS paths
make classes in the same group near-identical, which strengthens the case
for per-system calibration of the match bands; and ancestor text dominates
short queries within a section ("construction of buildings" ranks the
direct class #9 behind finishing trades).

## Japan SIC replaced with the complete JSIC (2026-10-03)

The first Japan file (529 rows) was a bad extraction of
`source_data/japan_sic_data/r3classification.xlsx`, the Statistics
Bureau's 2021 Economic Census classification. That sample was itself
complete (all of A-S, 529 level-4 groups, 109 census-specific
sub-groups); the extraction lost it. Its `#` marker means "sales per
establishment unavailable", a data-availability flag, but it was treated
as data: all of Construction, Utilities, Transport & postal and most of
Finance (90 groups) were dropped, six sections lost their English names,
two junk rows carried `#` as a code, and 89 sub-groups were mixed in
beside their own parents. The row count still came out at exactly 529
because the errors offset, so a count check could not have caught it.

The replacement (`japan_rev13_flat_embedded.feather`, 1,460 rows) is the
full 4-digit JSIC Rev. 13 and was checked before loading: 20 sections
A-T, 99 divisions, 530 groups, 1,460 industries (exactly JSIC's own
counts); every level nests (`class_id` prefixes equal its division and
group), one description per id, no placeholders, no empty English or
Japanese field, `unique_key` unique and following the same recipe as the
other systems; every vector re-embeds from its `embedding_text` at cosine
1.000000, unit-norm, no duplicates; retrieval on par with US and NACE
(self-retrieval R@1 .875 / R@5 .974, division P@5 .961); and the concepts
the old file could not answer now resolve (trucking, banks, insurance,
electricity, schools, telecoms, railways). Division 96 sits under R and
97-98 under S, which is JSIC's structure (the census file omits 96
because it is not tabulated). Its pairwise-score distribution
(median/p95/p99 .326/.616/.755) is now close to US SIC's (.355/.608/.776),
where the broken file's was visibly off (.264/.647/.795) - so the
cross-system score offset measured on the broken file (about -0.046 vs
US) should be treated as stale and re-measured.

**Follow-up, same day: text defects fixed upstream.** The mojibake in class
2596 (`General-purpose machinery and apparatus, n.e.c.`), the 28 curly
quotes and the NACE em dash in group 28.1 (`Manufacture of
general-purpose machinery`) were reported in
[`research/jsic-text-encoding-defect.md`](research/jsic-text-encoding-defect.md)
and fixed in new JSIC and NACE files. Both pass
`research/check_ic_feather.py` with no failures and no warnings (zero
non-ASCII characters in English text), every vector re-embeds from its
`embedding_text` at cosine >= 0.9999999, and the server was restarted on
them. The gate is the standing check before any future file lands in `tmp/`.

## What shipped (International / ISIC Rev. 4, 2026-10-03)

The first international file (`international_flat_embedded.feather`) was
ISIC **Rev. 5** (22 sections A-V, 87 divisions, no division 45, 258 groups,
463 classes). The intended edition was **Rev. 4** (21 / 88 / 238 / 419), so
it was replaced: `tmp/isic_rev4_flat_embedded.feather` (`ic_module`
`isic_rev4`, `classification_revision` "ISIC Rev. 4" in the metadata) is
registered as the fourth system - `ISIC_DATA_PATH` (default
`../../tmp/isic_rev4_flat_embedded.feather`), table `sic_data_isic`,
`source_type` "ISIC". Rev. 5 code, UI text and the Rev. 5 fix plan are
removed; the old Rev. 5 feather is still in `tmp/`, unused. UI: one
`IC_SOURCES` entry, checkboxes in the Keyword, Semantic and both Compare
facet rows, NACE-style Section / Division / Group card levels.

**First Rev. 4 file was defective, then replaced (same day).** It had 410 of
419 classes, 4 sections missing (E, G, O, T), wrong division on 20 rows,
wrong section on 54, wrong or missing group on 7, and literal quotes
around every text cell and vector input. Report:
[`research/isic-rev4-feather-defects.md`](research/isic-rev4-feather-defects.md)
(resolved). The revised file (419 rows, generated 2026-10-04T01:22Z) passes
`check_ic_feather.py` with no failures or warnings: 21 / 88 / 238 / 419
exactly, every id nests under its class prefix, every division inside its
section's official range, no quoting, no empty groups, `unique_key` and
`embedding_text` recipes hold, and every vector re-embeds at cosine
.9999999. It was installed and the server rebuilt and restarted.

Compared with the other systems (same script, same run): self-retrieval
R@1 / R@5 .933 / .993 (US .904 / .962, NACE .894 / .979, JSIC .755 / .854
on this measure), pairwise-score median/p95/p99 .349 / .644 / .885 (close
to NACE's .357 / .671 / .910; about a tenth of rows (41 of 419) have a >0.98 neighbour, the
same shared-ancestor-text effect as NACE). Against NACE Rev. 2, which
derives from ISIC Rev. 4: 335 of 419 ISIC class codes match a NACE
`XX.XX`; for those, the section letter agrees on 335 of 335, 232 class
names are identical after case/hyphen normalization, and the stored vector
is at cosine 1.000 for the median pair. The 84 ISIC classes without a code
match are ones where NACE splits or renumbers; 280 NACE four-digit codes
have no ISIC counterpart, as expected, since NACE is the finer system.

**License gate (not resolved).** The UN terms of use allow personal,
non-commercial download only; no redistribution and no derivative works
without permission (see the lineage note supplied with the UN file). ISIC
can be used for internal build and test, but must not ship in a released
V4 or a data product until UN Publications / UNSD permission is obtained
and recorded. The Rev. 5 file was under the same terms. The licences of the
other four sources (US SIC, JSIC, NACE) have not been checked here.

## Compare tab system filter (2026-10-04)

Each Compare column's row of checkbox-and-count text was replaced by a
"Systems" dropdown (holding the same checkboxes and counts) plus one chip
per system that is lit in the system's own colour when included, dimmed
when excluded, and toggles on click (`ic-explorer.js`: `icRenderCombinedChips`,
`icToggleChip`). Also fixed: the Keyword column used to take the first 10 of
the server's unordered, 50-capped result set (so a system could vanish
entirely); it now keeps the full set, shows 10 chosen round-robin across the
included systems, and counts and says "Showing N of M". The 50 cap itself
is still server-side and arbitrary (pagination, V4.1.0).

## Cross-system score calibration, re-measured (2026-10-03)

Re-run on the final US, JSIC (1,460) and NACE (615) files, 37 concepts x
2 query forms (short, long) plus 16 broad and 10 no-match queries, 100 in
all. Concept equivalents were picked from class text only, before any score
was seen. All 37 now have a 4-digit JSIC match (the first run had 23).
Script: `calibration_measure.py` (scratch, not committed).

| | US | JSIC | NACE |
|---|---|---|---|
| median top-1 score, all 100 queries | .564 | .574 | .527 |
| score of the correct row, mean (short / long) | .565 / .548 | .537 / .527 | .525 / .498 |
| correct row is own-system #1 (short / long) | .68 / .65 | .46 / .32 | .70 / .57 |

Paired difference on the same concept (mean of short and long, 95%
bootstrap CI): **JSIC - US -0.024 [-0.052, +0.003]**, **NACE - US -0.045
[-0.085, -0.005]**, NACE - JSIC -0.021 [-0.056, +0.015]. The broken Japan
file had measured about -0.046, so the gap has halved and is no longer
distinguishable from zero; NACE's is stable and the only one whose interval
excludes zero.

In the merged global ranking (per-system top 50 merged by raw score, as
the server does) the correct row lands in the top 10 for 82% of US, 73% of
JSIC and 59% of NACE concept-queries (top 3: 58 / 36 / 36%).

**Conclusion.** The earlier case for per-system shifts rested mostly on the
broken Japan file. With the real one: no Japan shift is justified, the
NACE shift (about +0.04) is supported but modest, and band labels
(Possible / Likely) are within a few points of each other across systems
(top-1 labelled Likely: 34% JSIC, 30% US, 22% NACE). Recommendation: do
not ship per-system offsets or per-system band cut-offs now; revisit if
NACE users report US results crowding the merged list, and re-measure with
a concept set picked by someone other than the author.

**ISIC added to the same measurement (2026-10-04).** Its 37 equivalents
are the NACE picks mapped through the shared four-digit code (11 by hand
where the code differs), so ISIC and NACE are compared on the same
concepts. Median top-1 .524 (US .564, JSIC .574, NACE .527); mean score of
the correct row .503 / .482 (short / long). Paired, mean of both forms:
**ISIC - US -0.064 [-0.108, -0.020]**, **ISIC - NACE -0.019 [-0.033,
-0.007]** (ISIC never scores higher than NACE on a concept; ties are where the text is identical), ISIC - JSIC
-0.040 [-0.079, -0.001]. In the merged ranking the correct ISIC row lands
in the top 10 for 51% of concept-queries (US 81%, JSIC 70%, NACE 58%).
ISIC is now the lowest-scoring system and its gap to US is the one whose
interval excludes zero by the widest margin, so the earlier "no shifts
now" conclusion holds for JSIC but is weaker for ISIC and NACE: a shift
of about +0.06 (ISIC) and +0.04 (NACE) is supported, and NACE and ISIC
users would see US and JSIC rows crowd them out of a merged list. The
reason ISIC scores below NACE on identical concepts was not investigated.

Limits: n=37 concepts, picked by one person (me) from class text, so some
equivalences are debatable (JSIC's fishing and construction classes are
split finer than the others, which depresses JSIC's own-R@1 and says
little about score scale). Short and long forms agree in sign for every pair.

## What's still not built

1. ~~**Keyword global**~~ - **done.**
2. ~~**Semantic global**~~ - **done, above.**
3. ~~**Hybrid global**~~ - **done** (2026-10-04): `/V4.0/global/sic/hybrid/{query}`
   and the Combined tab, see `sic-hybrid-search.md` section 9.

## Explicitly out of scope for this pass

UK SIC - still no data; `register_system` is ready for whenever
that changes, nothing else needs to. Semantic global's "same model
across systems" assumption is checked by inspecting feather-file
metadata, not re-verified at query time - a future system embedded
with a different model would silently miscalibrate rather than error
(noted in `global.rs`'s doc comment, not fixed here).
