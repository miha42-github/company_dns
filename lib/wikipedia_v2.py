"""
WikipediaQueriesV2 - shadow-endpoint alternative to lib/wikipedia.py.

Built for docs/plans/performance-improvements.md item 6. Replaces
wptools' request layer with narrowed, direct, ToS-compliant HTTP requests,
while reproducing wptools' exact data transformations so output matches
WikipediaQueries field-for-field (validated end-to-end against the live,
currently-deployed service in docs/plans/research/wikipedia-experiment.py
- see that plan section, Findings 1-6, for the full evidence).

What changed vs. WikipediaQueries, and why:
- Narrowed field requests (only what's actually read downstream) instead
  of wptools' full default prop sets - e.g. action=parse fetches only
  `parsetree`, not also the full rendered HTML (`text`), raw wikitext,
  interwiki links, and display title, none of which are ever used. Cuts
  the parse response from ~937KB to ~178KB for a well-developed company
  page (measured against IBM).
- One targeted Wikidata labels request for only the ~10-15 entities this
  module actually needs (the 5 target properties plus their Q-value
  targets), instead of wptools' get_wikidata()-triggered get_labels()
  cascade, which resolves *every* property and value referenced anywhere
  in the entity's claims - measured at 308 entities / 7 sequential
  requests / ~2.8s for IBM, when only 13 entities / 1 request / ~0.3s are
  ever used. This is the dominant fix - see item 6 Finding 4.
- A shared requests.Session() (module-level, matching lib/edgar.py's item
  5 fix) instead of wptools' pycurl layer, which opens a fresh connection
  for every single call with no reuse whatsoever, even within one lookup.
- A real, identifying User-Agent
  ("company_dns/<version> (github.com/miha42-github/company_dns;
  hello@mediumroast.io)") instead of wptools' hardcoded, shared-by-every-
  wptools-user-worldwide generic string - see item 6 Finding 5 for why
  this matters (Wikimedia's own User-Agent policy, and why company_dns's
  traffic being indistinguishable from any other wptools consumer's is a
  real operational risk, not just a compliance nicety).
- MediaWiki's `maxlag` "good citizen" parameter on every request, and
  basic 429/503 handling with Retry-After respect - wptools has neither.

`wptools` itself can't be imported here as a dependency to reuse its pure
parsing functions (get_infobox, reduce_claims, etc.): importing any
wptools submodule executes wptools/__init__.py, which unconditionally
imports its pycurl-based request layer. The infobox-parsing and
Wikidata-claims-to-labeled-dict functions below are copied verbatim from
wptools' source (not reimplemented from scratch - an initial hand-rolled
version already diverged subtly from the real thing before this was
caught, see item 6 Finding 6) so output is guaranteed byte-identical for
the logic that matters, not an approximation.
"""

import concurrent.futures
import logging
import re
import sys
import time
from collections import defaultdict
from itertools import chain

import html2text
import lxml.etree
import requests
from lxml.etree import tostring

__author__ = "Michael Hay"
__copyright__ = "Copyright 2026, Mediumroast, Inc. All rights reserved."
__license__ = "Apache 2.0"
__version__ = "1.0.0"
__maintainer__ = "Michael Hay"
__contact__ = 'https://github.com/miha42-github/company_dns'

#### Globals ####
UKN = 'Unknown'

DEPENDENCIES = {
    'modules': {'requests': 'https://pypi.org/project/requests/'},
    'data': {
        'wikipedia': 'https://www.mediawiki.org/wiki/API:Main_page',
        'wikiData': 'https://www.wikidata.org/wiki/Wikidata:Data_access',
    }
}

RE_BRACKETS = re.compile(r'\[\[|\]\]')
RE_PARENS = re.compile(r'\s*\(\S+\)$')
RE_PIPES = re.compile(r'\|')
RE_BRACES = re.compile(r'\{\{.+?\|.+?\}\}')
RE_BR = re.compile(r'<br>')
RE_QID = re.compile(r'^Q\d+$')

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"

# MediaWiki API etiquette best practice: ask the server to decline rather
# than serve us (and worsen replication lag) if lag exceeds this many
# seconds. https://www.mediawiki.org/wiki/Manual:Maxlag_parameter
MAXLAG = 5

