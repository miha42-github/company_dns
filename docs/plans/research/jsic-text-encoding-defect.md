> **RESOLVED (2026-10-03).** Fixed files landed: `check_ic_feather.py` prints `PASS` with no warnings for
> JSIC, NACE and US, English text is pure ASCII in both new files, and all 1,460 JSIC / 615 NACE vectors
> re-embed at cosine >= 0.9999999. Kept as the record of what was wrong.

# JSIC feather: one mojibake'd class name, and a text-hygiene gap across the IC exports

**File:** `tmp/japan_rev13_flat_embedded.feather` (1,460 rows, `japan-rev13-embedding-export-1`).
Everything else in this file checked out (structure, counts, Japanese columns, vectors), so this is a
small fix. The reason for a report anyway is section 2: the same kind of problem exists in a second
file, which points at the export pipeline rather than at one cell.

## 1. The defect

Row `japan_rev13-E-25-259-2596`:

| column | value |
|---|---|
| `class_desc` | `Generalï¼\x8dpurpose machinery and apparatus, n.e.c.` |
| should be | `General-purpose machinery and apparatus, n.e.c.` |
| `division_desc` / `group_desc` (same row) | `MANUFACTURE OF GENERAL-PURPOSE MACHINERY` / `MISCELLANEOUS GENERAL-PURPOSE MACHINERY AND MACHINE PARTS` (fine, plain hyphen) |

**Cause:** the UTF-8 bytes of a full-width hyphen-minus (U+FF0D `－`, bytes `EF BC 8D`) were decoded as
Latin-1. `x.encode('latin-1').decode('utf-8')` round-trips the cell exactly to `General－purpose ...`.
Only the class-level text carries it; the upper levels of the same row do not.

**Propagation:** the garbled text is in `class_desc`, in `embedding_text`
(`... > Generalï¼\x8dpurpose machinery and apparatus, n.e.c.`) and therefore in that row's vector. One row
of 1,460. It is the only mojibake in the US, JSIC and NACE files (US is clean; the `*_ja` columns are clean).

## 2. The general finding

The same phrase, "general-purpose machinery", carries a non-ASCII hyphen variant in two systems:

- **JSIC** class 2596: full-width hyphen decoded wrongly (above).
- **NACE** group 28.1 (classes 28.11-28.15, 5 rows): `Manufacture of general — purpose machinery`
  (a spaced em dash; the official text is `general-purpose`).
- **JSIC** also has curly quotes/apostrophes in 16 rows (`MEN’S ...`, `“TATAMI” ...`), harmless but the
  third variant of the same thing.

Three different encodings of one punctuation class across two files says the export has no
normalization or validation step for dashes, quotes and encoding artifacts. The outputs cannot show where
(reading the source with the wrong encoding, or a normalization that handles only some characters). One
clue: no other full-width character survives anywhere in the JSIC English text, so either a normalization
step exists and missed this cell, or the source has no others.

## 3. Requested fix

1. **JSIC 2596:** read the source cell with the right encoding, then normalize full-width forms
   (`unicodedata.normalize('NFKC', s)` maps U+FF0D to `-`) -> `General-purpose machinery and apparatus, n.e.c.`
2. **NACE 28.1:** `Manufacture of general-purpose machinery` (5 rows; cosmetic, same cause).
3. **Regenerate `embedding_text` and the vector** for the changed rows: JSIC 1 row, NACE 5 rows, and the
   16 JSIC curly-quote rows only if you also normalize quotes to ASCII (optional).
4. **Add a gate before a file lands in `tmp/`:** `docs/plans/research/check_ic_feather.py <file>`
   (pyarrow only, exits 1 on failure). It runs the checks below and detects the system from `ic_module`.

| Defect found so far | Check that catches it | Tested against |
|---|---|---|
| NACE: section letters shifted from division 36 up (323 rows) | division outside its section's official range; 20 vs 21 sections | the shifted layout reapplied to the corrected file (synthetic; the original is overwritten) |
| JSIC: `#` flag treated as data, 90 groups lost, row count still 529 | placeholders/empties; id nesting; counts vs official (17/69/381/529 vs 20/99/530/1,460); duplicate text | a reconstruction of the old file: 12 failing checks |
| JSIC: mojibake in 2596 | mojibake / control-character scan of every string column | the real file: flags exactly row 2596 |
| NACE: no group level | `group_desc` empty or just an id | by construction only (the old file is gone) |

The gate also checks `unique_key` recipe and uniqueness, `embedding_text` recipe, one description per id
at every level, and vector dimension and unit norm. Dashes and curly quotes are WARN, not FAIL.

5. **Vectors against text** needs the model, so it is not in the script. For each row, encode
   `embedding_text` with `all-MiniLM-L6-v2` (revision `1110a243...`, `normalize_embeddings=True`) and check
   cosine >= 0.9999 against the stored `vector_all_minilm_l6_v2`. All three current files pass at 1.000000,
   so the pipeline is reproducible; a changed row should too.

## 4. Acceptance

`check_ic_feather.py` prints `PASS` for all three exports. Today: US `PASS`; NACE `PASS` with 1 warning
(the em dash); JSIC `FAIL` on the mojibake check only, with 1 warning (curly quotes).
