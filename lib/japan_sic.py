import sys
import sqlite3
import logging
from typing import Optional, Dict, Any, List, Tuple

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
        'japanSicData': 'https://www.stat.go.jp/english/data/e-census/2021/industry.html'
    }
}

# Fields from the SQL Select results
DIVISION_CODE = 0
DIVISION_DESC = 1

MAJOR_GROUP_CODE = 0
MAJOR_GROUP_DESC = 1
MAJOR_GROUP_DIVISION = 2

GROUP_CODE = 0
GROUP_DESC = 1
GROUP_MAJOR_GROUP = 2
GROUP_DIVISION = 3

INDUSTRY_GROUP_CODE = 0
INDUSTRY_GROUP_DESC = 1
INDUSTRY_GROUP_GROUP = 2
INDUSTRY_GROUP_MAJOR_GROUP = 3
INDUSTRY_GROUP_DIVISION = 4

class JapanSICQueries:
    """A core set of methods designed to interact with a local instance of Japan SIC data.

    The design point is to enable key data to be retrieved from a cache of Japan SIC data, as stored in SQLite,
    and respond back to the calling user with appropriate data.

    Import and Construct the class:
        import japan_sic
        controller = japan_sic.JapanSICQueries()

    Methods:
        get_division_by_code(query_string) - Return division data for the given code
        get_major_group_by_code(query_string) - Return major group data for the given code
        get_group_by_code(query_string) - Return group data for the given code
        get_industry_group_by_code(query_string) - Return industry group data for the given code
        get_industry_group_by_description(query_string) - Return industry groups matching the description
    """

    def __init__(
        self, 
        db_file: str = './company_dns.db', 
        name: str = 'japan_sic', 
        description: str = 'A module to lookup Japan SIC data.'):

        # The SQLite database connection and cursor
        self.e_conn = sqlite3.connect(db_file)
        self.ec = self.e_conn.cursor()
        self.db_file: str = db_file

        # Naming helpers
        self.NAME: str = name
        self.DESC: str = description

        # Query object
        self.query: Optional[str] = None

        # Set up the logging
        self.logger = logging.getLogger(self.NAME)
        
    def _safe_query(self) -> str:
        """Return the query string safely, handling None values
        
        Returns:
            str: The query string or empty string if None
        """
        return "" if self.query is None else self.query

    def get_division_by_code(self) -> Dict[str, Any]:
        """Return division data for the given code
        
        Returns:
            divisions_data (dict): Data about the division
        """
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Set up the final data structure
        final_divisions: Dict[str, Any] = {
            'divisions': {},
            'total': 0
        }
        
        # Get safe query string
        query_str = self._safe_query()
        
        # Define the SQL Query
        sql_query = "SELECT division_code, description FROM japan_sic_divisions WHERE division_code LIKE ?"
        
        # Issue the query
        for row in self.ec.execute(sql_query, ('%' + query_str + '%',)):
            division_code = str(row[DIVISION_CODE])
            division_desc = str(row[DIVISION_DESC])
            
            final_divisions['divisions'][division_code] = {
                'description': division_desc
            }
        
        final_divisions['total'] = len(final_divisions['divisions'])
        
        if final_divisions['total'] == 0:
            return {
                'code': 404, 
                'message': 'No Japan SIC division found for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_divisions,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'Japan SIC division data has been returned for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_divisions,
                'dependencies': DEPENDENCIES
            }

    def get_major_group_by_code(self) -> Dict[str, Any]:
        """Return major group data for the given code
        
        Returns:
            major_groups_data (dict): Data about the major group
        """
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Set up the final data structure
        final_major_groups: Dict[str, Any] = {
            'major_groups': {},
            'total': 0
        }
        
        # Get safe query string
        query_str = self._safe_query()
        
        # Define the SQL Query
        sql_query = "SELECT major_group_code, description, division_code FROM japan_sic_major_groups WHERE major_group_code LIKE ?"
        
        # Issue the query
        for row in self.ec.execute(sql_query, ('%' + query_str + '%',)):
            major_group_code = str(row[MAJOR_GROUP_CODE])
            major_group_desc = str(row[MAJOR_GROUP_DESC])
            division_code = str(row[MAJOR_GROUP_DIVISION])
            
            final_major_groups['major_groups'][major_group_code] = {
                'description': major_group_desc,
                'division_code': division_code
            }
        
        final_major_groups['total'] = len(final_major_groups['major_groups'])
        
        if final_major_groups['total'] == 0:
            return {
                'code': 404, 
                'message': 'No Japan SIC major group found for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_major_groups,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'Japan SIC major group data has been returned for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_major_groups,
                'dependencies': DEPENDENCIES
            }

    def get_group_by_code(self) -> Dict[str, Any]:
        """Return group data for the given code
        
        Returns:
            groups_data (dict): Data about the group
        """
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Set up the final data structure
        final_groups: Dict[str, Any] = {
            'groups': {},
            'total': 0
        }
        
        # Get safe query string
        query_str = self._safe_query()
        
        # Define the SQL Query
        sql_query = "SELECT group_code, description, major_group_code, division_code FROM japan_sic_groups WHERE group_code LIKE ?"
        
        # Issue the query
        for row in self.ec.execute(sql_query, ('%' + query_str + '%',)):
            group_code = str(row[GROUP_CODE])
            group_desc = str(row[GROUP_DESC])
            major_group_code = str(row[GROUP_MAJOR_GROUP])
            division_code = str(row[GROUP_DIVISION])
            
            final_groups['groups'][group_code] = {
                'description': group_desc,
                'major_group_code': major_group_code,
                'division_code': division_code
            }
        
        final_groups['total'] = len(final_groups['groups'])
        
        if final_groups['total'] == 0:
            return {
                'code': 404, 
                'message': 'No Japan SIC group found for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_groups,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'Japan SIC group data has been returned for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_groups,
                'dependencies': DEPENDENCIES
            }

    def get_industry_group_by_code(self) -> Dict[str, Any]:
        """Return industry group data for the given code
        
        Returns:
            industry_groups_data (dict): Data about the industry group
        """
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Set up the final data structure
        final_industry_groups: Dict[str, Any] = {
            'industry_groups': {},
            'total': 0
        }
        
        # Get safe query string
        query_str = self._safe_query()
        
        # Define the SQL Query
        sql_query = "SELECT industry_code, description, group_code, major_group_code, division_code FROM japan_sic_industry_groups WHERE industry_code LIKE ?"
        
        # Issue the query
        for row in self.ec.execute(sql_query, ('%' + query_str + '%',)):
            industry_code = str(row[INDUSTRY_GROUP_CODE])
            industry_desc = str(row[INDUSTRY_GROUP_DESC])
            group_code = str(row[INDUSTRY_GROUP_GROUP])
            major_group_code = str(row[INDUSTRY_GROUP_MAJOR_GROUP])
            division_code = str(row[INDUSTRY_GROUP_DIVISION])
            
            final_industry_groups['industry_groups'][industry_code] = {
                'description': industry_desc,
                'group_code': group_code,
                'major_group_code': major_group_code,
                'division_code': division_code
            }
        
        final_industry_groups['total'] = len(final_industry_groups['industry_groups'])
        
        if final_industry_groups['total'] == 0:
            return {
                'code': 404, 
                'message': 'No Japan SIC industry group found for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_industry_groups,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'Japan SIC industry group data has been returned for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_industry_groups,
                'dependencies': DEPENDENCIES
            }

    def get_industry_group_by_description(self) -> Dict[str, Any]:
        """Return industry groups matching the description
        
        Returns:
            industry_groups_data (dict): Data about matching industry groups
        """
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Set up the final data structure
        final_industry_groups: Dict[str, Any] = {
            'industry_groups': {},
            'total': 0
        }
        
        # Get safe query string
        query_str = self._safe_query()
        
        # Define the SQL Query
        sql_query = "SELECT industry_code, description, group_code, major_group_code, division_code FROM japan_sic_industry_groups WHERE description LIKE ?"
        
        # Issue the query
        for row in self.ec.execute(sql_query, ('%' + query_str + '%',)):
            industry_code = str(row[INDUSTRY_GROUP_CODE])
            industry_desc = str(row[INDUSTRY_GROUP_DESC])
            group_code = str(row[INDUSTRY_GROUP_GROUP])
            major_group_code = str(row[INDUSTRY_GROUP_MAJOR_GROUP])
            division_code = str(row[INDUSTRY_GROUP_DIVISION])
            
            final_industry_groups['industry_groups'][industry_desc] = {
                'code': industry_code,
                'group_code': group_code,
                'major_group_code': major_group_code,
                'division_code': division_code
            }
        
        final_industry_groups['total'] = len(final_industry_groups['industry_groups'])
        
        if final_industry_groups['total'] == 0:
            return {
                'code': 404, 
                'message': 'No Japan SIC industry group found for description query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_industry_groups,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'Japan SIC industry group data has been returned for description query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_industry_groups,
                'dependencies': DEPENDENCIES
            }