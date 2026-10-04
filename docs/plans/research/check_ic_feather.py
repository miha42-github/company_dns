#!/usr/bin/env python3
"""Validation gate for the industry-classification flat feather exports (US SIC, JSIC, NACE).

    python3 check_ic_feather.py tmp/japan_rev13_flat_embedded.feather

Needs only pyarrow. Exits 1 on any FAIL (WARN does not fail). The system is detected from the file's
`ic_module` column. Re-embedding the vectors needs sentence-transformers and is a separate step
(see jsic-text-encoding-defect.md); this script checks everything that does not need the model.

Each check exists because a real defect got through without it: wrong section letters (NACE, 52% of
rows), `#` flag treated as data and 90 groups lost (JSIC, with a row count that still came out right),
mojibake in a class name (JSIC 2596), a missing group level (NACE).
"""
import collections, math, re, sys
import pyarrow.feather as feather

# section -> (first division, last division), from the official classifications
NACE = {"A": (1, 3), "B": (5, 9), "C": (10, 33), "D": (35, 35), "E": (36, 39), "F": (41, 43), "G": (45, 47),
        "H": (49, 53), "I": (55, 56), "J": (58, 63), "K": (64, 66), "L": (68, 68), "M": (69, 75), "N": (77, 82),
        "O": (84, 84), "P": (85, 85), "Q": (86, 88), "R": (90, 93), "S": (94, 96), "T": (97, 98), "U": (99, 99)}
JSIC = {"A": (1, 2), "B": (3, 4), "C": (5, 5), "D": (6, 8), "E": (9, 32), "F": (33, 36), "G": (37, 41),
        "H": (42, 49), "I": (50, 61), "J": (62, 67), "K": (68, 70), "L": (71, 74), "M": (75, 77), "N": (78, 80),
        "O": (81, 82), "P": (83, 85), "Q": (86, 87), "R": (88, 96), "S": (97, 98), "T": (99, 99)}
# per system: section ranges, expected distinct counts (section, division, group, class), how ids nest
CONFIG = {
    "us": dict(sections=None, counts=None, division=lambda r: r["class_id"][:2], group=lambda r: r["class_id"][:3]),
    "japan_rev13": dict(sections=JSIC, counts=(20, 99, 530, 1460), division=lambda r: r["class_id"][:2], group=lambda r: r["class_id"][:3]),
    # ISIC Rev. 4: same section/division table as NACE Rev. 2; 21 sections A-U, 88 divisions, 238 groups, 419 classes
    "isic_rev4": dict(sections=NACE, counts=(21, 88, 238, 419), division=lambda r: r["class_id"][:2], group=lambda r: r["class_id"][:3]),
    "nace_rev2": dict(sections=NACE, counts=(21, 88, 272, 615), division=lambda r: r["class_id"][:2], group=lambda r: r["class_id"][:4]),
}
MOJIBAKE = re.compile(r"[\u0080-\u009f]|ï¼|ã[\u0080-¿]|â€|Ã[\u0080-¿]|Â[ -¿]|�")
LEVELS = ("section", "division", "group", "class")

failures, warnings = [], []
def check(name, bad, examples=(), warn=False):
    (warnings if warn else failures).append(name) if bad else None
    tag = "OK  " if not bad else ("WARN" if warn else "FAIL")
    print(f"  {tag} {name}" + (f": {bad}" if bad else ""))
    for e in list(examples)[:3]:
        print(f"         e.g. {e}")

t = feather.read_table(sys.argv[1])
cols = {n: t.column(n).to_pylist() for n in t.column_names if n != "vector_all_minilm_l6_v2"}
n = t.num_rows
rows = [{k: v[i] for k, v in cols.items()} for i in range(n)]
module = rows[0]["ic_module"]
cfg = CONFIG.get(module)
print(f"{sys.argv[1]}: {n} rows, ic_module={module!r}")
if cfg is None:
    sys.exit(f"unknown ic_module {module!r}")

print("-- placeholders / empties")
for lvl in LEVELS:
    bad = [r for r in rows if not r[f"{lvl}_desc"] or r[f"{lvl}_desc"] == "#" or r[f"{lvl}_desc"] in (r["section_id"], r["division_id"], r["group_id"], r["class_id"])]
    check(f"{lvl}_desc empty, '#', or just an id", len(bad), [r["unique_key"] for r in bad])

print("-- hierarchy")
check("division_id != division prefix of class_id", sum(cfg["division"](r) != r["division_id"] for r in rows))
check("group_id != group prefix of class_id", sum(cfg["group"](r) != r["group_id"] for r in rows))
for lvl in LEVELS:
    d = collections.defaultdict(set)
    for r in rows: d[r[f"{lvl}_id"]].add(r[f"{lvl}_desc"])
    check(f"{lvl}_id with more than one description", sum(len(v) > 1 for v in d.values()))
