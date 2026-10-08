# Data package work item: the US SIC file and its division narrative

A brief for an engineer or coding agent who has not seen this project before. You do not need to know anything about earlier
versions of the service. Everything you need is in this file and the repository. Facts below were checked on 2026-10-08,
after two deliveries of a corrected US data file (the second, `us_flat_embedded.feather` dated 2026-10-08 06:06, is the current one).

## 1. Context in five lines

- This repository serves industry-classification and company data over an HTTP API (the Rust server in `v4/`).
- The classification data is loaded at startup from **flat data files** in the directory named by `COMPANY_DNS_DATA_DIR`
  (on the author's machine `/Users/mihay42/dev/company_dns/tmp/`; it is not committed).
- The files are supplied by the data owner (Mediumroast). The step that produces them **is not in this repository**; the repository
  only holds a validator for them (`docs/plans/research/check_ic_feather.py`) and notes on defects found in earlier deliveries
  (`docs/plans/research/*-defects.md`).
- When a new delivery of the files arrives, the server must work with it without anyone patching code.
- Your job is described in section 3. Sections 4 and 5 are two findings that are **not defects**; they are here so nobody
  re-opens them, plus one small check.

| # | Item | Verdict | What you do |
|---|---|---|---|
| 1a | The old US SIC file had no column for the division narrative text | **Fixed in the data** (new delivery, 2026-10-08); the server does not use it yet | Section 3.3: switch the server to the column, remove the stopgap |
| 1b | The first new file's narratives for sections A, B, C and G ended with a stray space | **Fixed in the data** (second delivery, 2026-10-08 06:06; validator passes) | Section 3.2: keep the server trim as a safeguard |
| 2 | EDGAR catalog does not contain one company a reference system finds | **Not a defect**: the company is outside the catalog's stated scope | Section 4: document, no code change |
| 3 | Japan SIC descriptions are upper case and there are more of them than a reference system returns | **Not a defect**: the data matches the official source | Section 5: one completeness check |

## 2. Vocabulary

- **Section / division / group / class**: the four levels of the US Standard Industrial Classification. Section is a letter A to J
  ("Transportation, Communications, Electric, Gas, And Sanitary Services" is section E). Division is a 2-digit code (40), group
  is 3 digits (401), class is 4 digits (4011). In the data file the columns are named `section_*`, `division_*`, `group_*`, `class_*`.
- **Narrative**: a long paragraph in the official classification that explains what a section covers (500 to 5,500 characters).
  The CSV column is called `Full Description`; the API field is `full_description`.
- **Reference system**: an older production service ("V3") that the new server was compared with, request by request. It is
  used here only as evidence of what the answers should contain. It is not part of this repository.

## 3. Item 1: the US SIC division narrative

### 3.1 Background and what the delivery contains

The API must return a long explanatory paragraph (the **narrative**) for each US SIC section on
`GET /V3.0/na/sic/division/{letter}`, in the field `data.division.{letter}.full_description`. The text lives in the repository's
source data, `source_data/sic_data/divisions.csv` (header `Division,Description,Full Description`, 10 rows, A to J).

The **old** `us_flat_embedded.feather` (1,005 rows, one per 4-digit class) had no column for it, so the server could not answer
from the data. As a stopgap, commit `2025b52` added a hand-generated side file that the server reads instead (section 3.4).

The **current** `us_flat_embedded.feather` (delivered 2026-10-08 06:06, 1,509,186 bytes) adds one column, `section_full_desc`
(placed right after `section_desc`; read it by name, not by position), repeated on every row of the section. Verified:

- Row count is still 1,005; every pre-existing column is identical to `us_flat.feather`; the 384-dimension vectors have no nulls.
- Each section has exactly one narrative, and it equals the CSV text with surrounding whitespace removed.
- The file grew by only 13 KB, so repeating the text per row is not a size problem (the file is compressed). Use this column; a
  companion table is not needed.

```csv
section,full_description_chars
A,2649
B,1901
C,5549
D,4981
E,1970
F,3161
G,3311
H,699
I,588
J,510
```

The validator passes on this file (`PASS`, no failures).

### 3.2 Defect 1b (fixed in the second delivery): stray trailing space in four narratives

History, so the safeguard below makes sense. The first corrected file (dated 2026-10-08 05:42) failed the validator on **179 rows**
(`python3 docs/plans/research/check_ic_feather.py <path>/us_flat_embedded.feather`, check "full-width char, NBSP, tab/newline, stray or
double spaces in English text"): every row of sections A (58), B (31), C (26) and G (64) had a narrative ending in one space. The
space came from the source text (`divisions.csv`). The second delivery strips it, and the validator now passes.

Wrong (first delivery) and right (current) for the end of each narrative:

```csv
section,length_first_delivery,length_current,last_14_chars_first_delivery,last_14_chars_current
A,2650,2649,"ps 01 and 02. |","s 01 and 02.|"
B,1902,1901,"stablishment. |","tablishment.|"
C,5550,5549," restaurants. |","restaurants.|"
G,3312,3311,"ry Group 596. |","y Group 596.|"
```

(The `|` marks the end of the string and is not part of the data.)

**Tasks for 1b (small, because the data is fixed)**
1. Keep the validator rule as it is; do not relax it.
2. Keep the server tolerant: when it reads `section_full_desc` (3.3), apply `trim()` to the value, so the API output stays clean even
   if a later delivery regresses. Add a Rust unit test with a value `"text. "` that expects `"text."`.
3. `source_data/sic_data/divisions.csv` still has the trailing space on the four rows (A, B, C, G). Remove it there too, so the
   repository's source matches the delivered data; confirm the other six rows have none.

### 3.3 Tasks for 1a: use the column in the server

1. **Read the column.** In `v4/crates/sic/src/systems.rs`, change `division_narrative` (and the `System::Us` / `Level::Section` branch that
   calls it) to take the narrative from the loaded `sic_data` rows (`section_full_desc`) instead of the side file. The query that
   builds section rows is in `v4/crates/sic/src/lookup.rs` and `systems.rs` (`find_in_system`); the table is registered in
   `SicCatalog::open` (`v4/crates/sic/src/lib.rs`).
2. **Fail soft on old files.** If a data file has no `section_full_desc` column, log one warning at startup and return an empty
   `full_description` for that file. The server must not refuse to start. Add a test using `us_flat.feather` (which lacks the column).
3. **Remove the stopgap** (3.4): delete `v4/crates/sic/data/us_division_narratives.json` and the `include_str!`/`OnceLock`
   code, and update the unit test in `systems.rs` that checks division E's text.
4. **Add a data-readiness test** in `api_tests/test_data_readiness.py`: `GET /V3.0/na/sic/division/{A..J}` returns a non-empty
   `full_description` with no leading or trailing whitespace, and with these exact lengths after trimming:
   A 2649, B 1901, C 5549, D 4981, E 1970, F 3161, G 3311, H 699, I 588, J 510.
5. **Validator check for presence.** In `docs/plans/research/check_ic_feather.py`, for `ic_module == "us"`, fail when `section_full_desc` is missing or
   empty for any section A to J. (The existing hygiene check already covers whitespace once the column exists.)
6. **Look for the same omission elsewhere.** For NACE, ISIC and Japan, list any column or table in `source_data/` that the feather
   files lack and report it in "Results" (do not fix it in this change).
7. **Update docs**: the "known intentional differences" paragraph in `docs/plans/v4-release-to-staging.md` and the non-US paragraph in
   `v4/README.md` both mention the narrative; make them say it comes from the data file.

### 3.4 The stopgap that exists today (you will remove it)

- `v4/crates/sic/data/us_division_narratives.json`: a flat JSON object `{"A": "<text>", ..., "J": "<text>"}`, generated once from the CSV with
  this script, which was not committed:
  ```python
  import csv, json
  d = {r['Division']: r['Full Description'] for r in csv.DictReader(open('source_data/sic_data/divisions.csv'))}
  json.dump(d, open('v4/crates/sic/data/us_division_narratives.json', 'w'), indent=1, ensure_ascii=False)
  ```
- `v4/crates/sic/src/systems.rs`: the function `division_narrative(division)` loads that file (`include_str!`, once, into a
  `HashMap`; empty string when the section is missing).

It is not acceptable as the end state: nothing regenerates the JSON, so it can drift from the CSV and from future data deliveries.
(It also carries the same four trailing spaces, since it was copied from the CSV.)

### 3.5 Definition of done

- The server serves `full_description` from `section_full_desc` in the data file; the JSON file and the `include_str!` are gone.
- `curl localhost:4000/V3.0/na/sic/division/{A..J}` returns the trimmed lengths in task 4 above.
- Loading `us_flat.feather` (no column) starts the server, logs one warning, and returns `""`.
- The validator fails on a US file that lacks the narrative, and passes on the current file (and fails if the narratives regain stray whitespace).
- `cd v4 && cargo test -p company-dns-sic -p company-dns-server` passes, and `API_TESTS_NETWORK=1 python3 api_tests/run.py --network` passes against a running server.
- "Results" (end of this file) lists what changed, and the other-systems omission list.

## 4. Item 2 (not a defect): the EDGAR catalog does not contain "PINEAPPLE, INC."

**Observation.** `GET /V3.0/na/companies/edgar/ciks/Apple` returns 7 companies. The reference system returns 8: the extra one is
`PINEAPPLE, INC.` (CIK 1654672).

**Finding (checked 2026-10-08).** The catalog file, `edgar_10x_catalog.feather` (72,813 rows; columns `cik, company_name, form_type,
year, month, day, accession, url`), is built by `ingest-edgar` (`v4/crates/edgar/src/periods.rs`) from the SEC's quarterly filing
indexes for **10-K and 10-Q forms in the last eight completed quarters** (2024 to 2026 in the current file). It contains no row
for CIK 1654672. The SEC's own record for that company (`https://data.sec.gov/submissions/CIK0001654672.json`) shows its last
10-Q on 2024-01-12, an `NT 10-K` on 2024-04-01 and a `15-12G` (deregistration) on 2024-05-07, so it has no 10-K or 10-Q in the window.
The catalog is working as designed: it lists companies that have recently filed periodic reports. The reference system searched a
larger list.

**Tasks.**
1. Record this finding in `docs/plans/v4-release-to-staging.md` as an intentional difference: "the EDGAR catalog covers 10-K and
   10-Q filers in a rolling eight-quarter window; companies that stopped filing before the window (for example PINEAPPLE, INC.,
   CIK 1654672) are not returned."
2. Add that sentence to the description of the EDGAR `ciks` operation in the API docs (`v4/crates/server/src/main.rs`, the
   `utoipa::path` for `edgar_ciks`), so users know the scope.
3. Do **not** widen the window or change `ingest-edgar` unless the owner asks. If the owner does want lapsed filers, the change is to the form-type
   filter and the window in `periods.rs`; report the row-count and ingest-time cost first.
4. In `api_tests/test_edgar_wikipedia_parity.py`, the `ciks` test compares only the structure, so no test change is needed.

## 5. Item 3 (not a defect): Japan SIC descriptions

**Observation.** `GET /V3.0/japan/sic/major_group/09` returns `MANUFACTURE OF FOOD`; the reference system returns
`Manufacture of food`. `GET /V3.0/japan/sic/description/food` returns 18 entries here and 13 there.

**Finding (checked 2026-10-08).** The official source,
<https://www.soumu.go.jp/english/dgpp_ss/seido/sangyo/san13-3a.htm> (Japan Standard Industrial Classification, Rev. 13, October
2013), prints major-group and group names in upper case (`09 MANUFACTURE OF FOOD`, `091 LIVESTOCK PRODUCTS`) and class names in
sentence case (`0911 Frozen meat and subprimal products`). It contains the entries that only this server returns (for example
`Sozai`, `Cured food`). The reference system was built from a partial extract of that classification. The data here is right.
**Do not change the case and do not change the stored data.**

**Task (one check, report only).** Compare the descriptions the server holds for Japan (`japan_rev13_flat_embedded.feather`, 1,460
class rows) with the entries on the source page. List, in this file, any entry on the page that the file lacks, and any file
entry whose text differs from the page other than by case. An empty list is a valid result. The author fetched the page once;
fetch it with a normal browser User-Agent, no more than once, and cite it rather than copying it into the repository.

## 6. How to run things

- Build the server: `cd v4 && cargo build --profile release-lean --bin company-dns-server` (about 7 minutes; `cargo build` is faster for debug).
- Run it: `cd v4/crates/server && COMPANY_DNS_DATA_DIR=<dir with the feather files> ../../target/release-lean/company-dns-server` (port 4000).
- Rust tests: `cd v4 && cargo test -p company-dns-sic -p company-dns-server`.
- API tests (Python standard library only): `API_TESTS_NETWORK=1 python3 api_tests/run.py --network` (against `http://localhost:4000`).
- Validator for the data files: `python3 docs/plans/research/check_ic_feather.py <file.feather>` (needs `pyarrow`).
- Optional comparison against the reference service: `python3 api_tests/parity_report.py` (one request a second, self-identifying User-Agent).

## 7. Constraints

- Do not commit credentials, tokens, `v4/.local/`, or the data files (`tmp/` is gitignored).
- The response shapes of the `/V4.0/` endpoints must not change.
- Do not call the reference service or the SEC faster than one request a second, and identify yourself in the `User-Agent`.
- Report what you changed and what you could not verify, in this file's "Results" section (add it at the end).
