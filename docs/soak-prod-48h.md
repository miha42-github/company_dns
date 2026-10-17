# The 48-hour soak against production: instructions

For whoever runs the long stability test from outside the network (thank you). It sends only `GET` requests, changes nothing on the server, and writes its numbers to disk as it goes. Production is `https://company-dns.mediumroast.io` (public), now served by V4. The test needs no password or token.

**Please start it as soon as you can and let it run for 48 hours without stopping**, and in any case so that it ends before **22 October**: nothing should be running during the event, 22 to 25 October.

## What you need

- Python **3.10 or newer** (`python3 --version`). Nothing to install.
- A machine that stays awake and online for two days, on a stable connection, with any VPN turned off. On a Mac keep it awake with `caffeinate -i`; on Linux or Windows keep the session alive (on Linux, `tmux`).
- The repository, `main` branch, up to date:

```bash
git clone https://github.com/miha42-github/company_dns.git && cd company_dns
```

(If you already have it: `cd company_dns && git checkout main && git pull`.)

## 1. A two-minute trial

Replace `your-name-where` with who and where you are (no spaces), for example `john-home`:

```bash
python3 perf_tests/soak.py --url https://company-dns.mediumroast.io --label your-name-where --hours 0.03 --window 10 --steps 2,4 --step-minutes 0.3 --hold-concurrency 4 --out ./soak-trial
```

It should print a line every ten seconds ending `canaries 5/5 ... ok`, then a summary that starts `# Soak test: PASS`. If it says `cannot start`, the message says what to change. If every request fails, check that `https://company-dns.mediumroast.io/health` opens in a browser on the same machine.

## 2. The 48-hour run

On a Mac:

```bash
caffeinate -i python3 perf_tests/soak.py --url https://company-dns.mediumroast.io --label your-name-where --hours 48 --rps 60 --out ./soak-prod
```

On Linux or Windows, run the same command without `caffeinate -i` (on Linux inside `tmux`, so closing the terminal does not stop it):

```bash
python3 perf_tests/soak.py --url https://company-dns.mediumroast.io --label your-name-where --hours 48 --rps 60 --out ./soak-prod
```

It sends about 60 requests a second at most, ramps through four steps in the first 40 minutes, then holds steady until 48 hours are up. It prints a line every minute and writes the same to `soak-prod/windows.csv`.

## While it runs

- Open `soak-prod/summary.md` any time: it is rewritten after every minute-long window and shows how it is going.
- You do not need to watch it. If the machine sleeps, the network drops or the program stops, **please start it again with a different `--out` folder** (for example `./soak-prod-2`) and tell the owner what happened and when.
- `Ctrl-C` stops it cleanly and writes the summary of what ran.
- A line that says it missed the bar, or `429` answers, is worth a note to the owner but not a reason to stop.

## When it finishes

Zip the whole `soak-prod` folder and send it to the owner, with one line on anything odd on your side (an outage, a sleeping laptop, a VPN). The folder holds no passwords and no addresses.

Please do not run other load tools at the same time or change anything on the server. More detail is in [soak-test.md](soak-test.md).
