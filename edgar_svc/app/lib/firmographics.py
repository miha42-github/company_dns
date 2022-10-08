#!/usr/local/bin/python3
import edgar
import wikipedia
import argparse
import pprint
import sys
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
        name='wikpedia', 
        description='A module and simple CLI too to search for company data in Wikipedia, EDGAR, and also a merger of the two data sources.'):
        
        # Construct the object to determin lat long pairs
        self.locator = ArcGIS (timeout=2)

        # Contains the company name or CIK
        self.company_or_cik = None

        # Command line naming helpers
        self.NAME = name
        self.DESC = description

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
        my_query = edgar.EdgarQueries(db_file='../edgar_cache.db')
        my_query.company_or_cik = self.company_or_cik
        return my_query.get_firmographics(self.company_or_cik)

    def get_all_ciks(self):
        my_query = edgar.EdgarQueries(db_file='../edgar_cache.db')
        my_query.company_or_cik = self.company_or_cik
        return my_query.get_all_ciks()

    def get_all_summaries(self):
        my_query = edgar.EdgarQueries(db_file='../edgar_cache.db')
        my_query.company_or_cik = self.company_or_cik
        return my_query.get_all_details(firmographics=False)

    def get_all_details(self):
        my_query = edgar.EdgarQueries(db_file='../edgar_cache.db')
        my_query.company_or_cik = self.company_or_cik
        return my_query.get_all_details(firmographics=True)

    def merge_data(self, wiki_data, formal_company_name):
        # Define the function and class name
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__

        # Obtain the edgar data for the formal_company_name
        my_query = edgar.EdgarQueries(db_file='../edgar_cache.db')
        my_query.company_or_cik = formal_company_name
        edgar_data = my_query.get_all_details(firmographics=True)

        # Sanity check 1 - Return the wikidata if there are no results from edgar.
        if edgar_data['totalCompanies'] < 1: 
            return {
                'code': 200, 
                'message': 'Only Wikipedia data has been detected for the company [' + formal_company_name + '].',
                'module': my_class + '-> ' + my_function,
                'data': wiki_data
            }
        
        # Sanity check 2 - if there's more than one company we need to bail out as this logic
        # will only work for a single company.
        elif edgar_data['totalCompanies'] > 1: return {
            'code': 500, 
            'message': 'A total of [' + edgar_data['totalCompanies'] + '] was detected for this search when only one result is supported.',
            'errorType': 'TooManyCompaniesError',
            'module': my_class + '-> ' + my_function
        }

        # Define the final object for return
        final_company = dict()

        # Phase 1 - Using edgar_data add in wiki_data for fields that are Unknown in edgar_data
        my_company  = list(edgar_data['companies'].keys())[0]
        for data in edgar_data['companies'][my_company]:
            final_company[data] = wiki_data[data] if edgar_data['companies'][my_company][data] == UKN else edgar_data['companies'][my_company][data]
            
        # Phase 2 - Using wiki_data add enrich edgar_data
        for data in wiki_data:
             if data not in final_company: final_company[data] = wiki_data[data]

        # Phase 3 - Add lat long data

        # Return the merged result
        return {
            'code': 200, 
            'message': 'Wikipedia data and ESDGAR has been detected and merged for the company [' + formal_company_name + '].',
            'module': my_class + '-> ' + my_function,
            'data': final_company
        }



    


if __name__ == '__main__':
    query = Query()
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
        results = query.merge_data(wiki_data, query.company_or_cik)
    
    if not DEBUG: pprint.pprint(results)