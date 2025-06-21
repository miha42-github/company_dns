import sys
import sqlite3
import logging

__author__ = "Michael Hay"
__copyright__ = "Copyright 2024, Mediumroast, Inc. All rights reserved."
__license__ = "Apache 2.0"
__version__ = "2.0.0"
__maintainer__ = "Michael Hay"
__status__ = "Production"
__contact__ = 'https://github.com/miha42-github/company_dns'

#### Globals ####
# Used for setting attributes consistently when unknown
UKN = "Unknown"

# Package and data dependencies
DEPENDENCIES = {
    'modules': {},
    'data': {
        'ukSicData': 'https://www.gov.uk/government/publications/standard-industrial-classification-of-economic-activities-sic'
    }
}

# Fields from the SQL Select results
SIC_CODE = 0
SIC_DESC = 1

class UKSICQueries:
    """A core set of methods designed to interact with a local instance of UK SIC data.

    The design point is to enable key data to be retrieved from a cache of UK SIC data, as stored in SQLite,
    and respond back to the calling user with appropriate data.

    Import and Construct the class:
        import uk_sic
        controller = uk_sic.UKSICQueries()

    Methods:
        get_uk_sic_by_code(query_string) - Using a query_string return only the data associated to a single UK SIC code
        get_uk_sic_by_name(query_string) - With query_string return all UK SICs that are a "fuzzy" match, uses SQL LIKE statement
    """

    def __init__(
        self, 
        db_file='./company_dns.db', 
        name='uk_sic', 
        description='A module to lookup UK SIC data.'):

        # The SQLite database connection and cursor
        self.e_conn = sqlite3.connect(db_file)
        self.ec = self.e_conn.cursor()
        self.db_file = db_file

        # Naming helpers
        self.NAME = name
        self.DESC = description

        # Query object
        self.query = None

        # Set up the logging
        self.logger = logging.getLogger(self.NAME)

    def get_uk_sic_by_code(self):
        """Using a query string find and return a dictionary containing UK SIC codes with their descriptions.

        A UK SIC lookup tool enabling a user to specify a query string and obtain a dictionary containing an object
        keyed by the formal UK SIC code and includes a dictionary with the description as the value.
        
        An example of the returned dictionary is below:
        {
            '01110': {'description': 'Growing of cereals (except rice), leguminous crops and oil seeds'},
            'total': 1
        }

        Returns:
            final_sics (dict): An object containing all returned UK SICs and their descriptions
        """
        # Define the function and class name
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__

        # Set up the final data structure
        final_sics = {
            'uk_sics': {},
            'total': 0
        }
        tmp_sics = {}

        # Define the SQL Query
        sql_query = "SELECT sic_code, description FROM uk_sic WHERE sic_code LIKE '%" + self.query + "%'"

        # Issue the query
        for row in self.ec.execute(sql_query):
            # Get the fields in a structure we can manipulate
            sic_code = str(row[SIC_CODE])
            sic_desc = str(row[SIC_DESC])

            # Should the SIC code not already be stored in the dict then store it otherwise continue
            if tmp_sics.get(sic_code) is None:
                tmp_sics[sic_code] = {
                    'description': sic_desc
                }
            else:
                continue
        
        final_sics['uk_sics'] = tmp_sics
        final_sics['total'] = len(tmp_sics)
        
        if final_sics['total'] == 0:
            return {
                'code': 404, 
                'message': 'No UK SIC found for query [' + self.query + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_sics,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'UK SIC data has been returned for query [' + self.query + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_sics,
                'dependencies': DEPENDENCIES
            }

    def get_uk_sic_by_name(self):
        """Using a query string find and return a dictionary containing UK SIC descriptions with their codes.

        A UK SIC lookup tool enabling a user to specify a query string and obtain a dictionary containing an object
        keyed by the description and includes a dictionary with the SIC code as the value.
        
        An example of the returned dictionary is below:
        {
            'Growing of cereals (except rice), leguminous crops and oil seeds': {'code': '01110'},
            'total': 1
        }

        Returns:
            final_sics (dict): An object containing all returned UK SICs and their codes
        """
        # Define the function and class name
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Set up the final data structure
        final_sics = {
            'uk_sics': {},
            'total': 0
        }
        tmp_sics = {}

        self.logger.debug('Querying db cache for [' + self.query + ']')

        # Define the SQL Query
        sql_query = "SELECT sic_code, description FROM uk_sic WHERE description LIKE '%" + self.query + "%'"

        # Issue the query
        for row in self.ec.execute(sql_query):
            self.logger.debug(f'Processing row [{row}]')

            # Get the fields in a structure we can manipulate
            sic_code = str(row[SIC_CODE])
            sic_desc = str(row[SIC_DESC])

            # Should the description not already be stored in the dict then store it otherwise continue
            if tmp_sics.get(sic_desc) is None:
                tmp_sics[sic_desc] = {
                    'code': sic_code
                }
            else:
                continue
        
        final_sics['uk_sics'] = tmp_sics
        final_sics['total'] = len(tmp_sics)

        self.logger.info('Found a total of [' + str(final_sics['total']) + '] UK SICs returning data.')

        if final_sics['total'] == 0:
            final_sics['uk_sics'] = []
            return {
                'code': 404, 
                'message': 'No UK SICs found for query [' + self.query + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_sics,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'UK SIC data has been returned for query [' + self.query + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_sics,
                'dependencies': DEPENDENCIES
            }