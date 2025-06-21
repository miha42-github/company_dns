#!/usr/bin/env python3
"""
Generate endpoint documentation from company_dns.py
This script parses the company_dns.py file to extract all API endpoints
and generates a JavaScript file with the endpoint definitions.
"""

import re
import os
import json
from collections import defaultdict

# Define path to company_dns.py and output file
COMPANY_DNS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "company_dns.py")
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "html", "endpoint-data.js")

# Regular expression to find Route definitions
ROUTE_PATTERN = r"Route\(['\"](?P<path>/V\d+\.\d+/[^'\"]+)['\"],\s*(?P<handler>[^,\)]+)"

# Dictionary to map handlers to descriptions
HANDLER_DESCRIPTIONS = {
    "sic_description": "Accepts a string containing a SIC description of interest, returns all SIC descriptions that matched the full or partial string.",
    "sic_code": "Accepts a string containing a SIC of interest, returns all SICs that matched the full or partial string.",
    "division_code": "Accepts a string containing a division id of interest, returns the SIC division description that matches the id.",
    "industry_code": "Accepts a string containing an industry group number of interest, returns the SIC industry group information that matches the number.",
    "major_code": "Accepts a string containing a major group number of interest, returns the SIC major group information that matches the number.",
    "edgar_detail": "Accepts a company search string, returns detailed EDGAR firmographics data for one or more companies.",
    "edgar_summary": "Accepts a company search string, returns summary EDGAR firmographics data for one or more companies.",
    "edgar_ciks": "Accepts a company search string of interest, returns a pairing of company names to CIKs.",
    "edgar_firmographics": "Accepts a string with a CIK (Central Index Key) for a company, returns EDGAR firmographics detail for that company.",
    "wikipedia_firmographics": "Accepts a string with a company name of interest, returns Wikipedia firmographics detail.",
    "general_query": "Accepts a string containing a company name of interest, returns merged EDGAR and Wikipedia firmographics detail.",
    "uk_sic_description": "Accepts a string containing a UK SIC description of interest, returns all UK SIC descriptions that matched the full or partial string.",
    "uk_sic_code": "Accepts a string containing a UK SIC code of interest, returns all UK SICs that matched the full or partial string.",
    "international_sic_section": "Accepts a string containing a section code, returns data about the matching ISIC section.",
    "international_sic_division": "Accepts a string containing a division code, returns data about the matching ISIC division.",
    "international_sic_group": "Accepts a string containing a group code, returns data about the matching ISIC group.",
    "international_sic_class": "Accepts a string containing a class code, returns data about the matching ISIC class.",
    "international_sic_class_description": "Accepts a string containing a description, returns ISIC classes matching the description.",
    "japan_sic_division": "Accepts a string containing a division code, returns data about the matching Japan SIC division.",
    "japan_sic_major_group": "Accepts a string containing a major group code, returns data about the matching Japan SIC major group.",
    "japan_sic_group": "Accepts a string containing a group code, returns data about the matching Japan SIC group.",
    "japan_sic_industry_group": "Accepts a string containing an industry code, returns data about the matching Japan SIC industry group.",
    "japan_sic_industry_group_description": "Accepts a string containing a description, returns Japan SIC industry groups matching the description.",
    "eu_sic_section": "Accepts a string containing a section code, returns data about the matching EU SIC (NACE) section.",
    "eu_sic_division": "Accepts a string containing a division code, returns data about the matching EU SIC (NACE) division.",
    "eu_sic_group": "Accepts a string containing a group code, returns data about the matching EU SIC (NACE) group.",
    "eu_sic_class": "Accepts a string containing a class code, returns data about the matching EU SIC (NACE) class.",
    "eu_sic_class_description": "Accepts a string containing a description, returns EU SIC (NACE) classes matching the description.",
}

