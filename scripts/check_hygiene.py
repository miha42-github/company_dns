#!/usr/bin/env python3
"""Open-source hygiene check: fail if tracked files contain what should not be public.

    python3 scripts/check_hygiene.py                 # check every tracked file
    python3 scripts/check_hygiene.py path ...        # check these files
    python3 scripts/check_hygiene.py --messages      # check every commit message on every branch and tag (the Git history clean-up)
    HYGIENE_DENYLIST=~/company_dns-private/denylist python3 scripts/check_hygiene.py

What it looks for (docs/plans/v4-documentation-update.md, DP2): IPv4 addresses (the ranges reserved for documentation, loopback and 0.0.0.0 are fine, and so is an
address that is clearly a version number or inside a lock file), host names under private suffixes (.local, .lan, .internal, .home.arpa), e-mail addresses other than the  # hygiene: allow
project's, personal home-directory paths, and secret-looking strings (tokens, private keys). A line can opt out with `hygiene: allow` in a comment, for the rare deliberate case (this file's tests).

The names of the lab's machines are NOT in this repository, so they cannot be in this script. Keep them in a file outside the repository, one term per line (`#` comments), and
name it in HYGIENE_DENYLIST: every term is matched case-insensitively as a whole word. The same file feeds the Git history clean-up. A term may contain `*`, which stands for any run
of letters, digits, dots and dashes (`10.20.30.*` is every address in that network, `*.corp.example` every host name under that domain), and a line that starts with `re:` is a regular
expression (`re:svc(42)?user`).
Exit status: 0 clean, 1 findings, 2 usage error.
"""
import ipaddress
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKIP_SUFFIXES = {".map", ".css", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".feather", ".parquet", ".db", ".woff", ".woff2", ".ttf", ".onnx", ".gz", ".zip", ".svg"}
SKIP_NAMES = {"Cargo.lock", "package-lock.json", "redoc.standalone.js"}  # vendored third-party files are not ours to edit
WELL_KNOWN_PUBLIC = {"1.1.1.1", "1.0.0.1", "8.8.8.8", "8.8.4.4", "9.9.9.9"}  # public DNS resolvers, named in text
ALLOWED_EMAILS = {"hello@mediumroast.io", "michael.hay@mediumroast.io", "noreply@anthropic.com", "noreply@github.com"}
ALLOWED_EMAIL_DOMAINS = ("example", "example.com", "example.org", "example.net", "example.invalid", "users.noreply.github.com")
ALLOWED_EMAILS = ALLOWED_EMAILS | {"git@github.com"}  # the GitHub SSH user
DOC_NETS = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]

IPV4 = re.compile(r"(?<![\w.])(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?![\w]|\.\d)")
PRIVATE_HOST = re.compile(r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:local|lan|internal|home\.arpa)\b", re.I)
HOME_PATH = re.compile(r"(?:/Users|/home)/(?!user\b|you\b|me\b|name\b|runner\b|node\b|app\b)[A-Za-z][A-Za-z0-9._-]+/")  # a person's home directory
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b")
SECRETS = [("a GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
           ("a private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----")),
           ("an AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
           ("a Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}\b"))]


def ip_finding(text: str) -> str | None:
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return None  # not an address (a version number such as 1.2.3.999)
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast or text in WELL_KNOWN_PUBLIC or any(ip in n for n in DOC_NETS):
        return None
    if ip.is_private or ip.is_link_local:
        return f"a private address ({text})"
    return f"an IP address ({text})"


def term_pattern(line: str) -> re.Pattern:
    """One deny-list line as a pattern: `re:...` is a regular expression; otherwise a literal, whole-word term in which `*` stands for any run of letters, digits, dots and dashes."""
    if line.startswith("re:"):
        return re.compile(line[3:], re.I)
    body = "[A-Za-z0-9._-]*".join(re.escape(part) for part in line.split("*"))
    return re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", re.I)


def load_denylist(path: str | None) -> list[re.Pattern]:
    if not path:
        return []
    terms = []
    for line in Path(path).expanduser().read_text().splitlines():
        line = line.split("#", 1)[0].strip() if not line.lstrip().startswith("re:") else line.strip()
        if line:
            terms.append(term_pattern(line))
    return terms


def scan_text(name: str, text: str, denylist: list[re.Pattern]) -> list[tuple[str, int, str]]:
    findings = []
    for n, line in enumerate(text.splitlines(), 1):
        if "hygiene: allow" in line:
            continue
        for m in IPV4.finditer(line):
            what = ip_finding(m.group(1))
            if what:
                findings.append((name, n, what))
        for m in PRIVATE_HOST.finditer(line):
            findings.append((name, n, f"an internal-looking host name ({m.group(0)})"))
        for m in HOME_PATH.finditer(line):
            findings.append((name, n, f"a personal home-directory path ({m.group(0)})"))
        for m in EMAIL.finditer(line):
            e = m.group(0).lower()
            domain = e.split("@")[1]
            if e not in ALLOWED_EMAILS and not any(domain == d or domain.endswith("." + d) for d in ALLOWED_EMAIL_DOMAINS):
                findings.append((name, n, f"an e-mail address ({m.group(0)})"))
        for label, rx in SECRETS:
            if rx.search(line):
                findings.append((name, n, f"{label}"))
        for rx in denylist:
            if rx.search(line):
                findings.append((name, n, "a term from the private deny-list"))
    return findings


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "-z"], capture_output=True, check=True).stdout.decode()
    return [f for f in out.split("\0") if f]


def scan_files(paths: list[str], denylist: list[re.Pattern]) -> list[tuple[str, int, str]]:
    findings = []
    for rel in paths:
        p = (REPO_ROOT / rel) if not os.path.isabs(rel) else Path(rel)
        if p.suffix.lower() in SKIP_SUFFIXES or p.name in SKIP_NAMES or not p.is_file():
            continue
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:4096]:
            continue  # binary
        findings += scan_text(rel, data.decode("utf-8", "replace"), denylist)
    return findings


def scan_messages(denylist: list[re.Pattern]) -> list[tuple[str, int, str]]:
    """Commit messages on every ref: the part of the history a file check cannot see."""
    out = subprocess.run(["git", "-C", str(REPO_ROOT), "log", "--all", "--format=%H%x00%B%x01"], capture_output=True, check=True).stdout.decode("utf-8", "replace")
    findings = []
    for entry in out.split("\x01"):
        sha, _, body = entry.strip("\n").partition("\x00")
        if sha:
            findings += [(f"commit {sha[:10]}", n, what) for _, n, what in scan_text("", body, denylist)]
    return findings


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    messages = "--messages" in args
    args = [a for a in args if a != "--messages"]
    try:
        denylist = load_denylist(os.environ.get("HYGIENE_DENYLIST"))
    except OSError as e:
        print(f"cannot read HYGIENE_DENYLIST: {e}", file=sys.stderr)
        return 2
    paths = args or tracked_files()
    findings = scan_messages(denylist) if messages else scan_files(paths, denylist)
    for name, n, what in findings:
        print(f"{name}:{n}: {what}")
    if findings:
        print(f"\n{len(findings)} finding(s). Replace addresses and names with placeholders (<traefik-lan-ip>, <public-ip>, <build-node>) or the documentation ranges "
              "(192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24); a deliberate exception takes `hygiene: allow` in a comment on the line.", file=sys.stderr)
        return 1
    note = "" if denylist else " (no HYGIENE_DENYLIST: lab-specific names were not checked)"
    print(f"clean: {'every commit message' if messages else str(len(paths)) + ' files'} checked{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
