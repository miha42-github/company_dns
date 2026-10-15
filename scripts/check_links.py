#!/usr/bin/env python3
"""Check that every relative link in the repository's Markdown files points at a file that exists (standard library only).

    python3 scripts/check_links.py            # every tracked .md file
    python3 scripts/check_links.py FILE ...   # these files

Fenced code blocks are skipped (they hold commands and examples, not links); web links and in-page anchors are not checked. Exit status: 0 all resolve, 1 some do not.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"\]\(([^)\s]+)\)")
FENCE = re.compile(r"```.*?```", re.S)


def tracked_markdown() -> list[str]:
    out = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "-z", "*.md"], capture_output=True, check=True).stdout.decode()
    return [f for f in out.split("\0") if f]


def broken_links(rel: str, text: str | None = None) -> list[tuple[str, int, str]]:
    """(file, line, target) for each relative link in `rel` whose target does not exist."""
    p = Path(rel) if os.path.isabs(rel) else REPO_ROOT / rel
    text = p.read_text(errors="replace") if text is None else text
    text = FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)  # keep line numbers
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        for m in LINK.finditer(line):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path = target.split("#", 1)[0]
            if path and not (p.parent / path).resolve().exists():
                found.append((rel, n, target))
    return found


def main(argv=None) -> int:
    files = sys.argv[1:] if argv is None else argv
    files = files or tracked_markdown()
    bad = []
    for f in files:
        try:
            bad += broken_links(f)
        except OSError:
            continue
    for f, n, t in bad:
        print(f"{f}:{n}: the link {t} does not resolve")
    print(f"{len(bad)} broken link(s) in {len(files)} files" if bad else f"clean: {len(files)} Markdown files checked")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
