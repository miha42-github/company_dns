# V4 data gaps found by the V3 parity run

Work item for a coding assistant (for example GitHub Copilot). Self-contained: everything needed is in this file and the repo.
Found 2026-10-07 by `api_tests/parity_report.py` against production V3. These are **data** differences, not shape differences
(the shapes match, apart from Gap 0 which is a pipeline problem; see `docs/plans/v4-release-to-staging.md`, step 4, decision Q14).

## Gap 0: the US division narrative is missing from the data pipeline (symptom patched, cause open)

| | |
|---|---|
| Request | `GET /V3.0/na/sic/division/E` |
| V3 | `full_description` carries the division narrative ("This division includes establishments providing, ...") |
| V4 before | `full_description` was empty |
| V4 now | filled from `v4/crates/sic/data/us_division_narratives.json`, a **hand-generated copy** of `source_data/sic_data/divisions.csv` (`Full Description` column), committed in `2025b52` |

**The symptom is patched; the problem is not.** The US SIC table (`sic_data`) is loaded from a prebuilt data file whose
schema has no narrative column, so any new data file from Mediumroast that is built the same way loses the narrative again.
The JSON side file works around that: nothing regenerates it (the one-off script was not committed), it can drift from the
CSV, and it only covers the US divisions.

**Tasks**
1. Find where the prebuilt SIC data file is produced (the embedding / ingest step that adds the vector columns) and why it drops
   `Full Description`. Document the pipeline end to end in this file: inputs, steps, outputs, who runs it.
2. Carry the narrative through the pipeline (a `section_full_desc` column or a small companion table), so it ships in the same
   data file as the rest of the SIC data. Serve it from there in `v4/crates/sic/src/systems.rs`.
3. Remove `v4/crates/sic/data/us_division_narratives.json` and the `include_str!` once the column exists. If a data file
   without the column is loaded, the server must log a warning and fall back to an empty `full_description`, not fail.
4. Add a data-readiness test (`api_tests/test_data_readiness.py`) that every US division A to J has a non-empty narrative, so a new
   data file that drops it fails the suite instead of reaching production.
5. Check the other systems (NACE, ISIC, Japan) for columns present in `source_data/` and absent from the loaded tables, and list any.

### Gap 0 handoff package (everything that was added, so nothing needs asking)

**Where the US SIC data comes from.** `v4/crates/server/src/main.rs` (around line 139) resolves `SIC_DATA_PATH`, default file
`us_flat_embedded.feather`, in `COMPANY_DNS_DATA_DIR`; `SicCatalog::open` (`v4/crates/sic/src/lib.rs`) reads it with DataFusion
`read_arrow` and registers it as table `sic_data` (columns used: `section_id`, `section_desc`, `division_id`, `division_desc`,
`group_id`, `group_desc`, `class_id`, `class_desc`, plus vector columns that the SQL endpoint hides). This file is a
Mediumroast artifact built outside this repo's Rust code (the embedding step adds the vectors): **find what builds it** (search
this repo, `source_data/`, `scripts/`, and ask the owner if it is not here), and inspect its schema, for example with
`pyarrow.ipc.open_file(...).schema`. The other systems load the same way: `JAPAN_SIC_DATA_PATH` (`sic_data_japan`), the NACE
file (`sic_data_nace`), and `ISIC_DATA_PATH` (`sic_data_isic`).

**The source text.** `source_data/sic_data/divisions.csv` (25,651 bytes) has the header `Division,Description,Full Description`
and 10 rows, A to J. The `Full Description` column is the narrative V3 serves. Its length per division, in characters:
A 2650, B 1902, C 5550, D 4981, E 1970, F 3161, G 3312, H 699, I 588, J 510. Division E begins
"This division includes establishments providing, to the general public or to other business enterprises, passenger and
freight transportation, communications services, electricity, gas, and sanitary services". The other source CSVs in the same
directory are `industry-groups.csv`, `major-groups.csv` and `sic-codes.csv`.

**What was added in commit `2025b52`.**
- `v4/crates/sic/data/us_division_narratives.json` (25,425 bytes): a flat object `{"A": "<narrative>", ..., "J": "<narrative>"}`
  with the same text as the CSV column. Generated once with this script, which was **not committed**:
  ```python
  import csv, json
  d = {r['Division']: r['Full Description'] for r in csv.DictReader(open('source_data/sic_data/divisions.csv'))}
  json.dump(d, open('v4/crates/sic/data/us_division_narratives.json', 'w'), indent=1, ensure_ascii=False)
  ```
- `v4/crates/sic/src/systems.rs`: the function `division_narrative(division: &str) -> String` loads that JSON once
  (`OnceLock<HashMap>` over `include_str!("../data/us_division_narratives.json")`, empty string when the division is absent),
  and the `System::Us` / `Level::Section` branch puts it in the entry as `full_description`. The unit test in the same file
  asserts division E's text starts with "This division includes establishments providing, to the general public or to other business enterprises".
