import sys
import sqlite3
import logging
from typing import Dict, Any, Optional, List, Union

__author__ = "Michael Hay"
__copyright__ = "Copyright 2024, Mediumroast, Inc. All rights reserved."
__license__ = "Apache 2.0"
__version__ = "2.0.0"
__maintainer__ = "Michael Hay"
__status__ = "Production"
__contact__ = 'https://github.com/miha42-github/company_dns'

#### Globals ####
# Used for setting attributes consistently when unknown
UKN: str = "Unknown"

# Package and data dependencies
DEPENDENCIES: Dict[str, Dict[str, str]] = {
    'modules': {},
    'data': {
        'ukSicData': 'https://www.gov.uk/government/publications/standard-industrial-classification-of-economic-activities-sic'
    }
}

# Fields from the SQL Select results
SIC_CODE: int = 0
SIC_DESC: int = 1

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
        db_file: str = './company_dns.db', 
        name: str = 'uk_sic', 
        description: str = 'A module to lookup UK SIC data.'
    ) -> None:

        # The SQLite database connection and cursor
        self.e_conn: sqlite3.Connection = sqlite3.connect(db_file)
        self.ec: sqlite3.Cursor = self.e_conn.cursor()
        self.db_file: str = db_file

        # Naming helpers
        self.NAME: str = name
        self.DESC: str = description

        # Query object
        self.query: Optional[str] = None

        # Set up the logging
        self.logger: logging.Logger = logging.getLogger(self.NAME)
    
    def _safe_query(self) -> str:
        """Return a safe version of the query string, handling None values
        
        Returns:
            str: The query string or empty string if None
        """
        return "" if self.query is None else str(self.query)

    def get_uk_sic_by_code(self) -> Dict[str, Any]:
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
        final_sics: Dict[str, Any] = {
            'uk_sics': {},
            'total': 0
        }
        tmp_sics: Dict[str, Dict[str, str]] = {}

        # Get safe query string
        query_str = self._safe_query()

        # Define the SQL Query - use parameter binding instead of string concatenation
        sql_query = "SELECT sic_code, description FROM uk_sic WHERE sic_code LIKE ?"

        # Issue the query
        for row in self.ec.execute(sql_query, ('%' + query_str + '%',)):
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
                'message': 'No UK SIC found for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_sics,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'UK SIC data has been returned for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_sics,
                'dependencies': DEPENDENCIES
            }

    def get_uk_sic_by_name(self) -> Dict[str, Any]:
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
        final_sics: Dict[str, Any] = {
            'uk_sics': {},
            'total': 0
        }
        tmp_sics: Dict[str, Dict[str, str]] = {}

        # Get safe query string
        query_str = self._safe_query()

        self.logger.debug('Querying db cache for [' + query_str + ']')

        # Define the SQL Query - use parameter binding instead of string concatenation
        sql_query = "SELECT sic_code, description FROM uk_sic WHERE description LIKE ?"

        # Issue the query
        for row in self.ec.execute(sql_query, ('%' + query_str + '%',)):
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
                'message': 'No UK SICs found for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_sics,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'UK SIC data has been returned for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_sics,
                'dependencies': DEPENDENCIES
            }