import csv
import logging

class ExtractSicData:
    """Extract, transform, and load the SIC data
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
                                                    'SIC_DATA_DIR': './sic_data',
                                                    'DIVISIONS': 'divisions.csv',
                                                    'MAJOR_GROUPS': 'major-groups.csv',
                                                    'INDUSTRY_GROUPS': 'industry-groups.csv',
                                                    'SIC_CODES': 'sic-codes.csv'
                                        }
                                    }
                                )
        self.data_dir = self.config['sic_data']['SIC_DATA_DIR']
        self.divisions = self.data_dir + '/' + self.config['sic_data']['DIVISIONS']
        self.major_groups = self.data_dir + '/' + self.config['sic_data']['MAJOR_GROUPS']
        self.industry_groups = self.data_dir + '/' + self.config['sic_data']['INDUSTRY_GROUPS']
        self.sics = self.data_dir + '/' + self.config['sic_data']['SIC_CODES']

    def _load_file(self, file_name):
        """Extract data from a CSV file
        """
        logger.info('Extracting data from the file %s.', file_name)
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

    def extract_data(self):
        """Load the SIC data into the DB cache file
        """
        logger.info('Loading SIC data into objects that will be inserted into the database.')
        # Return a dictionary of the data
        return {
            'divisions': self._load_file(self.divisions), 
            'major_groups': self._load_file(self.major_groups), 
            'industry_groups': self._load_file(self.industry_groups), 
            'sics': self._load_file(self.sics)
        }