# The only Wikidata properties this module (and lib/wikipedia.py) ever
# reads. Everything else in a company's claims is irrelevant to us - see
# item 6 Finding 4 for why fetching labels for only these matters so much.
WANTED_WIKIDATA_PROPS = {"P452", "P17", "P856", "P5531", "P414"}

# Shared across all WikipediaQueriesV2 instances and safe across threads
# (urllib3's connection pool handles concurrent use) - reused, pooled,
# keep-alive connections instead of wptools' fresh-connection-per-call.
USER_AGENT = (
    f"company_dns/{__version__} "
    "(https://github.com/miha42-github/company_dns; hello@mediumroast.io) "
    f"python-requests/{requests.__version__}"
)
_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


def _get_with_backoff(url, params, timeout=15, max_retries=2):
    """GET with basic 429/503 handling and Retry-After respect - wptools
    has none of this (item 6, Finding 5)."""
    last_resp = None
    for attempt in range(max_retries + 1):
        resp = _session.get(url, params=params, timeout=timeout)
        if resp.status_code in (429, 503) and attempt < max_retries:
            retry_after = resp.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else 2 ** attempt
            except ValueError:
                delay = 2 ** attempt
            time.sleep(delay)
            last_resp = resp
            continue
        resp.raise_for_status()
        return resp
    if last_resp is not None:
        last_resp.raise_for_status()
    raise RuntimeError("unreachable")


# --------------------------------------------------------------------- #
# BEGIN: verbatim port of wptools/utils.py's infobox-parsing functions.
# Not reimplemented - copied, so output is guaranteed identical to what
# wptools itself would produce from the same parsetree.
def _get_infobox(ptree, boxterm="box"):
    boxes = []
    for item in lxml.etree.fromstring(ptree).xpath("//template"):
        title = item.find('title').text
        if title and boxterm in title:
            box = _template_to_dict(item)
            if box:
                return box
            alt = _template_to_dict_alt(item, title)
            if alt:
                boxes.append(alt)
    if boxes:
        return {'boxes': boxes, 'count': len(boxes)}


def _template_to_dict(tree, debug=0, find=False):
    obj = defaultdict(str)
    errors = []
    for item in tree:
        try:
            name = item.findtext('name').strip()
            find_val = _template_to_dict_find(item, debug)  # DEPRECATED upstream
            iter_val = _template_to_dict_iter(item, debug)
            value = find_val if find else iter_val
            if name and value:
                obj[name] = value.strip()
        except AttributeError:
            if isinstance(item, lxml.etree.ElementBase):
                name = item.tag.strip()
                text = item.text.strip()
                if item.tag == 'title':
                    obj['infobox'] = text
                else:
                    obj[name] = text
        except Exception:
            errors.append(lxml.etree.tostring(item))
    if errors:
        obj['errors'] = errors
    return dict(obj)


def _template_to_dict_alt(tree, title):
    box = []
    part = []
    for item in tree.iter():
        if item.tag == 'part':
            if part:
                box.append(part)
            part = []
        if item.tag == 'name' or item.tag == 'value':
            for attr in item.keys():
                part.append({attr: item.get(attr)})
            if item.text:
                part.append(item.text.strip())
            if item.tail:
                part.append(item.tail.strip())
    if part:
        box.append(part)
    return {title.strip(): box}


def _template_to_dict_find(item, debug=0):
    tmpl = item.find('value').find('template')
    if tmpl is not None:
        value = _template_to_text(tmpl, debug)
    else:
        value = _text_with_children(item.find('value'), debug)
    return value


def _template_to_dict_iter(item, debug=0):
    valarr = []
    found_template = False
    for elm in item.iter():
        if elm.tag == 'value' and not found_template:
            valarr.append(elm.text.strip())
        if elm.tag == 'template':
            found_template = True
            valarr.append(_template_to_text(elm, debug).strip())
        if elm.tail:
            valarr.append(elm.tail.strip())
    return " ".join([x for x in valarr if x])


