from lib.prepare_db import MakeDb
from lib.db_functions import DbFunctions
from lib.utils import download_edgar_data, download_uk_sic_data, download_international_sic_data
import logging
import configparser
import argparse

# Parse command line arguments
parser = argparse.ArgumentParser(description='Build the company DNS database.')
parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
parser.add_argument('--debug', '-d', action='store_true', help='Enable debug logging')
args = parser.parse_args()

# Set logging level based on arguments
if args.debug:
    log_level = logging.DEBUG
elif args.verbose:
    log_level = logging.INFO
else:
    log_level = logging.WARNING

# Create a ConfigParser object
config = configparser.ConfigParser()

# Read the configuration from the file
config.read('company_dns.conf')

# Set up the logging
logging.basicConfig(format='%(levelname)s:\t%(asctime)s [module: %(name)s] %(message)s', level=log_level)
logger = logging.getLogger(__file__)

logger.debug("Debug logging enabled")
logger.info("Starting database build process")

# Check to see if the database cache file exists and if so log the event and exit
# if os.path.exists(config['db_control']['DB_NAME']):
#     logger.info('The database cache file %s already exists, exiting.', config['db_control']['DB_NAME'])
#     sys.exit(0)

# Ensure data directories exist and download required data
download_edgar_data(config)
download_uk_sic_data(config)
download_international_sic_data(config)

# Remove the existing database cache file
db_functions = DbFunctions(config=config)
db_functions.clean_db()

# Construct the database object and build the database
new_db = MakeDb(config=config)
new_db.build_db()