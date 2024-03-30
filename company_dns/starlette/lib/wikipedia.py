#!/usr/local/bin/python3
import wptools
import pprint
import re
import sys
import argparse

__author__ = "Michael Hay"
__copyright__ = "Copyright 2023, Mediumroast, Inc. All rights reserved."
__license__ = "Apache 2.0"
__version__ = "1.1.0"
__maintainer__ = "Michael Hay"
__status__ = "Beta"
__date__ = '2023-April-1'
__contact__ = 'https://github.com/miha42-github/company_dns'

#### Globals ####
# Used for setting attributes consistently when unknown
UKN = 'Unknown'

# Determine how we output when executed as a CLI
DEBUG = None

# Package and data dependencies
DEPENDENCIES = {
    'modules': {'wptools':'https://pypi.org/project/wptools/'},
    'data': {'wikiData': 'https://www.wikidata.org/wiki/Wikidata:Data_access'}
}

class WikipediaQueries:
    def __init__(self, name='wikipedia', description='A module and simple CLI too to search for company data in wikipedia.'):
        self.company_name = None
        self.NAME = name
        self.DESC = description


    def get_cli_args(self):
        """Parse common CLI arguments including system configs and behavior switches.
        """
        # Set up the argument parser
        parser = argparse.ArgumentParser(prog=self.NAME, description=self.DESC)

        # Setup the command line switches
        parser.add_argument(
            '--company',
            help="Company name to search for in Wikipedia.",
            type=str,
            dest='company_name',
            required=True
        )
        parser.add_argument(
            "--debug",
            help="Turn on debugging",
            dest="debug",
            type=int,
            default=0,
        )

        # Parse the CLI
        cli_args = parser.parse_args()

        # Return parsed arguments
        return cli_args

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
    
    def _transform_isin(self, isin):
        tmp_item = str()
        if re.search('ISIN', isin):
            tmp_item = re.findall(r'\{\{.+?\|.+?\}\}', isin.strip())[-1]
            tmp_item = isin.strip(r'[\{\}]')
            tmp_item = tmp_item.split('|')[-1] 
        else:
            tmp_item = isin.strip(r'[\{\}]')
        return tmp_item

    def _transform_stock_ticker(self, traded_as):
        """Transformation of the traded_as into sufficient stock exchange and ticker

        {{Unbulleted list'
                      '   | |NASDAQ|TSLA|'
                      '   | [[Nasdaq-100]] component'
                      '   | [[S&P 100]] component'
                      '   | [[S&P 500]] component}} {{NASDAQ|TSLA}}' <-- Get this last part as it is consistent
        """
        tmp_match = re.findall(r'\{\{.+?\|.+?\}\}', traded_as.strip())[-1]

        # {{{NASDAQ|TSLA}} -> NASDAQ|TSLA
        tmp_match = tmp_match.strip(r'[\{\}]')

        # NASDAQ|TSLA -> [NASDAQ, TSLA]
        exchange = None
        ticker = None
        try:
            [exchange, ticker] = tmp_match.split('|')
        except:
            [exchange, ticker] = [UKN, UKN]

        return [exchange, ticker]


    def get_firmographics(self):
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__

        # Store data here for return to the caller
        firmographics = dict()

        # Define the common lookup_error
        lookup_error = {
                'code': 404,
                'message': 'Unable to find a company by the name [' + self.company_name + ']. Maybe you should try an alternative structure like [' + self.company_name + ' Inc.,' + self.company_name + ' Corp., or ' + self.company_name + ' Corporation].',
                'errorType': 'LookupError',
                'module': my_class + '-> ' + my_function,
                'dependencies': DEPENDENCIES
            }

        # TODO try to do the right thing by trying different common combinations like Company, Inc.; Company Corp, etc.
        try:
            company_page = wptools.page(self.company_name, silent=True)
        except:
            return lookup_error

        # Prepare to get the infoblox for the company
        try:
            parse_results = company_page.get_parse(show=False)
        except:
            return lookup_error
        
        company_info = parse_results.data['infobox']
        if not company_info: return lookup_error

        # Obtain the query results
        try:
            query_results = company_page.get_query(show=False)
        except:
            return lookup_error
        
        # Try to get the wikidata for the company
        try:
            page_data = company_page.get_wikidata(show=False)
        except:
            return lookup_error
        
        # Debugging output
        if DEBUG == 1: pprint.pprint(page_data.data['wikidata'])
        elif DEBUG == 2: pprint.pprint(company_info)

        # Set the description
        firmographics['description'] = query_results.data['extext'].replace('\n', ' ').replace('**', '')

        # Wikipedia page URL
        firmographics['wikipediaURL'] = query_results.data['url']

        # Company type
        # [[Public company|Public]] This is the format if a public company, but others can be different
        firmographics['type'] = re.sub(r'\[\[|\]\]', '', company_info['type']) if 'type' in company_info else 'Private Company (Assumed)'
        firmographics['type'] = firmographics['type'].split('|')[0].strip() if re.search(r'\|', firmographics['type']) else firmographics['type']
        firmographics['type'] = firmographics['type'].split('(')[0].strip() if re.search(r'\(', firmographics['type']) else firmographics['type']
        firmographics['type'] = firmographics['type'].strip(']') # if re.search(r'\]', firmographics['type']) else firmographics['type']
        firmographics['type'] = firmographics['type'].strip('[') # if re.search(r'\[', firmographics['type']) else firmographics['type']

        # Industry ['industry (P452)'] <-- may contain more than one industry making this a list
        firmographics['industry'] = page_data.data['wikidata']['industry (P452)'] if 'industry (P452)' in page_data.data['wikidata'] else UKN
        # In the case this isn't a list clean off the last bit of string data: <Industry Name> (123...N) <-- this last part should be removed
        if not type(firmographics['industry']) is list: 
            firmographics['industry'] = [re.sub(r'\s*\(\S+\)$', '', firmographics['industry'])]
        else:
            firmographics['industry'] = [re.sub(r'\s*\(\S+\)$', '', industry) for industry in firmographics['industry']]

        # Formal company name
        firmographics['name'] = company_info['name'] if 'name' in company_info else UKN

        # Country ['country (P17)'] with a fallback to what is in company_info, the wikidata version is cleaner
        firmographics['country'] = page_data.data['wikidata']['country (P17)'] if 'country (P17)' in page_data.data['wikidata'] else self._get_item(company_info, ['location_country', 'hq_location_country'], r'[\[\]]', 0)
        if not type(firmographics['country']) is list: 
            firmographics['country'] = re.sub(r'\s*\(\S+\)$', '', firmographics['country'])
        else:
            firmographics['country'] = [re.sub(r'\s*\(\S+\)$', '', country) for country in firmographics['country']]


        # City
        firmographics['city'] = self._get_item(company_info, ['location_city', 'hq_location_city', 'location'], r'\[\[\]\]', 0)
        firmographics['city'] = firmographics['city'].replace('[[', '').replace(']]', '') if re.search('(\[)|(\])', firmographics['city']) else firmographics['city']
        firmographics['city'] = firmographics['city'].replace('<br>', ', ') if re.search('<br>', firmographics['city']) else firmographics['city']


        # Website ['official website (P856)'] <-- This could be an array of multiple websites we will return all of them
        firmographics['website'] = page_data.data['wikidata']['official website (P856)'] if 'official website (P856)' in page_data.data['wikidata'] else self._get_item(company_info, ['website', 'homepage', 'url'], r'[\{\}]', 1)
        firmographics['website'] = [firmographics['website']] if type(firmographics['website']) is not list else firmographics['website']

        # ISIN which is International Securities Identification Number
        firmographics['isin'] = self._transform_isin(company_info['ISIN']) if 'ISIN' in company_info else UKN

        # CIK Central Index Key for Public companies
        # ['Central Index Key (P5531)'] <-- Exists if this is a public company in the US
        firmographics['cik'] = page_data.data['wikidata']['Central Index Key (P5531)'] if 'Central Index Key (P5531)' in page_data.data['wikidata'] else UKN

        # Stock information if available
        # [firmographics['exchanges'], firmographics['tickers']] = self._transform_stock_ticker(company_info['traded_as'])
        
        # Stock exchange ['stock exchange (P414)'] <-- potentially an array if the company is listed on multiple exchanges
        firmographics['exchanges'] = page_data.data['wikidata']['stock exchange (P414)'] if 'stock exchange (P414)' in page_data.data['wikidata'] else UKN
        # In the case this isn't a list clean off the last bit of string data: <Exchange Name> (123...N) <-- this last part should be removed
        if not type(firmographics['exchanges']) is list: 
            firmographics['exchanges'] = [re.sub(r'\s*\(\S+\)$', '', firmographics['exchanges'])]
        else:
            firmographics['exchanges'] = [re.sub(r'\s*\(\S+\)$', '', exchange) for exchange in firmographics['exchanges']]

        if 'traded_as' in company_info: firmographics['tickers'] = self._transform_stock_ticker(company_info['traded_as'])

        return {
                'code': 200,
                'message': 'Discovered and returning wikipedia data for the company [' + self.company_name + '].',
                'module': my_class + '-> ' + my_function,
                'data': firmographics,
                'dependencies': DEPENDENCIES
        }
           


if __name__ == '__main__':
    query = WikipediaQueries()
    cli_args = query.get_cli_args()
    query.company_name = cli_args.company_name
    DEBUG = cli_args.debug
    firmographics = query.get_firmographics()
    if not DEBUG: pprint.pprint(firmographics)