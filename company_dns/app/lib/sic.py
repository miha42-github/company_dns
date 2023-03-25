#!/usr/bin/env python3

import argparse
import pprint
import sys
import pprint
import sqlite3
import re
import urllib.parse as url_parse

__author__ = "Michael Hay"
__copyright__ = "Copyright 2023, Mediumroast, Inc. All rights reserved."
__license__ = "Apache 2.0"
__version__ = "1.0.0"
__maintainer__ = "Michael Hay"
__status__ = "Alpha"
__date__ = '2023-March-11'

#### Globals ####
# Used for setting attributes consistently when unknown
UKN = "Unknown"

# Determine how we output when executed as a CLI
DEBUG = None

# Fields from the SQL Select results
DIVISIONS = 0
DIVISIONS_DESC = 1
DIVISIONS_FULL_DESC = 2

MAJOR_GROUPS = 1
MAJOR_GROUPS_DESC = 2

INDUSTRY_GROUPS = 2
INDUSTRY_GROUPS_DESC = 3

SICS = 3
SICS_DESC = 4


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
        db_file='./edgar_cache.db', 
        name='sic', 
        description='A module and simple CLI too to lookup SIC data.'):

        # The SQLite database connection and cursor
        self.e_conn = sqlite3.connect(db_file)
        self.ec = self.e_conn.cursor()

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
            '--query',
            help="Description of the SIC to search for in data cache.",
            type=str,
            dest='query',
            required=True
        )
        parser.add_argument(
            '--operation',
            help="Type of details to search for.",
            type=str,
            dest='operation',
            choices=['description', 'code'],
            default='description',
            required=True
        )
        parser.add_argument(
            "--debug",
            help="Turn on debugging",
            dest="debug",
            type=int,
            default=0,
        )

        # Parse the CLI
        cli_args = parser.parse_args()

        # Return parsed arguments
        return cli_args

    def get_all_sic_by_no(self):
        """Using a query string find and return a dictionary containing all SICs with additional metadata. 

        A SIC lookup tool enabling a user to specify a query string and obtain a dictionary containing an object
        keyed by the formal SIC code and includes a dictionary with additional information as the value.
        
        An example of the returned dictionary is below:
        {
            '4512': {'description': 'Air Transportation, Scheduled',
                   'division': 'E',
                   'industry_group': '451',
                   'major_group': '45',
                   'major_group_desc': 'Transportation By Air'} 
            'total': 1
        }

        Returns:
            final_sics (dict): An object containing all returned SICs and their associated metadata
        """
        # Define the function and class name
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__

        # Set up the final data structure
        final_sics = {
            'sics': {},
            'total': 0
        }
        tmp_sics = {}

        # Define the SQL Query
        sql_query = "SELECT sic.division, sic.major_group, sic.industry_group, sic.sic, sic.description, " + \
                    "major_groups.description a FROM sic INNER JOIN major_groups ON major_groups.major_group = sic.major_group WHERE sic.sic LIKE '%" + self.query + "%' "

        # Issue the query
        for row in self.ec.execute(sql_query):

            # Get the fields in a structure we can manipulate
            sic_code = str(row[SICS])
            sic_desc = str(row[SICS_DESC])
            division = str(row[DIVISIONS])
            major_group = str(row[MAJOR_GROUPS])
            industry_group = str(row[INDUSTRY_GROUPS])
            major_group_desc = str(row[5])

            # Should the company_name not already be stored in the dict then store it otherwise continue
            if tmp_sics.get(sic_code) == None:
                tmp_sics[sic_code] = {
                    'description': sic_desc,
                    'division': division,
                    'major_group': major_group,
                    'industry_group': industry_group,
                    'major_group_desc': major_group_desc
                }
            else:
                continue
        
        final_sics['sics'] = tmp_sics
        final_sics['total'] = len(tmp_sics)
        if final_sics['total'] == 0:
            return {
                'code': 404, 
                'message': 'No SIC found for query [' + self.query + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_sics
            }
        else:
            return {
                'code': 200, 
                'message': 'SIC data has been returned for query [' + self.query + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_sics
            }

    def get_all_sic_by_name(self):
        """Using a query string find and return a dictionary containing all SIC descriptions with additional metadata. 

        A SIC lookup tool enabling a user to specify a query string and obtain a dictionary containing an object
        keyed by the formal SIC description and includes a dictionary with additional information as the value
        
        An example of the returned dictionary is below:
        {
            'sics': {'code': '2075',
                                'division': 'D',
                                'industry_group': '207',
                                'major_group': '20',
                                'major_group_desc': 'Food And Kindred '
                                                    'Products'}, 
            'total': 1
        }

        Returns:
            final_sics (dict): An object containing all returned SICs and their associated metadata
        """
        # Define the function and class name
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Set up the final data structure
        final_sics = {
            'sics': {},
            'total': 0
        }
        tmp_sics = {}

        # Define the SQL Query
        sql_query = "SELECT sic.division, sic.major_group, sic.industry_group, sic.sic, sic.description, " + \
                    "major_groups.description a FROM sic INNER JOIN major_groups ON major_groups.major_group = sic.major_group WHERE sic.description LIKE '%" + self.query + "%' "

        # Issue the query
        for row in self.ec.execute(sql_query):

            # Get the fields in a structure we can manipulate
            sic_code = str(row[SICS])
            sic_desc = str(row[SICS_DESC])
            division = str(row[DIVISIONS])
            major_group = str(row[MAJOR_GROUPS])
            industry_group = str(row[INDUSTRY_GROUPS])
            major_group_desc = str(row[5])

            # Should the company_name not already be stored in the dict then store it otherwise continue
            if tmp_sics.get(sic_desc) == None:
                tmp_sics[sic_desc] = {
                    'code': sic_code,
                    'division': division,
                    'major_group': major_group,
                    'industry_group': industry_group,
                    'major_group_desc': major_group_desc
                }
            else:
                continue
        
        final_sics['sics'] = tmp_sics
        final_sics['total'] = len(tmp_sics)
        if final_sics['total'] == 0:
            return {
                'code': 404, 
                'message': 'No SICs found for query [' + self.query + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_sics
            }
        else:
            return {
                'code': 200, 
                'message': 'SIC data has been returned for query [' + self.query + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_sics
            }

    def get_all_major_group_by_no(self):
        """Using a query string find and return a dictionary containing all major group information with additional metadata. 
        
        An example of the returned dictionary is below:
        {
            'major_groups': {
                '01': {
                    ...
                }
            }
            'total': 1
        }

        Returns:
            final_descs (dict): An object containing all returned major group descriptions
        """
        # Define the function and class name
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Set up the final data structure
        final_descs = {
            'major_groups': {},
            'total': 0
        }
        tmp_descs = {}

        # Define the SQL Query
        sql_query = "SELECT * FROM major_groups WHERE major_group LIKE '%" + self.query + "%' "

        # Issue the query
        for row in self.ec.execute(sql_query):

            # Get the fields in a structure we can manipulate
            major_group_no = str(row[MAJOR_GROUPS])
            major_group_desc = str(row[MAJOR_GROUPS_DESC])
            division_id = str(row[DIVISIONS])

            # Should the company_name not already be stored in the dict then store it otherwise continue
            if tmp_descs.get(major_group_no) == None:
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
                'message': 'No Major Group found for query [' + self.query + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_descs
            }
        else:
            return {
                'code': 200, 
                'message': 'Major group data has been returned for query [' + self.query + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_descs
            }

    def get_all_industry_group_by_no(self):
        """Using a query string find and return a dictionary containing all industry group descriptions with additional metadata. 
        
        An example of the returned dictionary is below:
        {
            'industry_groups': {
                '011': {
                    ...
                }
            }
            'total': 1
        }

        Returns:
            final_descs (dict): An object containing all returned major group descriptions
        """
        # Define the function and class name
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Set up the final data structure
        final_descs = {
            'industry_groups': {},
            'total': 0
        }
        tmp_descs = {}

        # Define the SQL Query
        sql_query = "SELECT * FROM industry_groups WHERE industry_group LIKE '%" + self.query + "%' "

        # Issue the query
        for row in self.ec.execute(sql_query):

            # Get the fields in a structure we can manipulate
            industry_group_no = str(row[INDUSTRY_GROUPS])
            industry_group_desc = str(row[INDUSTRY_GROUPS_DESC])
            division_id = str(row[DIVISIONS])
            major_group_no = str(row[MAJOR_GROUPS])

            # Should the company_name not already be stored in the dict then store it otherwise continue
            if tmp_descs.get(industry_group_no) == None:
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
                'message': 'No Industry Group found for query [' + self.query + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_descs
            }
        else:
            return {
                'code': 200, 
                'message': 'Industry group data has been returned for query [' + self.query + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_descs
            }

    def get_division_desc_by_id(self):
        """Using a query string find and return a dictionary containing a division description.
        
        An example of the returned dictionary is below:
        {
            'division': {
                'id': 'A',
                'description': '',
                'full_description: ''
            }
            'total': 1
        }

        Returns:
            final_descs (dict): An object containing the returned division information
        """
        # Define the function and class name
        my_function = sys._getframe(0).f_code.co_name
        my_class = self.__class__.__name__
        
        # Set up the final data structure
        final_descs = {
            'division': {},
            'total': 0
        }
        tmp_descs = {}

        # Define the SQL Query
        sql_query = "SELECT * FROM divisions WHERE division LIKE '%" + self.query + "%' "

        # Issue the query
        for row in self.ec.execute(sql_query):

            # Get the fields in a structure we can manipulate
            division_id = str(row[DIVISIONS])
            division_desc = str(row[DIVISIONS_DESC])
            division_full_desc = str(row[DIVISIONS_FULL_DESC])

            # Should the company_name not already be stored in the dict then store it otherwise continue
            if tmp_descs.get(division_id) == None:
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
                'message': 'No Division found for query [' + self.query + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_descs
            }
        else:
            return {
                'code': 200, 
                'message': 'Division data has been returned for query [' + self.query + '].',
                'module': my_class + '-> ' + my_function,
                'data': final_descs
            }



if __name__ == '__main__':
    q = SICQueries(db_file='../company_dns.db')
    cli_args = q.get_cli_args()
    q.query = cli_args.query
    DEBUG = cli_args.debug
    
    results = dict()
    
    if cli_args.operation == 'description':
        results = q.get_all_sic_by_name()
    elif cli_args.operation == 'code':
        results = q.get_all_sic_by_no()
    
    if not DEBUG: pprint.pprint(results)
