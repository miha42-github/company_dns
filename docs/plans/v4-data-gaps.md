# V4 data gaps found by the V3 parity run

Work item for a coding assistant (for example GitHub Copilot). Self-contained: everything needed is in this file and the repo.
Found 2026-10-07 by `api_tests/parity_report.py` against production V3. These are **data** differences, not shape differences
(the shapes match; see `docs/plans/v4-release-to-staging.md`, step 4, decision Q14).

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

## Gap 2: Japan SIC description search returns a different set than V3

| | |
|---|---|
| Request | `GET /V3.0/japan/sic/description/food` |
| V3 | 13 entries, keyed by mixed-case descriptions (`Manufacture of food`, `Seafood products`, ...) |
| V4 | 18 entries, keyed by the corrected file's descriptions (`MANUFACTURE OF FOOD` upper-case; 15 entries V3 lacks such as `Cured food`, `Food processing services`) |
| Related | `GET /V3.0/japan/sic/major_group/09` and `/group/091`: same shape, but V4's `description` is upper-case (`MANUFACTURE OF FOOD`) where V3 is `Manufacture of food` |

V4 serves the corrected Japan files (a decision recorded in the plan: V4's Japan and NACE data are the corrected ones), so
more matches are expected. The open questions are whether the **upper-case** descriptions are deliberate, and whether any of
the ten entries V3 has and V4 lacks are real losses rather than case differences.

**Tasks**
1. Compare case-insensitively: list which V3 descriptions have no V4 counterpart at all (not just a different case). Report the list here.
2. Find where the upper-case text comes from (`source_data/` Japan CSV or the ingest) and decide, with evidence from the
   corrected source, whether to normalise to V3's mixed case on the `/V3.0/` and `/V2.0/` paths (V3 readers) while keeping
   the source text on `/V4.0/`. Prefer a display-only normalisation in `v4/crates/sic/src/systems.rs` (`v3_reply`) over
   changing stored data.
3. Add tests to `api_tests/test_non_us_sic.py::V3Parity`: V3-path Japan descriptions equal V3's fixtures for
   `japan_major_09` and `japan_group_091`; and every V3 fixture entry in `japan_desc_food` has a case-insensitive match in V4.

## Acceptance (both gaps)
- `python3 api_tests/parity_report.py` shows `japan_major_09` and `japan_group_091` IDENTICAL, and `edgar_ciks_apple` and
  `japan_desc_food` either IDENTICAL or differing only by entries documented in this file as intended.
- `cd v4 && cargo test -p company-dns-sic -p company-dns-server` and `API_TESTS_NETWORK=1 python3 api_tests/run.py --network` pass.
- Update the "Known intentional differences" paragraph in `docs/plans/v4-release-to-staging.md` to match what remains.

## Constraints
- Do not commit credentials, tokens or `v4/.local/`. Do not call the production V3 service more than once a second, and
  identify yourself in the `User-Agent`.
- The `/V4.0/` response shapes do not change.
- Build profile for the timing runs is `release-lean` (`cargo build --profile release-lean --bin company-dns-server`, about 7 minutes).