def _template_to_text(tmpl, debug=0):
    tarr = [item for item in tmpl.itertext()]
    return "{{%s}}" % "|".join(tarr).strip()


def _text_with_children(node, debug=0):
    parts = ([node.text] +
             list(chain(
                 *([tostring(c, with_tail=False, encoding=str), c.tail]
                   for c in node.getchildren())))
             + [node.tail])
    return ''.join(filter(lambda x: x or isinstance(x, str), parts)).strip()
# END: verbatim port of wptools/utils.py
# --------------------------------------------------------------------- #


# --------------------------------------------------------------------- #
# BEGIN: verbatim port of wptools/wikidata.py's claims/labels logic.
# One intentional deviation (noted inline): wptools' reduce_claims raises
# ValueError on any falsy claim value (arguably a bug), we skip it
# instead. Doesn't affect the 5 target properties for real company data.
def _reduce_claims(query_claims):
    claims = {}
    for claim, entities in query_claims.items():
        vals = []
        for ent in entities:
            snak = ent.get("mainsnak", {})
            snaktype = snak.get("snaktype")
            value = (snak.get("datavalue") or {}).get("value")
            if snaktype != "value":
                val = snaktype
            elif isinstance(value, dict) and value.get("id"):
                val = value.get("id")
            elif isinstance(value, dict) and value.get("text"):
                val = value.get("text")
            elif isinstance(value, dict) and value.get("time"):
                val = value.get("time")
            else:
                val = value
            if val:  # deviation: skip instead of raising, see note above
                vals.append(val)
        if vals:
            claims[claim] = vals
    return claims


def _needed_entities(claims, wanted_props):
    """Property IDs + their Q-number claim values, for JUST the
    properties this module reads - not every property on the entity."""
    entities = set()
    for prop in wanted_props:
        if prop in claims:
            entities.add(prop)
            for val in claims[prop]:
                if isinstance(val, str) and RE_QID.match(val):
                    entities.add(val)
    return entities


def _build_wikidata_dict(claims, labels):
    """Exact port of wptools' _update_wikidata(): builds
    {'industry (P452)': 'Software industry (Q1090583)', ...}. Matches
    wptools' actual fallback behavior: if a Q-number's label lookup
    fails, the value becomes None (not the raw Q-number)."""
    out = {}
    for prop, vals in claims.items():
        plabel = labels.get(prop)
        if plabel:
            plabel = f"{plabel} ({prop})"
        claim = []
        ilabel = None
        for item in vals:
            ilabel = item
            if isinstance(item, str) and RE_QID.match(item):
                ilabel = labels.get(item)
                if ilabel:
                    ilabel = f"{ilabel} ({item})"
            if len(vals) == 1:
                claim = ilabel
            else:
                claim.append(ilabel)
        if plabel and ilabel:
            out[plabel] = claim
    return out
# END: verbatim port of wptools/wikidata.py
# --------------------------------------------------------------------- #


