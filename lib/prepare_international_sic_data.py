import csv
import logging
import os
import glob

class ExtractInternationalSicData:
    """Extract, transform, and load the International SIC (ISIC) data
    """

    def __init__(self, **kwargs):
        """Initialize the module
        """
        global logger
        logging.basicConfig(format='%(asctime)s | %(levelname)s | %(name)s | %(message)s', level=kwargs.get('verbose', logging.WARNING))
        logger = logging.getLogger(__file__)
        
        self.config = kwargs.get('config')
        
        # Handle the config properly based on its type
        if hasattr(self.config, 'get') and callable(getattr(self.config, 'get')):
            # Check if it's a ConfigParser object (has get method that takes section, option)
            if hasattr(self.config, 'sections'):
                # It's a ConfigParser object
                self.data_dir = self.config.get('sic_data', 'INTERNATIONAL_SIC_DATA_DIR', 
                                             fallback='./international_sic_data')
            else:
                # It's a dictionary with get method
                self.data_dir = self.config.get('sic_data', {}).get('INTERNATIONAL_SIC_DATA_DIR', 
                                             './international_sic_data')
        else:
            # Default fallback
            self.data_dir = './international_sic_data'
        
        # Find the most recent ISIC file in the directory
        isic_files = glob.glob(os.path.join(self.data_dir, 'ISIC_Rev_*_english_structure.csv'))
        if isic_files:
            self.isic_file = max(isic_files)  # Get the most recent file based on string sorting
            logger.info(f'Using ISIC data file: {self.isic_file}')
        else:
            logger.warning(f'No ISIC data files found in {self.data_dir}')
            self.isic_file = None

    def _load_file(self, file_name):
        """Extract data from the ISIC CSV file
        """
        logger.info('Extracting data from the file %s.', file_name)
        
        # Initialize data structures
        sections = []
        divisions = []
        groups = []
        classes = []
        
        current_section = None
        current_division = None
        current_group = None
        
        # Try different encodings to handle potential encoding issues
        encodings_to_try = ['utf-8', 'latin-1', 'ISO-8859-1', 'cp1252']
        
        for encoding in encodings_to_try:
            try:
                logger.info(f'Attempting to open file with {encoding} encoding')
                # Open the CSV file with the current encoding
                with open(file_name, encoding=encoding) as csv_file:
                    # Create a CSV reader object
                    csv_reader = csv.reader(csv_file)

                    # Skip the header row
                    header = next(csv_reader)

                    # Loop through each row in the CSV file
                    for row in csv_reader:
                        if len(row) < 2:  # Skip rows that don't have enough columns
                            continue
                            
                        code = row[0].strip('"')
                        description = row[1].strip('"')
                        
                        # Determine the type of row based on the code
                        if len(code) == 1 and code.isalpha():
                            # This is a section
                            current_section = code
                            sections.append([code, description])
                        elif len(code) == 2 and code.isdigit():
                            # This is a division
                            current_division = code
                            divisions.append([code, description, current_section])
                        elif len(code) == 3 and code.isdigit():
                            # This is a group
                            current_group = code
                            groups.append([code, description, current_division, current_section])
                        elif len(code) == 4 and code.isdigit():
                            # This is a class
                            classes.append([code, description, current_group, current_division, current_section])
                
                # If we reach here, the file was successfully processed with this encoding
                logger.info(f'Successfully processed file with {encoding} encoding')
                break
                
            except UnicodeDecodeError:
                # If this encoding doesn't work, try the next one
                logger.warning(f'Failed to open file with {encoding} encoding, trying next encoding')
                continue
        else:
            # If none of the encodings worked
            logger.error('Failed to open file with any of the attempted encodings')
            return {
                'sections': [],
                'divisions': [],
                'groups': [],
                'classes': []
            }
        
        return {
            'sections': sections,
            'divisions': divisions,
            'groups': groups,
            'classes': classes
        }

    def extract_data(self):
        """Load the International SIC data into objects that will be inserted into the database
        """
        logger.info('Loading International SIC data into objects that will be inserted into the database.')
        
        if not self.isic_file:
            logger.error('No ISIC data file available for processing')
            return {
                'sections': [],
                'divisions': [],
                'groups': [],
                'classes': []
            }
            
        # Return the extracted data
        return self._load_file(self.isic_file)