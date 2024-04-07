#!/usr/local/bin/python3

from . import edgar
from . import wikipedia
import argparse
import pprint
import sys
import urllib.parse as url_parse
import logging
from geopy.geocoders import ArcGIS

__author__ = "Michael Hay"
__copyright__ = "Copyright 2023, Mediumroast, Inc. All rights reserved."
__license__ = "Apache 2.0"
__version__ = "2.1.0"
__maintainer__ = "Michael Hay"
__status__ = "Alpha"
__date__ = '2023-April-1'
__contact__ = 'https://github.com/miha42-github/company_dns'

#### Globals ####
# Used for setting attributes consistently when unknown
UKN = "Unknown"

# Determine how we output when executed as a CLI
DEBUG = None

# Package and data dependencies
DEPENDENCIES = {
    'modules': {
        'edgar': 'https://github.com/miha42-github/company_dns',
        'wikipedia': 'https://github.com/miha42-github/company_dns',
        'wptools': 'https://pypi.org/project/wptools/',
        'geopy': 'https://pypi.org/project/geopy/'
    },
    'data': {
        'sicData': 'https://github.com/miha42-github/sic4-list',
        'oshaSICQuery': 'https://www.osha.gov/data/sic-search',
        'wikiData': 'https://www.wikidata.org/wiki/Wikidata:Data_access'
    }
}

# Helpers for helper URLs
MAPSURL = 'https://www.google.com/maps/place/'
PATENTSURL = 'https://patents.google.com/?assignee='
NEWSURL = 'https://news.google.com/search?q='
FINANCEURL = 'https://www.google.com/finance/quote/'

