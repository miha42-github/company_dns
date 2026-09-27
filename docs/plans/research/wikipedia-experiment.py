#!/usr/bin/env python3
"""
Research experiment for docs/plans/performance-improvements.md item 6.

Makes narrowed, ToS-compliant direct HTTP requests (proper identifying
User-Agent per https://meta.wikimedia.org/wiki/User-Agent_policy, and the
`maxlag` "good citizen" parameter MediaWiki's own API etiquette
recommends), fetching only the fields company_dns actually uses, and
replicates wptools' own data transformations (get_infobox's lxml parsing,
reduce_claims, and the label-application logic that builds the
"{label} (P123)"-style dict our code reads) from wptools' source directly -
not importing wptools itself, since its pycurl dependency is broken in
this dev environment (unrelated issue, not something this experiment
needs to work around via wptools).

Goal: confirm the narrowed/optimized approach produces IDENTICAL final
field values to what the live, currently-deployed service returns today,
before touching any production code.

Status: research artifact, not production code and not wired into
perf_tests/ or lib/wikipedia.py. Kept here for reproducibility of the
findings in performance-improvements.md item 6 (Findings 5-6), and as a
starting point if Tier A is ever scheduled as real implementation work.

Usage: python3 docs/plans/research/wikipedia-experiment.py
Requires: requests, lxml, html2text (all already in requirements.txt).
"""

import re
import sys
import time
from collections import defaultdict
from itertools import chain

import requests
import lxml.etree
from lxml.etree import tostring
import html2text

# --- Wikimedia-compliant identification ---------------------------------- #
# Per https://meta.wikimedia.org/wiki/User-Agent_policy: identify the
# application, version, and a way to contact us - NOT wptools' generic,
# shared "wptools/x.y.z (github.com/siznax/wptools)" string every wptools
# user in the world sends today.
USER_AGENT = (
    "company_dns/3.2.0 "
    "(https://github.com/miha42-github/company_dns; hello@mediumroast.io) "
    f"python-requests/{requests.__version__}"
)
HEADERS = {"User-Agent": USER_AGENT}

# maxlag: MediaWiki API etiquette best practice - asks the server to return
# an error instead of serving us (and making replication lag worse) if the
# database is lagged beyond this many seconds. See
# https://www.mediawiki.org/wiki/Manual:Maxlag_parameter
MAXLAG = 5

session = requests.Session()
session.headers.update(HEADERS)

RE_PARENS = re.compile(r'\s*\(\S+\)$')


# --- Copied VERBATIM from the installed wptools/utils.py (pure functions,
# --- no pycurl dependency themselves - but `import wptools.utils` still
# --- triggers wptools/__init__.py's unconditional `from . import core`,
# --- which imports request.py, which imports the broken pycurl in this
# --- dev environment. Copying the exact source instead of reimplementing
# --- guarantees byte-identical extraction logic, not an approximation. ---#

def get_infobox(ptree, boxterm="box"):
    """
    Returns parse tree template with title containing <boxterm> as dict
    """
    boxes = []
    for item in lxml.etree.fromstring(ptree).xpath("//template"):
        title = item.find('title').text
        if title and boxterm in title:
            box = template_to_dict(item)
            if box:
                return box
            alt = template_to_dict_alt(item, title)
            if alt:
                boxes.append(alt)
    if boxes:
        return {'boxes': boxes, 'count': len(boxes)}


def template_to_dict(tree, debug=0, find=False):
    obj = defaultdict(str)
    errors = []
    for item in tree:
        try:
            name = item.findtext('name').strip()
            find_val = template_to_dict_find(item, debug)  # DEPRECATED
            iter_val = template_to_dict_iter(item, debug)
            value = iter_val
            if find:
                value = find_val
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


def template_to_dict_alt(tree, title):
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


def template_to_dict_find(item, debug=0):
    """DEPRECATED, but still called unconditionally by template_to_dict()
    to compute find_val even when unused - replicated for identical
    failure-mode behavior (an AttributeError here changes which except
    branch template_to_dict() takes)."""
    tmpl = item.find('value').find('template')
    if tmpl is not None:
        value = template_to_text(tmpl, debug)
    else:
        value = text_with_children(item.find('value'), debug)
    return value


