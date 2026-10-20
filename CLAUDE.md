# Working in this repository (instructions for Claude Code)

This file holds the rules the owner has set, most of them learned the hard way. Follow them without being reminded; when a rule and a request seem to conflict, say so and ask. Details live in the documents linked here, not in this file.

## What is here

- **V4, the service:** `v4/` (Rust: axum, DataFusion, ONNX Runtime). It answers V3's URLs and shapes. Settings and endpoints: [v4/README.md](v4/README.md).
- **V3, now source code only:** the Python at the repository root (`company_dns.py`, `lib/`, `html/`). It still runs in production as the standing rollback until about 26 October 2026, then it is retired (plan WP8).
- **Deployment:** `k8s/staging/` (V4 on staging), `k8s/prod-v4/` (V4 in production, beside V3), `k8s/prod/` (V3), `scripts/` (build, seal, hygiene, links). The production procedure is [docs/v4-production-runbook.md](docs/v4-production-runbook.md); its plan and status are [docs/plans/v4-production-cutover.md](docs/plans/v4-production-cutover.md).
- **Evidence:** `perf_tests/` (load, soak, ceiling, probes, reports), `api_tests/` (the contract suite), `docs/results/` (committed data and charts), [docs/performance-report.md](docs/performance-report.md).

## The repository is public: keep private things out

- **Never write** an IP address, an internal host name, a node name, a user name or home path, or an e-mail address (other than the project's) in any tracked file, commit message, PR title or body. Use placeholders (`<traefik-lan-ip>`, `<build-node>`, `<node-a>`) or compute the value in the command (for example from `kubectl`). The owner's GitHub account name on its own is fine.
- The private list of names to keep out lives **outside the repository** (`tmp/denylist`, which is gitignored). Never copy its contents into the repository, a commit message, a PR or memory. Never touch the private replacements file used for the history clean-up.
- Before every commit run, and fix what it reports:

```bash
HYGIENE_DENYLIST=<path to the private list> python3 scripts/check_hygiene.py
```

```bash
python3 scripts/check_links.py
```

- **No secrets, ever.** Credentials reach the cluster only as sealed secrets (`scripts/seal-secrets-v4.sh`); staging's and production's are separate and the script refuses to mix them. A token goes in an environment variable or to `curl` on its standard input (`-K -`), never on a command line, in a file in the repository, or in chat.

## Git and pull requests

- **The owner merges. You never merge a pull request.** Commit, push and open a PR when asked, or while working items already agreed. Branch from `origin/main`; avoid stacking PRs (rebuild a stacked one onto `main` by cherry-picking when its base merges).
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. PR descriptions end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- Never use a bare `git stash` (the stash is shared between worktrees); use a temporary commit. Delete branches only when asked, and only after checking their PRs are merged and their tips are in `main`.
- Write about people with they/them unless told otherwise.

## Production safety

- **Do not run anything against the cluster.** The development machine has no cluster context. Anything that touches staging or production is written as a runbook the owner runs on the build node, one command per step, with what to expect.
- **Promote, do not rebuild:** production runs the image tag that passed staging (same digest). The image is built once, by `scripts/build-and-deploy-v4.sh`.
- Never apply `k8s/prod/ingress.yaml` while V4 is live: it names V3's Service and would flip the traffic back.
- **Calendar:** the event is 22 to 25 October 2026, and the freeze starts on 21 October. No deploys and no load tests in that window unless a rollback trigger fires.

## Verify before you say it works

- Run the real thing. A change to the server's behaviour is not done until the API suite has run against a live server with the container smoke test's settings (see `v4/scripts/docker-smoke.sh`): unit tests alone missed a rate-limit change that throttled the whole suite.
- Any tool that talks to a network gets a test for the failure paths: unreachable, a server that never answers, wrong credentials. A tool that goes silent for twenty minutes is a bug.
- Do not guess a cause and present it as fact. Say what you observed, what you infer, and what would confirm it; retract a wrong claim at once and fix the documents that repeated it.
- Report what a number does not show (one run per cell, a known workload, a closed-loop generator) next to the number. Report failures as failures.

## How to write to the owner (chat)

- Step by step, each command in its own fenced block, with what to expect after it. Do not compress "repeat on all three machines" into one line; write each out.
- **Fill in real values in chat** (addresses are fine in chat, never in the repository). If a value is unknown, ask for it; do not leave a placeholder for the owner to finish.
- Shells: `zsh` on the Macs (for example `read -s "T?prompt: "`), `bash` on the build node. Use `tmux` for anything long.
- No tables for procedures. Do not ask the owner to compare clocks; line things up from the load itself.

## Commands

```bash
cd v4 && cargo test -p company-dns-server
```

```bash
python3 -m unittest k8s/test_staging_manifests.py k8s/test_prod_v4_manifests.py
```

```bash
python3 scripts/test_v4_scripts.py
```

```bash
python3 -m unittest discover -s perf_tests -p "test_*.py"
```

Charts and reports use `perf_tests/.venv` (matplotlib, gitignored): `perf_tests/.venv/bin/python perf_tests/report_runs.py ...`. The load tools are standard-library Python 3.10 or newer.

## Conventions

- Plans go in `docs/plans/` with the decisions and a recommendation first. Results go in `docs/results/<date>-<name>/` with a README saying what the files are; per-pod files are not committed.
- Numbers in documents are computed from committed data, and the documents say how to reproduce them.
- A rule you are told once should become a check or a line here, so it does not have to be repeated.