# Dictionary to map endpoints to friendly names
ENDPOINT_FRIENDLY_NAMES = {
    "/na/companies/edgar/detail/": "EDGAR Detail",
    "/na/companies/edgar/summary/": "EDGAR Summary",
    "/na/companies/edgar/ciks/": "Company CIK Search",
    "/na/company/edgar/firmographics/": "CIK Firmographics",
    "/global/company/wikipedia/firmographics/": "Company Wikipedia",
    "/global/company/merged/firmographics/": "Merged Firmographics",
    "/na/sic/description/": "SIC Description",
    "/na/sic/code/": "SIC Code",
    "/na/sic/division/": "SIC Division",
    "/na/sic/industry/": "SIC Industry",
    "/na/sic/major/": "SIC Major",
    "/uk/sic/description/": "UK SIC Description",
    "/uk/sic/code/": "UK SIC Code",
    "/international/sic/section/": "International SIC Section",
    "/international/sic/division/": "International SIC Division",
    "/international/sic/group/": "International SIC Group",
    "/international/sic/class/": "International SIC Class",
    "/international/sic/description/": "International SIC Description",
    # V2.0 endpoints
    "/companies/edgar/detail/": "EDGAR Detail",
    "/companies/edgar/summary/": "EDGAR Summary",
    "/companies/edgar/ciks/": "Company CIK Search",
    "/company/edgar/firmographics/": "CIK Firmographics",
    "/company/wikipedia/firmographics/": "Company Wikipedia",
    "/company/merged/firmographics/": "Merged Firmographics",
    "/sic/description/": "SIC Description",
    "/sic/code/": "SIC Code",
    "/sic/division/": "SIC Division",
    "/sic/industry/": "SIC Industry",
    "/sic/major/": "SIC Major",
    "/japan/sic/division/": "Japan SIC Division",
    "/japan/sic/major_group/": "Japan SIC Major Group",
    "/japan/sic/group/": "Japan SIC Group", 
    "/japan/sic/industry_group/": "Japan SIC Industry Group",
    "/japan/sic/description/": "Japan SIC Description",
}

def parse_endpoints():
    """Parse company_dns.py and extract endpoint definitions"""
    with open(COMPANY_DNS_PATH, 'r') as f:
        content = f.read()
    
    endpoints_data = defaultdict(dict)
    endpoints_map = defaultdict(dict)
    
    for match in re.finditer(ROUTE_PATTERN, content):
        path = match.group('path')
        handler = match.group('handler')
        
        # Extract version from path
        version_match = re.match(r"/(V\d+\.\d+)/", path)
        if not version_match:
            continue
            
        version = version_match.group(1)
        clean_path = re.sub(r"/{}".format(version), "", path, count=1)
        
        # Add to endpoints data
        endpoints_data[version][clean_path] = HANDLER_DESCRIPTIONS.get(
            handler, f"Handler: {handler}"
        )
        
        # Add to endpoints map
        friendly_name = ENDPOINT_FRIENDLY_NAMES.get(clean_path, clean_path)
        endpoints_map[version][friendly_name] = clean_path
    
    return {
        "endpointsData": dict(endpoints_data),
        "endpoints": dict(endpoints_map)
    }

def generate_js_file(endpoints_obj):
    """Generate JavaScript file with endpoint definitions"""
    js_content = """/**
 * Endpoint definitions for company_dns API
 * Auto-generated from company_dns.py - DO NOT EDIT MANUALLY
 */

const endpointsData = {json_endpoints};

const endpoints = {json_endpoint_map};
""".format(
        json_endpoints=json.dumps(endpoints_obj["endpointsData"], indent=2),
        json_endpoint_map=json.dumps(endpoints_obj["endpoints"], indent=2)
    )
    
    with open(OUTPUT_PATH, 'w') as f:
        f.write(js_content)
    
    print(f"Endpoint definitions written to {OUTPUT_PATH}")

if __name__ == "__main__":
    endpoints = parse_endpoints()
    generate_js_file(endpoints)