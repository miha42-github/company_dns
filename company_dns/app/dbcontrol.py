#!/usr/bin/env python3

import re
import sqlite3
import logging
import os
import argparse
import sys
import csv
import gzip
import shutil
from pyedgar.utilities.indices import IndexMaker
from os import path

"""
Copyright 2023 mediumroast.io.  All rights reserved
Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
in compliance with the License. You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License
is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied. See the License for the specific language governing permissions and limitations under
the License.
"""


__author__ = "Michael Hay"
__copyright__ = "Copyright 2021, mediumroast.io"
__license__ = "ASF 2.0"
__version__ = "2.1.0"
__maintainer__ = "Michael Hay"
__status__ = "Alpha"
__id__ = "$Id$"

# Globals
PATH = "./"
CACHE_CONTROL = '.cache_exists'
DB_CONTROL = '.db_exists'
DB_CACHE = 'company_dns.db'
DIVISIONS = 0
MAJOR_GROUPS = 1
INDUSTRY_GROUPS = 2
SICS = 3


def initialize(start_year=2019):
    """
    Using the appropriate method in PyEdgar download the file cache for that defines the relevant SEC filings for
    companies given the start_year variable. The method in this package then will format the content into tab
    delimited files and prepare them for processing.

    :type start_year: int
    ;param start_year: define the start year for the initialization of the cache
    """

    if path.exists(PATH + CACHE_CONTROL):
        return True, "Cache already exists, will not fetch cache files"
    else:
        i = IndexMaker()
        i.extract_indexes(start_year=start_year)  # Download and create the index
        open(PATH + CACHE_CONTROL, 'w').close()  # Create the file that controls the reindexing
        return True, "Downloaded cache files from the SEC"


def clean_cache():
    """
    Remove all cache file instances which include tab delimited files and gz files, and return the number of files
    removed.

    """
    logger.info('Cleaning up cache control file.')
    try:
        os.remove(PATH + CACHE_CONTROL)
    except FileNotFoundError:
        logger.warning('The supplied file name, %s, for the db cache control was not found.', CACHE_CONTROL)

    logger.info('Cleaning up cached quarterly EDGAR instances from the filesystem.')
    num = 0
    tab_type = re.compile('^form.*\.tab$')
    gz_type = re.compile('^full_index_\d+.*\.gz$')
    for subdir, dirs, files in os.walk(PATH):
        for fil in files:
            if tab_type.match(fil) or gz_type.match(fil):
                logger.debug('Removing cache file: %s', PATH + fil)
                num += 1
                try:
                    os.remove(PATH + fil)
                except FileNotFoundError:
                    logger.warning('The supplied file name, %s, for the file cache was not found.', fil)
    return num


def build_idx(file_name):
    """
    Generate an index suitable to load into a db cache

    :param file_name: name of the *.tab file to process
    """
    logger.info('Creating the data structure from the compressed index file.')
    header_re = re.compile('^cik', re.IGNORECASE)  # Detect the headers for the idx
    idx = list()
    num = 0
    with gzip.open(file_name + '.gz', 'rb') as f_in:
        with open(file_name, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)

    with open(file_name, newline='') as content:
        csv_reader = csv.reader(content, delimiter='\t')
        for entry in csv_reader:
            if header_re.match(entry[0]):
                continue
            logger.debug('Detected 10K form proceeding to process')
            my_cik = entry[0]
            my_company = entry[1]
            my_form = entry[2]
            (my_year, my_month, my_day) = entry[3].split('-')
            my_accession = entry[4]
            idx.append([my_cik, my_company, int(my_year), int(my_month), int(my_day), my_accession, my_form])
    return idx, len(idx)


def clean_db():
    """
    Remove the DB Cache from the file system including the control file

    """
    logger.info('Cleaning up the db cache instance, %s, from the filesystem.', PATH + DB_CACHE)
    try:
        os.remove(PATH + DB_CACHE)
        os.remove(PATH + DB_CONTROL)
    except FileNotFoundError:
        logger.warning('The supplied file names, %s and %s, for the db cache was not found.', DB_CACHE, DB_CONTROL)
        return


def create_db():
    """
    Create an empty database cache file and return the DB cursor

    :param db_name: name of the database cache file
    """
    logger.info('Attaching to the database file %s.', PATH + DB_CACHE)
    conn = sqlite3.connect(DB_CACHE)
    c = conn.cursor()
    conn.commit()
    return conn, c


def create_companies_table(c, conn):
    """Create the company table in the DB
    """
    logger.info('Creating table to store company data in the db cache file.')
    c.execute('CREATE TABLE companies (cik int, name text, year int, month int, day int, accession text, form text)')
    conn.commit()


def load_companies(c, conn, companies):
    """Load the EDGAR company data into the DB cache file
    """
    logger.info('Adding company data to the companies db cache file.')
    num = len(companies)
    c.executemany('INSERT INTO companies VALUES (?,?,?,?,?,?,?)', companies)
    conn.commit()
    open(PATH + DB_CONTROL, 'w').close()  # Create the file that controls the reindexing
    return num

def create_sic_tables(c, conn):
    """Create the SIC tables
    """
    logger.info('Creating table to store SIC data in the db cache file.')
    c.execute('CREATE TABLE sic (division text, major_group text, industry_group text, sic text, description text)')
    c.execute('CREATE TABLE industry_groups (division text, major_group text, industry_group text, description text)')
    c.execute('CREATE TABLE major_groups (division text, major_group text, description text)')
    c.execute('CREATE TABLE divisions (division text, description text, full_description text)')
    conn.commit()