def template_to_dict_iter(item, debug=0):
    valarr = []
    found_template = False
    for elm in item.iter():
        if elm.tag == 'value' and not found_template:
            valarr.append(elm.text.strip())
        if elm.tag == 'template':
            found_template = True
            valarr.append(template_to_text(elm, debug).strip())
        if elm.tail:
            valarr.append(elm.tail.strip())
    return " ".join([x for x in valarr if x])


def template_to_text(tmpl, debug=0):
    tarr = []
    for item in tmpl.itertext():
        tarr.append(item)
    return "{{%s}}" % "|".join(tarr).strip()


def text_with_children(node, debug=0):
    parts = ([node.text] +
             list(chain(
                 *([tostring(c, with_tail=False, encoding=str), c.tail]
                   for c in node.getchildren())))
             + [node.tail])
    return ''.join(filter(lambda x: x or isinstance(x, str), parts)).strip()


# --- Replicated from wptools/wikidata.py reduce_claims() + _update_wikidata()
# One intentional deviation, noted where it occurs: wptools' reduce_claims
# raises ValueError on any falsy claim value (arguably a bug - would crash
# the whole call), we skip it instead. Doesn't affect our 5 target
# properties for real company data, which never have falsy values.
def reduce_claims(query_claims):
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


def needed_entities(claims, wanted_props):
    """Property IDs + their Q-number claim values, for JUST the properties
    company_dns actually reads - not every property on the entity."""
    entities = set()
    for prop in wanted_props:
        if prop in claims:
            entities.add(prop)
            for val in claims[prop]:
                if isinstance(val, str) and re.match(r"^Q\d+$", val):
                    entities.add(val)
    return entities


def build_wikidata_dict(claims, labels):
    """Exact port of wptools/wikidata.py's _update_wikidata(): builds
    {'industry (P452)': 'Software industry (Q1090583)', ...} - same shape
    lib/wikipedia.py reads today. Matches wptools' actual fallback
    behavior: if a Q-number's label lookup fails, the value becomes None
    (not the raw Q-number) - easy to get wrong by "improving" it."""
    out = {}
    for prop, vals in claims.items():
        plabel = labels.get(prop)
        if plabel:
            plabel = f"{plabel} ({prop})"
        claim = []
        ilabel = None
        for item in vals:
            ilabel = item
            if isinstance(item, str) and re.match(r"^Q\d+$", item):
                ilabel = labels.get(item)  # None if lookup failed - matches wptools
                if ilabel:
                    ilabel = f"{ilabel} ({item})"
            if len(vals) == 1:
                claim = ilabel
            else:
                claim.append(ilabel)
        if plabel and ilabel:
            out[plabel] = claim
    return out


# --- The narrowed, direct-HTTP fetch pipeline ----------------------------- #
WANTED_WIKIDATA_PROPS = {"P452", "P17", "P856", "P5531", "P414"}


def fetch_infobox(title, timing):
    t0 = time.perf_counter()
    r = session.get("https://en.wikipedia.org/w/api.php", params={
        "action": "parse", "format": "json", "formatversion": 2,
        "contentmodel": "text", "disableeditsection": "", "disablelimitreport": "",
        "disabletoc": "", "redirects": 1, "page": title, "prop": "parsetree",
        "maxlag": MAXLAG,
    })
    r.raise_for_status()
    timing["parse"] = time.perf_counter() - t0
    data = r.json()
    if "error" in data:
        return None, data["error"]
    ptree = data["parse"]["parsetree"]
    return get_infobox(ptree), None


def fetch_query(title, timing):
    t0 = time.perf_counter()
    r = session.get("https://en.wikipedia.org/w/api.php", params={
        "action": "query", "exintro": "", "format": "json", "formatversion": 2,
        "inprop": "url", "prop": "extracts|info", "redirects": 1, "titles": title,
        "maxlag": MAXLAG,
    })
    r.raise_for_status()
    timing["query"] = time.perf_counter() - t0
    page = r.json()["query"]["pages"][0]
    extract = page.get("extract")
    extext = html2text.html2text(extract).strip() if extract else None
    return {"extext": extext, "url": page.get("fullurl")}


