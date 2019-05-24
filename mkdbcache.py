#  Copyright 2019 Michael Hay & Manju Ramanathpura
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
#  $Id:$


import re
import sqlite3
import http.client
import logging
import os
import gzip
import argparse
import sys
from datetime import date

# TODO think about creating a class here
# TODO consider the right security context including permissions on the file
# TODO consider how to handle and catch various error conditions
# TODO capture statistics about the number of entries for logging, debugging, etc.
# TODO add copyright and license
# TODO add method signatures and descriptions to clean up the documentation

EDGARSERVER = "www.sec.gov"
EDGARPATH = "/Archives/edgar/full-index/"
FILETYPE = "master.gz"
FILENAME = "master"
FILEEXT = ".gz"
EDGARARCHIVES = "Archives/"

def get_masters(years, quarters=[1, 2, 3, 4]):
    logger.info('Fetching the master indexes for years %s and quarters %s', years, quarters)
    num = 0
    global session
    session = http.client.HTTPSConnection(EDGARSERVER)
    fils = []
    for year in years:
        for quarter in quarters:
            try:
                url_name = str(year) + '/QTR' + str(quarter) + '/' + FILETYPE
                session.request("GET", EDGARPATH + '/' + url_name)
            except http.client.CannotSendRequest as e:
                logger.warning('Cannot fetch the requested resource %s', url_name)
                session.close()
                session = http.client.HTTPSConnection(EDGARSERVER)
                continue

            try:
                resp = session.getresponse()
            except http.client.ResponseNotReady as e:
                logger.warning('The referenced master.gz does not exist and the connection terminated.')
                continue

            logger.debug('HTTP response code: %s, %s', resp.status, resp.reason)
            if resp.status is 200: # If the directory exists we'll get a 200 status otherwise we need to continue
                fil_name = FILENAME + '-' + str(year) + '-' + 'QTR' + str(quarter) + FILEEXT
                logger.debug('Downloading master.idx for year %s and quarter %s as %s', str(year), str(quarter), fil_name)
                dat = resp.read()
                fil = open(fil_name, 'ab')
                fil.write(dat)
                fil.close()
                num += 1
                fils.append(fil_name)
            else:
                continue
    session.close()
    return fils, num


def clean_masters (path='./'):
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


def build_idx(file_name, company_name=None, report_type="10-K"):
    """

    :param file_name:
    :param company_name:
    :param report_type:
    """
    logger.info('Creating the data structure from the compressed index file.')
    global entry_dict
    global entry_array
    header_re = re.compile('^\w+.*:', re.IGNORECASE)  # Detect the headers for the idx
    ignore_re = re.compile('^-.*$')  # Skip the separator which is '----'
    skip_re = re.compile('^\S+\|')  # Skip an entry if it has a | symbol
    idx = {}
    raw_dict = []
    raw_array = []
    num = 0
    for line in file_name:
        line = line.rstrip()
        line = line.strip()

        if line:
            # Used to generate the header of the file specific index
            if header_re.match(line) and not skip_re.match(line):
                (key, value) = line.split(':', 1)
                idx[key] = value
                continue
            elif ignore_re.match(line):
                continue
            (cik, company, form, date, fil) = line.split('|')

            #  edgar/data/1000045/0001104659-19-005360.txt <- This is the file name structure we'll handle
            f_path = re.sub('\d+\-\d+\-\d+\.txt', '', fil)
            f_path = "https://" + EDGARSERVER + '/' + EDGARARCHIVES + f_path

            if form == report_type:  # Filter in only the report types we want to see, default is 10-k only
                (year, month, day) = date.split('-')
                if company_name is None:
                    entry_dict = {
                        'CIK': cik,
                        'Company Name': company,
                        'Form Type': form,
                        'Year Filed': year,
                        'Month Filed': month,
                        'Day Filed': day,
                        'File Name': f_path
                    }
                    raw_array.append((cik, company, form, year, month, day, f_path))
                    raw_dict.append(entry_dict)
                    num += 1
                    logger.debug('Processed file entry %s', str(line))
                elif company_name.lower() in company.lower():
                    entry_dict = {
                        'CIK': cik,
                        'Company Name': company,
                        'Form Type': form,
                        'Year Filed': year,
                        'Month Filed': month,
                        'Day Filed': day,
                        'File Name': f_path
                    }
                    raw_dict.append(entry_dict)
                    raw_array.append((cik, company, form, year, month, day, f_path))
                    num += 1
                    logger.debug('Processed file entry %s', str(line))
            else:
                continue
        else:
            continue

    idx['payload_dict'] = raw_dict
    idx['payload_array'] = raw_array
    return idx, num


def clean_db(db_name="edgar_idx.db", path="./"):
    logger.info('Cleaning up the db cache instance, %s, from the filesystem.', path + db_name)
    try:
        os.remove(path + db_name)
    except FileNotFoundError:
        logger.warning('The supplied file name, %s, for the db cache was not found.', db_name)
        return


def create_db(db_name="edgar_idx.db"):
    """

    :param db_name:
    """
    logger.info('Attaching to the database file %s.', db_name)
    conn = sqlite3.connect(db_name)
    c = conn.cursor()
    conn.commit()
    return conn, c


def create_companies(c, conn):
    logger.info('Creating table to store company data in the db cache file.')
    c.execute('CREATE TABLE companies (cik int, name text, form text, year int, month int, day int, file text)')
    conn.commit()


def load_companies(c, conn, companies):
    logger.info('Adding company data to the companies db cache file.')
    num = len(companies)
    c.executemany('INSERT INTO companies VALUES (?,?,?,?,?,?,?)', companies)
    conn.commit()
    return num


def close_db(conn):
    logger.info('Closing the connection to the database file.')
    conn.close()


def regen_db(path):
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


def build_db(years):
    logger.info('Initiating the db_cache build.')
    my_index = []
    clean_db()
    (my_conn, my_cursor) = create_db()
    create_companies(my_cursor, my_conn)
    (fils, total) = get_masters(args.years)
    for fil in fils:
        logger.debug('Loading file: %s', str(fil))
        f = gzip.open(path + fil, 'rt')
        (my_index, total) = build_idx(f)
        print('Processed ' + str(total) + ' entries in file ' + fil)
        f.close()
        total = load_companies(my_cursor, my_conn, my_index['payload_array'])
        print('Inserted ' + str(total) + ' entries in db cache file.')
    close_db(my_conn)


def clean_all (db_name="edgar_idx.db", path="./"):
    clean_db(db_name, path)
    print('Cleaned up ' + path + db_name)
    num = clean_masters(path)
    print('Cleaned up ' + str(num) + ' master.gz files from the filesystem.')




# TODO add __main__
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
    path = "./"
    if args.cleanall:
        logger.info('Cleaning up existing cache db and associated files.')
        clean_all()
        sys.exit(0)
    elif args.cleandb:
        logger.info('Cleaning up existing cache db.')
        clean_db()
        sys.exit(0)
    elif args.cleanmaster:
        logger.info('Cleaning up existing master.gz files.')
        total = clean_masters()
        print('Cleaned up ' + str(total) + ' master.gz files from the filesystem.')
        sys.exit(0)
    elif args.getmaster:
        (fils, total) = get_masters(args.years)
        print('Downloaded ' + str(total) + ' master.gz files from EDGAR.')
        sys.exit(0)
    elif args.regendb:
        logger.info('Regenerating cache db from existing master.gz files.')
        regen_db(path)
        sys.exit(0)
    else:
        logger.info('Initiating the db_cache build.')
        build_db(args.years)
        sys.exit(0)




