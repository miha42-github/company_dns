import csv
import logging
import os
from lib.utils import download_uk_sic_data

class ExtractUkSicData:
    """Extract, transform, and load the UK SIC data
    """

    def __init__(self, **kwargs):
        """Initialize the module
        """
        global logger
        logging.basicConfig(format='%(asctime)s | %(levelname)s | %(name)s | %(message)s', level=kwargs.get('verbose', logging.WARNING))
        logger = logging.getLogger(__file__)
        self.config = kwargs.get('config', 
                                    {
                                        'sic_data': {
                                                    'UK_SIC_DATA_DIR': './uk_sic_data',
                                                    'UK_SIC_DATA': 'uk-sic.csv'
                                        }
                                    }
                                )
        self.data_dir = self.config['sic_data']['UK_SIC_DATA_DIR']
        self.uk_sic_data = self.data_dir + '/' + self.config['sic_data']['UK_SIC_DATA']

    def _load_file(self, file_name):
        """Extract data from the UK SIC CSV file
        """
        logger.info('Extracting data from the file %s.', file_name)
        uk_sic_data = []
        # Open the CSV file
        with open(file_name) as csv_file:
            # Create a CSV reader object
            csv_reader = csv.reader(csv_file)

            # Skip the header row
            header = next(csv_reader)

            # Loop through each row in the CSV file
            for row in csv_reader:
                # Check if there are at least 2 columns (SIC Code and Description)
                if len(row) >= 2:
                    # CSV reader handles the quotes properly, but some descriptions
                    # might have additional quotes that need to be removed
                    description = row[1]
                    if description.startswith('"') and description.endswith('"'):
                        description = description[1:-1]
                    
                    # Create a new row with the cleaned description
                    cleaned_row = [row[0], description]
                    uk_sic_data.append(cleaned_row)
        return uk_sic_data

    def extract_data(self):
        """Load the UK SIC data into the DB cache file
        """
        logger.info('Loading UK SIC data into objects that will be inserted into the database.')
        
        # Check if the file exists, if not, download it
        if not os.path.exists(self.uk_sic_data):
            logger.info('File %s does not exist. Attempting to download.', self.uk_sic_data)
            downloaded_file = download_uk_sic_data(self.config)
            if not downloaded_file:
                logger.error('Failed to download UK SIC data.')
                return {'uk_sic': []}
        
        # Return a dictionary with the UK SIC data
        return {
            'uk_sic': self._load_file(self.uk_sic_data)
        }