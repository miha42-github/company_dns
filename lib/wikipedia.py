import wptools
import pprint
import re
import sys
import logging
import time
import concurrent.futures

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

# Precompiled regex patterns for better performance
RE_BRACKETS = re.compile(r'\[\[|\]\]')
RE_PARENS = re.compile(r'\s*\(\S+\)$')
RE_PIPES = re.compile(r'\|')
RE_BRACES = re.compile(r'\{\{.+?\|.+?\}\}')
RE_BR = re.compile(r'<br>')

class WikipediaQueries:
    def __init__(self, name='wikipedia', description='A module and simple CLI too to search for company data in wikipedia.'):
        self.query = None
        self.NAME = name
        self.DESC = description
        # Construct the logger
        self.logger = logging.getLogger(self.NAME)
        # What we are are to query
        self.query = None

    # Update _get_item method
    def _get_item(self, obj, variants, rules, idx):
        for variant in variants:
            if variant in obj:
                # Remove the unnecessary characters
                tmp_item = obj[variant].strip(rules)
                # If there are pipes then get rid of them
                if RE_PIPES.search(tmp_item):
                    return tmp_item.split('|')[idx]  
                else: 
                    return tmp_item
            else:
                continue
        return UKN
    
    # Update _transform_isin method
    def _transform_isin(self, isin):
        tmp_item = str()
        if 'ISIN' in isin:
            try:
                tmp_item = RE_BRACES.findall(isin.strip())[-1]
                tmp_item = tmp_item.strip('{}')
                return tmp_item.split('|')[-1]
            except (IndexError, AttributeError):
                return UKN
        else:
            tmp_item = isin.strip('{}')
        return tmp_item

    # Update _transform_stock_ticker method
    def _transform_stock_ticker(self, traded_as):
        try:
            tmp_match = RE_BRACES.findall(traded_as.strip())[-1]
            tmp_match = tmp_match.strip('{}')

            exchange = None
            ticker = None
            try:
                parts = RE_PIPES.split(tmp_match)
                exchange, ticker = parts[0], parts[1]
            except:
                exchange, ticker = UKN, UKN

            return [exchange, ticker]
        except (IndexError, AttributeError):
            return [UKN, UKN]


    def get_firmographics(self, fields=None):
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Start timing the entire operation
        total_start_time = time.time()
        self.logger.info(f'Starting retrieval of firmographics for [{self.query}] via its wikipedia page.')

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

        # Track all timing separately
        page_creation_start = time.time()
        # Create the page object once
        company_page = wptools.page(self.query, silent=True)
        page_elapsed = time.time() - page_creation_start

        # Execute API calls in parallel
        parallel_api_start = time.time()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            # Submit all tasks
            parse_future = executor.submit(company_page.get_parse, show=False)
            query_future = executor.submit(company_page.get_query, show=False)
            wikidata_future = executor.submit(company_page.get_wikidata, show=False)
            
            # Get results as they complete
            try:
                parse_results = parse_future.result()
                query_results = query_future.result()
                page_data = wikidata_future.result()
            except Exception as e:
                parallel_api_elapsed = time.time() - parallel_api_start
                self.logger.error(f"Error retrieving data for [{self.query}]: {str(e)} after {parallel_api_elapsed:.3f} seconds")
                return lookup_error
    
        parallel_api_elapsed = time.time() - parallel_api_start
        self.logger.info(f'Completed parallel API calls for [{self.query}] in {parallel_api_elapsed:.3f} seconds')

        # Prepare to get the infoblox for the company
        parse_start_time = time.time()
        self.logger.info(f'Starting process to retrieve infobox for [{self.query}].')
        parse_results = None
        try:
            parse_results = company_page.get_parse(show=False)
            if not parse_results.data['infobox']: # type: ignore
                parse_elapsed = time.time() - parse_start_time
                self.logger.error(f'An infobox for [{self.query}] was not found. Operation took {parse_elapsed:.3f} seconds')
                return lookup_error
            parse_elapsed = time.time() - parse_start_time
            self.logger.info(f'Completed infobox retrieval for [{self.query}] in {parse_elapsed:.3f} seconds')
        except Exception as e:
            parse_elapsed = time.time() - parse_start_time
            self.logger.error(f'An infobox for [{self.query}] was not found due to [{e}]. Operation took {parse_elapsed:.3f} seconds')
            return lookup_error
        
        # Get the company info from the infobox
        infobox_start_time = time.time()
        company_info = None
        try:
            company_info = parse_results.data['infobox'] # type: ignore
            if not company_info: 
                infobox_elapsed = time.time() - infobox_start_time
                self.logger.error(f'An infobox for [{self.query}] was not found. Operation took {infobox_elapsed:.3f} seconds')
                return lookup_error
            infobox_elapsed = time.time() - infobox_start_time
            self.logger.info(f'Completed infobox parse for [{self.query}] in {infobox_elapsed:.3f} seconds')
        except Exception as e:
            infobox_elapsed = time.time() - infobox_start_time
            self.logger.error(f'An infobox for [{self.query}] was not found due to [{e}]. Operation took {infobox_elapsed:.3f} seconds')
            return lookup_error

        # Obtain the query results
        query_start_time = time.time()
        try:
            self.logger.info(f'Starting get query for [{self.query}].')
            query_results = company_page.get_query(show=False)
            query_elapsed = time.time() - query_start_time
            self.logger.info(f'Completed get query for [{self.query}] in {query_elapsed:.3f} seconds')
        except Exception as e:
            query_elapsed = time.time() - query_start_time
            self.logger.error(f'Query for [{self.query}] failed due to [{e}]. Operation took {query_elapsed:.3f} seconds')
            return lookup_error
        
        # Try to get the wikidata for the company
        wikidata_start_time = time.time()
        try:
            self.logger.info(f'Starting wikidata retrieval for [{self.query}].')
            page_data = company_page.get_wikidata(show=False)
            wikidata_elapsed = time.time() - wikidata_start_time
            self.logger.info(f'Completed wikidata retrieval for [{self.query}] in {wikidata_elapsed:.3f} seconds')
        except Exception as e:
            wikidata_elapsed = time.time() - wikidata_start_time
            self.logger.error(f'Wikidata retrieval for [{self.query}] failed due to [{e}]. Operation took {wikidata_elapsed:.3f} seconds')
            return lookup_error

        # Log the beginning of the firmographics data extraction
        extraction_start_time = time.time()
        self.logger.info(f'Starting firmographics data extraction for [{self.query}].')

        # Set the description
        desc_start_time = time.time()
        # Don't store the entire HTML content if not needed
        if 'extext' in query_results.data: # type: ignore
            firmographics['description'] = query_results.data['extext'].replace('\n', ' ').replace('**', '') # type: ignore
            # Remove the original text to save memory
            del query_results.data['extext'] # type: ignore
        desc_elapsed = time.time() - desc_start_time
        self.logger.debug(f'Description extraction completed in {desc_elapsed:.3f} seconds')

        # Wikipedia page URL
        firmographics['wikipediaURL'] = query_results.data['url'] # type: ignore

        # Company type
        type_start_time = time.time()
        if 'type' in company_info:
            company_type = RE_BRACKETS.sub('', company_info['type'])
            if RE_PIPES.search(company_type):
                company_type = RE_PIPES.split(company_type)[0].strip()
            firmographics['type'] = company_type.split('(')[0].strip() if '(' in company_type else company_type
        else:
            firmographics['type'] = 'Private Company (Assumed)'
        type_elapsed = time.time() - type_start_time
        self.logger.debug(f'Company type extraction completed in {type_elapsed:.3f} seconds')

        # Industry ['industry (P452)'] <-- may contain more than one industry making this a list
        industry_start_time = time.time()
        firmographics['industry'] = page_data.data['wikidata'].get('industry (P452)', UKN) # type: ignore
        # In the case this isn't a list clean off the last bit of string data: <Industry Name> (123...N) <-- this last part should be removed
        if not isinstance(firmographics['industry'], list): 
            firmographics['industry'] = [RE_PARENS.sub('', firmographics['industry'])]
        else:
            firmographics['industry'] = [RE_PARENS.sub('', industry) for industry in firmographics['industry']]
        industry_elapsed = time.time() - industry_start_time
        self.logger.debug(f'Industry extraction completed in {industry_elapsed:.3f} seconds')

        # Formal company name
        firmographics['name'] = company_info.get('name', UKN)

        # Country ['country (P17)'] with a fallback to what is in company_info, the wikidata version is cleaner
        country_start_time = time.time()
        firmographics['country'] = page_data.data['wikidata']['country (P17)'] if 'country (P17)' in page_data.data['wikidata'] else self._get_item(company_info, ['location_country', 'hq_location_country'], r'[\[\]]', 0) # type: ignore
        if not isinstance(firmographics['country'], list): 
            firmographics['country'] = RE_PARENS.sub('', firmographics['country'])
        else:
            firmographics['country'] = [RE_PARENS.sub('', country) for country in firmographics['country']]
        country_elapsed = time.time() - country_start_time
        self.logger.debug(f'Country extraction completed in {country_elapsed:.3f} seconds')

        # City
        city_start_time = time.time()
        firmographics['city'] = self._get_item(company_info, ['location_city', 'hq_location_city', 'location'], r'\[\[\]\]', 0)
        firmographics['city'] = RE_BRACKETS.sub('', firmographics['city'])
        firmographics['city'] = RE_BR.sub(', ', firmographics['city'])
        city_elapsed = time.time() - city_start_time
        self.logger.debug(f'City extraction completed in {city_elapsed:.3f} seconds')

        # Website ['official website (P856)'] <-- This could be an array of multiple websites we will return all of them
        website_start_time = time.time()
        firmographics['website'] = page_data.data['wikidata']['official website (P856)'] if 'official website (P856)' in page_data.data['wikidata'] else self._get_item(company_info, ['website', 'homepage', 'url'], r'[\{\}]', 1) # type: ignore
        if not isinstance(firmographics['website'], list): 
            firmographics['website'] = [firmographics['website'].strip()]
        website_elapsed = time.time() - website_start_time
        self.logger.debug(f'Website extraction completed in {website_elapsed:.3f} seconds')

        # ISIN which is International Securities Identification Number
        isin_start_time = time.time()
        firmographics['isin'] = self._transform_isin(company_info['ISIN']) if 'ISIN' in company_info else UKN
        isin_elapsed = time.time() - isin_start_time
        self.logger.debug(f'ISIN extraction completed in {isin_elapsed:.3f} seconds')

        # CIK Central Index Key for Public companies
        # ['Central Index Key (P5531)'] <-- Exists if this is a public company in the US
        cik_start_time = time.time()
        firmographics['cik'] = page_data.data['wikidata'].get('Central Index Key (P5531)', UKN) # type: ignore
        cik_elapsed = time.time() - cik_start_time
        self.logger.debug(f'CIK extraction completed in {cik_elapsed:.3f} seconds')

        # Stock exchange ['stock exchange (P414)'] <-- potentially an array if the company is listed on multiple exchanges
        exchange_start_time = time.time()
        firmographics['exchanges'] = page_data.data['wikidata'].get('stock exchange (P414)', UKN) # type: ignore
        # In the case this isn't a list clean off the last bit of string data: <Exchange Name> (123...N) <-- this last part should be removed
        if not isinstance(firmographics['exchanges'], list): 
            firmographics['exchanges'] = [RE_PARENS.sub('', firmographics['exchanges'])]
        else:
            firmographics['exchanges'] = [RE_PARENS.sub('', exchange) for exchange in firmographics['exchanges']]
        exchange_elapsed = time.time() - exchange_start_time
        self.logger.debug(f'Stock exchange extraction completed in {exchange_elapsed:.3f} seconds')

        if 'traded_as' in company_info: 
            ticker_start_time = time.time()
            firmographics['tickers'] = self._transform_stock_ticker(company_info['traded_as'])
            ticker_elapsed = time.time() - ticker_start_time
            self.logger.debug(f'Ticker extraction completed in {ticker_elapsed:.3f} seconds')
        
        extraction_elapsed = time.time() - extraction_start_time
        total_elapsed = time.time() - total_start_time
        self.logger.info(f'Completed firmographics data extraction for [{self.query}] in {extraction_elapsed:.3f} seconds')
        self.logger.info(f'Total firmographics retrieval for [{self.query}] completed in {total_elapsed:.3f} seconds')

        # If fields is specified, only extract those fields
        if fields:
            # Create a subset of firmographics with only the requested fields
            result = {field: firmographics.get(field, UKN) for field in fields if field in firmographics}
        else:
            result = firmographics

        return {
                'code': 200,
                'message': f'Discovered and returning wikipedia data for the company [{self.query}].',
                'module': my_class + '-> ' + my_function,
                'data': result,
                'dependencies': DEPENDENCIES,
                'performance': {
                    'total_time': total_elapsed,
                    'page_creation': page_elapsed,
                    'parallel_api_time': parallel_api_elapsed,
                    'parse_time': parse_elapsed if 'parse_elapsed' in locals() else 0,
                    'infobox_time': infobox_elapsed if 'infobox_elapsed' in locals() else 0,
                    'query_time': query_elapsed if 'query_elapsed' in locals() else 0,
                    'wikidata_time': wikidata_elapsed if 'wikidata_elapsed' in locals() else 0,
                    'extraction_time': extraction_elapsed
                }
        }

    # Add static resource pool
    _page_pool = []
    _pool_size = 5

    # Get a page object from the pool
    def _get_page_object(self):
        if WikipediaQueries._page_pool:
            page = WikipediaQueries._page_pool.pop()
            page.refresh(self.query)
        else:
            page = wptools.page(self.query, silent=True)
        return page

    # Return a page object to the pool
    def _return_page_object(self, page):
        if len(WikipediaQueries._page_pool) < WikipediaQueries._pool_size:
            WikipediaQueries._page_pool.append(page)