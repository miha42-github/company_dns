> **RESOLVED (2026-10-03).** The revised file (419 rows, generated `2026-10-04T01:22Z`) passes
> `check_ic_feather.py` with no failures or warnings and all vectors re-embed at cosine .9999999. It was
> installed. Kept as the record of what was wrong. The licence note in section 5 is still open.

# ISIC Rev. 4 feather: lost sections/divisions, wrong joins, and quoted text

**File:** `tmp/isic_rev4_flat_embedded.feather` - 410 rows, pipeline `isic-rev4-embedding-export-1`,
generated `2026-10-04T01:15:50Z`, `classification_revision` "ISIC Rev. 4", model all-MiniLM-L6-v2.
**Source:** UNSD `ISIC_Rev_4_english_structure.Txt` (CSV, header `"Code","Description"`, every field quoted;
section letters are separate rows; level is derived from code shape; section for a division comes from row order).
**Found by:** loading it into the V4 server and running `docs/plans/research/check_ic_feather.py`.
**Status:** integrated as-is; nothing patched downstream. A corrected file at the same path needs no code change.

The revision is now right (the earlier `international_...` file was Rev. 5). The content is not: the export
loses structure and leaks CSV quoting into the text. `check_ic_feather.py` prints `FAIL - 7 failing check(s)`.

## 1. Defects

### 1.1 Every text cell is wrapped in literal double quotes (all 410 rows)

`section_desc`, `division_desc`, `class_desc`, `embedding_text` (407 of 410 `group_desc`; 3 are empty, see 1.4) read
`"Growing of fibre crops"` with the quote characters in the value. The source CSV quotes every field, so the
export is not parsing it as CSV (or is splitting on commas by hand, which would also explain
1.2-1.3). The quotes are inside `embedding_text`, so **every vector was computed from quoted text** and the
quotes show in the UI. Fix: read with a real CSV parser (`csv` / `pandas.read_csv`, not `split(",")`).

### 1.2 Sections E, G, O and T are missing; their divisions sit under the previous section (54 rows)

The file has 17 sections (A B C D F H I J K L M N P Q R S U); official ISIC Rev. 4 has 21. Divisions 36-39 are
labelled D, 45-47 F, 84 N, 97-98 S. Section rows are separate rows in the source and a division takes the most
recent preceding section letter, so the section rows for E, G, O and T were not picked up as sections.

### 1.3 Divisions 16, 38, 70, 71 and 84 are missing; their classes carry the previous division id (20 rows)

83 distinct divisions instead of 88. Examples: class 1610/1621/1622/1623 carry division 15 (should be 16);
3811/3812/3821/3822/3830 carry 37 (should be 38); 7010/7020 and 7110/7120 carry 69 (should be 70 and 71);
8411/8412/8413/8421/8422/8423/8430 carry 82 (should be 84). The class code prefix is right, only
`division_id` / `division_desc` (and therefore the section) is wrong. `check_ic_feather.py` rule:
`division_id == class_id[:2]`.

### 1.4 Group join errors (7 rows)

- `group_id`/`group_desc` empty on 3 rows: 1512 (group 151), 6311 and 6312 (group 631), so their unique_key reads
  `isic_rev4-C-15--1512`.
- Wrong group on 4 rows: 2593 and 2599 carry group 252 "Manufacture of weapons and ammunition" (should be 259);
  2651 and 2652 carry group 264 "Manufacture of consumer electronics" (should be 265).

### 1.5 Count is short: 410 classes, 232 groups (official 419 and 238)

Nine classes and six groups are missing from the file. The comparison could not be made class by class here
(the UN structure file is not in the repo); the acceptance check below will list them.

## 2. Root cause (inferred; the pipeline code was not inspected)

1.2-1.5 look like one cause: a hand-rolled parse of the flat file that does not treat section and division
rows reliably, so some rows are consumed as the wrong level. 1.1 is the same parser not handling CSV quoting.
Recommended: parse with a CSV reader, derive `level` from code shape (letter = section, 2 digits = division,
3 = group, 4 = class), carry the current section/division/group down by row order, and fail the build if counts
differ from 21 / 88 / 238 / 419.

## 3. What has to be regenerated

Everything: unquoting changes `embedding_text` for all rows, so all vectors change. Rows for sections A-C and
the unaffected divisions should differ only by the removed quotes.

## 4. Acceptance

```bash
python3 docs/plans/research/check_ic_feather.py tmp/isic_rev4_flat_embedded.feather
```
Must print `PASS` with no warnings: counts 21 / 88 / 238 / 419, every `division_id`/`group_id` equals the class
prefix, every division inside its section's official range (A 01-03, B 05-09, C 10-33, D 35, E 36-39, F 41-43,
G 45-47, H 49-53, I 55-56, J 58-63, K 64-66, L 68, M 69-75, N 77-82, O 84, P 85, Q 86-88, R 90-93, S 94-96,
T 97-98, U 99), no text wrapped in quotes, no empty groups. Then re-embed each `embedding_text` (revision
`1110a243...`, normalized) and confirm cosine >= 0.9999 with the stored vectors.
Per the supplied lineage note, also record the source URL, retrieval date and SHA-256 in the file metadata.

## 5. Licence (separate from the data fix)

The UN terms of use permit personal, non-commercial use and give no right to redistribute or build derivative
datasets without permission. Keep ISIC internal until written permission from UN Publications / UNSD is on
record.