- `api_tests/test_non_us_sic.py::V3Parity::test_us_division_matches_including_the_narrative` asserts the whole `/V3.0/na/sic/division/E`
  `data` equals V3's fixture `api_tests/fixtures/v3/us_division_E.json`.
- `api_tests/test_edgar_wikipedia_parity.py::V3ShapedEdgar::test_us_division_carries_v3s_full_description` asserts the same field.
- Docs that mention it: `docs/plans/v4-release-to-staging.md` (known intentional differences paragraph) and `v4/README.md` (non-US section).
  Update both when the side file is gone.

**How to see the current behaviour.** Build with `cd v4 && cargo build --profile release-lean --bin company-dns-server` (about 7
minutes), run it from `v4/crates/server` with the data directory set, then
`curl localhost:4000/V3.0/na/sic/division/E` and compare with the fixture; `python3 api_tests/parity_report.py` compares all 25
requests against production V3 (be polite: one request a second).

**Definition of done for Gap 0.** The narrative reaches `sic_data` (or a companion table) through the data pipeline; the
JSON file and `include_str!` are deleted; a data file without the column logs a warning and yields an empty `full_description`
(no startup failure); a data-readiness test fails when any division A to J lacks its narrative; the pipeline is documented in
this file; both docs above are updated; both test suites pass.

## Gap 1: the EDGAR catalog is missing a company V3 finds

| | |
|---|---|
| Request | `GET /V3.0/na/companies/edgar/ciks/Apple` |
| V3 | 8 companies, including `"PINEAPPLE, INC."` (CIK `1654672`) |
| V4 | 7 companies; `PINEAPPLE, INC.` is absent |
| Evidence | fixture `api_tests/fixtures/v3/edgar_ciks_apple.json`; run `python3 api_tests/parity_report.py` and read the `edgar_ciks_apple` line |

**Hypothesis to verify first:** V3 searches the SEC's full company list; V4 searches a catalog built by `ingest-edgar`
(`v4/crates/edgar/src/periods.rs`, default window of recent quarters from the SEC form index), so a company with no filing in
the window is not in it. Confirm by checking whether CIK 1654672 has filings in the ingested quarters and what window the
current catalog covers.

**Tasks**
1. Establish the cause (window too short, a form-type filter, name normalisation, or an ingest bug). Write the finding in this file.
2. Fix it in `ingest-edgar` or the catalog query (`find_by_name`, `find_grouped_by_name` in `v4/crates/edgar/`), without
   changing the catalog's size beyond what is justified (state the before and after row counts and ingest time).
3. Add a test: a Rust unit test for the cause, and make `api_tests/test_edgar_wikipedia_parity.py::V3ShapedEdgar` also assert
   that `ciks/Apple` contains every company name in the V3 fixture (a data check, skipped when the catalog is not loaded).

## Gap 2: Japan SIC description search returns a different set than V3 (decided 2026-10-08: V4 is right, case is an intentional difference)

| | |
|---|---|
| Request | `GET /V3.0/japan/sic/description/food` |
| V3 | 13 entries, keyed by mixed-case descriptions (`Manufacture of food`, `Seafood products`, ...) |
| V4 | 18 entries from the corrected file (15 entries V3 lacks such as `Cured food`, `Food processing services`) |
| Related | `GET /V3.0/japan/sic/major_group/09` and `/group/091`: V4's `description` is upper-case (`MANUFACTURE OF FOOD`) where V3 is `Manufacture of food` |

**Source (owner-supplied, 2026-10-08):** <https://www.soumu.go.jp/english/dgpp_ss/seido/sangyo/san13-3a.htm#a> (Japan's Ministry of Internal Affairs and Communications, English Japan Standard Industrial Classification). Fetching it is a download-free read; cite it, do not copy the page into the repo.

**Evidence (page read 2026-10-08).** The page is the Japan Standard Industrial Classification (Rev. 13, October 2013), Structure and
Explanatory Notes. It prints major group and group names in upper case: `09     MANUFACTURE OF FOOD`, and under it
`091     LIVESTOCK PRODUCTS` (group 091), while class-level (4-digit) names are in sentence case (`0911  Frozen meat and subprimal
products`). It also contains `Sozai` and `Cured food`, two of the entries V4 has and V3 lacks. So V4's upper case is the
source's text for major groups and groups, and the extra entries are in the source. The page has about 1,400 four-digit rows.
One open question for task 1: V3's description-search keys such as `Manufacture of food` are the same names in sentence
case, so V3 (or its extract) lower-cased them.

**Decision (owner, 2026-10-08).** The English source HTML from the Japanese government's classification gives group names in
upper case, so V4's upper-case descriptions are the source's own text. V3's Japan implementation was built from a partial
extract of that project, not the full system, which is why it has fewer entries and different case. **V4 is correct; do not
normalise the case on any path, and do not change the stored data.** The upper-case descriptions are a recorded, intentional
difference from V3 (already listed in `docs/plans/v4-release-to-staging.md`).

