#!/usr/bin/env python3
"""Fetch the classification data files (the Mediumroast SIC feather files) from a directory or a URL.

    python3 v4/scripts/fetch_data.py --source dir:/path/to/files   --out ./data
    python3 v4/scripts/fetch_data.py --source url:https://host/dir/ --out ./data [--header-file FILE]

This is the stub for the data-supply step (docs/plans/v4-release-to-staging.md, "Data supply"). It does not wait for a CI workflow:
the Docker build, a developer and a node all call the same script. Standard library only.

A source is `dir:PATH` (a local directory, for example a mounted share or a build context) or `url:BASE` (files are fetched
from BASE/<name> over HTTP or HTTPS; `file:` URLs also work). The files come from the manifest (`--manifest`, default
`v4/data-manifest.json`) or, with no manifest, `--files`. When the manifest lists a SHA-256 the file is verified and a
mismatch fails the run (`--no-verify` skips that). A header file (one `Name: value` line, for example `Authorization: Bearer ...`)
adds authentication to URL fetches; in a Docker build pass it as a BuildKit secret, never as an argument or a layer.

The delivery location from Mediumroast is not decided yet (v4-deployment.md section 3.2, point 3), so there is no default URL:
`--source` is required. This script only moves files and checks their hashes; `docs/plans/research/check_ic_feather.py` still
validates what is inside them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_FILES = [
    "us_flat_embedded.feather",
    "japan_rev13_flat_embedded.feather",
    "nace_rev2_flat_embedded.feather",
    "isic_rev4_flat_embedded.feather",
]
DEFAULT_MANIFEST = Path(__file__).resolve().parent.parent / "data-manifest.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch_url(base: str, name: str, dest: Path, header: str | None, retries: int = 3) -> None:
    url = base.rstrip("/") + "/" + name
    req = urllib.request.Request(url, headers={"User-Agent": "company_dns-fetch-data/1.0"})
    if header:
        k, _, v = header.partition(":")
        req.add_header(k.strip(), v.strip())
    last = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as out:
                shutil.copyfileobj(r, out)
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
            print(f"  attempt {attempt}/{retries} failed for {name}: {e}", file=sys.stderr)
    raise SystemExit(f"could not fetch {url}: {last}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True, help="dir:PATH or url:BASE")
    ap.add_argument("--out", required=True, help="directory to write the files to")
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="JSON manifest with sha256 per file (default: v4/data-manifest.json)")
    ap.add_argument("--files", nargs="+", help="file names, used when there is no manifest")
    ap.add_argument("--header-file", help="a file holding one 'Name: value' header line for URL fetches")
    ap.add_argument("--no-verify", action="store_true", help="do not check SHA-256 against the manifest")
    a = ap.parse_args()

    kind, _, where = a.source.partition(":")
    if kind not in ("dir", "url") or not where:
        ap.error("--source must be dir:PATH or url:BASE")

    manifest = {}
    mpath = Path(a.manifest)
    if mpath.exists():
        manifest = json.loads(mpath.read_text()).get("files", {})
    names = a.files or (list(manifest) if manifest else DEFAULT_FILES)
    header = Path(a.header_file).read_text().strip() if a.header_file else None
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    failed = []
    for name in names:
        dest = out / name
        if kind == "dir":
            src = Path(where) / name
            if not src.is_file():
                print(f"MISSING {name} in {where}")
                failed.append(name)
                continue
            shutil.copyfile(src, dest)
        else:
            fetch_url(where, name, dest, header)
        want = manifest.get(name, {}).get("sha256")
        got = sha256(dest)
        if want and not a.no_verify and got != want:
            print(f"HASH MISMATCH {name}: expected {want[:12]}..., got {got[:12]}... (new delivery? update v4/data-manifest.json on purpose, or use --no-verify)")
            failed.append(name)
            dest.unlink()
            continue
        status = "verified" if want and not a.no_verify else "not verified (no manifest hash)"
        print(f"OK   {name}  {dest.stat().st_size} bytes  sha256={got[:12]}...  {status}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