class GeneralQueries:
    def __init__(
        self,
        database=None,
        name='general', 
        description='A module and simple CLI too to search for company data in Wikipedia, EDGAR, and also a merger of the two data sources.'):
        
        # Construct the object to determine lat long pairs
        self.locator = ArcGIS(timeout=2, user_agent="company_dns")

        # Contains the company name or CIK
        self.query = None

        # Command line naming helpers
        self.NAME = name
        self.DESC = description

        # Define the db_cache location
        self.db_file='./company_dns.db' if database is None else database

        # Set up the logging
        self.logger = logging.getLogger(self.NAME)

    def get_cli_args(self):
        """Parse common CLI arguments including system configs and behavior switches.
        """
        # Set up the argument parser
        parser = argparse.ArgumentParser(prog=self.NAME, description=self.DESC)

        # Setup the command line switches
        parser.add_argument(
            '--query',
            help="Company name to search for in Wikipedia or EDGAR",
            type=str,
            dest='query',
            required=True
        )
        parser.add_argument(
            "--debug",
            help="Turn on debugging",
            dest="debug",
            type=int,
            default=0,
        )
        parser.add_argument(
            '--operation',
            help="Company name to search for in Wikipedia.",
            type=str,
            dest='operation',
            choices=['merge', 'ciks', 'details', 'summaries', 'firmographics_wiki', 'firmographics_edgar'],
            default='merge',
            required=True
        )

        # Parse the CLI
        cli_args = parser.parse_args()

        # Return parsed arguments
        return cli_args
    
    def locate (self, place):
        # Log the place to locate via a debug message
        self.logger.debug('Locating the place [' + place + ']')
        l = self.locator.geocode(place)
        # Log the location data
        self.logger.debug('Location data for [' + place + '] is [' + str(l) + ']')
        return l.longitude, l.latitude, l.address, l.raw

    def get_firmographics_wikipedia(self):
        my_query = wikipedia.WikipediaQueries()
        my_query.query = self.query
        return my_query.get_firmographics()

    def get_firmographics_edgar(self):
        my_query = edgar.EdgarQueries(db_file=self.db_file)
        my_query.query = self.query
        return my_query.get_firmographics(self.query)

    def get_all_ciks(self):
        my_query = edgar.EdgarQueries(db_file=self.db_file)
        my_query.query = self.query
        return my_query.get_all_ciks()

    def get_all_summaries(self):
        my_query = edgar.EdgarQueries(db_file=self.db_file)
        my_query.query = self.query
        return my_query.get_all_details(firmographics=False)

    def get_all_details(self):
        my_query = edgar.EdgarQueries(db_file=self.db_file)
        my_query.query = self.query
        return my_query.get_all_details(firmographics=True)

    def _augment_wikidata(self, wiki_return):
        my_location = " ".join([wiki_return['data']['city'], wiki_return['data']['country']])
        (longitude, latitude, address, raw_data) = self.locate(my_location)
        wiki_return['data']['longitude'] = longitude
        wiki_return['data']['latitude'] = latitude
        wiki_return['data']['address'] = wiki_return['data']['address'] if 'address' in wiki_return['data'] else UKN
        wiki_return['data']['googleMaps'] = MAPSURL + url_parse.quote(my_location)

        # Add news and patent google urls
        my_encoded_name = url_parse.quote(wiki_return['data']['name'])
        wiki_return['data']['googleNews'] = NEWSURL + my_encoded_name
        wiki_return['data']['googlePatents'] = PATENTSURL + my_encoded_name

        # Add Stock ticker google urls if available
        if 'tickers' in wiki_return['data']:
            # For now we'll detect and change the indexes based upon trial and error.
            raw_echange = wiki_return['data']['tickers'][0]
            if raw_echange == 'Saudi Stock Exchange': raw_echange = 'TADAWUL'
            elif raw_echange == 'NAG': raw_echange = 'TYO'

            my_encoded_exchange = url_parse.quote(raw_echange)
            my_ticker = wiki_return['data']['tickers'][1]
            wiki_return['data']['googleFinance'] = FINANCEURL + my_ticker + ':' + my_encoded_exchange

        return wiki_return


    def merge_data(self, wiki_data, cik, company_name=None):
        # TODO there are potential cases where there isn't a wikipedia page, but there is EDGAR data.
        #       Therefore we need to figure out how to handle this, perhaps we can do an OR? For sure
        #       it is better to return something instead of nothing.  In fact and in general if we 
        #       cannot return both then we need to return something and say what kind of data is returned.
        #
        # TODO Add attribution of the data in an additional field.
        # Define the function and class name
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__

        # If there isn't a cik that is know we need to return with wiki_data
        wiki_return = {
                'code': 200, 
                'message': 'Only Wikipedia data has been detected for the company [' + 
                 wiki_data['name'] + '].',
                'module': my_class + '-> ' + my_function,
                'data': wiki_data,
                'dependencies': DEPENDENCIES
        }
        if cik == UKN and wiki_data['city'] == UKN and wiki_data['country'] and wiki_data['website'][0] == UKN:
            return {
                'code': 404,
                'message': 'Unable to find a company by the name [' + wiki_data['name']+ ']. Maybe you should try an alternative structure like [' + wiki_data['name'] + ' Inc., ' + wiki_data['name'] + ' Corp., or ' + wiki_data['name'] + ' Corporation].',
                'errorType': 'LookupError',
                'module': my_class + '-> ' + my_function,
                'dependencies': DEPENDENCIES  
            }
        elif cik == UKN or isinstance(cik, list): return self._augment_wikidata(wiki_return)

        # Obtain the edgar data for the cik in question
        my_query = edgar.EdgarQueries(db_file=self.db_file, flat_return=True)
        edgar_data = {}
        my_query.query = cik.lstrip('0')
        # Log the start of the query including CIK
        self.logger.info('Starting the EDGAR CIK query for CIK [' + my_query.query + ']')
        edgar_data = my_query.get_all_details(firmographics=True, cik_query=True)
        # Log the end of the query including CIK
        self.logger.info('Completed the EDGAR CIK query for CIK [' + my_query.query + ']')

        # Sanity check 1 - Return the wikidata if there are no results from edgar.
        # NOTE the location data is inconsistently formatted for now so we won't create a lat long pair yet
        # TODO when the wikipedia data is more consistent in format add in the lat long data
        if edgar_data['totalCompanies'] < 1: return self._augment_wikidata(wiki_return)
        
        # Sanity check 2 - if there's more than one company we need to potentially bail out as this logic
        # should only work for a single company.
        elif edgar_data['totalCompanies'] > 1: 
            return {
                # TODO Ok let's check the CIKs if the CIKs are the same then we can pick one and return that one
                # TODO If the CIKs aren't the same then we have an error condition, and we need to think about what to return
                'code': 500, 
                'message': 'A total of [' + str(edgar_data['totalCompanies']) + '] companies detected for this search when only one result is supported.',
                'errorType': 'TooManyCompaniesError',
                'module': my_class + '-> ' + my_function,
                'data': edgar_data,
                'dependencies': DEPENDENCIES
            }

        #### BEGIN data merge
        # Define the final object for return
        final_company = dict()

        # Phase 1 - Using edgar_data add in wiki_data for fields that are Unknown in edgar_data
        my_company  = list(edgar_data['companies'].keys())[0]
        for data in edgar_data['companies'][my_company]:
            if edgar_data['companies'][my_company][data] == UKN and data in wiki_data:
                final_company[data] = wiki_data[data]
            else: 
                final_company[data] = edgar_data['companies'][my_company][data]
            
        # Phase 2 - Using wiki_data add enrich edgar_data
        for data in wiki_data:
             if data not in final_company: final_company[data] = wiki_data[data]

        # Phase 3 - Add lat long data
        if 'address' in final_company:
            my_country = str()
            if not type(final_company['country']) is list: 
                my_country = final_company['country']
            else:
                my_country = final_company['country'][0]
    
            my_address = ", ".join([final_company['address'], final_company['city'], final_company['stateProvince'], final_company['zipPostal'], my_country,])
            (longitude, latitude, address, raw_data) = self.locate(my_address)
            final_company['longitude'] = longitude
            final_company['latitude'] = latitude
            final_company['googleMaps'] = MAPSURL + url_parse.quote(address)
        else:
            final_company['longitude'] = UKN
            final_company['latitude'] = UKN
            final_company['address'] = UKN

        # Phase 4 - Add google links for various services
        my_encoded_name = url_parse.quote(final_company['name'])
        final_company['googleNews'] = NEWSURL + my_encoded_name
        final_company['googlePatents'] = PATENTSURL + my_encoded_name

        if 'tickers' in final_company:
            my_encoded_exchange = url_parse.quote(final_company['tickers'][0])
            my_ticker = final_company['tickers'][1]
            final_company['googleFinance'] = FINANCEURL + my_ticker + ':' + my_encoded_exchange
        

        # Return the merged result
        return {
            'code': 200, 
            'message': 'Wikipedia data and EDGAR has been detected and merged for the company [' + wiki_data['name'] + '].',
            'module': my_class + '-> ' + my_function,
            'data': final_company,
            'dependencies': DEPENDENCIES
        }



if __name__ == '__main__':
    query = GeneralQueries('../company_dns.db')
    cli_args = query.get_cli_args()
    query.query = cli_args.query
    DEBUG = cli_args.debug
    
    results = dict()
    if cli_args.operation == 'ciks':
        results = query.get_all_ciks()
    elif cli_args.operation == 'details':
        results = query.get_all_details()
    elif cli_args.operation == 'summaries':
        results = query.get_all_summaries()
    elif cli_args.operation == 'firmographics_wiki':
        results = query.get_firmographics_wikipedia()
    elif cli_args.operation == 'firmographics_edgar':
        results = query.get_firmographics_edgar()
    elif cli_args.operation == 'merge':
        wiki_data = query.get_firmographics_wikipedia()
        if wiki_data['code'] != 200: results = wiki_data
        results = query.merge_data(wiki_data, wiki_data['cik'])
    
    if not DEBUG: pprint.pprint(results)