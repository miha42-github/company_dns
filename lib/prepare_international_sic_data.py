import csv
import logging
import os
import glob
from typing import Dict, Any, Optional, List, Union

class ExtractInternationalSicData:
    """Extract, transform, and load the International SIC (ISIC) data
    """

    def __init__(self, **kwargs):
        """Initialize the module
        """
        global logger
        logging.basicConfig(format='%(asctime)s | %(levelname)s | %(name)s | %(message)s', level=kwargs.get('verbose', logging.WARNING))
        logger = logging.getLogger(__file__)
        
        # Get the config object - could be a ConfigParser or a dict
        config_obj = kwargs.get('config', {})
        
        # Check if it's a ConfigParser object (has 'get' method but not dict-like behavior)
        if hasattr(config_obj, 'get') and not isinstance(config_obj, dict):
            # It's a ConfigParser object - handle it differently
            try:
                # Use ConfigParser's get method with fallback
                self.data_dir = config_obj['sic_data']['INTERNATIONAL_SIC_DATA_DIR']
            except (KeyError, TypeError):
                # Fallback if the key doesn't exist
                self.data_dir = './international_sic_data'
        else:
            # It's a dictionary or dictionary-like
            self.config = config_obj
            self.data_dir = self.config.get('sic_data', {}).get('INTERNATIONAL_SIC_DATA_DIR', './international_sic_data')
        
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
        encodings_to_try = ['utf-8', 'latin-1', 'ISO-8859-1', 'cp1252', 'utf-16']
        
        for encoding in encodings_to_try:
            try:
                logger.info(f'Attempting to open file with {encoding} encoding')
                # Open the CSV file with the current encoding
                with open(file_name, encoding=encoding) as csv_file:
                    # Create a CSV reader object
                    csv_reader = csv.reader(csv_file)

                    # Skip the header row
                    try:
                        header = next(csv_reader)
                    except StopIteration:
                        logger.warning(f'Empty file or header issue with {encoding} encoding')
                        continue

                    # Loop through each row in the CSV file
                    for row in csv_reader:
                        if not row or len(row) < 2:  # Skip empty rows or malformed rows
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
                return {
                    'sections': sections,
                    'divisions': divisions,
                    'groups': groups,
                    'classes': classes
                }
            
            except UnicodeDecodeError as e:
                logger.debug(f'Failed to open file with {encoding} encoding: {str(e)}')
                continue
            except Exception as e:
                logger.error(f'Unexpected error processing file with {encoding} encoding: {str(e)}')
                import traceback
                logger.error(traceback.format_exc())
                continue
        
        # If all encodings fail, raise an error
        error_msg = f'Failed to open file {file_name} with any of the attempted encodings'
        logger.error(error_msg)
        raise RuntimeError(error_msg)

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