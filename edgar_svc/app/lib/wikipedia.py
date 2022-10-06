#!/usr/local/bin/python3
import wptools
import pprint
import re
import sys

__author__ = "Michael Hay"
__copyright__ = "Copyright 2022, Mediumroast, Inc. All rights reserved."
__license__ = "Apache 2.0"
__version__ = "1.0.0"
__maintainer__ = "Michael Hay"
__status__ = "Alpha"
__date__ = '2022-October-4'

#### Globals ####
UKN = 'Unknown'

class WikipediaQueries:
    def __init__(self, company_name):
        self.company_name = company_name

    def _get_item(self, obj, variants, rules, idx):
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

    def _transform_stock_ticker(self, traded_as):
        """Transformation of the traded_as into sufficient stock exchange and ticker

        {{Unbulleted list'
                      '   | |NASDAQ|TSLA|'
                      '   | [[Nasdaq-100]] component'
                      '   | [[S&P 100]] component'
                      '   | [[S&P 500]] component}} {{NASDAQ|TSLA}}' <-- Get this last part as it is consistent
        """
        tmp_match = re.search(r'{{.*\w+\|\w+}}', traded_as)
        
        # {{NASDAQ|TSLA}}
        tmp_stock = str(tmp_match.group())
        
        # NASDAQ|TSLA
        tmp_stock = tmp_stock.strip(r'[\{\}]')

        # [NASDAQ, TSLA]
        return tmp_stock.split('|')


    def get_firmographics(self):

        # Store data here for return to the caller
        firmographics = dict()

        company_page = wptools.page(self.company_name, silent=True)
        parse_results = company_page.get_parse(show=False)
        query_results = company_page.get_query(show=False)
        company_info = parse_results.data['infobox']
        page_data = company_page.get_wikidata()
        # pprint.pprint(page_data.data['wikidata'])

        # ['industry (P452)'] <-- May not always exist
        # ['official website (P856)']
        # ['official name (P1448)']
        # ['country (P17)']
        # ['official website (P856)']
        # ['headquarters location (P159)']
        # ['Central Index Key (P5531)'] <-- Exists if this is a public company


        # Set the description
        firmographics['description'] = query_results.data['extext'].replace('\n', ' ').replace('**', '')

        # Wikipedia page URL
        firmographics['wikipediaURL'] = query_results.data['url']

        # Get additional detail
        # company_info = parse_results.data['infobox']['traded_as']
        # pprint.pprint(company_info)

        # Company type
        # [[Public company|Public]] This is the format if a public company, but others are different
        firmographics['type'] = company_info['type'].strip(r'[\[\]]') if 'type' in company_info else 'Private Company'
        firmographics['type'] = firmographics['type'].split('|')[0] if re.search(r'\|', firmographics['type']) else firmographics['type']

        # Industry TODO You are here and need to perform a standard and fallback operation
        # firmographics['industry'] = company_info['industry'].strip(r'[\[\]]') if 'industry' in company_info else UKN
        # firmographics['industry']= firmographics['industry'].replace('|', ', ')
        # firmographics['industry'] = page_data.data['wikidata']['industry (P452)']

        # Formal company name
        firmographics['name'] = company_info['name'] if 'name' in company_info else UKN

        # Location
        # TODO there appear to be many variations including, location, location_city + location_country, 
        # hq_location_* some grace is needed here
        firmographics['country'] = page_data.data['wikidata']['country (P17)'] if 'country (P17)' in page_data.data['wikidata'] else self._get_item(company_info, ['location_country', 'hq_location_country'], r'[\[\]]', 0)
        firmographics['country'] = re.sub(r'\s*\(\S+\)$', '', firmographics['country'])

        # firmographics['city'] = self._get_item(company_info, ['location_city', 'hq_location_city'], r'[\[\]]', 0)

        # Website
        firmographics['website'] = page_data.data['wikidata']['official website (P856)'] if 'official website (P856)' in page_data.data['wikidata'] else self._get_item(company_info, ['website', 'homepage', 'url'], r'[\{\}]', 1)

        # ISIN which is International Securities Identification Number
        firmographics['isin'] = company_info['ISIN'] if 'ISIN' in company_info else UKN

        # CIK Central Index Key for Public companies
        firmographics['cik'] = page_data.data['wikidata']['Central Index Key (P5531)'] if 'Central Index Key (P5531)' in page_data.data['wikidata'] else UKN

        # # Stock information if available
        # [firmographics['exchanges'], firmographics['tickers']] = self._transform_stock_ticker(company_info['traded_as'])

        # # Temporarily store for development
        # firmographics['all'] = company_info

        return firmographics   


if __name__ == '__main__':
    company_name = sys.argv[1]
    query = WikipediaQueries(company_name)
    firmographics = query.get_firmographics()
    pprint.pprint(firmographics)