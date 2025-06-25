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
        'isicData': 'https://unstats.un.org/unsd/classifications/Econ/isic'
    }
}

# Fields from the SQL Select results
SECTION_CODE = 0
SECTION_DESC = 1

DIVISION_CODE = 0
DIVISION_DESC = 1
DIVISION_SECTION = 2

GROUP_CODE = 0
GROUP_DESC = 1
GROUP_DIVISION = 2
GROUP_SECTION = 3

CLASS_CODE = 0
CLASS_DESC = 1
CLASS_GROUP = 2
CLASS_DIVISION = 3
CLASS_SECTION = 4

class InternationalSICQueries:
    """A core set of methods designed to interact with a local instance of International SIC (ISIC) data.

    The design point is to enable key data to be retrieved from a cache of ISIC data, as stored in SQLite,
    and respond back to the calling user with appropriate data.

    Import and Construct the class:
        import international_sic
        controller = international_sic.InternationalSICQueries()

    Methods:
        get_section_by_code(query_string) - Return section data for the given code
        get_division_by_code(query_string) - Return division data for the given code
        get_group_by_code(query_string) - Return group data for the given code
        get_class_by_code(query_string) - Return class data for the given code
        get_class_by_description(query_string) - Return classes matching the description
    """

    def __init__(
        self, 
        db_file: str = './company_dns.db', 
        name: str = 'international_sic', 
        description: str = 'A module to lookup International SIC (ISIC) data.'):

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

    def get_section_by_code(self) -> Dict[str, Any]:
        """Return section data for the given code
        
        Returns:
            sections_data (dict): Data about the section
        """
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Set up the final data structure
        final_sections: Dict[str, Any] = {
            'sections': {},
            'total': 0
        }
        
        # Get safe query string
        query_str = self._safe_query()
        
        # Define the SQL Query
        sql_query = "SELECT section_code, description FROM isic_sections WHERE section_code LIKE ?"
        
        # Issue the query
        for row in self.ec.execute(sql_query, ('%' + query_str + '%',)):
            section_code = str(row[SECTION_CODE])
            section_desc = str(row[SECTION_DESC])
            
            final_sections['sections'][section_code] = {
                'description': section_desc
            }
        
        final_sections['total'] = len(final_sections['sections'])
        
        if final_sections['total'] == 0:
            return {
                'code': 404, 
                'message': 'No section found for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_sections,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'Section data has been returned for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_sections,
                'dependencies': DEPENDENCIES
            }

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
        sql_query = "SELECT division_code, description, section_code FROM isic_divisions WHERE division_code LIKE ?"
        
        # Issue the query
        for row in self.ec.execute(sql_query, ('%' + query_str + '%',)):
            division_code = str(row[DIVISION_CODE])
            division_desc = str(row[DIVISION_DESC])
            section_code = str(row[DIVISION_SECTION])
            
            final_divisions['divisions'][division_code] = {
                'description': division_desc,
                'section_code': section_code
            }
        
        final_divisions['total'] = len(final_divisions['divisions'])
        
        if final_divisions['total'] == 0:
            return {
                'code': 404, 
                'message': 'No division found for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_divisions,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'Division data has been returned for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_divisions,
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
        sql_query = "SELECT group_code, description, division_code, section_code FROM isic_groups WHERE group_code LIKE ?"
        
        # Issue the query
        for row in self.ec.execute(sql_query, ('%' + query_str + '%',)):
            group_code = str(row[GROUP_CODE])
            group_desc = str(row[GROUP_DESC])
            division_code = str(row[GROUP_DIVISION])
            section_code = str(row[GROUP_SECTION])
            
            final_groups['groups'][group_code] = {
                'description': group_desc,
                'division_code': division_code,
                'section_code': section_code
            }
        
        final_groups['total'] = len(final_groups['groups'])
        
        if final_groups['total'] == 0:
            return {
                'code': 404, 
                'message': 'No group found for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_groups,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'Group data has been returned for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_groups,
                'dependencies': DEPENDENCIES
            }

    def get_class_by_code(self) -> Dict[str, Any]:
        """Return class data for the given code
        
        Returns:
            classes_data (dict): Data about the class
        """
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Set up the final data structure
        final_classes: Dict[str, Any] = {
            'classes': {},
            'total': 0
        }
        
        # Get safe query string
        query_str = self._safe_query()
        
        # Define the SQL Query
        sql_query = "SELECT class_code, description, group_code, division_code, section_code FROM isic_classes WHERE class_code LIKE ?"
        
        # Issue the query
        for row in self.ec.execute(sql_query, ('%' + query_str + '%',)):
            class_code = str(row[CLASS_CODE])
            class_desc = str(row[CLASS_DESC])
            group_code = str(row[CLASS_GROUP])
            division_code = str(row[CLASS_DIVISION])
            section_code = str(row[CLASS_SECTION])
            
            final_classes['classes'][class_code] = {
                'description': class_desc,
                'group_code': group_code,
                'division_code': division_code,
                'section_code': section_code
            }
        
        final_classes['total'] = len(final_classes['classes'])
        
        if final_classes['total'] == 0:
            return {
                'code': 404, 
                'message': 'No class found for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_classes,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'Class data has been returned for query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_classes,
                'dependencies': DEPENDENCIES
            }

    def get_class_by_description(self) -> Dict[str, Any]:
        """Return classes matching the description
        
        Returns:
            classes_data (dict): Data about matching classes
        """
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Set up the final data structure
        final_classes: Dict[str, Any] = {
            'classes': {},
            'total': 0
        }
        
        # Get safe query string
        query_str = self._safe_query()
        
        # Define the SQL Query
        sql_query = "SELECT class_code, description, group_code, division_code, section_code FROM isic_classes WHERE description LIKE ?"
        
        # Issue the query
        for row in self.ec.execute(sql_query, ('%' + query_str + '%',)):
            class_code = str(row[CLASS_CODE])
            class_desc = str(row[CLASS_DESC])
            group_code = str(row[CLASS_GROUP])
            division_code = str(row[CLASS_DIVISION])
            section_code = str(row[CLASS_SECTION])
            
            final_classes['classes'][class_desc] = {
                'code': class_code,
                'group_code': group_code,
                'division_code': division_code,
                'section_code': section_code
            }
        
        final_classes['total'] = len(final_classes['classes'])
        
        if final_classes['total'] == 0:
            return {
                'code': 404, 
                'message': 'No class found for description query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_classes,
                'dependencies': DEPENDENCIES
            }
        else:
            return {
                'code': 200, 
                'message': 'Class data has been returned for description query [' + query_str + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_classes,
                'dependencies': DEPENDENCIES
            }