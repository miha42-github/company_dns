# Soak test guide: running `perf_tests/soak.py` from outside the network

For whoever runs the load test from their own network (home, office or a cloud machine) against the staging service. It sends only `GET` requests, changes nothing
on the server, and writes its numbers to disk as it goes, so you can send us the results afterwards. Staging is
`https://company-dns-staging.mediumroast.io` (public).

## What you need

- Python **3.10 or newer** (`python3 --version`). Nothing to install: the script uses only the standard library.
- The repository: `git clone https://github.com/miha42-github/company_dns.git` (public), then `cd company_dns`. Use the `main` branch.
- A machine that stays awake and online for the whole run (a laptop must not sleep: on macOS `caffeinate -i python3 ...`; on Linux run it in `tmux` or `screen`). Turn off any VPN
  unless the test is meant to include it.
- Optional, from the owner (never in the repository, chat logs or a command line): a profile token with no rate limit, as `PROFILE:TOKEN`.

## 1. A short trial first (about 2 minutes)

```bash
python3 perf_tests/soak.py --label your-name-where --hours 0.03 --window 10 --steps 2,4 --step-minutes 0.3 --hold-concurrency 4 --out ./soak-trial
```

It should print one line every ten seconds ending `canaries 5/5 ... ok`, then a summary that starts `# Soak test: PASS`. If it prints `cannot start`, the message says what to change.
If every request errors, check that `https://company-dns-staging.mediumroast.io/health` opens in a browser from the same machine.

## 2. The soak run (24 hours)

Without credentials, each address gets a standard quota (a per-minute rate and a burst; the owner has the figures); `--rps` keeps the test under it so the numbers measure
the service, not the quota:

```bash
python3 perf_tests/soak.py --label your-name-where --hours 24 --rps 60 --out ./soak-24h
```

It ramps through 4, 8, 16 and 32 concurrent requests (ten minutes each), then holds 16 until 24 hours are up. A line is printed, and a row is written to `windows.csv`, every minute.

## 3. A capacity ramp with credentials (about 2 hours)

Only when the owner has agreed a time (the staging cluster shares machines with other services) and has given you a token:

```bash
export SOAK_AUTH='PROFILE:TOKEN'
python3 perf_tests/soak.py --label your-name-where --hours 2 --steps 8,16,32,64 --step-minutes 15 --hold-concurrency 32 --out ./soak-capacity
```

The token profile has no rate limit, so this measures the service. To include the embedding searches (the heaviest routes) add `--mix mixed`; do that only in a run agreed with the owner.

## While it runs, and when it stops

- `summary.md` in the output directory is rewritten after every window: open it any time to see how it is going. `Ctrl-C` stops cleanly and writes the summary of what ran.
- A window "misses the bar" if its error rate is above 1%, its p95 latency above 2 seconds (that includes your network), or a **canary** is wrong. The canaries are five fixed
  questions with known answers (health, US SIC by code on the V4 and V3 paths, an EU NACE class, a Japan SIC industry group) asked every window; they catch a service that is fast but wrong.
- `429` answers mean the per-address quota was exceeded. They are counted apart from errors; lower `--rps`.
- The run **stops early** if the server refuses the credentials (401/403 to nearly everything). That is a configuration problem, not a result.
- The exit code is 0 for PASS, 1 for FAIL, 2 for a stop on refused credentials, 130 for Ctrl-C.

## What to send back

The whole output directory (`windows.csv`, `windows.jsonl`, `canaries.jsonl`, `meta.json`, `summary.md`), zipped, plus a line on anything odd on your side (a network outage, a laptop that slept,
a VPN). `meta.json` records the Python and operating system versions. It contains no credentials and no addresses.

Please do not change the server, run other load tools at the same time, or share the token.
