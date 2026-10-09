#!/usr/bin/env python3
"""Build companies_pool.json: description snapshots plus the filer-reported SEC SIC.

    python3 build_dataset.py <base_url> [names.txt]    # stdlib only; server must be running

For each company name: the Wikipedia description and CIK come from the running
V4 server (`/V4.0/global/company/wikipedia/firmographics/{name}`), and the SIC
code the company filed under comes from the SEC's public submissions API
(data.sec.gov), NOT from memory. Descriptions are snapshotted so runs are
repeatable; they are Wikipedia text (CC BY-SA), kept here for evaluation only.

select_set.py then picks the evaluation set (companies.json) from the pool.
Existing records keep their hand-judged `acceptable` and `notes` fields: this
script only refreshes description/cik/filer_sic, never your labels.
See docs/plans/company-sic-match.md section 8.
"""
import json, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "companies_pool.json"
UA = "company-sic-eval/1.0 (michael.hay@mediumroast.io)"
DEFAULT_NAMES = HERE / "names.txt"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            return json.load(urllib.request.urlopen(req, timeout=60))
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 3:
                raise
            time.sleep(2 + 3 * attempt)  # rate limited: back off and retry


def main():
    base = sys.argv[1].rstrip("/")
    args = [a for a in sys.argv[2:] if not a.startswith("--")]
    names_file = Path(args[0]) if args else DEFAULT_NAMES
    names = [n.strip() for n in names_file.read_text().splitlines() if n.strip() and not n.startswith("#")]
    existing = {r["name"]: r for r in json.loads(OUT.read_text())["companies"]} if OUT.exists() else {}
    records = []
    for name in names:
        rec = existing.get(name, {"name": name, "acceptable": {}, "notes": ""})
        if rec.get("description") and rec.get("filer_sic") and "--refresh" not in sys.argv:
            records.append(rec)  # already built: reuse the snapshot (pass --refresh to refetch)
            continue
        try:
            w = (get(f"{base}/V4.0/global/company/wikipedia/firmographics/{urllib.parse.quote(name)}").get("data") or {})
        except Exception as e:
            print(f"  skip {name}: wikipedia lookup failed ({e})")
            continue
        desc, cik = w.get("description") or "", w.get("cik") or ""
        if not desc or not str(cik).isdigit():
            print(f"  skip {name}: no description or no CIK (cik={cik!r})")
            continue
        time.sleep(0.2)  # SEC asks for <= 10 requests/second
        try:
            sub = get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
        except Exception as e:
            print(f"  skip {name}: SEC submissions failed ({e})")
            continue
        rec.update(
            wikipedia_title=w.get("name") or name, cik=int(cik), description=desc,
            description_source="wikipedia", wikipedia_url=w.get("wikipediaURL"),
            filer_sic=str(sub.get("sic") or ""), filer_sic_description=sub.get("sicDescription") or "",
        )
        records.append(rec)
        print(f"  {name:36s} cik={int(cik):>8d}  sic={rec['filer_sic']}  {rec['filer_sic_description']}")
    OUT.write_text(json.dumps({"format": 1, "companies": records}, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {len(records)} companies to {OUT}")


if __name__ == "__main__":
    main()
