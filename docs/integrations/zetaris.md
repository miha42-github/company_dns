# Using company_dns from Zetaris AI Data Harness

How to load the company_dns industry classifications (US SIC, EU NACE, Japan SIC) into [Zetaris AI Data Harness](https://zetaris.github.io/getting-started) as SQL tables, what to know about the service while you do it, and what to expect at a hackathon where many teams do the same thing. The worked SQL lives in Zetaris's own repository; this page is the service's side of it: what the endpoints return, why the examples are written the way they are, and what can go wrong.

- **Zetaris's worked examples** (SQL for the Zetaris REST tables, in their repository): [`open_data/rest_apis/sql/rate_limited`](https://github.com/zetaris/getting-started/tree/main/open_data/rest_apis/sql/rate_limited), the files `12_company_dns_*` (US SIC, both service versions side by side), `13_company_dns_eu_nace_*` and `14_company_dns_japan_*`, each a `_create.sql` (load the data) and a `_select.sql` (example queries). Their REST cookbook is [`open_data/rest_apis/HOWTO`](https://zetaris.github.io/getting-started/open_data/rest_apis/HOWTO.html). Zetaris owns and updates those files; this repository links to them and does not copy them.
- **The service's own guide:** [using-the-api.md](../using-the-api.md).

Checked against the V4 staging service on 16 October 2026 (the row counts and sizes below were measured that day). The Zetaris scripts were recorded by Zetaris as run end to end on 11 October 2026.

## Before you run anything: set a real `User-Agent`

The Zetaris scripts send `user-agent "YOUR_APP_NAME YOUR_CONTACT_EMAIL"` and tell you to replace it. **Do replace it, with a real contact, such as `MyTeam/1.0 (you@example.org)`.** The service gives the standard limit only to a `User-Agent` that contains an e-mail address or a URL (`@`, `http://` or `https://`). The placeholder has neither, so it is treated as an unidentified caller and gets the strictest limit: by default 5 a minute with a burst of 1. In a test on 16 October a client sending the placeholder text got about a dozen answers and then `429`s (`Retry-After` about a minute, and a message that says to set a self-identifying `User-Agent`).

As of 16 October 2026 the placeholder is still what Zetaris's scripts carry, so every team has to make this change itself (or Zetaris has to change the default).

How to set it: put the real value in the three `HEADER (user-agent "...")` lines, or run the scripts with Zetaris's `scripts/run_sql.py`, which fills it in from the `ZETARIS_USER_AGENT` environment variable.

| The `User-Agent` | What the service does with it |
|---|---|
| missing, empty, a library default (`curl/...`, `python-requests/...`) or no way to reach you (the placeholder) | strictest limit (default 5 a minute, burst 1) |
| contains an e-mail address or a URL | standard limit (the staging service is set to 6,000 a minute with a burst of 600 **per client address**; the built-in default is 200 a minute with a burst of 20) |
| HTTP Basic credentials for a profile | what the profile was granted; only the operator can issue one |

## The three data sets

Each is one request, with `%25` (an encoded `%`) as the query so that every row comes back. Responses have the same envelope for all three: `{code, message, module, data, dependencies, total}`, where `data` is a **flat array** of objects with eight string fields and `total` is its length. Counts and sizes measured on staging:

| Data set | Request path | Rows | Response size | Levels (and how many of each) |
|---|---|---|---|---|
| US SIC | `/V4.0/na/sic/code/%25` | 1,005 | about 271 KB | section (a letter, 10), division (2 digits, 83), group (3 digits, 416), class (the 4-digit code, 1,005) |
| EU NACE Rev. 2 | `/V4.0/eu/sic/class/%25` | 615 | about 189 KB | section (letters A to U, 21), division (88), group (272), class (dotted, such as `01.11`, 615) |
| Japan SIC (JSIC Rev. 13) | `/V4.0/japan/sic/industry_group/%25` | 1,460 | about 420 KB | section (letters A to T, 20), division (99), group (530), class (4 digits, 1,460) |

Every row carries its full rollup: `section_id`, `section_desc`, `division_id`, `division_desc`, `group_id`, `group_desc`, `class_id`, `class_desc`. In Zetaris terms, a REST table over such a response is flattened with one `LATERAL VIEW explode(data) AS item` and a select of `item.<field>`; no JSON coercion is needed, which is what makes V4 simpler than V3 for this (V3's US answer was a dictionary keyed by code and needed `from_json(to_json(...))` to explode).

## Facts the Zetaris scripts ask the maintainer to confirm

- **Revisions.** The EU data is **NACE Rev. 2**; the Japan data is **JSIC Rev. 13** (the 2013 revision). The responses themselves do not say so; the repository's [data sources table](../../README.md#data-sources-and-terms) does.
- **`sic` in the path.** `/V4.0/eu/sic/...` and `/V4.0/japan/sic/...` use `sic` as the name of the route family (the original service was US SIC first), not as a claim that the data is US SIC. Do not join NACE or Japan codes to US SIC codes: the formats or meanings differ (NACE class codes are dotted; Japan's four-digit codes are not US SIC codes).
- **The `%` wildcard is supported, not an accident.** Code and description lookups match with a case-insensitive `LIKE` (`ILIKE`), the same fuzzy matching V3 had, so `%` matches everything. It is documented in [using-the-api.md](../using-the-api.md#fetching-a-whole-classification-in-one-request).
- **The path segment chooses the level returned.** For `%` it selects how many rows you get, and each row still carries its parents:

  | Segment | US SIC | EU NACE | Japan SIC |
  |---|---|---|---|
  | the top letter level | `division` (10) | `section` (21) | `division` (20) |
  | the 2-digit level | `major` (83) | `division` (88) | `major_group` (99) |
  | the 3-digit or dotted group level | `industry` (416) | `group` (272) | `group` (530) |
  | the finest (class) level | `code` (1,005) | `class` (615) | `industry_group` (1,460) |

  The Japan example uses `industry_group` because, in Japan's naming, that is the finest level; it returns classes, as Zetaris saw ("1460 class matches"). There is no `/class/` segment for Japan (it is a `404`). A coarser level is a smaller download (the Japan `division` segment returns 20 rows). `description` also returns class rows for the US and EU data (1,005 and 615 for `%`).
- **Level names changed between V3 and V4 for US SIC.** V3 called the top letter level `division` and the 2-digit level `major_group`; V4 calls them section and division. The same word, `division_desc`, therefore means a different level in the two versions: a V3-style `WHERE division_desc LIKE '%Manufacturing%'` returns nothing against V4 data. The Zetaris US SIC script builds views that map the names both ways (`sic_codes_v4_compat_table` gives V4 data under V3 names), so queries written for V3 keep running. The mapping:

  | Level | V3 field | V4 field |
  |---|---|---|
  | letter | `division`, `division_desc` | `section_id`, `section_desc` |
  | 2 digits | `major_group`, `major_group_desc` | `division_id`, `division_desc` |
  | 3 digits | `industry_group`, `industry_group_desc` | `group_id`, `group_desc` |
  | 4 digits | `sic_code`, `description` | `class_id`, `class_desc` |

## Which host to use

The Zetaris scripts point at the V4 **staging** host and, for the US data, also at the V3 production host. Use whichever host your operator tells you is the one for the event. When V4 replaces V3 on the production host, the `/V3.0/` paths there are answered by V4 in V3's shape (with one extra field, `total`), so a script that loads `/V3.0/na/sic/code/%25` keeps working unchanged, and only the host in the `/V4.0/` scripts changes. Everything else in the scripts stays as it is.

## Rate limits, caching and many teams at once

- **Cache on the Zetaris side.** A Zetaris REST table fetches again on every query unless it is cached, so the `CACHE TABLE` statements in the scripts are required. Each data set is then fetched once. Run the scripts once, one statement at a time; do not put them in a loop.
- **How many requests that is.** One team loading all three data sets sends about six requests (three fetches and three cache fetches), more if Zetaris retries a failed fetch. Against the standard limit (100 a second per address, after a burst of 600) that is nothing, even for hundreds of teams.
- **The limit is per client address, and that address is where Zetaris makes the request from.** A Zetaris instance fetches the endpoints itself. If every team's instance runs on one shared cluster (a managed service, a venue network), all of them arrive from **one address** and share one allowance. That is fine at the standard limit, and it is exactly why the `User-Agent` matters most: **if the placeholder is left in, all those teams share the strictest limit, a few requests a minute in total, and most will see `429`s.** Check this first when a group of teams reports `429`.
- **If you do get a `429`:** wait at least the number of seconds in the `Retry-After` header (the Zetaris scripts say 60) and retry that one statement. Do not retry in a loop.
- **Pacing.** The scripts say to wait 15 seconds between statements that call the service. That is safe at any tier; at the standard limit it is more careful than it needs to be.
- **What the pods carry.** On the 20-pod staging service, the ceiling measured on 14 and 16 October is about 2,100 single-code lookups a second, with no errors until far beyond that; see [performance-report.md](../performance-report.md). A full-classification fetch is heavier than one lookup (it returns up to 420 KB), but a few hundred of them, spread over minutes, are small next to that.

## Licensing and credit

company_dns is Apache 2.0. The classification content has its own terms: US SIC is a US Government work; the EU NACE data is from Eurostat and the Japan data from e-Stat (Japan), both CC BY 4.0, so credit them when you reuse the data (the links are in the [data sources table](../../README.md#data-sources-and-terms)). Query the service live rather than bulk-redistributing the extracted data.

## When something goes wrong

| What you see | Likely cause | What to do |
|---|---|---|
| `429` on the first statements | the `User-Agent` is the placeholder, empty or a library default | set a real contact in the header and wait out `Retry-After` |
| `429` after several statements in a row | too many requests close together (the burst) | wait 60 seconds, then retry one statement at a time |
| `404` with `total: 0` and the text "No route matches this path" | a wrong path segment (for example `/japan/sic/class/` or `/eu/sic/code/`) | use the segments in the table above |
| a `404` with `total: 0` on a lookup, not a route error | nothing matched that code | not an error: an empty result |
| zero rows in a view | the explode ran on the wrong field | the data is `data` (an array), not `data.sics` (V3's dictionary) |
| a query on `division_desc` returns the wrong level | V3 and V4 name the levels differently | use the view whose names match your query (see above) |
| `5xx` or a timeout | a problem on the service side | retry later; tell the operator if it persists |

To check the service independently of Zetaris, run one request and compare the count with the table above (use your own `User-Agent`):

```bash
curl -s -A "MyTeam/1.0 (you@example.org)" "<service-url>/V4.0/eu/sic/class/%25" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['total'], len(d['data']))"
```

## What this page does not cover

- How Zetaris AI Data Harness behaves on its side (its REST tables, caching, views and USL models); that is in Zetaris's own documentation.
- The semantic and hybrid search routes, the Industry Match endpoint, the company (EDGAR) lookups and the SQL endpoint: none was tried through Zetaris. Semantic searches cost far more than lookups (see the performance report), so plan for a lower rate if you use them.
- Whether a Zetaris view reads the cached copy of a REST table or fetches again is a Zetaris question that Zetaris's own scripts list as unconfirmed; time the first `COUNT(*)` as they suggest.
