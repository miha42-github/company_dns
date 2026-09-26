"""
Curated set of well-known companies used by the performance baseline suite.

Each entry carries the different name/ID forms company_dns's various
endpoints expect, since they don't agree with each other:
  - edgar_name: a substring that matches EDGAR's official filer name via
    SQL LIKE '%edgar_name%' (used by the /companies/edgar/* endpoints).
    Note this is NOT always the common name - e.g. IBM's EDGAR filer name is
    "INTERNATIONAL BUSINESS MACHINES CORP", which doesn't contain "IBM".
  - wiki_name: the Wikipedia page title (used by /company/wikipedia/* and
    /company/merged/* endpoints).
  - cik: the company's SEC EDGAR Central Index Key, used by
    /company/edgar/firmographics/{cik} directly (no name search involved).

All ten were spot-checked against the live deployment
(https://company-dns.mediumroast.io) on 2026-09-27 and returned 200 on
every endpoint category below before being included here.
"""

COMPANIES = [
    {"key": "ibm", "edgar_name": "International Business Machines", "wiki_name": "IBM", "cik": "51143"},
    {"key": "apple", "edgar_name": "Apple", "wiki_name": "Apple Inc.", "cik": "320193"},
    {"key": "microsoft", "edgar_name": "Microsoft", "wiki_name": "Microsoft", "cik": "789019"},
    {"key": "amazon", "edgar_name": "Amazon", "wiki_name": "Amazon (company)", "cik": "1018724"},
    {"key": "alphabet", "edgar_name": "Alphabet", "wiki_name": "Alphabet Inc.", "cik": "1652044"},
    {"key": "tesla", "edgar_name": "Tesla", "wiki_name": "Tesla, Inc.", "cik": "1318605"},
    {"key": "meta", "edgar_name": "Meta Platforms", "wiki_name": "Meta Platforms", "cik": "1326801"},
    {"key": "walmart", "edgar_name": "Walmart", "wiki_name": "Walmart", "cik": "104169"},
    {"key": "jpmorgan", "edgar_name": "JPMorgan Chase", "wiki_name": "JPMorgan Chase", "cik": "19617"},
    {"key": "exxonmobil", "edgar_name": "Exxon Mobil", "wiki_name": "ExxonMobil", "cik": "34088"},
]
