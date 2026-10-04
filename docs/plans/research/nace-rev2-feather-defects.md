# NACE Rev. 2 feather: wrong section assignment (52% of rows) and missing group level

> **RESOLVED (2026-10-02).** The corrected `nace_rev2_flat_embedded.feather` (pipeline run
> `2026-10-03T03:20:33Z`) was checked and pulled in. Both items below were fixed: 21 sections, all 615
> rows' sections match the official table, and the real group level is populated (272 groups, 4-level
> `embedding_text` with `>`). Every vector re-embeds from its `embedding_text` at cosine 1.000000. The
> report below is kept as the record of what was wrong.

**File:** `tmp/nace_rev2_flat_embedded.feather` - 615 rows, pipeline version
`nace-rev2-embedding-export-1`, generated `2026-10-03T02:33:41Z`, model
`sentence-transformers/all-MiniLM-L6-v2` (revision `1110a243...`, 384-d, normalized).
**Found by:** loading it into the company_dns V4 server alongside the US SIC and Japan SIC files.
**Status:** integrated as-is; nothing patched downstream. A corrected file dropped at the same path
needs no code change on the consuming side.

## 1. Defect (must fix): section letters are wrong for every division from 36 up

323 of 615 rows (52%, 55 of 88 divisions) carry the wrong `section_id` / `section_desc`.

Example: class `47.71` "Retail sale of clothing in specialised stores" is labelled section `F`
"CONSTRUCTION". In NACE Rev. 2 it belongs to section `G` "WHOLESALE AND RETAIL TRADE; REPAIR OF MOTOR
VEHICLES AND MOTORCYCLES". Division 99 is labelled `T`; it should be `U`, and `U` never appears in the
file (20 distinct sections instead of 21).

| Divisions | Rows | File has | Should be |
|---|---|---|---|
| 01-03 | 39 | A | A (ok) |
| 05-09 | 15 | B | B (ok) |
| 10-33 | 230 | C | C (ok) |
| 35 | 8 | D | D (ok) |
| 36-39 | 9 | D | **E** |
| 41-43 | 22 | E | **F** |
| 45-47 | 91 | F | **G** |
| 49-53 | 23 | G | **H** |
| 55-56 | 8 | H | **I** |
| 58-63 | 26 | I | **J** |
| 64-66 | 18 | J | **K** |
| 68 | 4 | K | **L** |
| 69-75 | 19 | L | **M** |
| 77-82 | 33 | M | **N** |
| 84 | 9 | N | **O** |
| 85 | 11 | O | **P** |
| 86-88 | 12 | P | **Q** |
| 90-93 | 15 | Q | **R** |
| 94-96 | 19 | R | **S** |
| 97-98 | 3 | S | **T** |
| 99 | 1 | T | **U** |

### Likely root cause (inferred from the data; the generator was not inspected)

Letters look like they were assigned sequentially to division ranges, with the boundary between D
(division 35 only) and E (divisions 36-39) missing, so 20 ranges got letters A-T instead of 21 getting
A-U. Evidence that only the division-to-section lookup is wrong: the file's letter-to-description pairing
is already correct for every letter it contains (F = CONSTRUCTION, G = WHOLESALE AND RETAIL TRADE...,
etc.), and the division and class levels (88 divisions, 615 classes) are complete and correct.

Correct section table (NACE Rev. 2). Descriptions are the ones already in the file, in the file's
all-caps style; `U` is the only one the file lacks:

| Section | Divisions | `section_desc` |
|---|---|---|
| A | 01-03 | AGRICULTURE, FORESTRY AND FISHING |
| B | 05-09 | MINING AND QUARRYING |
| C | 10-33 | MANUFACTURING |
| D | 35 | ELECTRICITY, GAS, STEAM AND AIR CONDITIONING SUPPLY |
| E | 36-39 | WATER SUPPLY; SEWERAGE, WASTE MANAGEMENT AND REMEDIATION ACTIVITIES |
| F | 41-43 | CONSTRUCTION |
| G | 45-47 | WHOLESALE AND RETAIL TRADE; REPAIR OF MOTOR VEHICLES AND MOTORCYCLES |
| H | 49-53 | TRANSPORTATION AND STORAGE |
| I | 55-56 | ACCOMMODATION AND FOOD SERVICE ACTIVITIES |
| J | 58-63 | INFORMATION AND COMMUNICATION |
| K | 64-66 | FINANCIAL AND INSURANCE ACTIVITIES |
| L | 68 | REAL ESTATE ACTIVITIES |
| M | 69-75 | PROFESSIONAL, SCIENTIFIC AND TECHNICAL ACTIVITIES |
| N | 77-82 | ADMINISTRATIVE AND SUPPORT SERVICE ACTIVITIES |
| O | 84 | PUBLIC ADMINISTRATION AND DEFENCE; COMPULSORY SOCIAL SECURITY |
| P | 85 | EDUCATION |
| Q | 86-88 | HUMAN HEALTH AND SOCIAL WORK ACTIVITIES |
| R | 90-93 | ARTS, ENTERTAINMENT AND RECREATION |
| S | 94-96 | OTHER SERVICE ACTIVITIES |
| T | 97-98 | ACTIVITIES OF HOUSEHOLDS AS EMPLOYERS; UNDIFFERENTIATED GOODS- AND SERVICES-PRODUCING ACTIVITIES OF HOUSEHOLDS FOR OWN USE |
| U | 99 | ACTIVITIES OF EXTRATERRITORIAL ORGANISATIONS AND BODIES |

