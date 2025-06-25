import csv
import logging
import os
import glob
from typing import Dict, Any, Optional, List, Union

class ExtractEuSicData:
    """Extract, transform, and load the European SIC (NACE) data
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
                self.data_dir = config_obj['sic_data']['EU_SIC_DATA_DIR']
            except (KeyError, TypeError):
                # Fallback if the key doesn't exist
                self.data_dir = './eu_sic_data'
        else:
            # It's a dictionary or dictionary-like
            self.config = config_obj
            self.data_dir = self.config.get('sic_data', {}).get('EU_SIC_DATA_DIR', './eu_sic_data')
        
        # Find the NACE file in the directory
        nace_files = glob.glob(os.path.join(self.data_dir, 'NACE_Rev*_Heading_All_Languages.tsv'))
        if nace_files:
            self.nace_file = max(nace_files)  # Get the most recent file based on string sorting
            logger.info(f'Using EU SIC data file: {self.nace_file}')
        else:
            logger.warning(f'No EU SIC data files found in {self.data_dir}')
            self.nace_file = None

    def _load_file(self, file_name):
        """Extract data from the NACE TSV file
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
                # Open the TSV file with the current encoding
                with open(file_name, encoding=encoding) as tsv_file:
                    # Create a CSV reader object with tab delimiter
                    tsv_reader = csv.reader(tsv_file, delimiter='\t')

                    # Skip the header row
                    try:
                        header = next(tsv_reader)
                        logger.debug(f'Header: {header}')
                    except StopIteration:
                        logger.warning(f'Empty file or header issue with {encoding} encoding')
                        continue

                    # Loop through each row in the TSV file
                    for row in tsv_reader:
                        if not row or len(row) < 2:  # Skip empty rows or malformed rows
                            continue
                        
                        code = row[0].strip('"')
                        description = row[1].strip('"')  # EN_DESC is the second column
                        
                        # Determine the type of row based on the code
                        if len(code) == 1 and code.isalpha():
                            # This is a section (e.g., "A", "B", "C")
                            current_section = code
                            sections.append([code, description])
                            logger.debug(f'Added section: {code} - {description}')
                        elif len(code) == 2 and code.isdigit():
                            # This is a division (e.g., "01", "02", "10")
                            current_division = code
                            divisions.append([code, description, current_section])
                            logger.debug(f'Added division: {code} - {description}')
                        elif '.' in code and len(code.split('.')[0]) == 2 and len(code.split('.')[1]) == 1:
                            # This is a group (e.g., "01.1", "10.2")
                            current_group = code
                            # Extract division from the group (first two digits)
                            division_code = code.split('.')[0]
                            groups.append([code, description, division_code, current_section])
                            logger.debug(f'Added group: {code} - {description}')
                        elif '.' in code and len(code.split('.')[0]) == 2 and len(code.split('.')[1]) == 2:
                            # This is a class (e.g., "01.11", "25.91")
                            # Extract group from the class (first three characters including the dot)
                            group_parts = code.split('.')
                            group_code = f"{group_parts[0]}.{group_parts[1][0]}"
                            division_code = code.split('.')[0]
                            classes.append([code, description, group_code, division_code, current_section])
                            logger.debug(f'Added class: {code} - {description}')
                
                # If we reach here, the file was successfully processed with this encoding
                logger.info(f'Successfully processed file with {encoding} encoding')
                logger.info(f'Extracted {len(sections)} sections, {len(divisions)} divisions, {len(groups)} groups, and {len(classes)} classes')
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
        """Load the EU SIC data into objects that will be inserted into the database
        """
        logger.info('Loading EU SIC data into objects that will be inserted into the database.')
        
        if not self.nace_file:
            logger.error('No EU SIC data file available for processing')
            return {
                'sections': [],
                'divisions': [],
                'groups': [],
                'classes': []
            }
            
        # Return the extracted data
        return self._load_file(self.nace_file)