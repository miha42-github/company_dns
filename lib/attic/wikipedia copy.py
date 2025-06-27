import wptools
import pprint
import re
import sys
import logging

__author__ = "Michael Hay"
__copyright__ = "Copyright 2025, Mediumroast, Inc. All rights reserved."
__license__ = "Apache 2.0"
__version__ = "1.2.0"
__maintainer__ = "Michael Hay"
__contact__ = 'https://github.com/miha42-github/company_dns'

#### Globals ####
# Used for setting attributes consistently when unknown
UKN = 'Unknown'

# Package and data dependencies
DEPENDENCIES = {
    'modules': {'wptools':'https://pypi.org/project/wptools/'},
    'data': {'wikiData': 'https://www.wikidata.org/wiki/Wikidata:Data_access'}
}

class WikipediaQueries:
    def __init__(self, name='wikipedia', description='A module and simple CLI too to search for company data in wikipedia.'):
        self.query = None
        self.NAME = name
        self.DESC = description
        # Construct the logger
        self.logger = logging.getLogger(self.NAME)
        # What we are are to query
        self.query = None

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
                'message': f'Unable to find a company by the name [{self.query}]. Maybe you should try an alternative structure like [{self.query} Inc.,{self.query} Corp., or {self.query} Corporation].',
                'error': 'LookupError',
                'module': my_class + '-> ' + my_function,
                'dependencies': DEPENDENCIES,
                'data': {
                    'total': 0,
                    'results': []
                }
            }

        # TODO try to do the right thing by trying different common combinations like Company, Inc.; Company Corp, etc.
        # Log the start of this process including self.query
        self.logger.info(f'Starting retrieval of firmographics for [{self.query}] via its wikipedia page.')
        company_page = None
        try:
            company_page = wptools.page(self.query, silent=True)
            if not company_page:
                self.logger.error(f'A wikipedia page for [{self.query}] was not found.')
                return lookup_error
            # Log the completion of the page creation
            self.logger.debug(f'Page results for [{self.query}]: {company_page}')
        except Exception as e:
            self.logger.error(f'A wikipedia page for [{self.query}] was not found due to [{e}].')
            return lookup_error

        # Prepare to get the infoblox for the company
        # Log the start of the process to get the infobox for the company
        self.logger.info(f'Starting process to retrieve infobox for [{self.query}].')
        parse_results = None
        try:
            parse_results = company_page.get_parse(show=False)
            if not parse_results.data['infobox']:
                self.logger.error('An infobox for [' + self.query + '] was not found.')
                return lookup_error
            # Log the completion of the infobox creation
            self.logger.info('Completed infobox retrieval for [' + self.query + '].')
        except Exception as e:
            self.logger.error(f'An infobox for [{self.query}] was not found due to [{e}].')
            return lookup_error
        
        # Get the company info from the infobox
        company_info = None
        try:
            company_info = parse_results.data['infobox']
            if not company_info: 
                self.logger.error('An infobox for [' + self.query + '] was not found.')
                return lookup_error
            self.logger.info('Completed infobox parse for [' + self.query + '].')
        except Exception as e:
            self.logger.error(f'An infobox for [{self.query}] was not found due to [{e}].')
            return lookup_error

        # Obtain the query results
        try:
            # Log the start of the process to get the query results for the company
            self.logger.info('Starting get query for [' + self.query + '].')
            query_results = company_page.get_query(show=False)
            # Log the completion of the query results for the company
            self.logger.info('Completed get query for [' + self.query + '].')
        except:
            return lookup_error
        
        # Try to get the wikidata for the company
        try:
            # Log the start of the process to get the wikidata for the company
            self.logger.info('Starting wikidata retrieval for [' + self.query + '].')
            page_data = company_page.get_wikidata(show=False)
            # Log the completion of the wikidata for the company
            self.logger.info('Completed wikidata retrieval for [' + self.query + '].')
        except:
            return lookup_error

        # Log the beginning of the firmographics data extraction
        self.logger.info('Starting firmographics data extraction for [' + self.query + '].')

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
        firmographics['city'] = firmographics['city'].replace('[[', '').replace(']]', '') if re.search(r'(\[)|(\])', firmographics['city']) else firmographics['city']
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
        
        # Log the completion of the firmographics data extraction
        self.logger.info('Completed firmographics data extraction for [' + self.query + '].')

        return {
                'code': 200,
                'message': 'Discovered and returning wikipedia data for the company [' + self.query + '].',
                'module': my_class + '-> ' + my_function,
                'data': firmographics,
                'dependencies': DEPENDENCIES
        }