### What has to be regenerated, not just relabelled

The wrong section is baked into four more columns, so a relabel of `section_id`/`section_desc` alone is
not enough:

- `unique_key` - second segment is the section letter (e.g. `nace_rev2-F-47-47-47.71` should be `...-G-47-...`)
- `embedding_text` - starts with the section description (currently e.g. `CONSTRUCTION > Retail trade, except of motor vehicles and motorcycles > ...`)
- `vector_all_minilm_l6_v2` - computed from that text, so all 323 affected vectors are tainted

The other 292 rows (divisions 01-35) should come out of the regenerated file **unchanged**.

## 2. Decision needed (not a bug): there is no group level

NACE Rev. 2 has 272 groups (e.g. `01.1 Growing of non-perennial crops`). In this file `group_id` just
repeats `division_id` and `group_desc` is the empty string on all 615 rows; `embedding_text` has 3
levels (section > division > class) where the US and Japan files have 4.

Either populate the real group level (`group_id` like `01.1`, `group_desc`, and a 4-level
`embedding_text`) or leave it empty on purpose. The consuming UI currently shows Section and Division
only for this system and will show a third level if groups are populated. Note that adding groups
changes `embedding_text` for **all** 615 rows, so it should be done in the same regeneration as section 1
rather than as a second pass.

## 3. Minor, no action required unless convenient

- Schema metadata `source_file` says `us_flat.feather` (same in the Japan file) - presumably copied from
  the US pipeline.
- `section_desc` is ALL CAPS while the US and Japan files use title/sentence case. Harmless for the
  uncased MiniLM; cosmetic in the UI.
- 8 rows have `division_desc == class_desc` (`12.00`, `36.00`, `37.00`, `39.00`, `75.00`, `92.00`,
  `97.00`, `99.00`). That matches NACE's single-class divisions; no action.

## 4. Why it matters downstream

Every EU NACE result in keyword and semantic search shows the section label, and for 52% of rows it is
wrong ("Retail sale of clothing" under CONSTRUCTION). The wrong section words are also part of the text
that was embedded, so semantic similarity for those rows is computed against partly incorrect text.

## 5. Acceptance checks for the fixed file

Run with `python3` + `pyarrow`: `python3 check_nace.py path/to/file.feather`. On the current file it prints
`FAIL - 324 problems` (the 323 mislabelled rows plus the 21-sections check); it should print `PASS` after
the fix. It compares each row's section to the official table above and checks that `unique_key` and
`embedding_text` agree with `section_id` / `section_desc`.

```python
import sys, pyarrow.feather as feather

OFFICIAL = [("A",1,3),("B",5,9),("C",10,33),("D",35,35),("E",36,39),("F",41,43),("G",45,47),
            ("H",49,53),("I",55,56),("J",58,63),("K",64,66),("L",68,68),("M",69,75),("N",77,82),
            ("O",84,84),("P",85,85),("Q",86,88),("R",90,93),("S",94,96),("T",97,98),("U",99,99)]
def section_for(div):
    return next(s for s, lo, hi in OFFICIAL if lo <= int(div) <= hi)

t = feather.read_table(sys.argv[1] if len(sys.argv) > 1 else "tmp/nace_rev2_flat_embedded.feather")
c = {n: t.column(n).to_pylist() for n in ["section_id","section_desc","division_id","unique_key","embedding_text"]}
n = t.num_rows
problems = []
if n != 615: problems.append(f"expected 615 rows, got {n}")
if len(set(c["section_id"])) != 21: problems.append(f"expected 21 distinct sections, got {len(set(c['section_id']))}")
desc = {}
for i in range(n):
    want = section_for(c["division_id"][i])
    if c["section_id"][i] != want:
        problems.append(f"{c['unique_key'][i]}: section_id {c['section_id'][i]!r}, should be {want!r}")
    desc.setdefault(c["section_id"][i], set()).add(c["section_desc"][i])
    if c["unique_key"][i].split("-")[1] != c["section_id"][i]:
        problems.append(f"{c['unique_key'][i]}: unique_key section segment != section_id")
    if not c["embedding_text"][i].startswith(c["section_desc"][i] + " > "):
        problems.append(f"{c['unique_key'][i]}: embedding_text does not start with section_desc")
for s, d in desc.items():
    if len(d) != 1: problems.append(f"section {s} has {len(d)} different descriptions")
print("PASS" if not problems else f"FAIL - {len(problems)} problems")
for p in problems[:8]: print("  ", p)
sys.exit(1 if problems else 0)
```

Vectors can only be checked by re-embedding. With `sentence-transformers`, encode every row's
`embedding_text` using `all-MiniLM-L6-v2` (revision `1110a243...`, `normalize_embeddings=True`) and
confirm the cosine against the stored `vector_all_minilm_l6_v2` is at least 0.9999 for all 615 rows. The
same check on the US and Japan files returns exactly 1.0000, so the pipeline is reproducible.
