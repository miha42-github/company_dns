import sys
import sqlite3
import logging
from typing import Dict, Any, Optional, List, Union

__author__ = "Michael Hay"
__copyright__ = "Copyright 2025, Mediumroast, Inc. All rights reserved."
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
        'sicData': 'https://github.com/miha42-github/sic4-list',
        'oshaSICQuery': 'https://www.osha.gov/data/sic-search'
    }
}

# Determine how we output when executed as a CLI
DEBUG: Optional[bool] = None

# Fields from the SQL Select results
DIVISIONS: int = 0
DIVISIONS_DESC: int = 1
DIVISIONS_FULL_DESC: int = 2

MAJOR_GROUPS: int = 1
MAJOR_GROUPS_DESC: int = 2

INDUSTRY_GROUPS: int = 2
INDUSTRY_GROUPS_DESC: int = 3

SICS: int = 3
SICS_DESC: int = 4


class SICQueries:
    """A core set of methods designed to interact with a local instance of SIC data.

    The design point is to enable key data to be retrieved from a cache of SIC data, as stored in SQLite,
    and respond back to the calling user with appropriate data.

    Import and Construct the class:
        import sic
        controller = sic.SICQueries()

    Methods:
        get_all_sic_by_no(query_string) - Using a query_string return only the data associated to a single SIC
        get_all_sic_by_name(query_string) - With query_string return all SICs that are a "fuzzy" match, uses SQL LIKE statement
    """

    def __init__(
        self, 
        db_file: str = './company_dns.db', 
        name: str = 'sic', 
        description: str = 'A module to lookup SIC data.'
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

    def get_all_sic_by_no(self) -> Dict[str, Any]:
        """Using a query string find and return a dictionary containing all SICs with additional metadata. 

        A SIC lookup tool enabling a user to specify a query string and obtain a dictionary containing an object
        keyed by the formal SIC code and includes a dictionary with additional information as the value.
        
        Returns:
            final_sics (dict): An object containing all returned SICs and their associated metadata
        """
        # Define the function and class name
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__

        # Set up the final data structure
        final_sics: Dict[str, Any] = {
            'sics': {},
            'total': 0
        }
        tmp_sics: Dict[str, Dict[str, str]] = {}

        # Get safe query string
        query_str = self._safe_query()

        # Define the SQL Query
        sql_query = "SELECT sic.division, sic.major_group, sic.industry_group, sic.sic, sic.description, " + \
                    "major_groups.description a FROM sic INNER JOIN major_groups ON major_groups.major_group = sic.major_group WHERE sic.sic LIKE ?"

        # Issue the query
        for row in self.ec.execute(sql_query, ('%' + query_str + '%',)):

            # Get the fields in a structure we can manipulate
            sic_code = str(row[SICS])
            sic_desc = str(row[SICS_DESC])
            division = str(row[DIVISIONS])
            major_group = str(row[MAJOR_GROUPS])
            major_group_desc = str(row[5])
            industry_group = str(row[INDUSTRY_GROUPS])

            # Obtain some additional data to make the results have sufficient data
            local_sic = SICQueries()
            local_sic.query = division
            division_results = local_sic.get_division_desc_by_id()
            division_desc = division_results['data']['division'][division]['description']
            local_sic.query = industry_group
            industry_results = local_sic.get_all_industry_group_by_no()
            industry_desc = industry_results['data']['industry_groups'][industry_group]['description']

            # Should the company_name not already be stored in the dict then store it otherwise continue
            if tmp_sics.get(sic_code) is None:
                tmp_sics[sic_code] = {
                    'description': sic_desc,
                    'division': division,
                    'division_desc': division_desc,
                    'major_group': major_group,
                    'major_group_desc': major_group_desc,
                    'industry_group': industry_group,
                    'industry_group_desc': industry_desc
                }
            else:
                continue
        
        final_sics['sics'] = tmp_sics
        final_sics['total'] = len(tmp_sics)
        
        if final_sics['total'] == 0:
            return {
                'code': 404, 
                'message': 'No SIC found for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_sics,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'SIC data has been returned for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_sics,
                'dependencies': DEPENDENCIES
            }

    def get_all_sic_by_name(self) -> Dict[str, Any]:
        """Using a query string find and return a dictionary containing all SIC descriptions with additional metadata. 

        A SIC lookup tool enabling a user to specify a query string and obtain a dictionary containing an object
        keyed by the formal SIC description and includes a dictionary with additional information as the value
        
        Returns:
            final_sics (dict): An object containing all returned SICs and their associated metadata
        """
        # Define the function and class name
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Set up the final data structure
        final_sics: Dict[str, Any] = {
            'sics': {},
            'total': 0
        }
        tmp_sics: Dict[str, Dict[str, str]] = {}

        # Get safe query string
        query_str = self._safe_query()

        self.logger.debug('Querying db cache for [' + query_str + ']')

        # Define the SQL Query
        sql_query = "SELECT sic.division, sic.major_group, sic.industry_group, sic.sic, sic.description, " + \
                    "major_groups.description a FROM sic INNER JOIN major_groups ON major_groups.major_group = sic.major_group WHERE sic.description LIKE ?"

        # Issue the query
        for row in self.ec.execute(sql_query, ('%' + query_str + '%',)):

            self.logger.debug(f'Processing row [{row}]')

            # Get the fields in a structure we can manipulate
            sic_code = str(row[SICS])
            sic_desc = str(row[SICS_DESC])
            division = str(row[DIVISIONS])
            major_group = str(row[MAJOR_GROUPS])
            major_group_desc = str(row[5])
            industry_group = str(row[INDUSTRY_GROUPS])

            # Obtain some additional data to make the results have sufficient data
            local_sic = SICQueries()
            local_sic.query = division
            division_results = local_sic.get_division_desc_by_id()
            division_desc = division_results['data']['division'][division]['description']
            local_sic.query = industry_group
            industry_results = local_sic.get_all_industry_group_by_no()
            industry_desc = industry_results['data']['industry_groups'][industry_group]['description']

            # Should the company_name not already be stored in the dict then store it otherwise continue
            if tmp_sics.get(sic_desc) is None:
                tmp_sics[sic_desc] = {
                    'code': sic_code,
                    'division': division,
                    'division_desc': division_desc,
                    'major_group': major_group,
                    'major_group_desc': major_group_desc,
                    'industry_group': industry_group,
                    'industry_group_desc': industry_desc
                }
            else:
                continue
        
        final_sics['sics'] = tmp_sics
        final_sics['total'] = len(tmp_sics)

        self.logger.info('Found a total of [' + str(final_sics['total']) + '] SICs returning data.')

        if final_sics['total'] == 0:
            final_sics['sics'] = []
            return {
                'code': 404, 
                'message': 'No SICs found for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_sics,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'SIC data has been returned for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_sics,
                'dependencies': DEPENDENCIES
            }

    def get_all_major_group_by_no(self) -> Dict[str, Any]:
        """Using a query string find and return a dictionary containing all major group information with additional metadata. 
        
        Returns:
            final_descs (dict): An object containing all returned major group descriptions
        """
        # Define the function and class name
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Set up the final data structure
        final_descs: Dict[str, Any] = {
            'major_groups': {},
            'total': 0
        }
        tmp_descs: Dict[str, Dict[str, str]] = {}

        # Get safe query string
        query_str = self._safe_query()

        # Define the SQL Query
        sql_query = "SELECT * FROM major_groups WHERE major_group LIKE ?"

        # Issue the query
        for row in self.ec.execute(sql_query, ('%' + query_str + '%',)):

            # Get the fields in a structure we can manipulate
            major_group_no = str(row[MAJOR_GROUPS])
            major_group_desc = str(row[MAJOR_GROUPS_DESC])
            division_id = str(row[DIVISIONS])

            # Should the company_name not already be stored in the dict then store it otherwise continue
            if tmp_descs.get(major_group_no) is None:
                tmp_descs[major_group_no] = {
                    'description': major_group_desc,
                    'division': division_id,
                }
            else:
                continue

        final_descs['major_groups'] = tmp_descs
        final_descs['total'] = len(tmp_descs)

        if final_descs['total'] == 0:
            return {
                'code': 404, 
                'message': 'No Major Group found for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_descs,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'Major group data has been returned for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_descs,
                'dependencies': DEPENDENCIES
            }

    def get_all_industry_group_by_no(self) -> Dict[str, Any]:
        """Using a query string find and return a dictionary containing all industry group descriptions with additional metadata. 
        
        Returns:
            final_descs (dict): An object containing all returned major group descriptions
        """
        # Define the function and class name
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Set up the final data structure
        final_descs: Dict[str, Any] = {
            'industry_groups': {},
            'total': 0
        }
        tmp_descs: Dict[str, Dict[str, str]] = {}

        # Get safe query string
        query_str = self._safe_query()

        # Define the SQL Query
        sql_query = "SELECT * FROM industry_groups WHERE industry_group LIKE ?"

        # Issue the query
        for row in self.ec.execute(sql_query, ('%' + query_str + '%',)):

            # Get the fields in a structure we can manipulate
            industry_group_no = str(row[INDUSTRY_GROUPS])
            industry_group_desc = str(row[INDUSTRY_GROUPS_DESC])
            division_id = str(row[DIVISIONS])
            major_group_no = str(row[MAJOR_GROUPS])

            # Should the company_name not already be stored in the dict then store it otherwise continue
            if tmp_descs.get(industry_group_no) is None:
                tmp_descs[industry_group_no] = {
                    'description': industry_group_desc,
                    'division': division_id,
                    'major_group': major_group_no
                }
            else:
                continue

        final_descs['industry_groups'] = tmp_descs
        final_descs['total'] = len(tmp_descs)

        if final_descs['total'] == 0:
            return {
                'code': 404, 
                'message': 'No Industry Group found for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_descs,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'Industry group data has been returned for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_descs,
                'dependencies': DEPENDENCIES
            }

    def get_division_desc_by_id(self) -> Dict[str, Any]:
        """Using a query string find and return a dictionary containing a division description.
        
        Returns:
            final_descs (dict): An object containing the returned division information
        """
        # Define the function and class name
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Set up the final data structure
        final_descs: Dict[str, Any] = {
            'division': {},
            'total': 0
        }
        tmp_descs: Dict[str, Dict[str, str]] = {}

        # Get safe query string
        query_str = self._safe_query()

        # Define the SQL Query
        sql_query = "SELECT * FROM divisions WHERE division LIKE ?"

        # Issue the query
        for row in self.ec.execute(sql_query, ('%' + query_str + '%',)):

            # Get the fields in a structure we can manipulate
            division_id = str(row[DIVISIONS])
            division_desc = str(row[DIVISIONS_DESC])
            division_full_desc = str(row[DIVISIONS_FULL_DESC])

            # Should the company_name not already be stored in the dict then store it otherwise continue
            if tmp_descs.get(division_id) is None:
                tmp_descs[division_id] = {
                    'description': division_desc,
                    'full_description': division_full_desc
                }
            else:
                continue

        final_descs['division'] = tmp_descs
        final_descs['total'] = len(tmp_descs)

        if final_descs['total'] == 0:
            return {
                'code': 404, 
                'message': 'No Division found for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_descs,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'Division data has been returned for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_descs,
                'dependencies': DEPENDENCIES
            }
