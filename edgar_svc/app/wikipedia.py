#!/usr/bin/python3
import wptools
import pprint
import re
import sys

UKN = 'Unknown'

def _get_item(obj, variants, rules, idx):
    for variant in variants:
        if variant in obj:
            # Remove the uncessary characters
            tmp_item = obj[variant].strip(rules)
            # If there are pipes then get rid of them
            # TODO this might not be so general purpose check it out
            if re.search(r'\|', tmp_item):
                return tmp_item.split('|')[idx]  
            else: 
                return tmp_item
        else:
            continue
    return UKN


# Store data here for return to the caller
firmographics = dict()

company = sys.argv[1]

company_page = wptools.page(company, silent=True)
parse_results = company_page.get_parse(show=False)
query_results = company_page.get_query(show=False)

# Set the description
firmographics['description'] = query_results.data['extext'].replace('\n', ' ').replace('**', '')

# Wikipedia page URL
firmographics['wikipedia_url'] = query_results.data['url']

# Get additional detail
company_info = parse_results.data['infobox']

# Company type
# [[Public company|Public]] This is the format if a public company, but others are different
firmographics['type'] = company_info['type'].strip(r'[\[\]]') if 'type' in company_info else 'Private Company'
firmographics['type'] = firmographics['type'].split('|')[0] if re.search(r'\|', firmographics['type']) else firmographics['type']

# Industry
firmographics['industry'] = company_info['industry'].strip(r'[\[\]]') if 'industry' in company_info else UKN

# Formal company name
firmographics['name'] = company_info['name'] if 'name' in company_info else UKN

# Location
# TODO there appear to be many variations including, location, location_city + location_country, 
# hq_location_* some grace is needed here
firmographics['country'] = _get_item(company_info, ['location_country', 'hq_location_country'], r'[\[\]]', 0)
firmographics['city'] = _get_item(company_info, ['location_city', 'hq_location_city'], r'[\[\]]', 0)

# Website
firmographics['url'] = _get_item(company_info, ['website', 'homepage', 'url'], r'[\{\}]', 1)

# ISIN which is International Securities Identification Number
firmographics['isin'] = company_info['ISIN'] if 'ISIN' in company_info else UKN

firmographics['all'] = company_info   


pprint.pprint(firmographics)