import re
import sqlite3
import http.client
import logging
import os
import gzip
import argparse
import sys

# TODO change the name of the file and create a package
# TODO create an option to run this like a CLI as well as a package
# TODO consider the right security context including permissions on the file
# TODO consider how to handle and catch various error conditions
# TODO capture statistics about the number of entries for logging, debugging, etc.
# TODO test substrings to create smaller db files
# TODO Should we think about a housekeeping DB table describing the last time things were loaded
# TODO should we consider a housekeeping DB table that has other statistics, etc.

EDGARSERVER = "www.sec.gov"
EDGARPATH = "/Archives/edgar/full-index/"
FILETYPE = "master.gz"
FILENAME = "master"
FILEEXT = ".gz"
EDGARARCHIVES = "Archives/"

def get_masters(years, quarters=[1, 2, 3, 4]):
    logger.info('Fetching the master indexes for years %s and quarters %s', years, quarters)
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
                fils.append(fil_name)
            else:
                continue
    session.close()
    return fils


def clean_masters (path='./'):
    logger.info('Cleaning up cached master.gz instances from the filesystem.')
    fil_type = re.compile('master\-\d+\-\S+\.gz$')
    for subdir, dirs, files in os.walk(path):
        for fil in files:
            if fil_type.match(fil):
                logger.debug('Removing cache file: %s', path + fil)
                os.remove(path + fil)



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
    # TODO handle a gzip
    for line in file_name.read():
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
            path = re.sub('\d+\-\d+\-\d+\.txt', '', fil)
            path = EDGARARCHIVES + path

            if form == report_type:  # Filter in only the report types we want to see, default is 10-k only
                if company_name is None:
                    entry_dict = {
                        'CIK': cik,
                        'Company Name': company,
                        'Form Type': form,
                        'Date Filed': date,
                        'File Name': path
                    }
                    raw_array.append((cik, company, form, date, path))
                    raw_dict.append(entry_dict)
                elif company_name.lower() in company.lower():
                    entry_dict = {
                        'CIK': cik,
                        'Company Name': company,
                        'Form Type': form,
                        'Date Filed': date,
                        'File Name': path
                    }
                    raw_dict.append(entry_dict)
                    raw_array.append((cik, company, form, date, path))
            else:
                continue
        else:
            continue

    idx['payload_dict'] = raw_dict
    idx['payload_array'] = raw_array
    return idx


def clean_db(db_name="edgar_idx.db", path="./"):
    logger.info('Cleaning up the db cache instance, %s, from the filesystem.', path + db_name)
    os.remove(path + db_name)


def create_db(db_name="edgar_idx.db"):
    """

    :param db_name:
    """
    logger.info('Attaching to the database file %s.', db_name)
    conn = sqlite3.connect(db_name)
    c = conn.cursor()
    conn.commit()
    return conn, c


def create_companies (c, conn):
    c.execute('CREATE TABLE companies (cik int, name text, form text, date text, file text)')
    conn.commit()


def load_companies(c, conn, companies):
    c.executemany('INSERT INTO companies VALUES (?,?,?,?,?)', companies)
    conn.commit()


def close_db(conn):
    logger.info('Closing the connection to the database file.')
    conn.close()


# f1 = open("master.idx") TODO these files are now gzipped so gunzip is required
# index = build_idx(f1)
# f1.close()



# Set up the logger for the module
global logger
logging.basicConfig(format='%(asctime)s | %(levelname)s | %(message)s', level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.info('Initiating the db_cache build.')

parser = argparse.ArgumentParser(description="A utility to create a db cache for select SEC edgar data.")
parser.add_argument('--cleanall', '-a', action="store_true", help="Clean up the master.idx files and db cache and exit.")
parser.add_argument('--cleandb', '-d', action="store_true", help="Clean up the db cache only and exit.")
parser.add_argument('--cleanmaster', '-m', action="store_true", help="Clean up the master.gz files only and exit.")
parser.add_argument('--regendb', '-r', action="store_true", help="Create a new db cache from existing data and exit.")
parser.add_argument('--getmaster', '-g', action="store_true", help="Get the master.gz files only and exit.")
args = parser.parse_args()

global files
files=[]
path="./"
if args.cleanall:
    # Capture the master index files from EDGAR which will be used to create the SQLite DB
    logger.info('Cleaning up existing cache db and associated files.')
    clean_masters()
    clean_db()
    sys.exit(0)
elif args.cleandb:
    logger.info('Cleaning up existing cache db.')
    clean_db()
    sys.exit(0)
elif args.cleanmaster:
    logger.info('Cleaning up existing master.gz files.')
    clean_masters()
    sys.exit(0)
elif args.getmaster:

elif regendb:
    logger.info('Regenerating cache db from existing master.gz files.')
    logger.debug('Capturing existing master.gz files from the filesystem.')
    my_index = []
    clean_db()
    (my_cursor, my_conn) = create_db()
    create_companies(my_cursor, my_conn)
    fil_type = re.compile('master\-\d+\-\S+\.gz$')
    for subdir, dirs, fils in os.walk(path):
        for fil in fils:
            if fil_type.match(fil):
                logger.debug('Loading file: %s', fil)
                f = gzip.open(path + fil)
                my_index = build_idx(f)
                f.close()
                load_companies(my_cursor, my_conn, my_index['payload_array'])
    close_db(my_conn)


files = get_masters([2019, 2018])  # TODO this should be a parameter and the default should be this year

(my_cursor, my_conn) = create_db()
if args.clean is True:
    create_companies(my_cursor, my_conn)

for fil in files:
    f = gzip.open(fil, 'rt')
    index = build_idx(f)
    load_companies(my_cursor, my_conn, index['payload_array'])

close_db(my_conn)


