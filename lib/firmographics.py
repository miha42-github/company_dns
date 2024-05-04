from . import edgar
from . import wikipedia
import sys
import unicodedata
import urllib.parse as url_parse
import logging
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

class GeneralQueries:
    def __init__(
        self,
        database=None,
        name='general', 
        description='A module to search for company data in Wikipedia, EDGAR, and also a merger of the two data sources.'):
        
        # Construct the object to determine lat long pairs
        self.locator = ArcGIS(timeout=2, user_agent="company_dns")

        # Contains the company name or CIK
        self.query = None

        # Define the db_cache location
        self.db_file='./company_dns.db' if database is None else database

        # Naming helpers
        self.NAME = name
        self.DESC = description

        # Set up the logging
        self.logger = logging.getLogger(self.NAME)
    
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

    def get_all_details(self, flat_return=False):
        my_query = edgar.EdgarQueries(db_file=self.db_file, flat_return=flat_return)
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
    
    def _set_location_data(self, final_company):
        if 'address' in final_company:
            my_address = ", ".join([final_company['address'], final_company['city'], final_company['stateProvince'], final_company['zipPostal']])
            (longitude, latitude, address, raw_data) = self.locate(my_address)
            final_company['longitude'] = longitude
            final_company['latitude'] = latitude
            final_company['googleMaps'] = MAPSURL + url_parse.quote(address)
        else:
            final_company['longitude'] = UKN
            final_company['latitude'] = UKN
            final_company['address'] = UKN
        return final_company
    
    def _set_google_urls(self, final_company):
        my_encoded_name = url_parse.quote(final_company['name'])
        final_company['googleNews'] = NEWSURL + my_encoded_name
        final_company['googlePatents'] = PATENTSURL + my_encoded_name
        if 'tickers' in final_company:
            my_encoded_exchange = url_parse.quote(final_company['tickers'][0])
            my_ticker = final_company['tickers'][1]
            final_company['googleFinance'] = FINANCEURL + my_ticker + ':' + my_encoded_exchange
        return final_company

    def merge_data(self, wiki_data=None):
        # TODO there are potential cases where there isn't a wikipedia page, but there is EDGAR data.
        #       Therefore we need to figure out how to handle this, perhaps we can do an OR? For sure
        #       it is better to return something instead of nothing.  In fact and in general if we 
        #       cannot return both then we need to return something and say what kind of data is returned.
        #
        # TODO Add attribution of the data in an additional field.
        # Define the function and class name
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__

        # Set the CIK to UKN
        cik = UKN

        # If wiki_data is not None and it exists then we need to set the CIK to wiki_data['cik']
        if wiki_data is not None and wiki_data['cik']: cik = wiki_data['cik']

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

        # Phase 4 - Add google urls
        final_company = self._set_google_urls(final_company)
        
        # Return the merged result
        return {
            'code': 200, 
            'message': f'Wikipedia data and EDGAR has been detected and merged for the company [{wiki_data['name']}].',
            'module': my_class + '-> ' + my_function,
            'data': final_company,
            'dependencies': DEPENDENCIES
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
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__

        lookup_err_prototype = {
                'errorType': 'LookupError',
                'module': my_class + '-> ' + my_function,
                'dependencies': DEPENDENCIES  
        }

        company_firmographics = None

        # Log the start of the query
        self.logger.info(f'Attempting to gather firmographics company [{self.query}]')
        
        try:
            self.logger.debug(f'Performing general query for company name: [{self.query}]')
            wiki_response = self.get_firmographics_wikipedia()
            if wiki_response['code'] == 200:
                self.logger.info(f'Wikipedia results for [{self.query}] returned successfully.')
                company_firmographics = self.merge_data(wiki_data=wiki_response['data'])
        except Exception as e:
            self.logger.error(f'Wikidata results for [{self.query}] returned [{e}].')
            lookup_err_prototype['code'] = 542
            lookup_err_prototype['message'] = f'Using general query nable to find a company by the name [{self.query}], encountered error: [{e}]. Maybe you should try an alternative structure like [{self.query} Inc., {self.query} Corp., or {self.query} Corporation].'
            return lookup_err_prototype
        if company_firmographics: return company_firmographics
        
        try:
            self.logger.debug(f'Performing EDGAR query for company name: [{self.query}]')
            company_firmographics = self.get_all_details(flat_return=True)
        except Exception as e:
            self.logger.error(f'Wikidata results for [{self.query}] returned [{e}].')
            lookup_err_prototype['code'] = 542
            lookup_err_prototype['message'] = f'Using EDGAR query nable to find a company by the name [{self.query}], encountered error: [{e}]. Maybe you should try an alternative structure like [{self.query} Inc., {self.query} Corp., or {self.query} Corporation].'
            return lookup_err_prototype
        
        # If we have a company_firmographics object then we need to clean it up and 
        # enrich it with urls and location data
        if company_firmographics:
            self.logger.info(f'EDGAR results for [{self.query}] returned successfully.')
            # Get the first key company_firmographics['companies'] 
            new_company_name = next(iter(company_firmographics['companies']), None)
            company_firmographics = company_firmographics['companies'][new_company_name]
            company_firmographics = self._set_location_data(company_firmographics)
            company_firmographics = self._set_google_urls(company_firmographics)
            # Remove all leading and trailing white space from the category
            self.logger.debug(f'Extra characters in category [{ord(company_firmographics['category'][0])}]')
            company_firmographics['category'] = company_firmographics['category'].lstrip('<br>').rstrip('</br>')
            company_firmographics['type'] = 'Public company'           
            return {
                'code': 200, 
                'message': f'Only EDGAR has been detected and returned for the company [{new_company_name}].',
                'module': my_class + '-> ' + my_function,
                'data': company_firmographics,
                'dependencies': DEPENDENCIES
            }
        else:
            lookup_err_prototype['code'] = 404
            lookup_err_prototype['message'] = f'Unable to find a company by the name [{self.query}]. Maybe you should try an alternative structure like [{self.query} Inc., {self.query} Corp., or {self.query} Corporation].'
            return lookup_err_prototype