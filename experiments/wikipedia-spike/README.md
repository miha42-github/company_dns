# wikipedia-spike

Research spike for `docs/plans/v4-server-prototype.md` §8.1 (Wikipedia
staging) — requested explicitly as a follow-up once §8.1 flagged that no
`experiments/` piece had proven a Rust HTTP client can reproduce
`lib/wikipedia_v2.py`'s behavior against the real Wikimedia API. Two
questions, both settled below:

1. **Is there an existing Rust crate worth building on**, the way
   `edgarkit` was for EDGAR (`edgar-backend.md` §2's Option 2 decision)?
2. **Does `lib/wikipedia_v2.py`'s actual approach — narrowed field
   requests, one targeted Wikidata labels call, a real User-Agent,
   `maxlag`/429/503/Retry-After handling — reproduce in Rust against the
   live API**, not just in principle?

## Existing crate evaluation

Checked via crates.io's API (`created_at`/`updated_at`/downloads — the
JS-rendered crates.io website itself doesn't serve to a plain fetch):

| crate | latest | updated | downloads | verdict |
|---|---|---|---|---|
| [`mediawiki`](https://crates.io/crates/mediawiki) | 0.5.1 | 2026-03-13 | 87,975 | closest fit — actively maintained, async+sync variants, queries both Wikipedia and Wikidata (incl. SPARQL) |
| [`wikibase_rest_api`](https://crates.io/crates/wikibase_rest_api) | 0.3.0 | 2026-07-23 | 8,077 | newest/most-active, but REST-only (claims/labels), no page-content/infobox access |
| [`wikidata`](https://crates.io/crates/wikidata) | 1.1.0 | 2024-06-29 | 15,445 | stale (16 months), Wikidata-only |
| [`wikipedia`](https://crates.io/crates/wikipedia) | 0.5.0 | 2025-02-16 | 81,771 | page content only, no Wikidata |
| `wme-client`, `tools_interface`, `wiki-api`, `wikimedia-api` | — | — | low (<13k) | too niche or too new to trust for this |

**Decided: don't adopt one, hand-roll on `reqwest` instead** — a real
difference from the EDGAR case, not a reflexive "not invented here."
`edgarkit` earned its adoption because it replaced a large amount of
SEC-specific domain logic (submissions parsing, quarterly index
fetching) that would have been expensive to reproduce correctly.
Here, the expensive, valuable part is the opposite: reproducing
wptools' exact infobox/claims parsing (`lib/wikipedia_v2.py`'s
verbatim ports, lines 135–307) — and **no candidate crate provides
that logic**; every one of them stops at "here's the raw API
response," which is exactly where this project's own hand-rolled HTTP
layer also starts. On top of that, none of the candidates expose
`maxlag`, 429/503/Retry-After handling, or field-narrowing as
first-class options — `lib/wikipedia_v2.py`'s docstring calls these
out as its three real fixes over wptools, and adopting a generic
client would mean re-adding all three around it anyway. Raw `reqwest`
gives this spike (and, if promoted, `v4/crates/wikipedia/`) direct
control over the request shape instead of working around a
general-purpose client's defaults. Worth revisiting if a future crate
adds narrowed-field + maxlag support out of the box, but that's not
today's landscape.

## What this spike proves

**Update (2026-09-28, extended): the infobox/claims parsing and the
final `get_firmographics()` field mapping are now real, ported code**
(`src/infobox.rs`, `src/firmographics.rs`), not a placeholder — see
"Extended: the real parsing port" below for what changed and why.
The original infrastructure-only run is kept below for the historical
record of what was proven first.

Ran live against `en.wikipedia.org`/`www.wikidata.org` for three real
companies (IBM, Apple Inc., Tesla, Inc.) — `cargo run`, no mocks:

```
=== IBM ===
  elapsed: 1.319910125s
  infobox fields: 38
  url: Some("https://en.wikipedia.org/wiki/IBM")
  wikidata claims resolved: {"industry (P452)": ["software industry (Q880371)", ...], ...}

=== Apple Inc. ===
  elapsed: 1.048017709s
  infobox fields: 39
  wikidata claims resolved: {..., "Central Index Key (P5531)": ["0000320193"], ...}

=== Tesla, Inc. ===
  elapsed: 943.889584ms
  infobox fields: 33
  wikidata claims resolved: {"stock exchange (P414)": ["Nasdaq (Q82059)", "Frankfurt Stock Exchange (Q151139)", ...], ...}
```

Confirms, against the real API, in Rust:

- **Narrowed `action=parse`/`action=query` requests** work exactly as
  `lib/wikipedia_v2.py` shapes them (`prop=parsetree` only,
  `prop=extracts|info` only) — real infobox templates parsed back (33–39
  fields per company), real extract text and canonical URL returned.
- **The one-targeted-labels-request Wikidata fix reproduces**: claims
  fetched, reduced to the 5 wanted properties
  (`WANTED_WIKIDATA_PROPS`), only the entities actually referenced by
  those claims resolved to labels in a second request — same shape as
  `lib/wikipedia_v2.py`'s `_fetch_wikidata`, same result (CIK, industry,
  country, website, stock exchange all correctly labeled, e.g. Apple's
  real CIK `0000320193` came back attached to `Central Index Key
  (P5531)`).
- **Concurrent fetch** (`tokio::join!` on infobox + query + wikidata,
  mirroring `lib/wikipedia_v2.py`'s `ThreadPoolExecutor(3)`) completes
  end-to-end in ~0.9–1.3s per company for all three calls together —
  in the neighborhood of `lib/wikipedia_v2.py`'s own measured numbers,
  not a regression.
- **`maxlag` is sent on every request, and the 429/503/Retry-After
  backoff path is now proven, not just implemented** — see "429/503
  backoff: now proven" below.
- **Real, identifying User-Agent** sent on every request
  (`company_dns-v4-wikipedia-spike/0.1.0 (...; hello@mediumroast.io)`).

## Extended: the real parsing port

`src/infobox.rs` now ports wptools' `_template_to_dict`/
`_template_to_dict_iter`/`_template_to_text`/`_template_to_dict_alt`
(the same source `lib/wikipedia_v2.py` lines 135–234 verbatim-port
from) using `roxmltree` in place of `lxml.etree` — walking the
`<template>`/`<part>`/`<name>`/`<value>` structure in document order,
including nested-template-in-value handling and per-element `.tail`
text, not just flat top-level `name`/`value` pairs. `_template_to_dict_find`/
`_text_with_children` (the `find=True` branch) were deliberately **not**
ported — `_get_infobox` never calls `_template_to_dict` with
`find=True`, so that branch is genuinely dead code on the path this
project exercises, not an omission.

`src/firmographics.rs` now ports `get_firmographics`'s field-construction
logic (`_get_item`, `_transform_isin`, `_transform_stock_ticker`, the
Wikidata-vs-infobox fallback chains for country/city/website, the
`Private Company (Assumed)` default) — the spike now prints V3's actual
firmographics shape, not raw ingredients. Real output for IBM:

```json
{
  "cik": "0000051143",
  "city": "Armonk, New York",
  "country": "United States",
  "exchanges": ["New York Stock Exchange", "Tokyo Stock Exchange"],
  "industry": ["software industry", "computer industry", "IT service management", ...],
  "isin": "US4592001014",
  "name": "International Business Machines Corporation",
  "tickers": ["NYSE", "IBM"],
  "type": "Public company",
  "website": ["https://www.ibm.com/", ...],
  "wikipediaURL": "https://en.wikipedia.org/wiki/IBM"
}
```

Real ISIN (`US4592001014`), real ticker/exchange split (`["NYSE",
"IBM"]`), real CIK, real city/country/industry all correctly extracted
and shaped — run `cargo run` to see the same for Apple Inc. and Tesla,
Inc. (`isin` correctly resolved to `US0378331005`/`US88160R1014`,
`tickers` to `["NASDAQ", "AAPL"]`/`["NASDAQ", "TSLA"]`). Note `cik`/
`country` are bare strings, not 1-element lists — see "Side-by-side
diff" below for why that shape matters and isn't a stylistic choice.

## 429/503 backoff: now proven

`cargo test` mocks a real 503 response with `Retry-After: 1` using
`wiremock` and asserts `get_with_backoff` actually sleeps ~1s and
retries (not a different fixed delay, not ignoring the header), plus a
second test confirming a persistent 503 exhausts retries and returns an
error rather than hanging or silently succeeding:

```
running 2 tests
test tests::gives_up_after_max_retries_on_persistent_503 ... ok
test tests::retries_after_503_with_retry_after_header ... ok

test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
```

This replaces the earlier "implemented but not exercised" caveat — the
retry path is now proven against a real (mocked) throttling response,
not just read-through-and-trusted.

## Side-by-side diff: real bugs found and fixed

Fetched V3's actual live output — `curl
https://company-dns.mediumroast.io/V3.0/global/company/wikipedia/firmographics/{IBM,Apple%20Inc.,Tesla%2C%20Inc.}`
(V3's default `/V3.0/global/company/wikipedia/firmographics/` route
already uses the `WikipediaQueriesV2` v2 backend, per
`company_dns.py` line 508 — no shadow-endpoint path needed) — and
diffed every field programmatically against this spike's output for
the same three companies. Found and fixed two real V3-parity bugs the
"extended" pass above had gotten wrong, not just gaps:

1. **`description` still had raw HTML tags** (`<p class="mw-empty-elt">`
   etc.) — `lib/wikipedia_v2.py`'s `_fetch_query` runs the extract
   through Python's `html2text` before returning it; this spike's
   `fetch_query` never did. Fixed with the `html2text` crate (`src/
   main.rs::fetch_query`).
2. **`cik` and `country` were always wrapped in a 1-element list; V3
   returns them as bare strings.** This was flagged as "an intentional
   simplification, not a fidelity gap" in the previous pass — that was
   wrong. wptools' `_build_wikidata_dict` collapses a single-value claim
   to a bare string, and `get_firmographics` does NOT re-wrap `country`
   or `cik` the way it re-wraps `industry`/`exchanges`/`website`
   (`lib/wikipedia_v2.py` lines 477-503: those three fields' `if not
   isinstance(..., list)` branches explicitly rebuild a 1-element list;
   `country`'s does not, and `cik` has no isinstance check at all).
   Fixed by changing `fetch_wikidata`'s return type from
   `HashMap<String, Vec<String>>` to `HashMap<String, Value>`
   (`String` for a single value, `Array` for multiple — mirroring
   wptools' own collapse rule) and handling `country`/`cik` differently
   from the always-list fields in `firmographics.rs`.

After both fixes, a field-by-field diff against live V3 output for all
three companies matched exactly except `description`'s whitespace
(e.g. IBM's first diff was `"Corporation , doing"` [V3, a stray space
before the comma] vs. `"Corporation, doing"` [this spike]) — that
stray space is Python's `html2text` leaving a space behind where it
strips an empty inline element (`<span></span>`, common in Wikipedia's
pronunciation-respelling markup); the Rust `html2text` crate doesn't
reproduce that specific artifact. Judged a benign implementation
difference between the two `html2text`s, not a data-fidelity bug.

## Widened to 10 companies

Extended past the original 3 to the full `perf_tests/companies.py`
list (IBM, Apple Inc., Microsoft, Amazon (company), Alphabet Inc.,
Tesla Inc., Meta Platforms, Walmart, JPMorgan Chase, ExxonMobil) — the
same test set the rest of this project already trusts for V3-vs-V4
comparison, not a hand-picked easy sample. Field-by-field diff against
live V3 output for all 10:

```
IBM               : 11/12 fields MATCH (description: benign whitespace)
Apple Inc.        : 11/12 fields MATCH (description: benign whitespace)
Microsoft         : 11/12 fields MATCH (description: benign whitespace)
Amazon (company)  : 11/12 fields MATCH (description: benign whitespace)
Alphabet Inc.     : 12/12 fields MATCH (description matched exactly too)
Tesla, Inc.       : 11/12 fields MATCH (description: benign whitespace)
Meta Platforms    : 11/12 fields MATCH (description: benign whitespace)
Walmart           : 11/12 fields MATCH (description: benign whitespace)
JPMorgan Chase    : 11/12 fields MATCH (description: benign whitespace)
ExxonMobil        : 11/12 fields MATCH (description: benign whitespace)
```

**Zero non-description field mismatches across all 10 companies.**
`description` length differences ranged from 0 to 8 characters (all
the same benign `html2text`-whitespace pattern characterized above,
confirmed at every company, not just IBM) — genuinely the smallest,
most consistent gap left, not a hidden landmine. This closes the
"only checked against 3 companies" caveat from the previous pass.

## Company-name-to-page-title resolution: attempted, partial success

Implemented `resolve_title` (`src/main.rs`) using MediaWiki's
full-text search API (`action=query&list=search`, namespace 0, top
hit) to answer the open question both previous passes deferred: can a
bare company name (not V3's near-exact `wiki_name` page title) be
resolved to the right page? Neither V3 nor `lib/wikipedia_v2.py` do
this at all - genuinely new work, not a port of existing behavior.

Tested 5 bare names against their expected page title:

```
  Alphabet     -> Alphabet                 (expected Alphabet Inc.       ) DIFFERS
  Amazon       -> Amazon (company)         (expected Amazon (company)    ) MATCH
  JPMorgan     -> JPMorgan Chase           (expected JPMorgan Chase      ) MATCH
  Exxon        -> ExxonMobil               (expected ExxonMobil          ) MATCH
  Meta         -> Meta                     (expected Meta Platforms      ) DIFFERS
```

**3/5 (60%) — a real, honest partial result, not a solved problem
[via this mechanism specifically].** Both failures have the same
shape: "Alphabet" and "Meta" are common English words with their own
well-established, independently notable Wikipedia articles (the
alphabet-as-a-writing-system concept; the "meta" prefix/concept),
which outrank the company page in MediaWiki's plain relevance ranking.
Naive top-hit full-text search is not a reliable resolution strategy
on its own for a company whose name collides with a common word or
concept - "JPMorgan"/"Exxon" resolve fine because those strings have
no competing generic-word article. **Note (2026-09-28): "Alphabet" and
"Meta" specifically are now solved anyway** - not by this search-based
mechanism, but by the suffix-hint mechanism below gaining an
infobox-presence check, which rejects exactly these two collisions and
falls through to the correct company page via a suffix guess. See
"Fixed: require an infobox, not just a page, to accept a candidate"
further down - this section's 60% result stands as-is for the
*general* bare-name-resolution problem, just not for these two specific
examples anymore.
Worth trying if this gets built out for real: restricting results to
pages carrying an `Infobox company`-shaped template (this spike's own
`infobox::get_infobox` could double as that filter - fetch the
infobox for the top 2-3 search hits and prefer the first one that
parses as a company infobox), or biasing the search query itself
(e.g. appending "company" to the search string). Neither attempted
here.

**Checked against the live V3 deployment (2026-09-28) - V3 has the
same problem, and doesn't even attempt to solve it.** Curled
`company-dns.mediumroast.io`'s live `/V3.0/global/company/wikipedia/
firmographics/{name}` with the same bare names:

```
IBM        -> 200 (exact title)
Walmart    -> 200 (exact title)
JPMorgan   -> 200 (works only because Wikipedia itself has a real
                    redirect page titled "JPMorgan" -> "JPMorgan Chase" -
                    MediaWiki's own redirects=1 follows it, no resolution
                    logic in V3 at all)
Exxon      -> 200 (same story, a real redirect to "ExxonMobil")
Alphabet   -> 404 (no resolution attempted; "Alphabet" isn't a redirect,
                    it's Wikipedia's own primary-topic article about the
                    writing-system concept)
Meta       -> 404 (same - "Meta" is its own concept article)
MetaX      -> 200 but WRONG COMPANY - a real, unrelated Chinese chip
                    company's actual Wikipedia page, returned silently
                    as if correct, no error at all
```

`lib/wikipedia_v2.py` calls MediaWiki's `action=query&titles={name}&
redirects=1` directly - zero search, zero resolution. It only succeeds
when the input is already the exact title or Wikipedia happens to have
a literal redirect page under that exact string, and it will silently
return the *wrong* company for any bare name that happens to collide
with an unrelated real page (`MetaX` above), with no error signal at
all. **This means company-name resolution is not a V3-parity gap** -
V3's own behavior already is "caller supplies the near-exact title,
full stop," exactly what `perf_tests/companies.py`'s comments say. This
spike's `resolve_title` goes further than V3 does at all (V3 doesn't
try), and even that extra effort only reached 60% - a real V4-only
feature question worth its own design discussion, not something
blocking V3-parity promotion.

## V3 does compute a hint - but never delivers it

Both `lib/wikipedia.py` and `lib/wikipedia_v2.py`'s `lookup_error`
build an identical `message`:

```
Unable to find a company by the name [{query}]. Maybe you should try an
alternative structure like [{query} Inc.,{query} Corp., or {query} Corporation].
```

A real, if narrow, heuristic hint - not a dynamic search suggestion,
just "try appending a corporate suffix." Tracing how it actually flows
out: `_check_status_and_return` (`company_dns.py:37-47`) raises
`HTTPException(status_code=404, detail=return_msg)` with that message
as `detail`. But `company_dns.py`'s custom exception handler
(`company_dns.py:129-146`) unconditionally serves a static themed HTML
404 page for **any** 404 status, discarding `exc.detail` entirely -
confirmed by curling the live deployment for "Alphabet"/"Meta"/a
nonsense name and getting back the themed HTML page each time, not a
JSON body with the hint text anywhere in it (not even embedded in the
page's own JS-populated fields). **The hint is computed, then silently
thrown away before it reaches the client - dead code on the response
path, not a working feature.** V4's `not_found` responses are always
JSON, never HTML (`envelope.rs`), so there's no equivalent swallowing
bug to reproduce - V4 has a clean opportunity to actually deliver the
hint V3's code already computes but never ships.

## Suffix hint: added back, and taken one step further

Per direct instruction: don't just restore the hint text, actually
issue the suggested REST calls server-side so a caller gets the
resolved company back directly instead of a suggestion to retry
manually. Implemented in `src/main.rs`:

- **`hint_message(query)`** - byte-for-byte the same text
  `lib/wikipedia_v2.py`'s `lookup_error['message']` builds, kept as a
  real V3-parity string rather than paraphrased.
- **`resolve_candidate(client, wikipedia_api, raw_name)`** - tries the
  raw name first (the common case), then V3's exact three suffix
  candidates (`" Inc."`, `" Corp."`, `" Corporation"`) in order, using
  `fetch_query` as a cheap existence probe. Takes `wikipedia_api` as a
  parameter (not a hardcoded constant) specifically so this could be
  tested deterministically - see below.
- **`lookup_firmographics(client, raw_name)`** - wraps
  `resolve_candidate`; on a hit, runs the full concurrent
  infobox+wikidata fetch for the resolved title and returns real
  firmographics data plus which title was used and whether a suffix was
  needed; on a total miss, returns `hint_message`'s text.

**Deterministic proof it works** (`cargo test`, `tests::
suffix_hint_resolves_when_bare_name_is_missing`): mocks "Fizzbuzz
Widgets" as missing and "Fizzbuzz Widgets Inc." as real (with an
infobox), and asserts `resolve_candidate` returns the suffixed title
with `resolved_via_suffix: true` and the real data.

**First live run exposed a real gap in the mechanism itself: page
existence alone isn't enough.** `resolve_candidate` originally accepted
the *first* candidate that had any page at all. Live-testing `Alphabet`
and `Meta` against it, both "resolved" immediately via their bare
name - because both exist as real, unrelated Wikipedia pages (see
"Help me understand more" below), never even reaching the suffix
branch. That's not a suffix-hint failure, it's a precondition the
mechanism was missing.

## Fixed: require an infobox, not just a page, to accept a candidate

Investigated "what does a bare 'Alphabet' lookup actually return" by
running `lookup_firmographics(client, "Alphabet")` directly: a **200
response**, every structured field `"Unknown"` except `description`
(real prose - about the linguistic concept of an alphabet, not
Alphabet Inc.) and `type: "Private Company (Assumed)"`. Confirmed why:
pulled the real page's parsetree - 98 templates total, **zero** with
"box" in any title (same check on "Meta": 6 templates, also zero). A
page without an infobox being accepted as a hit produces a
misleadingly "successful" response with no signal anything's wrong -
worse than a 404, since nothing prompts a caller to look twice.

**Fix**: `resolve_candidate` now requires BOTH `fetch_query` (page
exists) AND `fetch_infobox` (an infobox exists) to succeed before
accepting a candidate - fetched concurrently per candidate, tried in
the same raw-name-then-suffixes order as before. Proved deterministically
with a new test, `tests::rejects_a_real_page_that_has_no_infobox`: a
mock page that exists but has no infobox, with none of the three
suffix candidates existing either, must come back `None` - not the
infobox-less page.

**Re-ran live: this actually fixed Alphabet and Meta, for real.**

```
Alphabet   -> Alphabet Inc.  (via suffix hint)
Meta       -> Meta Inc.      (via suffix hint)
```

Bare `Alphabet` is now correctly rejected (no infobox), retries with
" Inc.", finds the real "Alphabet Inc." page, and returns fully correct
data: real CIK `0001652044`, real ISIN `US02079K1079`, real tickers
`GOOG`/`GOOGL` - identical to querying "Alphabet Inc." directly.

## A second real bug, found by testing Meta: Wikidata doesn't follow Wikipedia's redirects

"Meta" resolved to "Meta Inc." (a real page) - but only `description`/
`name`/`website`/`wikipediaURL` came back correct; `cik`, `industry`,
and `exchanges` all came back `"Unknown"`, and `country` came back
garbled (`"U.S.<br /> {{Coord"`, an infobox-parsing artifact on a
coordinate template - a separate, smaller known limitation, not fixed
here). Traced it: `action=query&titles=Meta Inc.&redirects=1` correctly
follows Wikipedia's own redirect to "Meta Platforms" (confirmed via the
response's own `"redirects": [{"from": "Meta Inc.", "to": "Meta
Platforms"}]`), but Wikidata's *separate* API
(`action=wbgetentities&sites=enwiki&titles=Meta Inc.`) does **not**
follow that redirect - it only indexes the canonical title as a
sitelink, and comes back `"missing"` for the alias. `fetch_wikidata`
was being called with the literal candidate string ("Meta Inc."), not
the canonical title Wikipedia's own redirect resolution already knew.

**Fix**: `QueryData` now carries a `canonical_title` field (the `title`
MediaWiki's `action=query` response returns after following any
redirect), and `lookup_firmographics` uses that for the Wikidata call
instead of the candidate string. Re-verified live - "Meta" bare now
returns the real CIK `0001326801`, clean `"country": "United States"`
(the garbling is gone too, since this pulls from the clean Wikidata
value instead of the buggy infobox fallback), correct industry and
exchanges - matching "Meta Platforms" queried directly, field for
field (only `isin: "Unknown"` differs from a "fixed" value, and that's
V3's own real value too - Meta's infobox genuinely has no ISIN).

## First organic (non-synthetic) real-world success, and a real limitation found alongside it

Re-ran the suffix-hint demo cases with the infobox gate active:

```
Alphabet          -> Alphabet Inc.   (via suffix hint)
Meta              -> Meta Inc.       (via suffix hint)
Lear              -> Lear Corp.      (via suffix hint)
Timken            -> NOT FOUND: ...try [Timken Inc., Timken Corp., or Timken Corporation]
Dover             -> Dover           (exact/redirect)
Fortive           -> Fortive         (exact/redirect)
Vulcan Materials  -> Vulcan Materials (exact/redirect)
```

**`Lear` is the first real, non-synthetic example of the suffix hint
actually mattering.** Bare "Lear" is a real Wikipedia page (pageid
1052734 - almost certainly the King Lear/Shakespeare-adjacent sense,
not checked further), correctly rejected for having no company
infobox; " Corp." then correctly finds the real automotive-parts
company's page. No mock needed for this one - it happened for real.

**`Timken` surfaced a genuine, honest limitation of V3's own
three-suffix heuristic, not a bug in this port.** It 404s even with the
fix, because none of `" Inc."`/`" Corp."`/`" Corporation"` match its
actual title: the real page is **"Timken Company"** (confirmed via
search) - "Company" spelled out, not abbreviated, and not
"Corporation" either. This is a real gap in the heuristic
`lib/wikipedia_v2.py` itself defines, faithfully reproduced here rather
than quietly patched over by adding a fourth guess - that would be
scope creep past "restore V3's exact hint," not a bug fix. Worth
flagging as a concrete, real candidate for a future 4th suffix
(`" Company"`) if this becomes a priority, not something to silently
add now.

## What this spike still does NOT prove — real work ahead

- **The infobox-parsing bug the "country" garbling surfaced** (a
  coordinate template inside a `<value>` not handled cleanly by
  `template_to_dict_iter`) is real but low-priority - not hit on any of
  the 10 companies in the main diff sample, only on "Meta Inc." before
  the Wikidata canonical-title fix made it moot for that specific case
  (the field is now sourced from Wikidata instead). Still a latent
  infobox-parsing gap worth fixing before this is called a complete
  port.
- **`" Company"` isn't one of V3's three suffix guesses**, and
  `Timken` proved that's a real gap (its actual title is "Timken
  Company") - not fixed here, since it's not part of V3's own hint
  text; a real, scoped candidate for later, not urgent.
- **Rate limiting beyond `maxlag`** (e.g. a client-side
  request-per-second cap, matching MediaWiki's documented anonymous
  rate limits more proactively rather than only reacting to a 429)
  isn't attempted here.
- **Still only US, English-Wikipedia companies** - a non-US listing,
  a company without an English Wikipedia page, or unusual/sparse
  infobox markup could still surface a gap this sample didn't hit.

## Recommended next step

Promote into `v4/crates/wikipedia/` — infobox parsing, firmographics
field construction, 429/503 backoff, and the suffix hint mechanism
(now infobox-gated and canonical-title-correct) are all real, tested,
and diff-verified/mock-verified, not a to-do list. Company-name
resolution is confirmed NOT a blocker (V3 doesn't solve it either, and
taking a near-exact title is real V3-parity behavior, not a gap to
close first) - and the Alphabet/Meta collision case specifically is
now actually solved by the infobox gate, not just documented as
unsolved:
1. Wire the result into the same `company-dns-cache` pattern
   `company-dns-edgar`'s client already uses (title/QID-keyed, per
   `docs/plans/v4-server-prototype.md` §8.1's original module-boundary
   plan — still correct, unchanged by this spike).
2. Ship the `{company_name}`-keyed endpoint using `lookup_firmographics`
   as-is: near-exact title first (real V3 parity), V3's exact suffix
   hint as an actual fallback REST call, infobox-gated so a real-but-
   wrong page (the original Alphabet/Meta failure) can't be mistaken
   for a match, canonical-title-correct so a redirect's Wikidata claims
   aren't silently lost, `hint_message` as the not-found response body
   when nothing resolves.
3. `resolve_title`'s search-based 60% result stays available for the
   narrower remaining case - a company whose name doesn't match any
   suffix variant at all (not just missing "Inc."/"Corp."/
   "Corporation", but phrased completely differently from its Wikipedia
   title) - but nothing about promotion needs to wait on it.

## Running it

```bash
cd experiments/wikipedia-spike
cargo run
```

Hits the real, live `en.wikipedia.org` and `www.wikidata.org` APIs —
no API key needed, but be considerate of request volume (this spike
already sends `maxlag=5` and a real User-Agent per MediaWiki etiquette).