def fetch_wikidata(title, timing):
    t0 = time.perf_counter()
    r = session.get("https://www.wikidata.org/w/api.php", params={
        "action": "wbgetentities", "format": "json", "formatversion": 2,
        "props": "claims", "sites": "enwiki", "titles": title, "maxlag": MAXLAG,
    })
    r.raise_for_status()
    t_claims = time.perf_counter() - t0
    data = r.json()
    if "entities" not in data:
        timing["wikidata_claims"] = t_claims
        timing["wikidata_labels"] = 0
        return {}
    entity_id = next(iter(data["entities"]))
    raw_claims = data["entities"][entity_id].get("claims", {})
    claims = reduce_claims(raw_claims)

    entities = needed_entities(claims, WANTED_WIKIDATA_PROPS)

    t0 = time.perf_counter()
    labels = {}
    if entities:
        r2 = session.get("https://www.wikidata.org/w/api.php", params={
            "action": "wbgetentities", "format": "json", "formatversion": 2,
            "languages": "en", "props": "labels", "ids": "|".join(entities),
            "maxlag": MAXLAG,
        })
        r2.raise_for_status()
        ldata = r2.json()
        for eid, ent in ldata.get("entities", {}).items():
            lbl = ent.get("labels", {}).get("en", {}).get("value")
            if lbl:
                labels[eid] = lbl
    t_labels = time.perf_counter() - t0

    timing["wikidata_claims"] = t_claims
    timing["wikidata_labels"] = t_labels
    timing["wikidata_entities_resolved"] = len(entities)

    # Only keep the properties we actually care about in the final dict,
    # matching what lib/wikipedia.py reads
    narrow_claims = {p: claims[p] for p in WANTED_WIKIDATA_PROPS if p in claims}
    return build_wikidata_dict(narrow_claims, labels)


def _as_list_cleaned(val):
    """Matches lib/wikipedia.py's repeated pattern: wrap non-list values in
    a list, strip trailing '(Q123)'/'(P123)' parenthetical suffixes."""
    if val is None:
        return ["Unknown"]  # UKN, matching lib/wikipedia.py's default
    if not isinstance(val, list):
        return [RE_PARENS.sub('', val)]
    return [RE_PARENS.sub('', v) for v in val]


def run_experiment(title):
    timing = {}
    t_total = time.perf_counter()

    infobox, err = fetch_infobox(title, timing)
    query_data = fetch_query(title, timing)
    wikidata = fetch_wikidata(title, timing)

    timing["total_sequential"] = time.perf_counter() - t_total

    # Exactly mirrors lib/wikipedia.py's get_firmographics() post-processing
    # for the fields this experiment covers, so the output is directly
    # comparable to what the live /wikipedia_firmographics endpoint returns.
    extext = query_data["extext"]
    description = extext.replace('\n', ' ').replace('**', '') if extext else "Unknown"

    website = wikidata.get("official website (P856)")
    website = [website.strip()] if isinstance(website, str) else (website or ["Unknown"])

    result = {
        "description": description,
        "wikipediaURL": query_data["url"],
        "industry": _as_list_cleaned(wikidata.get("industry (P452)")),
        "country": (RE_PARENS.sub('', wikidata["country (P17)"])
                    if isinstance(wikidata.get("country (P17)"), str)
                    else wikidata.get("country (P17)", "Unknown")),
        "website": website,
        "cik": wikidata.get("Central Index Key (P5531)", "Unknown"),
        "exchanges": _as_list_cleaned(wikidata.get("stock exchange (P414)")),
        "type": infobox.get("type") if infobox else None,
    }
    return result, timing


if __name__ == "__main__":
    companies = ["IBM", "Apple Inc.", "Microsoft", "Amazon (company)", "Tesla, Inc.",
                 "Alphabet Inc.", "Meta Platforms", "Walmart", "JPMorgan Chase", "ExxonMobil"]

    for name in companies:
        print(f"\n=== {name} ===")
        try:
            result, timing = run_experiment(name)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue
        for k, v in result.items():
            display = (v[:100] + "...") if isinstance(v, str) and len(v) > 100 else v
            print(f"  {k:15s}: {display!r}")
        print(f"  timing: parse={timing['parse']*1000:.0f}ms "
              f"query={timing['query']*1000:.0f}ms "
              f"wikidata_claims={timing['wikidata_claims']*1000:.0f}ms "
              f"wikidata_labels={timing['wikidata_labels']*1000:.0f}ms "
              f"(resolved {timing.get('wikidata_entities_resolved', 0)} entities) "
              f"TOTAL_SEQUENTIAL={timing['total_sequential']*1000:.0f}ms")
