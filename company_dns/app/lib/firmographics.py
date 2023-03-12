#!/usr/local/bin/python3

from . import edgar
from . import wikipedia
import argparse
import pprint
import sys
import urllib.parse as url_parse
from geopy.geocoders import ArcGIS

__author__ = "Michael Hay"
__copyright__ = "Copyright 2022, Mediumroast, Inc. All rights reserved."
__license__ = "Apache 2.0"
__version__ = "2.0.0"
__maintainer__ = "Michael Hay"
__status__ = "Alpha"
__date__ = '2022-October-4'

#### Globals ####
# Used for setting attributes consistently when unknown
UKN = "Unknown"

# Determine how we output when executed as a CLI
DEBUG = None

class Query:
    def __init__(
        self,
        database,
        name='wikpedia', 
        description='A module and simple CLI too to search for company data in Wikipedia, EDGAR, and also a merger of the two data sources.'):
        
        # Construct the object to determine lat long pairs
        self.locator = ArcGIS (timeout=2)

        # Contains the company name or CIK
        self.company_or_cik = None

        # Command line naming helpers
        self.NAME = name
        self.DESC = description

        # Define the db_cache location
        self.database = database

    def get_cli_args(self):
        """Parse common CLI arguments including system configs and behavior switches.
        """
        # Set up the argument parser
        parser = argparse.ArgumentParser(prog=self.NAME, description=self.DESC)

        # Setup the command line switches
        parser.add_argument(
            '--company_or_cik',
            help="Company name to search for in Wikipedia or EDGAR",
            type=str,
            dest='company_or_cik',
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
        l = self.locator.geocode (place)
        return l.longitude, l.latitude, l.address

    def get_firmographics_wikipedia(self):
        my_query = wikipedia.WikipediaQueries()
        my_query.company_name = self.company_or_cik
        return my_query.get_firmographics()

    def get_firmographics_edgar(self):
        my_query = edgar.EdgarQueries(db_file=self.database)
        my_query.company_or_cik = self.company_or_cik
        return my_query.get_firmographics(self.company_or_cik)

    def get_all_ciks(self):
        my_query = edgar.EdgarQueries(db_file=self.database)
        my_query.company_or_cik = self.company_or_cik
        return my_query.get_all_ciks()

    def get_all_summaries(self):
        my_query = edgar.EdgarQueries(db_file=self.database)
        my_query.company_or_cik = self.company_or_cik
        return my_query.get_all_details(firmographics=False)

    def get_all_details(self):
        my_query = edgar.EdgarQueries(db_file=self.database)
        my_query.company_or_cik = self.company_or_cik
        return my_query.get_all_details(firmographics=True)

    def merge_data(self, wiki_data, cik):
        # Define the function and class name
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__

        # If there isn't a cik that is know we need to return with wiki_data
        wiki_return = {
                'code': 200, 
                'message': 'Only Wikipedia data has been detected for the company [' + 
                 wiki_data['name'] + '].',
                'module': my_class + '-> ' + my_function,
                'data': wiki_data
        }
        if cik == UKN:
            # Add location data and associated google urls
            my_location = " ".join([wiki_return['data']['city'], wiki_return['data']['country']])
            (longitude, latitude, address) = self.locate(my_location)
            wiki_return['data']['longitude'] = longitude
            wiki_return['data']['latitude'] = latitude
            wiki_return['data']['address'] = address
            wiki_return['data']['googleMaps'] = 'https://www.google.com/maps/place/' + url_parse.quote(my_location)

            # Add news and patent google urls
            my_encoded_name = url_parse.quote(wiki_return['data']['name'])
            wiki_return['data']['googleNews'] = 'https://news.google.com/search?q=' + my_encoded_name
            wiki_return['data']['googlePatents'] = 'https://patents.google.com/?assignee=' + my_encoded_name

            # Add Stock ticker google urls if available
            if 'tickers' in wiki_return['data']:
                my_encoded_exchange = url_parse.quote(wiki_return['data']['tickers'][0])
                my_ticker = wiki_return['data']['tickers'][1]
                wiki_return['data']['googleFinance'] = 'https://www.google.com/finance/quote/' + my_ticker + ':' + my_encoded_exchange
            return wiki_return 

        # Obtain the edgar data for the cik in question
        my_query = edgar.EdgarQueries(db_file=self.database)
        my_query.company_or_cik = cik.lstrip('0')
        edgar_data = my_query.get_all_details(firmographics=True, cik_query=True)

        # Sanity check 1 - Return the wikidata if there are no results from edgar.
        # NOTE the location data is inconsistently formatted for now so we won't create a lat long pair yet
        # TODO when the wikipedia data is more consistent in format add in the lat long data
        if edgar_data['totalCompanies'] < 1: return wiki_return
        
        # Sanity check 2 - if there's more than one company we need to bail out as this logic
        # will only work for a single company.
        elif edgar_data['totalCompanies'] > 1: return {
            'code': 500, 
            'message': 'A total of [' + str(edgar_data['totalCompanies']) + '] companies was detected for this search when only one result is supported.',
            'errorType': 'TooManyCompaniesError',
            'module': my_class + '-> ' + my_function,
            'data': edgar_data
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
            # final_company[data] = wiki_data[data] if edgar_data['companies'][my_company][data] == UKN else edgar_data['companies'][my_company][data]
            
        # Phase 2 - Using wiki_data add enrich edgar_data
        for data in wiki_data:
             if data not in final_company: final_company[data] = wiki_data[data]

        # Phase 3 - Add lat long data
        if 'address' in final_company:
            my_address = ", ".join([final_company['address'], final_company['city'], final_company['stateProvince'], final_company['zipPostal'], final_company['country'],])
            (longitude, latitude, address) = self.locate(my_address)
            final_company['longitude'] = longitude
            final_company['latitude'] = latitude
            final_company['address'] = address
            final_company['googleMaps'] = 'https://www.google.com/maps/place/' + url_parse.quote(address)
        else:
            final_company['longitude'] = UKN
            final_company['latitude'] = UKN
            final_company['address'] = UKN

        # Phase 4 - Add google links for various services
        my_encoded_name = url_parse.quote(final_company['name'])
        final_company['googleNews'] = 'https://news.google.com/search?q=' + my_encoded_name
        final_company['googlePatents'] = 'https://patents.google.com/?assignee=' + my_encoded_name

        if 'tickers' in final_company:
            my_encoded_exchange = url_parse.quote(final_company['tickers'][0])
            my_ticker = final_company['tickers'][1]
            final_company['googleFinance'] = 'https://www.google.com/finance/quote/' + my_ticker + ':' + my_encoded_exchange
        

        # Return the merged result
        return {
            'code': 200, 
            'message': 'Wikipedia data and EDGAR has been detected and merged for the company [' + wiki_data['name'] + '].',
            'module': my_class + '-> ' + my_function,
            'data': final_company
        }



if __name__ == '__main__':
    query = Query('../edgar_cache.db')
    cli_args = query.get_cli_args()
    query.company_or_cik = cli_args.company_or_cik
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