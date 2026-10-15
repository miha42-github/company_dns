# Git history clean-up: a runbook (an action for the repository owner)

Status: **NOT DONE. Written 2026-10-12; run it in a quiet window (not 22 to 25 October; the plan recommends from 26 October).**
Owner: michael.hay@mediumroast.io
Why: earlier commit messages (and possibly older file versions) mention the names of the lab's machines and a private address. The working tree is clean and guarded
(`scripts/check_hygiene.py`, `docs/plans/v4-documentation-update.md` DP2), but anyone can still read the history. `python3 scripts/check_hygiene.py --messages` lists the commit
messages with findings; with a private deny-list (below) it also finds the machine names.

**This rewrites history. Every clone, fork and open branch is affected, and commit hashes change.** Nothing here is reversible once force-pushed except from the backup of step 1.

## 0. Before you start

1. **Choose the window:** no open pull requests (merge or close them), no deploy or event in progress, and tell everyone who has a clone (the remote soak tester, the platform partner, forks) that they will have to re-clone.
2. **Keep the private list outside the repository.** A file such as `~/company_dns-private/denylist` (one term per line, `#` comments) with the machine names and any other terms. A term may use `*` for "any run of letters, digits, dots and dashes" (`10.20.30.*` for every address in a network, `*.corp.example` for every host under a domain), and a line starting with `re:` is a regular expression (`re:svc(42)?user`); `scripts/check_hygiene.py` explains the format. It must never be committed. Also make
   `~/company_dns-private/replacements.txt` for the rewrite, one rule per line in `old==>new` form, for example `<name>==><build-node>` and the private address `==><private-address>`.
3. **Install `git-filter-repo`** (`brew install git-filter-repo`, or from its repository). Check `git filter-repo --version`.

## 1. Back up

```bash
git clone --mirror https://github.com/miha42-github/company_dns.git ~/company_dns-private/company_dns-backup.git
```

Keep it until the rewrite has been verified and a month has passed.

## 2. Measure

In a **fresh** clone (never your working checkout):

```bash
git clone https://github.com/miha42-github/company_dns.git company_dns-rewrite && cd company_dns-rewrite
HYGIENE_DENYLIST=~/company_dns-private/denylist python3 scripts/check_hygiene.py --messages     # the messages
HYGIENE_DENYLIST=~/company_dns-private/denylist python3 scripts/check_hygiene.py --history   # every line ever added to a file, with the same list (add --verbose for one line per finding)
```

Also run a secret scanner over the whole history (for example `gitleaks detect --source . --log-opts="--all"`) and record what it finds; a found secret must be **rotated**, not just removed.

## 3. Rewrite

```bash
git filter-repo --replace-text ~/company_dns-private/replacements.txt --replace-message ~/company_dns-private/replacements.txt
```

`git filter-repo` removes the `origin` remote on purpose. Save the old-to-new commit map it writes (`.git/filter-repo/commit-map`) outside the repository: plans, the build log (`v4/.build-log`) and image labels quote old hashes.

## 4. Verify before pushing

```bash
HYGIENE_DENYLIST=~/company_dns-private/denylist python3 scripts/check_hygiene.py --messages
HYGIENE_DENYLIST=~/company_dns-private/denylist python3 scripts/check_hygiene.py --history
python3 scripts/check_hygiene.py
cd v4 && cargo test --workspace            # the code still builds and passes
```

Everything must come back clean. Compare file contents of `HEAD` with the backup's `HEAD` (`git diff` between the two checkouts should show only the replaced text).

## 5. Push

```bash
git remote add origin https://github.com/miha42-github/company_dns.git
git push --force --all origin
git push --force --tags origin
```

If branch protection blocks the force-push, lift it for the push only, then restore it. GitHub keeps the old commits reachable by hash and in pull-request views for a while: open a support request
asking GitHub to remove cached views and run garbage collection if the old messages must disappear, and delete the old pull-request refs if possible.

## 6. Afterwards

- Everyone re-clones (do not merge the old history into the new).
- Add the old-to-new commit map to the maintainers' area; update the commit hashes quoted in `docs/` where they matter (the staging build tags name a commit: record the mapping).
- GHCR images are unaffected; their labels quote old hashes, which is fine, but note the mapping.
- Record the date of the rewrite in `docs/plans/v4-documentation-update.md` (DP2) and mark this runbook done.
