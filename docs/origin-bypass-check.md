# Does a client-set `Origin` or `Referer` skip the rate limit? A check for the cluster administrator

Status: **the bypass was closed in the code on 2026-10-16** (a trusted `Origin` or `Referer` now gets the standard tier, 6,000 a minute per address on staging, instead of no limit). On a build from before that change the check reports the bypass; on a build with it, the expected result is **CLOSED**: run it against staging after the new image is deployed, and again against production after the cutover. It changes nothing on the cluster and sends about 10,000 lookups in a minute from the machine it runs on.

## What is being checked

The service limits lookups per caller address (6,000 a minute, burst 600 on staging). It deliberately does **not** limit a lookup that carries a trusted `Origin` header (or, with no `Origin`, a trusted `Referer`): the first-party web sites (`mediumroast.io` and its subdomains) and local development origins (`localhost`, `127.0.0.1`, `::1`).
Only the host is compared, so `mediumroast.io.evil.example` is not trusted. But the header is set by the caller, so **anyone who sends one of these headers is not limited**. The SQL route ignores the headers. The rule is in `v4/crates/server/src/trusted_origin.rs`.

For the event this means: a team's browser app running on `localhost` is never limited, and any caller who sends `Origin: https://mediumroast.io` skips the limit. The pods' capacity (about 2,100 lookups a second) is then the only limit for them.

## Run it (one command, any machine with Python 3.10 or newer)

```
git clone https://github.com/miha42-github/company_dns.git && cd company_dns
python3 perf_tests/origin_check.py
```

It sends the same flood of lookups seven ways, one after another with a 12-second pause for the allowance to refill, and prints a table:

| header sent | what it is | expected today |
|---|---|---|
| none | the baseline | limited (`429`s) |
| `Origin: https://mediumroast.io` | a first-party site | **not limited** |
| `Origin: https://app.mediumroast.io` | a first-party subdomain | **not limited** |
| `Referer: https://mediumroast.io/page` | a first-party page | **not limited** |
| `Origin: http://localhost:3000` | a web app on a developer's machine | **not limited** |
| `Origin: https://partner.example` | another site | limited |
| `Origin: https://mediumroast.io.evil.example` | a host that only contains the name | limited |

The last line prints **BYPASS PRESENT** (with the headers that skip the limit) or **CLOSED**. If the baseline is not limited it says it cannot judge. Against the real service code on 2026-10-15, with the staging settings, it reported the bypass for the first four headers and limited the last two.

For a different URL (a service you operate), add `--allow-other-url`; for the staging service from a machine whose DNS does not reach it, `--connect-to <ingress-address>`.

## A check without the repository

Two commands from one machine, the second straight after the first (the first uses up the allowance; the second should still be answered):

```
seq 1 1500 | xargs -P 40 -I{} curl -s -o /dev/null -w "%{http_code}\n" -A "check/1.0 (you@example.org)" https://company-dns-staging.mediumroast.io/V4.0/na/sic/code/3571 | sort | uniq -c
seq 1 1500 | xargs -P 40 -I{} curl -s -o /dev/null -w "%{http_code}\n" -A "check/1.0 (you@example.org)" -H "Origin: https://mediumroast.io" https://company-dns-staging.mediumroast.io/V4.0/na/sic/code/3571 | sort | uniq -c
```

The first shows hundreds of `429`; the second, with the header, shows only `200`s while the bypass exists.

## After a fix

If the trusted headers are changed so they no longer skip the limit, confirm with:

```
python3 perf_tests/origin_check.py --expect closed
```

It exits with status 1 if any header still skips the limit (status 3 if it cannot judge), so it can be used in a script.

## What was decided (2026-10-16)

The first-party web pages cannot hold credentials or set a contact `User-Agent`, so they cannot simply lose the exemption: V4's own `/ui/` and the `html/` app would become anonymous callers (5 a minute by default). Instead of no limit, a trusted `Origin` or `Referer` now earns the **standard tier**: the pages keep working, and anyone forging the header gets no more than a contact in their `User-Agent` already gives. Credentials are looked at first: a profile's own grant applies, and a wrong credential is a `401`. The SQL route never honoured the headers. Making the trusted origins a setting for outside deployments remains on the debt list in `v4/README.md`.