ds = collections.defaultdict(set)
for r in rows: ds[r["division_id"]].add(r["section_id"])
check("division under more than one section", sum(len(v) > 1 for v in ds.values()))
if cfg["sections"]:
    def in_range(r):  # non-numeric division ids (e.g. 'G1') or unknown sections count as failures, not crashes
        lo, hi = cfg["sections"].get(r["section_id"], (1, 0))
        return r["division_id"].isdigit() and lo <= int(r["division_id"]) <= hi
    wrong = [r for r in rows if not in_range(r)]
    check("division outside its section's official range (or non-numeric / unknown section)", len(wrong), [f"{r['unique_key']} (section {r['section_id']})" for r in wrong])
if cfg["counts"]:
    got = tuple(len(set(r[f"{l}_id"] for r in rows)) for l in LEVELS)
    check(f"distinct section/division/group/class counts {got} != official {cfg['counts']}", got != cfg["counts"])

print("-- keys and text recipe")
check("unique_key != <module>-<section>-<division>-<group>-<class>", sum(r["unique_key"] != "-".join((module, r["section_id"], r["division_id"], r["group_id"], r["class_id"])) for r in rows))
check("duplicate unique_key", n - len(set(r["unique_key"] for r in rows)))
check("'-' inside an id (breaks unique_key parsing)", sum("-" in r[f"{l}_id"] for r in rows for l in LEVELS))
def recipe(r):
    p = [r["section_desc"], r["division_desc"], r["group_desc"], r["class_desc"]] + ([r["subclass_desc"]] if r.get("subclass_desc") else [])
    return " > ".join(p)
check("embedding_text != ' > '.join(section, division, group, class)", sum(recipe(r) != r["embedding_text"] for r in rows), [r["unique_key"] for r in rows if recipe(r) != r["embedding_text"]])
check("identical embedding_text across rows", n - len(set(r["embedding_text"] for r in rows)))

print("-- text hygiene (all string columns)")
bad = [(c, r["unique_key"], r[c]) for r in rows for c in cols if isinstance(r[c], str) and MOJIBAKE.search(r[c])]
check("mojibake / control characters", len(bad), [f"{c} {k}: {v[:60]!r}" for c, k, v in bad])
en = [c for c in cols if isinstance(rows[0][c], str) and not c.endswith("_ja")]
bad = [(c, r["unique_key"], r[c]) for r in rows for c in en if re.search(r"[＀-￯ \t\n\r]", r[c]) or r[c] != r[c].strip() or "  " in r[c]]
check("full-width char, NBSP, tab/newline, stray or double spaces in English text", len(bad), [f"{c} {k}: {v[:60]!r}" for c, k, v in bad])
bad = [(c, r["unique_key"]) for r in rows for c in en if re.search(r"[–—‘’“”]", r[c])]
check("typographic dashes/quotes in English text (normalize to ASCII, or confirm intended)", len({k for _, k in bad}), [f"{c} {k}" for c, k in bad[:3]], warn=True)
wrapped = [(c, r["unique_key"]) for r in rows for c in en if isinstance(r[c], str) and len(r[c]) > 1 and r[c][0] == '"' and r[c][-1] == '"']
check("text wrapped in literal double quotes (CSV quoting leaked into the data)", len(wrapped), [f"{c} {k}" for c, k in wrapped[:3]])
if module == "japan_rev13":
    jp = lambda s: bool(re.search(r"[぀-ヿ一-鿿]", s))
    ja = [f"{l}_desc_ja" for l in LEVELS if f"{l}_desc_ja" in cols]  # subclass_desc_ja is empty by design
    check("Japanese level column missing, empty, or without Japanese characters", (len(LEVELS) - len(ja)) * n + sum(1 for r in rows for c in ja if not r[c] or not jp(r[c])))

print("-- vectors (structure only; re-embedding is a separate step)")
vecs = t.column("vector_all_minilm_l6_v2").to_pylist()
norms = [math.sqrt(sum(x * x for x in v)) for v in vecs]
check("vector dim != 384", sum(len(v) != 384 for v in vecs))
check("vector not unit-norm or non-finite", sum(not math.isfinite(s) or abs(s - 1) > 1e-3 for s in norms))
check("rows != vectors", n - len(vecs))

print(f"\n{'PASS' if not failures else 'FAIL'}" + (f" - {len(failures)} failing check(s)" if failures else "") + (f", {len(warnings)} warning(s)" if warnings else ""))
sys.exit(1 if failures else 0)