def load_sic_file(file_name):
    my_data = []
    # Open the CSV file
    with open(file_name) as csv_file:
        # Create a CSV reader object
        csv_reader = csv.reader(csv_file)

        # Skip the header row
        header = next(csv_reader)

        # Loop through each row in the CSV file
        for row in csv_reader:
            # Append the row to the data list
            my_data.append(row)
    return my_data

def load_sic_data(c, conn, divisions, major_groups, industry_groups, sics):
    """Load the SIC data into the DB cache file
    """
    logger.info('Adding sic data to the companies db cache file.')
    num = len(divisions) + len(major_groups) + len(industry_groups) + len(sics)
    c.executemany('INSERT INTO divisions VALUES (?,?,?)', divisions)
    c.executemany('INSERT INTO major_groups VALUES (?,?,?)', major_groups)
    c.executemany('INSERT INTO industry_groups VALUES (?,?,?,?)', industry_groups)
    c.executemany('INSERT INTO sic VALUES (?,?,?,?,?)', sics)
    conn.commit()
    return num


def close_db(conn):
    """
    Close the DB cache file and connection

    :param conn: connection to the database
    """
    logger.info('Closing the connection to the database file.')
    conn.close()


def build_db(edgar_file_name, sic_dir, sic_files):
    """
    Perform all operations needed to build the DB cache file

    ;param file_name: name of the tab file to pull into create the cache

    """

    # TODO If the DB_CONTROL file exists this process should not run, and that needs to be fixed
    # TODO When you change to account for the above return the print statements as strings and also create a return statement as a string saying the DB Create was not needed

    if path.exists(PATH + DB_CONTROL):
        return True, "Not regenerating the data base cache as it already exists"
    else:
        logger.info('Initiating the db_cache build.')
        # Connect to the database
        (my_conn, my_cursor) = create_db()

        ## Create all required tables
        # Create the table for companies EDGAR data
        create_companies_table(my_cursor, my_conn)
        
        # Create the tables for SIC data
        create_sic_tables(my_cursor, my_conn)

        ## Load data into the tables
        # Build and load companies data
        (my_index, total) = build_idx(edgar_file_name)
        total = load_companies(my_cursor, my_conn, my_index)

        # Build and load the SIC data
        divisions = load_sic_file(sic_dir + sic_files[DIVISIONS])
        major_groups = load_sic_file(sic_dir + sic_files[MAJOR_GROUPS])
        industry_groups = load_sic_file(sic_dir + sic_files[INDUSTRY_GROUPS])
        sics = load_sic_file(sic_dir + sic_files[SICS])
        total += load_sic_data(my_cursor, my_conn, divisions, major_groups, industry_groups, sics)

        close_db(my_conn)
        return True, "Created the database cache with " + str(total) + " entries stored in " + DB_CACHE


def clean_all():
    """
    Clean up all cache files, control files and the DB cache.  The underlying functions will gracefully handle any
    errors like files not being found, etc.

    """
    clean_db()
    print('Cleaned up ' + PATH + DB_CACHE)
    num = clean_cache()
    print('Cleaned up ' + str(num) + ' cache files from the filesystem.')


if __name__ == '__main__':

    # TODO Consider only allowing the initialization operation to run

    # capture the command line options for when this is run as a separate utility
    par = argparse.ArgumentParser(description="A utility to create a db cache for select SEC edgar data.")
    par.add_argument('--cleanall', '-a', action="store_true", help="Clean up the cache files and db cache and exit.")
    par.add_argument('--cleandb', '-d', action="store_true", help="Clean up the db cache only and exit.")
    par.add_argument('--cleancache', '-c', action="store_true", help="Clean up the cache files only and exit.")
    par.add_argument('--getmaster', '-g', action="store_true", help="Get the master.gz files only and exit.")
    par.add_argument('--year', '-y', metavar='Y', type=int, default=2018,
                     help='Define the year to start from, defaults to 2018.')

    # For the purposes of logging verbosity SILENT = 50, ERROR = 40, WARNING = 30, INFO = 20, DEBUG = 10
    par.add_argument('--verbose', '-v', type=int, choices=[50, 40, 30, 20, 10],
                     default=30, help="Set the logging verbosity.")
    args = par.parse_args()

    # Set up the logger for the module
    global logger
    logging.basicConfig(format='%(asctime)s | %(levelname)s | %(name)s | %(message)s', level=args.verbose)
    logger = logging.getLogger(__file__)

    my_path = "./"
    if args.cleanall:
        logger.info('Cleaning up existing cache db and associated files.')
        clean_all()
        sys.exit(0)
    elif args.cleancache:
        logger.info('Cleaning up existing cache file on the file system.')
        clean_cache()
        sys.exit(0)
    elif args.cleandb:
        logger.info('Cleaning up existing cache db.')
        clean_db()
        sys.exit(0)
    else:
        # TODO If the DB_CONTROL file exists should any of this execute?
        logger.info('Initiating the db_cache build, default start year is 2010 unless overridden.')
        clean_db()
        (status, msg) = initialize(start_year=args.year)
        print (msg)
        (status, msg) = build_db(
            'form_all.tab', 
            './sic4-list-2.1.0-company_dns/', 
            [
                'divisions.csv',
                'major-groups.csv',
                'industry-groups.csv',
                'sic-codes.csv'
            ]
        )
        print (msg)
        clean_cache()
        sys.exit(0)
