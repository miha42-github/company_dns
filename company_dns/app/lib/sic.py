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
        """
        """
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
                    'code': sic_desc,
                    'division': division,
                    'major_group': major_group,
                    'industry_group': industry_group,
                    'major_group_desc': major_group_desc
                }
            else:
                continue
        
        final_sics['sics'] = tmp_sics
        final_sics['total'] = len(tmp_sics)
        return final_sics

    def get_all_sic_by_name(self):
        """
        """
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
        return final_sics


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