class WikipediaQueriesV2:
    """
    Drop-in alternative to lib.wikipedia.WikipediaQueries - same
    interface (a settable `.query` attribute, a `get_firmographics()`
    method returning the same {code, message, module, data, dependencies}
    envelope) so it works with company_dns.py's `_handle_request` exactly
    like the original. See module docstring for what's different and why.
    """

    def __init__(self, name='wikipedia_v2', description='Shadow-endpoint alternative to WikipediaQueries - see docs/plans/performance-improvements.md item 6.'):
        self.query = None
        self.NAME = name
        self.DESC = description
        self.logger = logging.getLogger(self.NAME)

    # --- Ported unchanged from lib/wikipedia.py - pure infobox-dict
    # transforms, no network layer involved, so nothing here needed to
    # change. ---
    def _get_item(self, obj, variants, rules, idx):
        for variant in variants:
            if variant in obj:
                tmp_item = obj[variant].strip(rules)
                if RE_PIPES.search(tmp_item):
                    return tmp_item.split('|')[idx]
                return tmp_item
        return UKN

    def _transform_isin(self, isin):
        if 'ISIN' in isin:
            try:
                tmp_item = RE_BRACES.findall(isin.strip())[-1]
                tmp_item = tmp_item.strip('{}')
                return tmp_item.split('|')[-1]
            except (IndexError, AttributeError):
                return UKN
        return isin.strip('{}')

    def _transform_stock_ticker(self, traded_as):
        try:
            tmp_match = RE_BRACES.findall(traded_as.strip())[-1]
            tmp_match = tmp_match.strip('{}')
            try:
                parts = RE_PIPES.split(tmp_match)
                exchange, ticker = parts[0], parts[1]
            except Exception:
                exchange, ticker = UKN, UKN
            return [exchange, ticker]
        except (IndexError, AttributeError):
            return [UKN, UKN]

    # --- The narrowed, direct-HTTP fetch pipeline ---
    def _fetch_infobox(self):
        resp = _get_with_backoff(WIKIPEDIA_API, {
            "action": "parse", "format": "json", "formatversion": 2,
            "contentmodel": "text", "disableeditsection": "", "disablelimitreport": "",
            "disabletoc": "", "redirects": 1, "page": self.query, "prop": "parsetree",
            "maxlag": MAXLAG,
        })
        data = resp.json()
        if "error" in data or "parse" not in data:
            return None
        return _get_infobox(data["parse"]["parsetree"])

    def _fetch_query(self):
        resp = _get_with_backoff(WIKIPEDIA_API, {
            "action": "query", "exintro": "", "format": "json", "formatversion": 2,
            "inprop": "url", "prop": "extracts|info", "redirects": 1, "titles": self.query,
            "maxlag": MAXLAG,
        })
        data = resp.json()
        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            return None
        page = pages[0]
        extract = page.get("extract")
        extext = html2text.html2text(extract).strip() if extract else None
        return {"extext": extext, "url": page.get("fullurl")}

    def _fetch_wikidata(self):
        resp = _get_with_backoff(WIKIDATA_API, {
            "action": "wbgetentities", "format": "json", "formatversion": 2,
            "props": "claims", "sites": "enwiki", "titles": self.query, "maxlag": MAXLAG,
        })
        data = resp.json()
        entities = data.get("entities")
        if not entities:
            return {}
        entity_id = next(iter(entities))
        if entities[entity_id].get("missing"):
            return {}
        raw_claims = entities[entity_id].get("claims", {})
        claims = _reduce_claims(raw_claims)

        needed = _needed_entities(claims, WANTED_WIKIDATA_PROPS)
        labels = {}
        if needed:
            resp2 = _get_with_backoff(WIKIDATA_API, {
                "action": "wbgetentities", "format": "json", "formatversion": 2,
                "languages": "en", "props": "labels", "ids": "|".join(needed),
                "maxlag": MAXLAG,
            })
            ldata = resp2.json()
            for eid, ent in ldata.get("entities", {}).items():
                lbl = ent.get("labels", {}).get("en", {}).get("value")
                if lbl:
                    labels[eid] = lbl

        narrow_claims = {p: claims[p] for p in WANTED_WIKIDATA_PROPS if p in claims}
        return _build_wikidata_dict(narrow_claims, labels)

    def get_firmographics(self, fields=None):
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__

        total_start_time = time.time()
        self.logger.info(f'Starting retrieval of firmographics for [{self.query}] via its wikipedia page (v2 backend).')

        firmographics = dict()

        lookup_error = {
            'code': 404,
            'message': f'Unable to find a company by the name [{self.query}]. Maybe you should try an alternative structure like [{self.query} Inc.,{self.query} Corp., or {self.query} Corporation].',
            'error': 'LookupError',
            'module': my_class + '-> ' + my_function,
            'dependencies': DEPENDENCIES,
            'data': {'total': 0, 'results': []}
        }

        parallel_api_start = time.time()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                infobox_future = executor.submit(self._fetch_infobox)
                query_future = executor.submit(self._fetch_query)
                wikidata_future = executor.submit(self._fetch_wikidata)

                company_info = infobox_future.result()
                query_data = query_future.result()
                wikidata = wikidata_future.result()
        except Exception as e:
            parallel_api_elapsed = time.time() - parallel_api_start
            self.logger.error(f"Error retrieving data for [{self.query}]: {str(e)} after {parallel_api_elapsed:.3f} seconds")
            return lookup_error
        parallel_api_elapsed = time.time() - parallel_api_start

        if not company_info or not query_data:
            self.logger.error(f'An infobox or page for [{self.query}] was not found.')
            return lookup_error

        # --- From here down: field construction mirrors
        # lib/wikipedia.py's get_firmographics() exactly, so the output
        # shape is identical (validated in
        # docs/plans/research/wikipedia-experiment.py).
        extraction_start_time = time.time()

        if query_data.get('extext'):
            firmographics['description'] = query_data['extext'].replace('\n', ' ').replace('**', '')

        firmographics['wikipediaURL'] = query_data.get('url')

        if 'type' in company_info:
            company_type = RE_BRACKETS.sub('', company_info['type'])
            if RE_PIPES.search(company_type):
                company_type = RE_PIPES.split(company_type)[0].strip()
            firmographics['type'] = company_type.split('(')[0].strip() if '(' in company_type else company_type
        else:
            firmographics['type'] = 'Private Company (Assumed)'

        firmographics['industry'] = wikidata.get('industry (P452)', UKN)
        if not isinstance(firmographics['industry'], list):
            firmographics['industry'] = [RE_PARENS.sub('', firmographics['industry'])]
        else:
            firmographics['industry'] = [RE_PARENS.sub('', industry) for industry in firmographics['industry']]

        firmographics['name'] = company_info.get('name', UKN)

        firmographics['country'] = wikidata['country (P17)'] if 'country (P17)' in wikidata else self._get_item(company_info, ['location_country', 'hq_location_country'], r'[\[\]]', 0)
        if not isinstance(firmographics['country'], list):
            firmographics['country'] = RE_PARENS.sub('', firmographics['country'])
        else:
            firmographics['country'] = [RE_PARENS.sub('', country) for country in firmographics['country']]

        firmographics['city'] = self._get_item(company_info, ['location_city', 'hq_location_city', 'location'], r'\[\[\]\]', 0)
        firmographics['city'] = RE_BRACKETS.sub('', firmographics['city'])
        firmographics['city'] = RE_BR.sub(', ', firmographics['city'])

        firmographics['website'] = wikidata['official website (P856)'] if 'official website (P856)' in wikidata else self._get_item(company_info, ['website', 'homepage', 'url'], r'[\{\}]', 1)
        if not isinstance(firmographics['website'], list):
            firmographics['website'] = [firmographics['website'].strip()]

        firmographics['isin'] = self._transform_isin(company_info['ISIN']) if 'ISIN' in company_info else UKN

        firmographics['cik'] = wikidata.get('Central Index Key (P5531)', UKN)

        firmographics['exchanges'] = wikidata.get('stock exchange (P414)', UKN)
        if not isinstance(firmographics['exchanges'], list):
            firmographics['exchanges'] = [RE_PARENS.sub('', firmographics['exchanges'])]
        else:
            firmographics['exchanges'] = [RE_PARENS.sub('', exchange) for exchange in firmographics['exchanges']]

        if 'traded_as' in company_info:
            firmographics['tickers'] = self._transform_stock_ticker(company_info['traded_as'])

        extraction_elapsed = time.time() - extraction_start_time
        total_elapsed = time.time() - total_start_time
        self.logger.info(f'Completed firmographics data extraction (v2) for [{self.query}] in {extraction_elapsed:.3f} seconds')
        self.logger.info(f'Total firmographics retrieval (v2) for [{self.query}] completed in {total_elapsed:.3f} seconds')

        if fields:
            result = {field: firmographics.get(field, UKN) for field in fields if field in firmographics}
        else:
            result = firmographics

        return {
            'code': 200,
            'message': f'Discovered and returning wikipedia data for the company [{self.query}] (v2 backend).',
            'module': my_class + '-> ' + my_function,
            'data': result,
            'dependencies': DEPENDENCIES,
            'performance': {
                'total_time': total_elapsed,
                'parallel_api_time': parallel_api_elapsed,
                'extraction_time': extraction_elapsed,
            }
        }
