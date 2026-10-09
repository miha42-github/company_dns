#!/usr/bin/env python3
"""Human review of the drafted acceptable codes, in a plain text file.

    python3 review.py make  <tmp_dir>     # writes review.md from companies.json (drafts only)
    python3 review.py apply <tmp_dir>     # reads review.md back into companies.json

In review.md, for each company and system:
  * a line "- [x] 3571 Electronic Computers ..." is KEPT; change [x] to [ ] to REMOVE it
  * "- add: 7372, 3577" adds codes (checked against the corpus; unknown codes are rejected)
  * "reviewed: yes" at the end of the company block marks it done (labels_status -> "reviewed");
    leave "reviewed: no" to keep it draft
Needs pyarrow only. `apply` refuses to write if any code is unknown, and prints what it changed.
"""
import json, re, sys
from pathlib import Path
import pyarrow.feather as f

HERE = Path(__file__).parent
SYSTEMS = [("us_sic", "US SIC", "us_flat_embedded.feather"), ("isic_rev4", "ISIC Rev.4", "isic_rev4_flat_embedded.feather"),
           ("nace_rev2", "NACE Rev.2", "nace_rev2_flat_embedded.feather")]


def corpora(tmp):
    out = {}
    for key, _, fn in SYSTEMS:
        t = f.read_table(Path(tmp) / fn)
        out[key] = dict(zip(t.column("class_id").to_pylist(), t.column("embedding_text").to_pylist()))
    return out


def make(tmp):
    corp, data = corpora(tmp), json.loads((HERE / "companies.json").read_text())
    lines = ["# Review of drafted acceptable codes", "",
             "Keep a code: leave `[x]`. Remove: change to `[ ]`. Add: put codes after `add:`. When you have finished a company,",
             "set `reviewed: yes`. Then run `python3 review.py apply <tmp_dir>`. Think: would a reasonable analyst accept this code",
             "as describing a real line of business of this company? (Not: is it the one code the company filed.)", ""]
    n = 0
    for c in data["companies"]:
        if c.get("labels_status") != "draft":
            continue
        n += 1
        lines += [f"## {n}. {c['name']}", f"filer SIC {c['filer_sic']} {c['filer_sic_description']}  |  draft note: {c.get('notes','')}",
                  "> " + re.sub(r"\s+", " ", c["description"])[:420] + " ...", ""]
        for key, label, _ in SYSTEMS:
            lines.append(f"### {label}")
            for code in c["acceptable"].get(key, []):
                lines.append(f"- [x] {code} {corp[key].get(code, '?').split(' > ')[-1]}   ({corp[key].get(code, '?')})")
            lines += ["- add: ", ""]
        lines += ["reviewed: no", ""]
    (HERE / "review.md").write_text("\n".join(lines) + "\n")
    print(f"wrote review.md ({n} companies)")


def apply(tmp):
    corp = corpora(tmp)
    path = HERE / "companies.json"
    data = json.loads(path.read_text())
    by = {c["name"]: c for c in data["companies"]}
    text = (HERE / "review.md").read_text()
    blocks = re.split(r"^## \d+\. ", text, flags=re.M)[1:]
    errors, changes = [], []
    for b in blocks:
        name = b.splitlines()[0].strip()
        if name not in by:
            errors.append(f"unknown company: {name}"); continue
        rec, new = by[name], {}
        system = None
        for line in b.splitlines():
            m = re.match(r"### (.+)", line)
            if m:
                system = next((k for k, l, _ in SYSTEMS if l == m.group(1).strip()), None); new.setdefault(system, [])
                continue
            if system is None:
                continue
            m = re.match(r"- \[(x| )\] (\S+) ", line)
            if m and m.group(1) == "x":
                new[system].append(m.group(2))
            m = re.match(r"- add:\s*(.*)$", line)
            if m and m.group(1).strip():
                for code in re.split(r"[,\s]+", m.group(1).strip()):
                    if code in corp[system]:
                        new[system].append(code)
                    else:
                        errors.append(f"{name}: {system} code {code!r} is not in the corpus")
        done = re.search(r"^reviewed:\s*(yes|no)", b, flags=re.M)
        for k, v in new.items():
            v = list(dict.fromkeys(v))
            if v != rec["acceptable"].get(k, []):
                changes.append(f"{name}: {k} {rec['acceptable'].get(k, [])} -> {v}")
            rec["acceptable"][k] = v
        if done and done.group(1) == "yes":
            rec["labels_status"] = "reviewed"
    if errors:
        print("NOT WRITTEN, fix these first:\n  " + "\n  ".join(errors)); sys.exit(1)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print(f"applied. {len(changes)} code-list changes; reviewed: {sum(1 for c in data['companies'] if c.get('labels_status')=='reviewed')}")
    print("\n".join("  " + c for c in changes))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] in ("make", "apply"):
        {"make": make, "apply": apply}[sys.argv[1]](sys.argv[2])
    else:
        print(__doc__); sys.exit(2)
