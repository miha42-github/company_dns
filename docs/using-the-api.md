# Using the company_dns API

For developers calling a company_dns service (V4.0.0-pre, which also answers V3's URLs). Your operator gives you the service address; below it is written `<service-url>`.
Everything here is a `GET` unless it says otherwise. The service is read-only public classification and company data.

## Your first requests

Always send a `User-Agent` that says who you are and how to reach you (see "Identify yourself"):

```bash
UA='YourApp/1.0 (you@example.org)'
curl -s -A "$UA" '<service-url>/V4.0/na/sic/code/3571'              # US SIC, one class by its code
curl -s -A "$UA" '<service-url>/V4.0/na/sic/description/software'   # US SIC, search by words
curl -s -A "$UA" '<service-url>/V4.0/eu/sic/class/25.91'            # EU NACE Rev. 2
curl -s -A "$UA" '<service-url>/V4.0/japan/sic/industry_group/0911' # Japan SIC (JSIC Rev. 13)
```

The first returns:

```json
{
  "code": 200,
  "message": "1 SIC matches for [3571]",
  "module": "SicCatalog->find_by_code",
  "data": [{"section_id": "D", "section_desc": "Manufacturing", "division_id": "35", "division_desc": "Industrial And Commercial Machinery And Computer Equipment",
            "group_id": "357", "group_desc": "Computer And Office Equipment", "class_id": "3571", "class_desc": "Electronic Computers"}],
  "dependencies": {"modules": {"company_dns_v4": "https://github.com/miha42-github/company_dns"}},
  "total": 1
}
```

Every answer is this **envelope**: `code` (the same as the HTTP status), `message`, `data` (the results, or `null`), and a top-level **`total`**, the number of results in `data`. A search with no match is a `404` with
`total: 0` (a JSON envelope, not an error page); treat it as "nothing found", not as a failure.

## Which paths

- **`/V4.0/...`** answers in V4's shape: a list of matches, each with its parents (section, division, group, class). Use these for new work.
- **`/V3.0/...` and `/V2.0/...`** answer in V3's exact shape (a dictionary keyed by code), so an existing V3 integration keeps working. The only addition is the top-level `total`.
- The interactive documentation lists every route and its parameters: `<service-url>/docs` (Swagger UI), `/redoc`, and the raw `/openapi.json`. `<service-url>/` opens the web UI.

| Look up | Route |
|---|---|
| US SIC | `/V4.0/na/sic/{description,code,division,industry,major}/{query}` |
| EU NACE Rev. 2 | `/V4.0/eu/sic/{section,division,group,class,description}/{query}` |
| Japan SIC | `/V4.0/japan/sic/{division,major_group,group,industry_group,description}/{query}` |
| Companies (SEC EDGAR) | `/V4.0/na/companies/edgar/{ciks,detail,summary}/{company_name}` |
| Search across systems | `/V4.0/global/sic/...` (keyword, semantic and hybrid; see `/docs`) |

ISIC (`/V4.0/international/...`) is available but **its redistribution permission is pending and it may be removed**; do not build on it yet (see the repository README, "Data sources and terms").

## Identify yourself

The service limits requests **per client address**, and how much you get depends on whether it can tell who you are:

| You send | You get |
|---|---|
| no `User-Agent`, or a library default (`curl/...`, `python-requests/...`, `Go-http-client/...`) | the strictest limit (the built-in default is 5 a minute, burst of 1) |
| a `User-Agent` with a way to reach you (an e-mail address or a URL), for example `YourApp/1.0 (you@example.org)` | the standard limit (the built-in default is 200 a minute, burst of 20) |
| HTTP Basic credentials for a profile your operator issued | whatever the profile is granted: no limit, or a quota of its own |

The numbers are **settings of the deployment you use** and are often higher than the defaults above; ask your operator for the figures. Wrong credentials are a `401`, never treated as anonymous.

## Rate limits and `429`

The limit is a rate per minute plus a **burst allowance** (how many requests may arrive at once). It is shared across all the copies of the service, which each enforce their share, so keep your parallelism well below the burst:
a loop that fires 100 requests at once will get `429`s even if its average is low.

When you are over the limit you get `429` with a **`Retry-After`** header (seconds to wait). Wait that long, then retry. A small client that does this and caches what it learns:

```python
import json, time, urllib.error, urllib.parse, urllib.request

BASE = "<service-url>"                     # from your operator
UA = "YourApp/1.0 (you@example.org)"       # who you are
_cache = {}                                 # the classification data changes rarely: remember answers

def lookup(path, retries=5):
    if path in _cache:
        return _cache[path]
    for attempt in range(retries):
        req = urllib.request.Request(BASE + urllib.parse.quote(path, safe="/.:"), headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                _cache[path] = json.load(r)
                return _cache[path]
        except urllib.error.HTTPError as e:
            if e.code == 404:                                   # no match is an answer
                _cache[path] = json.load(e)
                return _cache[path]
            if e.code == 429:                                   # over the limit: wait as told
                time.sleep(int(e.headers.get("Retry-After", "1")) + attempt)
                continue
            raise
    raise RuntimeError(f"still rate limited after {retries} tries: {path}")

print(lookup("/V4.0/na/sic/code/3571")["data"][0]["class_desc"])
```

## Be a good neighbour

- **Cache on your side.** Industry-classification data changes rarely (the classifications are revised over years); the EDGAR catalog is refreshed quarterly. Ask once, keep the answer.
- **Look up codes, do not scan.** To list a classification, fetch its sections and divisions and walk down; do not request every code one by one.
- **Keep concurrency modest** (a handful of parallel requests), and back off when you see `429`s or `5xx`.
- **Do not send secrets in URLs.** Credentials go in the Basic `Authorization` header only.
- Semantic and hybrid searches (`similarity`, `hybrid`) cost far more computing than a code lookup; use them where they matter.

## Errors

| Status | Meaning |
|---|---|
| `200` | found; `data` holds the results |
| `404` | nothing matched (`total` is 0) |
| `401` | credentials sent but wrong |
| `429` | over the limit; wait `Retry-After` seconds |
| `5xx` | a problem on the service side or in an upstream source (SEC, Wikipedia); retry later and tell your operator if it persists |

## More

- Moving an existing V3 integration: [migrating-to-v4.md](migrating-to-v4.md).
- Running the service yourself, and every setting: [v4/README.md](../v4/README.md).
- Problems or questions: [GitHub issues](https://github.com/miha42-github/company_dns/issues).