**Tasks (what remains)**
1. Compare case-insensitively: list which V3 descriptions have no V4 counterpart at all (not just a different case). Report the
   list here. Any that are missing from V4 are a real loss to explain (the extract may use older wording), not a case issue.
2. Replace the V3 comparison tests for Japan with tests that encode the decision, in `api_tests/test_non_us_sic.py::V3Parity`:
   Japan `description` values compare equal to V3's fixtures case-insensitively (`japan_major_09`, `japan_group_091`), and every
   V3 `japan_desc_food` entry that has a V4 counterpart matches it case-insensitively, with the missing ones from task 1 listed
   as an explicit allow-list.
3. Make `api_tests/parity_report.py` compare Japan descriptions case-insensitively (and report the extra V4 entries as
   "V4 has more", not as a difference), so the report stops flagging an intended difference.
4. (Done 2026-10-08, see Evidence below; nothing left to do.)

## Examples: wrong and right output (CSV)

"Wrong" is what V4 returned (or would return from a new data file that lacks the data); "right" is what production V3 returns and
V4 must match (except Gap 2, where V4 is right and V3 is the partial extract). Values were captured on 2026-10-07. Each row is one field of the response.

### Gap 0: `GET /V3.0/na/sic/division/E`, field `data.division.E`

```csv
case,description,full_description_chars,full_description_starts_with
"wrong (V4 before 2025b52, or a new data file without the column)","Transportation, Communications, Electric, Gas, And Sanitary Services",0,
"right (V3, and V4 now)","Transportation, Communications, Electric, Gas, And Sanitary Services",1970,"This division includes establishments providing, to the general public or to other business enterprises, passenger and freight transportation, communications services, electricity, gas, and sanitary services"
```

Expected character counts for every division (the readiness test should assert each is greater than zero, and these exactly):

```csv
division,full_description_chars
A,2650
B,1902
C,5550
D,4981
E,1970
F,3161
G,3312
H,699
I,588
J,510
```

### Gap 1: `GET /V3.0/na/companies/edgar/ciks/Apple`, field `data.companies`

```csv
company_name,cik,v3_right,v4_wrong_today
"Apple Hospitality REIT, Inc.",1418121,yes,yes
Apple Inc.,320193,yes,yes
"Apple iSports Group, Inc.",1134982,yes,yes
MAUI LAND & PINEAPPLE CO INC,63330,yes,yes
PINEAPPLE EXPRESS CANNABIS Co,1710495,yes,yes
"PINEAPPLE, INC.",1654672,yes,MISSING
Pineapple Energy Inc.,22701,yes,yes
Pineapple Financial Inc.,1938109,yes,yes
```

`data.totalCompanies` must be 8 (V4 returns 7).

### Gap 2: Japan SIC descriptions

`GET /V3.0/japan/sic/major_group/09` and `GET /V3.0/japan/sic/group/091`, field `description`:

```csv
request,code,v3_partial_extract,v4_correct_per_source
major_group/09,09,Manufacture of food,MANUFACTURE OF FOOD
group/091,091,Livestock products,LIVESTOCK PRODUCTS
```

`GET /V3.0/japan/sic/description/food`, first entries of `data.industry_groups` (V3 has 13, V4 has 18):

```csv
source,description_key,code,group_code,major_group_code,division_code
V3 partial extract,"Eating and drinking places, and Food tale out and delivery services",M2,759,75,M
V3 partial extract,"Food and beverage stores, n.e.c.",58B,589,58,I
V3 partial extract,Food and beverages,522,522,52,I
V4 has more (correct),"""Sozai"" (side-dish foods)",0996,099,09,E
V4 has more (correct),Canned or bottled seafood and seaweed,0921,092,09,E
V4 has more (correct),"Convenience stores, primarily for sale of food and beverages",5891,589,58,I
```

The upper-case text and the extra V4 entries are correct (owner's check of the source HTML, 2026-10-08); V3 is the partial extract. These rows show the intended difference, not a defect.

## Acceptance (all gaps)
- Gap 0: no side data file remains, and the division narrative test fails when the column is absent.
- `python3 api_tests/parity_report.py` shows `edgar_ciks_apple` IDENTICAL, and the Japan rows IDENTICAL or differing only by case and the extra V4 entries (Gap 2, intended).
- `cd v4 && cargo test -p company-dns-sic -p company-dns-server` and `API_TESTS_NETWORK=1 python3 api_tests/run.py --network` pass.
- Update the "Known intentional differences" paragraph in `docs/plans/v4-release-to-staging.md` to match what remains.

## Constraints
- Do not commit credentials, tokens or `v4/.local/`. Do not call the production V3 service more than once a second, and
  identify yourself in the `User-Agent`.
- The `/V4.0/` response shapes do not change.
- Build profile for the timing runs is `release-lean` (`cargo build --profile release-lean --bin company-dns-server`, about 7 minutes).
