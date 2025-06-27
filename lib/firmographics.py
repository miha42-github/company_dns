from . import edgar
from . import wikipedia
import sys
import unicodedata
import urllib.parse as url_parse
import logging
import time
import re
from geopy.geocoders import ArcGIS

__author__ = "Michael Hay"
__copyright__ = "Copyright 2024, Mediumroast, Inc. All rights reserved."
__license__ = "Apache 2.0"
__version__ = "2.1.0"
__maintainer__ = "Michael Hay"
__status__ = "Production"
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

# Regular expression patterns for cleaning up company names
RE_BRACKETS = re.compile(r'\[\[|\]\]')
RE_PARENS = re.compile(r'\s*\(\S+\)$')
RE_PIPES = re.compile(r'\|')

class GeneralQueries:
    def __init__(
        self,
        database=None,
        name='general', 
        description='A module to search for company data in Wikipedia, EDGAR, and also a merger of the two data sources.'):
        
        # Construct the object to determine lat long pairs
        self.locator = ArcGIS(user_agent="company_dns")
        self.locator.timeout = 2  # Set a timeout for geocoding requests

        # Contains the company name or CIK
        self.query = None

        # Define the db_cache location
        self.db_file='./company_dns.db' if database is None else database

        # Naming helpers
        self.NAME = name
        self.DESC = description

        # Set up the logging
        self.logger = logging.getLogger(self.NAME)
    
    def locate(self, place):
        # Start timing the location operation
        locate_start_time = time.time()
        
        # Log the place to locate via a debug message
        self.logger.debug(f'Locating the place [{place}]')
        
        try:
            # Get the geocode result
            l = self.locator.geocode(place)
            
            # Check if the result is None or if it's a coroutine
            if l is None:
                locate_elapsed = time.time() - locate_start_time
                self.logger.warning(f'No location found for [{place}] after {locate_elapsed:.3f} seconds')
                return UKN, UKN, UKN, {}
                
            # Log the location data
            locate_elapsed = time.time() - locate_start_time
            self.logger.debug(f'Location data for [{place}] found in {locate_elapsed:.3f} seconds: {l}')
            
            # Extract attributes safely
            longitude = getattr(l, 'longitude', UKN)
            latitude = getattr(l, 'latitude', UKN)
            address = getattr(l, 'address', UKN)
            raw_data = getattr(l, 'raw', {})
            
            return longitude, latitude, address, raw_data
            
        except Exception as e:
            locate_elapsed = time.time() - locate_start_time
            self.logger.error(f'Failed to locate [{place}] after {locate_elapsed:.3f} seconds: {e}')
            return UKN, UKN, UKN, {}

    def get_firmographics_wikipedia(self):
        # Start timing the Wikipedia query
        wiki_start_time = time.time()
        
        self.logger.info(f'Starting Wikipedia query for [{self.query}]')
        try:
            my_query = wikipedia.WikipediaQueries()
            my_query.query = self.query
            result = my_query.get_firmographics()
            wiki_elapsed = time.time() - wiki_start_time
            self.logger.info(f'Wikipedia query for [{self.query}] completed in {wiki_elapsed:.3f} seconds')
            return result
        except Exception as e:
            wiki_elapsed = time.time() - wiki_start_time
            self.logger.error(f'Wikipedia query for [{self.query}] failed after {wiki_elapsed:.3f} seconds: {e}')
            raise

    def get_firmographics_edgar(self):
        # Start timing the EDGAR query
        edgar_start_time = time.time()
        
        self.logger.info(f'Starting EDGAR query for [{self.query}]')
        try:
            my_query = edgar.EdgarQueries(db_file=self.db_file)
            my_query.query = self.query
            result = my_query.get_firmographics(self.query)
            edgar_elapsed = time.time() - edgar_start_time
            self.logger.info(f'EDGAR query for [{self.query}] completed in {edgar_elapsed:.3f} seconds')
            return result
        except Exception as e:
            edgar_elapsed = time.time() - edgar_start_time
            self.logger.error(f'EDGAR query for [{self.query}] failed after {edgar_elapsed:.3f} seconds: {e}')
            raise

    def get_all_ciks(self):
        ciks_start_time = time.time()
        self.logger.info(f'Starting retrieval of all CIKs')
        
        try:
            my_query = edgar.EdgarQueries(db_file=self.db_file)
            my_query.query = self.query
            result = my_query.get_all_ciks()
            ciks_elapsed = time.time() - ciks_start_time
            self.logger.info(f'Retrieved all CIKs in {ciks_elapsed:.3f} seconds')
            return result
        except Exception as e:
            ciks_elapsed = time.time() - ciks_start_time
            self.logger.error(f'Failed to retrieve all CIKs after {ciks_elapsed:.3f} seconds: {e}')
            raise

    def get_all_summaries(self):
        summaries_start_time = time.time()
        self.logger.info(f'Starting retrieval of all summaries')
        
        try:
            my_query = edgar.EdgarQueries(db_file=self.db_file)
            my_query.query = self.query
            result = my_query.get_all_details(firmographics=False)
            summaries_elapsed = time.time() - summaries_start_time
            self.logger.info(f'Retrieved all summaries in {summaries_elapsed:.3f} seconds')
            return result
        except Exception as e:
            summaries_elapsed = time.time() - summaries_start_time
            self.logger.error(f'Failed to retrieve all summaries after {summaries_elapsed:.3f} seconds: {e}')
            raise

    def get_all_details(self, flat_return=False):
        details_start_time = time.time()
        self.logger.info(f'Starting retrieval of all details with flat_return={flat_return}')
        
        try:
            my_query = edgar.EdgarQueries(db_file=self.db_file, flat_return=flat_return)
            my_query.query = self.query
            result = my_query.get_all_details(firmographics=True)
            details_elapsed = time.time() - details_start_time
            self.logger.info(f'Retrieved all details in {details_elapsed:.3f} seconds')
            return result
        except Exception as e:
            details_elapsed = time.time() - details_start_time
            self.logger.error(f'Failed to retrieve all details after {details_elapsed:.3f} seconds: {e}')
            raise

    def _augment_wikidata(self, wiki_return):
        augment_start_time = time.time()
        self.logger.info(f"Starting to augment wikidata for [{wiki_return['data']['name'] if 'name' in wiki_return['data'] else 'Unknown Company'}]")
        
        try:
            # Location data
            location_start_time = time.time()
            my_location = " ".join([wiki_return['data']['city'], wiki_return['data']['country']])
            longitude, latitude, address, raw_data = self.locate(my_location)
            wiki_return['data']['longitude'] = longitude
            wiki_return['data']['latitude'] = latitude
            wiki_return['data']['address'] = wiki_return['data']['address'] if 'address' in wiki_return['data'] else UKN
            wiki_return['data']['googleMaps'] = MAPSURL + url_parse.quote(my_location)
            location_elapsed = time.time() - location_start_time
            self.logger.debug(f"Location data augmentation completed in {location_elapsed:.3f} seconds")

            # Add news and patent google urls
            urls_start_time = time.time()
            my_encoded_name = url_parse.quote(wiki_return['data']['name'])
            wiki_return['data']['googleNews'] = NEWSURL + my_encoded_name
            wiki_return['data']['googlePatents'] = PATENTSURL + my_encoded_name
            urls_elapsed = time.time() - urls_start_time
            self.logger.debug(f"URL augmentation completed in {urls_elapsed:.3f} seconds")

            # Add Stock ticker google urls if available
            finance_start_time = time.time()
            if 'tickers' in wiki_return['data']:
                raw_echange = wiki_return['data']['tickers'][0]
                # Clean exchange name using RE_PARENS if needed
                raw_echange = RE_PARENS.sub('', raw_echange)
    
                if raw_echange == 'Saudi Stock Exchange': raw_echange = 'TADAWUL'
                elif raw_echange == 'NAG': raw_echange = 'TYO'

                my_encoded_exchange = url_parse.quote(raw_echange)
                my_ticker = wiki_return['data']['tickers'][1]
                wiki_return['data']['googleFinance'] = FINANCEURL + my_ticker + ':' + my_encoded_exchange
    
            finance_elapsed = time.time() - finance_start_time
            self.logger.debug(f"Finance URL augmentation completed in {finance_elapsed:.3f} seconds")

            augment_elapsed = time.time() - augment_start_time
            self.logger.info(f"Wikidata augmentation completed in {augment_elapsed:.3f} seconds")
            
            # Add performance metrics to the return
            if 'performance' not in wiki_return:
                wiki_return['performance'] = {}
            wiki_return['performance']['augmentation_time'] = augment_elapsed
            wiki_return['performance']['location_time'] = location_elapsed
            wiki_return['performance']['urls_time'] = urls_elapsed
            wiki_return['performance']['finance_time'] = finance_elapsed
            
            return wiki_return
        except Exception as e:
            augment_elapsed = time.time() - augment_start_time
            self.logger.error(f"Wikidata augmentation failed after {augment_elapsed:.3f} seconds: {e}")
            return wiki_return
    
    def _set_location_data(self, final_company):
        location_start_time = time.time()
        self.logger.info(f"Starting to set location data for [{final_company['name'] if 'name' in final_company else 'Unknown Company'}]")
        
        try:
            if 'address' in final_company:
                address_start_time = time.time()
                my_address = ", ".join([final_company['address'], final_company['city'], 
                                      final_company['stateProvince'], final_company['zipPostal']])
                longitude, latitude, address, raw_data = self.locate(my_address)
                final_company['longitude'] = longitude
                final_company['latitude'] = latitude
                final_company['googleMaps'] = MAPSURL + url_parse.quote(address)
                address_elapsed = time.time() - address_start_time
                self.logger.debug(f"Address-based location data set in {address_elapsed:.3f} seconds")
            else:
                final_company['longitude'] = UKN
                final_company['latitude'] = UKN
                final_company['address'] = UKN
                self.logger.debug("No address found, using Unknown for location data")
                
            location_elapsed = time.time() - location_start_time
            self.logger.info(f"Location data setting completed in {location_elapsed:.3f} seconds")
            return final_company
        except Exception as e:
            location_elapsed = time.time() - location_start_time
            self.logger.error(f"Setting location data failed after {location_elapsed:.3f} seconds: {e}")
            return final_company
    
    def _set_google_urls(self, final_company):
        urls_start_time = time.time()
        self.logger.info(f"Starting to set Google URLs for [{final_company['name'] if 'name' in final_company else 'Unknown Company'}]")
        
        try:
            my_encoded_name = url_parse.quote(final_company['name'])
            final_company['googleNews'] = NEWSURL + my_encoded_name
            final_company['googlePatents'] = PATENTSURL + my_encoded_name
            
            if 'tickers' in final_company:
                finance_start_time = time.time()
                my_encoded_exchange = url_parse.quote(final_company['tickers'][0])
                # Clean ticker using regex if needed
                my_ticker = RE_BRACKETS.sub('', final_company['tickers'][1])
                final_company['googleFinance'] = FINANCEURL + my_ticker + ':' + my_encoded_exchange
    
                finance_elapsed = time.time() - finance_start_time
                self.logger.debug(f"Finance URL set in {finance_elapsed:.3f} seconds")
                
            urls_elapsed = time.time() - urls_start_time
            self.logger.info(f"Google URLs setting completed in {urls_elapsed:.3f} seconds")
            return final_company
        except Exception as e:
            urls_elapsed = time.time() - urls_start_time
            self.logger.error(f"Setting Google URLs failed after {urls_elapsed:.3f} seconds: {e}")
            return final_company

    def merge_data(self, wiki_data=None):
        merge_start_time = time.time()
        # Define the function and class name
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Log the start of merging data
        self.logger.info(f"Starting to merge data for [{wiki_data.get('name', 'Unknown Company') if wiki_data else 'Unknown Company'}]")

        # Set the CIK to UKN
        cik = UKN

        # Copy key wiki_data fields for comparison
        city = wiki_data['city'] if wiki_data and 'city' in wiki_data else UKN
        country = wiki_data['country'] if wiki_data and 'country' in wiki_data else UKN
        first_website = wiki_data['website'][0] if wiki_data and 'website' in wiki_data and wiki_data['website'] else UKN
        name = wiki_data['name'] if wiki_data and 'name' in wiki_data else UKN

        # If wiki_data is not None and it exists then we need to set the CIK to wiki_data['cik']
        if wiki_data is not None and 'cik' in wiki_data and wiki_data['cik']: 
            cik = wiki_data['cik']
            self.logger.debug(f"Found CIK [{cik}] in wiki_data")

        # If there isn't a cik that is know we need to return with wiki_data
        wiki_return = {
                'code': 200, 
                'message': f"Only Wikipedia data has been detected for the company [{wiki_data['name'] if wiki_data and 'name' in wiki_data else 'Unknown Company'}].",
                'module': my_class + '-> ' + my_function,
                'data': wiki_data,
                'dependencies': DEPENDENCIES
        }
        
        # Return early if we don't have enough data
        if cik == UKN and city == UKN and country and first_website == UKN:
            merge_elapsed = time.time() - merge_start_time
            self.logger.error(f"Not enough data for company [{wiki_data['name'] if wiki_data and 'name' in wiki_data else 'Unknown Company'}], returning error after {merge_elapsed:.3f} seconds")
            return {
                'code': 404,
                'message': f"Unable to find a company by the name [{name}]. Maybe you should try an alternative structure like [{name} Inc., {name} Corp., or {name} Corporation].",
                'errorType': 'LookupError',
                'module': my_class + '-> ' + my_function,
                'dependencies': DEPENDENCIES,
                'performance': {
                    'merge_time': merge_elapsed
                }
            }
        elif cik == UKN or isinstance(cik, list): 
            augment_start_time = time.time()
            result = self._augment_wikidata(wiki_return)
            augment_elapsed = time.time() - augment_start_time
            merge_elapsed = time.time() - merge_start_time
            self.logger.info(f"Returning augmented Wikipedia data after {merge_elapsed:.3f} seconds")
            
            # Add performance data
            if 'performance' not in result:
                result['performance'] = {}
            result['performance']['merge_time'] = merge_elapsed
            result['performance']['augment_time'] = augment_elapsed
            
            return result

        # Obtain the edgar data for the cik in question
        edgar_start_time = time.time()
        my_query = edgar.EdgarQueries(db_file=self.db_file, flat_return=True)
        edgar_data = {}
        my_query.query = cik.lstrip('0')
        
        # Log the start of the query including CIK
        self.logger.info(f'Starting the EDGAR CIK query for CIK [{my_query.query}]')
        edgar_data = my_query.get_all_details(firmographics=True, cik_query=True)
        edgar_elapsed = time.time() - edgar_start_time
        self.logger.info(f'Completed the EDGAR CIK query for CIK [{my_query.query}] in {edgar_elapsed:.3f} seconds')

        # Sanity check 1 - Return the wikidata if there are no results from edgar.
        if edgar_data['totalCompanies'] < 1: 
            augment_start_time = time.time()
            result = self._augment_wikidata(wiki_return)
            augment_elapsed = time.time() - augment_start_time
            merge_elapsed = time.time() - merge_start_time
            self.logger.info(f"No EDGAR data found, returning augmented Wikipedia data after {merge_elapsed:.3f} seconds")
            
            # Add performance data
            if 'performance' not in result:
                result['performance'] = {}
            result['performance']['merge_time'] = merge_elapsed
            result['performance']['edgar_time'] = edgar_elapsed
            result['performance']['augment_time'] = augment_elapsed
            
            return result
        
        # Sanity check 2 - if there's more than one company we need to potentially bail out
        elif edgar_data['totalCompanies'] > 1: 
            merge_elapsed = time.time() - merge_start_time
            self.logger.error(f"Too many companies found ({edgar_data['totalCompanies']}) for CIK [{my_query.query}], returning error after {merge_elapsed:.3f} seconds")
            return {
                'code': 500, 
                'message': f"A total of [{str(edgar_data['totalCompanies'])}] companies detected for this search when only one result is supported.",
                'errorType': 'TooManyCompaniesError',
                'module': my_class + '-> ' + my_function,
                'data': edgar_data,
                'dependencies': DEPENDENCIES,
                'performance': {
                    'merge_time': merge_elapsed,
                    'edgar_time': edgar_elapsed
                }
            }

        #### BEGIN data merge
        merge_process_start_time = time.time()
        self.logger.info(f"Starting actual data merge process for [{wiki_data['name'] if wiki_data and 'name' in wiki_data else 'Unknown Company'}]")
        
        # Define the final object for return
        final_company = dict()

        # Phase 1 - Using edgar_data add in wiki_data for fields that are Unknown in edgar_data
        phase1_start_time = time.time()
        if 'companies' in edgar_data and edgar_data['companies']:
            my_company = list(edgar_data['companies'].keys())[0]
            for data in edgar_data['companies'][my_company]:
                if edgar_data['companies'][my_company][data] == UKN and wiki_data and data in wiki_data:
                    final_company[data] = wiki_data[data]
                else: 
                    final_company[data] = edgar_data['companies'][my_company][data]
        else:
            self.logger.error("No companies found in edgar_data")
            # You might want to add appropriate error handling here
        phase1_elapsed = time.time() - phase1_start_time
        self.logger.debug(f"Phase 1 merge (EDGAR fields) completed in {phase1_elapsed:.3f} seconds")
            
        # Phase 2 - Using wiki_data add enrich edgar_data
        phase2_start_time = time.time()
        if wiki_data:
            for data in wiki_data:
                if data not in final_company: 
                    final_company[data] = wiki_data[data]
            phase2_elapsed = time.time() - phase2_start_time
            self.logger.debug(f"Phase 2 merge (Wikipedia fields) completed in {phase2_elapsed:.3f} seconds")
        else:
            phase2_elapsed = 0
            self.logger.warning("No Wikipedia data available for Phase 2 merge")

        # Phase 3 - Add lat long data
        phase3_start_time = time.time()
        if 'address' in final_company:
            my_country = str()
            if not isinstance(final_company['country'], list):  # Use isinstance instead of type() is
                my_country = final_company['country']
            else:
                my_country = final_company['country'][0]
    
            my_address = ", ".join([final_company['address'], final_company['city'], final_company['stateProvince'], final_company['zipPostal'], my_country,])
            longitude, latitude, address, raw_data = self.locate(my_address)
            final_company['longitude'] = longitude
            final_company['latitude'] = latitude
            final_company['googleMaps'] = MAPSURL + url_parse.quote(address)
        else:
            final_company['longitude'] = UKN
            final_company['latitude'] = UKN
            final_company['address'] = UKN
        phase3_elapsed = time.time() - phase3_start_time
        self.logger.debug(f"Phase 3 merge (location data) completed in {phase3_elapsed:.3f} seconds")

        # Phase 4 - Add google urls
        phase4_start_time = time.time()
        final_company = self._set_google_urls(final_company)
        phase4_elapsed = time.time() - phase4_start_time
        self.logger.debug(f"Phase 4 merge (Google URLs) completed in {phase4_elapsed:.3f} seconds")
        
        merge_process_elapsed = time.time() - merge_process_start_time
        merge_elapsed = time.time() - merge_start_time
        self.logger.info(f"Data merge completed in {merge_process_elapsed:.3f} seconds, total merge operation took {merge_elapsed:.3f} seconds")
        
        # Return the merged result
        return {
            'code': 200, 
            'message': f"Wikipedia data and EDGAR has been detected and merged for the company [{name}].",
            'module': my_class + '-> ' + my_function,
            'data': final_company,
            'dependencies': DEPENDENCIES,
            'performance': {
                'total_merge_time': merge_elapsed,
                'edgar_query_time': edgar_elapsed,
                'merge_process_time': merge_process_elapsed,
                'phase1_time': phase1_elapsed,
                'phase2_time': phase2_elapsed,
                'phase3_time': phase3_elapsed,
                'phase4_time': phase4_elapsed
            }
        }
    
    def get_firmographics(self):
        """This function is the main entry point for the module used to gather company firmographics from a variety of data sources.  The basic flow of the function is as follows as of today:
        
        1. It will first query wikipedia for the firmographics based upon company name as defined in self.query.
        2. If the wikipedia data is successfully returned and the company is public it will then query EDGAR for additional firmographics and merge the data with the wikipedia data.
        3. If the wikipedia data is successfully returned and the company is not public it will return the wikipedia data.
        4. If the wikipedia data is not successfully returned it will then query EDGAR for the firmographics and that is successful it will be reformatted and returned.
        5. Finally if there isn't any data returned it will return an error message.

        Returns:
            dict: A dictionary with the following keys:
                code (int): The HTTP status code of the response.
                message (str): A message describing the result of the query.
                module (str): The module and function that was executed.
                data (dict): The firmographics data for the company.
                dependencies (dict): A dictionary of the dependencies for the module.
        """
        # Start timing the entire operation
        total_start_time = time.time()
        
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__

        lookup_err_prototype = {
                'errorType': 'LookupError',
                'module': my_class + '-> ' + my_function,
                'dependencies': DEPENDENCIES  
        }

        company_firmographics = None

        # Log the start of the query
        self.logger.info(f'Starting firmographics gathering for company [{self.query}]')
        
        # Try Wikipedia first
        wiki_start_time = time.time()
        try:
            self.logger.debug(f'Performing general query for company name: [{self.query}]')
            wiki_response = self.get_firmographics_wikipedia()
            wiki_elapsed = time.time() - wiki_start_time
            
            if wiki_response['code'] == 200:
                self.logger.info(f'Wikipedia results for [{self.query}] returned successfully in {wiki_elapsed:.3f} seconds')
                
                # Try to merge with EDGAR data if applicable
                merge_start_time = time.time()
                company_firmographics = self.merge_data(wiki_data=wiki_response['data'])
                merge_elapsed = time.time() - merge_start_time
                self.logger.info(f'Data merge for [{self.query}] completed in {merge_elapsed:.3f} seconds')
            else:
                self.logger.warning(f'Wikipedia query for [{self.query}] returned non-success code {wiki_response["code"]} in {wiki_elapsed:.3f} seconds')
        except Exception as e:
            wiki_elapsed = time.time() - wiki_start_time
            self.logger.error(f'Wikipedia query for [{self.query}] failed after {wiki_elapsed:.3f} seconds: {e}')
            lookup_err_prototype['code'] = 542
            lookup_err_prototype['message'] = f'Using general query unable to find a company by the name [{self.query}], encountered error: [{e}]. Maybe you should try an alternative structure like [{self.query} Inc., {self.query} Corp., or {self.query} Corporation].'
            lookup_err_prototype['performance'] = {
                'total_time': time.time() - total_start_time,
                'wiki_time': wiki_elapsed
            }
            return lookup_err_prototype
            
        # If we have results from Wikipedia/merge, return them
        if company_firmographics: 
            total_elapsed = time.time() - total_start_time
            self.logger.info(f'Total firmographics gathering for [{self.query}] completed in {total_elapsed:.3f} seconds')
            
            # Add overall performance data
            if 'performance' not in company_firmographics:
                company_firmographics['performance'] = {}
            company_firmographics['performance']['total_time'] = total_elapsed
            company_firmographics['performance']['wiki_time'] = wiki_elapsed
            if 'merge_time' in locals():
                company_firmographics['performance']['merge_time'] = merge_elapsed
                
            return company_firmographics
        
        # Try EDGAR as fallback
        edgar_start_time = time.time()
        try:
            self.logger.debug(f'Performing EDGAR query for company name: [{self.query}]')
            company_firmographics = self.get_all_details(flat_return=True)
            edgar_elapsed = time.time() - edgar_start_time
            self.logger.info(f'EDGAR query for [{self.query}] completed in {edgar_elapsed:.3f} seconds')
        except Exception as e:
            edgar_elapsed = time.time() - edgar_start_time
            self.logger.error(f'EDGAR query for [{self.query}] failed after {edgar_elapsed:.3f} seconds: {e}')
            lookup_err_prototype['code'] = 542
            lookup_err_prototype['message'] = f'Using EDGAR query unable to find a company by the name [{self.query}], encountered error: [{e}]. Maybe you should try an alternative structure like [{self.query} Inc., {self.query} Corp., or {self.query} Corporation].'
            lookup_err_prototype['performance'] = {
                'total_time': time.time() - total_start_time,
                'wiki_time': wiki_elapsed if 'wiki_elapsed' in locals() else 0,
                'edgar_time': edgar_elapsed
            }
            return lookup_err_prototype
        
        # If we have a company_firmographics object from EDGAR then we need to clean it up and 
        # enrich it with urls and location data
        if company_firmographics:
            self.logger.info(f'EDGAR results for [{self.query}] returned successfully')
            
            # Process EDGAR results
            edgar_process_start_time = time.time()

            # Check if 'companies' exists and has entries
            if company_firmographics and 'companies' in company_firmographics and company_firmographics['companies']:
                # Get the first key from company_firmographics['companies'] 
                new_company_name = next(iter(company_firmographics['companies']), None)
                
                if new_company_name is not None:
                    company_firmographics = company_firmographics['companies'][new_company_name]
                    
                    # Add location data
                    location_start_time = time.time()
                    company_firmographics = self._set_location_data(company_firmographics)
                    location_elapsed = time.time() - location_start_time
                    self.logger.debug(f'Location data added in {location_elapsed:.3f} seconds')
                    
                    # Add Google URLs
                    urls_start_time = time.time()
                    company_firmographics = self._set_google_urls(company_firmographics)
                    urls_elapsed = time.time() - urls_start_time
                    self.logger.debug(f'Google URLs added in {urls_elapsed:.3f} seconds')
                    
                    # Clean up category if it exists
                    category_elapsed = 0
                    if 'category' in company_firmographics and company_firmographics['category']:
                        category_start_time = time.time()
                        self.logger.debug(f'Extra characters in category [{ord(company_firmographics["category"][0])}]')
                        company_firmographics['category'] = re.sub(r'<br\s*?/?>', '', company_firmographics['category'])
                        category_elapsed = time.time() - category_start_time
                        self.logger.debug(f'Category cleaned in {category_elapsed:.3f} seconds')
                    
                    company_firmographics['type'] = 'Public company'
                    
                    edgar_process_elapsed = time.time() - edgar_process_start_time
                    total_elapsed = time.time() - total_start_time
                    self.logger.info(f'EDGAR results processing completed in {edgar_process_elapsed:.3f} seconds')
                    self.logger.info(f'Total firmographics gathering for [{self.query}] completed in {total_elapsed:.3f} seconds')
                    
                    return {
                        'code': 200, 
                        'message': f'Only EDGAR has been detected and returned for the company [{new_company_name}].',
                        'module': my_class + '-> ' + my_function,
                        'data': company_firmographics,
                        'dependencies': DEPENDENCIES,
                        'performance': {
                            'total_time': total_elapsed,
                            'wiki_time': wiki_elapsed if 'wiki_elapsed' in locals() else 0,
                            'edgar_time': edgar_elapsed,
                            'edgar_process_time': edgar_process_elapsed,
                            'location_time': location_elapsed,
                            'urls_time': urls_elapsed,
                            'category_time': category_elapsed
                        }
                    }
                else:
                    # No valid company name found
                    self.logger.error(f"No valid company name found in EDGAR results for [{self.query}]")
            else:
                # No companies data found
                self.logger.error(f"No companies data found in EDGAR results for [{self.query}]")

        # If we reached here, there was an issue with the EDGAR data
        total_elapsed = time.time() - total_start_time
        lookup_err_prototype['code'] = 404
        lookup_err_prototype['message'] = f'Unable to find a company by the name [{self.query}]. Maybe you should try an alternative structure like [{self.query} Inc., {self.query} Corp., or {self.query} Corporation].'
        lookup_err_prototype['performance'] = {
            'total_time': total_elapsed,
            'wiki_time': wiki_elapsed if 'wiki_elapsed' in locals() else 0,
            'edgar_time': edgar_elapsed if 'edgar_elapsed' in locals() else 0
        }
        self.logger.error(f'No data found for [{self.query}] after {total_elapsed:.3f} seconds')
        return lookup_err_prototype