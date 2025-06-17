from pyedgar.utilities.indices import IndexMaker
from os import path
import logging
import csv
import re
import gzip
import shutil
import datetime


class ExtractEdgarData:
    def __init__(self, **kwargs):
        global logger
        logging.basicConfig(format='%(asctime)s | %(levelname)s | %(name)s | %(message)s', level=kwargs.get('verbose', logging.WARNING))
        logger = logging.getLogger(__file__)
        self.operating_path = kwargs.get('operating_path', './')
        self.config = kwargs.get('config', {"db_control": {"CACHE_EXISTS": "cache_exists"}})
        self.data_dir = self.config['edgar_data']['EDGAR_DATA_DIR']
        self.company_data = self.data_dir + '/' + self.config['edgar_data']['ALL_FORMS']
        self.cache_exists = self.data_dir + '/' + self.config['edgar_data']['CACHE_EXISTS']

    def _initialize(self, start_year=None):
        """
        Using the appropriate method in PyEdgar download the file cache that defines the relevant SEC filings for
        companies given the start_year variable. The method in this package then will format the content into tab
        delimited files and prepare them for processing.

        :type start_year: int

        :param start_year: define the start year for the initialization of the cache
        """
        # set the start year to two years ago using the datetime module
        if start_year is None:
            start_year = datetime.datetime.now().year - 2

        # Check to see if the cache file exists and if so return
        if path.exists(self.cache_exists):
            return False, "Cache files already exist, returning."
        
        i = IndexMaker()
        i.extract_indexes(start_date=start_year)  # Download and create the index
        # Create the cache.exists file as a zero byte file
        with open(self.cache_exists, 'w') as f:
            f.write('')
            f.close()
        return True, "Downloaded cache files from SEC EDGAR."
        
    def extract_data(self):
        """
        Generate an index suitable to load into a db cache

        :param file_name: name of the *.tab file to process
        """
        logger.info('Downloading the cache files from SEC EDGAR.')
        success, message = self._initialize()

        logger.info('Creating the data structure from the compressed index file.')
        header_re = re.compile('^cik', re.IGNORECASE)  # Detect the headers for the idx
        idx = list()
        num = 0
        with gzip.open(self.company_data + '.gz', 'rb') as f_in:
            with open(self.company_data, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)

        with open(self.company_data, newline='') as content:
            csv_reader = csv.reader(content, delimiter='\t')
            for entry in csv_reader:
                if header_re.match(entry[0]):
                    continue
                logger.debug('Detected 10K form proceeding to process.')
                my_cik = entry[0]
                my_company = entry[1]
                my_form = entry[2]
                (my_year, my_month, my_day) = entry[3].split('-')
                my_accession = entry[4]
                idx.append([my_cik, my_company, int(my_year), int(my_month), int(my_day), my_accession, my_form])
        return idx, len(idx)