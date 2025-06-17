/**
 * Endpoint definitions for company_dns API
 * Auto-generated from company_dns.py - DO NOT EDIT MANUALLY
 */

const endpointsData = {
  "V2.0": {
    "/companies/edgar/detail/": "Accepts a company search string, returns detailed EDGAR firmographics data for one or more companies.",
    "/companies/edgar/summary/": "Accepts a company search string, returns summary EDGAR firmographics data for one or more companies.",
    "/companies/edgar/ciks/": "Accepts a company search string of interest, returns a pairing of company names to CIKs.",
    "/company/edgar/firmographics/": "Accepts a string with a CIK (Central Index Key) for a company, returns EDGAR firmographics detail for that company.",
    "/company/wikipedia/firmographics/": "Accepts a string with a company name of interest, returns Wikipedia firmographics detail.",
    "/company/merged/firmographics/": "Accepts a string containing a company name of interest, returns merged EDGAR and Wikipedia firmographics detail.",
    "/sic/description/": "Accepts a string containing a SIC description of interest, returns all SIC descriptions that matched the full or partial string.",
    "/sic/code/": "Accepts a string containing a SIC of interest, returns all SICs that matched the full or partial string.",
    "/sic/division/": "Accepts a string containing a division id of interest, returns the SIC division description that matches the id.",
    "/sic/industry/": "Accepts a string containing an industry group number of interest, returns the SIC industry group information that matches the number.",
    "/sic/major/": "Accepts a string containing a major group number of interest, returns the SIC major group information that matches the number."
  },
  "V3.0": {
    "/na/companies/edgar/detail/": "Accepts a company search string, returns detailed EDGAR firmographics data for one or more companies.",
    "/na/companies/edgar/summary/": "Accepts a company search string, returns summary EDGAR firmographics data for one or more companies.",
    "/na/companies/edgar/ciks/": "Accepts a company search string of interest, returns a pairing of company names to CIKs.",
    "/na/company/edgar/firmographics/": "Accepts a string with a CIK (Central Index Key) for a company, returns EDGAR firmographics detail for that company.",
    "/global/company/wikipedia/firmographics/": "Accepts a string with a company name of interest, returns Wikipedia firmographics detail.",
    "/global/company/merged/firmographics/": "Accepts a string containing a company name of interest, returns merged EDGAR and Wikipedia firmographics detail.",
    "/na/sic/description/": "Accepts a string containing a SIC description of interest, returns all SIC descriptions that matched the full or partial string.",
    "/na/sic/code/": "Accepts a string containing a SIC of interest, returns all SICs that matched the full or partial string.",
    "/na/sic/division/": "Accepts a string containing a division id of interest, returns the SIC division description that matches the id.",
    "/na/sic/industry/": "Accepts a string containing an industry group number of interest, returns the SIC industry group information that matches the number.",
    "/na/sic/major/": "Accepts a string containing a major group number of interest, returns the SIC major group information that matches the number.",
    "/uk/sic/description/": "Accepts a string containing a UK SIC description of interest, returns all UK SIC descriptions that matched the full or partial string.",
    "/uk/sic/code/": "Accepts a string containing a UK SIC code of interest, returns all UK SICs that matched the full or partial string.",
    "/international/sic/section/": "Accepts a string containing a section code, returns data about the matching ISIC section.",
    "/international/sic/division/": "Accepts a string containing a division code, returns data about the matching ISIC division.",
    "/international/sic/group/": "Accepts a string containing a group code, returns data about the matching ISIC group.",
    "/international/sic/class/": "Accepts a string containing a class code, returns data about the matching ISIC class.",
    "/international/sic/description/": "Accepts a string containing a description, returns ISIC classes matching the description."
  }
};

const endpoints = {
  "V3.0": {
    "EDGAR Detail": "/na/companies/edgar/detail/",
    "EDGAR Summary": "/na/companies/edgar/summary/",
    "Company CIK Search": "/na/companies/edgar/ciks/",
    "CIK Firmographics": "/na/company/edgar/firmographics/",
    "Company Wikipedia": "/global/company/wikipedia/firmographics/",
    "Merged Firmographics": "/global/company/merged/firmographics/",
    "SIC Description": "/na/sic/description/",
    "SIC Code": "/na/sic/code/",
    "SIC Division": "/na/sic/division/",
    "SIC Industry": "/na/sic/industry/",
    "SIC Major": "/na/sic/major/",
    "UK SIC Description": "/uk/sic/description/",
    "UK SIC Code": "/uk/sic/code/",
    "International SIC Section": "/international/sic/section/",
    "International SIC Division": "/international/sic/division/",
    "International SIC Group": "/international/sic/group/",
    "International SIC Class": "/international/sic/class/",
    "International SIC Description": "/international/sic/description/"
  },
  "V2.0": {
    "EDGAR Detail": "/companies/edgar/detail/",
    "EDGAR Summary": "/companies/edgar/summary/",
    "Company CIK Search": "/companies/edgar/ciks/",
    "CIK Firmographics": "/company/edgar/firmographics/",
    "Company Wikipedia": "/company/wikipedia/firmographics/",
    "Merged Firmographics": "/company/merged/firmographics/",
    "SIC Description": "/sic/description/",
    "SIC Code": "/sic/code/",
    "SIC Division": "/sic/division/",
    "SIC Industry": "/sic/industry/",
    "SIC Major": "/sic/major/"
  }
};