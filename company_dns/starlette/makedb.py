from lib.prepare_db import MakeDb
from lib.db_functions import DbFunctions
import logging
import os
import sys
import configparser

# Create a ConfigParser object
config = configparser.ConfigParser()

# Read the configuration from the file
config.read('company_dns.conf')

# Set up the logging
logging.basicConfig(format='%(asctime)s | %(levelname)s | %(name)s | %(message)s', level=logging.INFO)
logger = logging.getLogger(__file__)

#  Check to see if the database cache file exists and if so log the event and exit
if os.path.exists(config['db_control']['DB_NAME']):
    logger.info('The database cache file %s already exists, exiting.', config['db_control']['DB_NAME'])
    sys.exit(0)

# Check to see if the directory ./edgar_data exists if not create it
logger.info('Checking for the existence of the directory %s.', config['edgar_data']['EDGAR_DATA_DIR'])
try:
    os.mkdir(config['edgar_data']['EDGAR_DATA_DIR'])
    logger.info('%s does not exist creating it.', config['edgar_data']['EDGAR_DATA_DIR'])
except FileExistsError:
    logger.info('%s exists skipping creation.', config['edgar_data']['EDGAR_DATA_DIR'])
    pass

# Remove the existing database cache file
db_functions = DbFunctions(config=config)
db_functions.clean_db()

# Construct the database object and build the database
new_db = MakeDb(config=config)
new_db.build_db()