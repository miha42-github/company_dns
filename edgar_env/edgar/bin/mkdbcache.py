#  Copyright 2019 Cameron Solutions
#  Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
#  in compliance with the License. You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software distributed under the License
#  is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
#  or implied. See the License for the specific language governing permissions and limitations under
#  the License.
#
#


import re
import sqlite3
import http.client
import logging
import os
import gzip
import argparse
import sys
import csv
from datetime import date



__author__ = "Michael Hay"
__copyright__ = "Copyright 2019, Cameron Solutions"
__license__ = "ASF 2.0"
__version__ = "1.0.0"
__maintainer__ = "Michael Hay"
__status__ = "Prototype"
__id__ = "$Id$"


# TODO think about creating a class here?
# TODO consider the right security context including permissions on the file
# TODO consider how to handle and catch various error conditions
# TODO capture statistics about the number of entries for logging, debugging, etc.
# TODO fix function signatures and descriptions to clean up the documentation
# TODO clean up variable names
# TODO move print statements out of methods

EDGARSERVER = "www.sec.gov"
EDGARPATH = "/Archives/edgar/full-index/"
FILETYPE = "master.gz"
FILENAME = "master"
FILEEXT = ".gz"
EDGARARCHIVES = "Archives/"


def clean_masters(path='./'):
    """
    Remove all master.gz files regardless of their name

    :param path: specify the path of the master.gz files
    """
    logger.info('Cleaning up cached master.gz instances from the filesystem.')
    num = 0
    fil_type = re.compile('master\-\d+\-\S+\.gz$')
    for subdir, dirs, files in os.walk(path):
        for fil in files:
            if fil_type.match(fil):
                logger.debug('Removing cache file: %s', path + fil)
                num += 1
                os.remove(path + fil)
    return num


def build_idx(file_name):
    """
    Generate an index suitable to load into a db cache

    :param file_name: name of the master.gz file to process
    :param company_name: name of a specific company to focus the index on, default None
    :param report_type: type of report to capture, default 10-K
    """
    logger.info('Creating the data structure from the compressed index file.')
    header_re = re.compile('^cik', re.IGNORECASE)  # Detect the headers for the idx
    idx = list()
    num = 0
    with open(file_name, newline='') as content:
        csv_reader = csv.reader(content, delimiter='\t')
        for entry in csv_reader:
            if header_re.match(entry[0]):
                continue
            my_cik = entry[0]
            my_company = entry[1]
            (my_year, my_month, my_day) = entry[3].split('-')
            my_accession = entry[4]
            idx.append([my_cik, my_company, int(my_year), int(my_month),int(my_day), my_accession])
    return idx, len(idx)


def clean_db(db_name="edgar_10k_idx.db", path="./"):
    """

    :type path: object
    """
    logger.info('Cleaning up the db cache instance, %s, from the filesystem.', path + db_name)
    try:
        os.remove(path + db_name)
    except FileNotFoundError:
        logger.warning('The supplied file name, %s, for the db cache was not found.', db_name)
        return


def create_db(db_name="edgar_10k_idx.db"):
    """

    :param db_name:
    """
    logger.info('Attaching to the database file %s.', db_name)
    conn = sqlite3.connect(db_name)
    c = conn.cursor()
    conn.commit()
    return conn, c


def create_companies(c, conn):
    """

    :param db_name:
    """
    logger.info('Creating table to store company data in the db cache file.')
    c.execute('CREATE TABLE companies (cik int, name text, year int, month int, day int, accession text)')
    conn.commit()


def load_companies(c, conn, companies):
    """

    :param db_name:
    """
    logger.info('Adding company data to the companies db cache file.')
    num = len(companies)
    c.executemany('INSERT INTO companies VALUES (?,?,?,?,?,?)', companies)
    conn.commit()
    return num


def close_db(conn):
    """

    :param db_name:
    """
    logger.info('Closing the connection to the database file.')
    conn.close()


def regen_db(path):
    """

    :param db_name:
    """
    logger.debug('Capturing existing master.gz files from the filesystem.')
    clean_db()
    my_index = []
    (my_conn, my_cursor) = create_db()
    create_companies(my_cursor, my_conn)
    fil_type = re.compile('master\-\d+\-\S+\.gz$')
    for subdir, dirs, fils in os.walk(path):
        for fil in fils:
            if fil_type.match(fil):
                logger.debug('Loading file: %s', fil)
                f = gzip.open(path + fil, 'rt')
                (my_index, total) = build_idx(f)
                f.close()
                print('Processed ' + str(total) + ' entries in file ' + fil)
                load_companies(my_cursor, my_conn, my_index['payload_array'])
    close_db(my_conn)

# TODO: Pull in the appropriate PyEdgar module to download the right set of data
# TODO: Make the command line switches handle years and type of cache 10-k or other to create
# TODO: Rewire the cleanup operations to clean up the appropriate GZ files even during DB Create

def build_db(file_name):
    """

    :param years:
    """
    logger.info('Initiating the db_cache build.')
    clean_db()
    (my_conn, my_cursor) = create_db()
    create_companies(my_cursor, my_conn)
    (my_index, total) = build_idx(file_name)
    print('Processed ' + str(total) + ' entries in file ' + file_name)
    total = load_companies(my_cursor, my_conn, my_index)
    print("Inserted {0} entries in db cache file.".format(str(total)))
    close_db(my_conn)


def clean_all (db_name="edgar_idx.db", path="./"):
    """

    :param db_name:
    """
    clean_db(db_name, path)
    print('Cleaned up ' + path + db_name)
    num = clean_masters(path)
    print('Cleaned up ' + str(num) + ' master.gz files from the filesystem.')


if __name__ == '__main__':

    # capture the command line options for when this is run as a separate utility
    my_year = []
    my_year.append(int(date.today().year))
    par = argparse.ArgumentParser(description="A utility to create a db cache for select SEC edgar data.")
    par.add_argument('--cleanall', '-a', action="store_true", help="Clean up the master.idx files and db cache and exit.")
    par.add_argument('--cleandb', '-d', action="store_true", help="Clean up the db cache only and exit.")
    par.add_argument('--cleanmaster', '-m', action="store_true", help="Clean up the master.gz files only and exit.")
    par.add_argument('--regendb', '-r', action="store_true", help="Create a new db cache from existing data and exit.")
    par.add_argument('--getmaster', '-g', action="store_true", help="Get the master.gz files only and exit.")
    par.add_argument('--years', '-y', metavar='Y', type=int, nargs='+', default=my_year, help='Define the years of interest defaults to the current year.')

    # For the purposes of logging verbosity DEBUG = 50, ERROR = 40, WARNING = 30, INFO = 20, DEBUG = 10
    par.add_argument('--verbose', '-v', type=int, choices=[50, 40, 30, 20, 10], default=30, help="Set the logging verbosity.")
    args = par.parse_args()

    # Set up the logger for the module
    global logger
    logging.basicConfig(format='%(asctime)s | %(levelname)s | %(name)s | %(message)s', level=args.verbose)
    logger = logging.getLogger(__file__)

    global files
    files = []
    my_path = "./"
    if args.cleanall:
        logger.info('Cleaning up existing cache db and associated files.')
        clean_all()
        sys.exit(0)
    elif args.cleandb:
        logger.info('Cleaning up existing cache db.')
        clean_db()
        sys.exit(0)
    elif args.regendb:
        logger.info('Regenerating cache db from existing master.gz files.')
        regen_db(my_path)
        sys.exit(0)
    else:
        logger.info('Initiating the db_cache build.')
        build_db('form_10-K.tab')
        sys.exit(0)




