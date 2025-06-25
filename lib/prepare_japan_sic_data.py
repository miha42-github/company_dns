import logging
import os
import glob
import pandas as pd
from typing import Dict, Any, Optional, List, Union

class ExtractJapanSicData:
    """Extract, transform, and load the Japanese SIC data
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
                self.data_dir = config_obj['sic_data']['JAPAN_SIC_DATA_DIR']
            except (KeyError, TypeError):
                # Fallback if the key doesn't exist
                self.data_dir = './japan_sic_data'
        else:
            # It's a dictionary or dictionary-like
            self.config = config_obj
            self.data_dir = self.config.get('sic_data', {}).get('JAPAN_SIC_DATA_DIR', './japan_sic_data')
        
        # Find the most recent Japan SIC file in the directory
        japan_sic_files = glob.glob(os.path.join(self.data_dir, '*.xls*'))
        if japan_sic_files:
            self.japan_sic_file = max(japan_sic_files)  # Get the most recent file based on string sorting
            logger.info(f'Using Japan SIC data file: {self.japan_sic_file}')
        else:
            logger.warning(f'No Japan SIC data files found in {self.data_dir}')
            self.japan_sic_file = None

    def _load_file(self, file_name):
        """Extract data from the Japan SIC Excel file
        """
        logger.info('Extracting data from the file %s.', file_name)
        
        # Initialize data structures
        divisions = []
        major_groups = []
        groups = []
        industry_groups = []
        
        try:
            # Get correct sheet - "ⅠTabulation of Establishmens"
            xl = pd.ExcelFile(file_name)
            sheet_names = xl.sheet_names
            logger.info(f'Available sheets: {sheet_names}')
            
            # Find sheet with "Tabulation of Establishmens" in the name
            target_sheet = next((s for s in sheet_names if "Tabulation of Establishmens" in str(s)), sheet_names[0])
            logger.info(f'Using sheet: {target_sheet}')
            
            # Read the entire sheet for inspection
            df = pd.read_excel(file_name, sheet_name=target_sheet, header=None)
            logger.info(f'Excel file has {len(df)} rows and {df.shape[1]} columns')
            
            # Find actual data start by looking for the first row with hierarchy=1 or 0
            data_start_idx = None
            for idx in range(20, min(50, len(df))):  # Look between rows 20-50
                if pd.notna(df.iloc[idx, 1]) and str(df.iloc[idx, 1]).strip() in ['0', '1']:
                    data_start_idx = idx
                    logger.info(f"Found first data row at index {idx} with hierarchy {df.iloc[idx, 1]}")
                    break
            
            if data_start_idx is None:
                logger.warning(f"Could not find data start, using row 25 as fallback")
                data_start_idx = 25
            
            # Keep only data rows
            df = df.iloc[data_start_idx:]
            df.reset_index(drop=True, inplace=True)
            
            # Print the first few data rows to help with debugging
            logger.info("First 5 data rows:")
            for idx in range(min(5, len(df))):
                values = [str(val) if pd.notna(val) else "" for val in df.iloc[idx, :15]]
                logger.info(f"Row {idx}: {', '.join(values)}")
            
            # Process each row
            current_division = None
            current_major_group = None
            
            for idx, row in df.iterrows():
                try:
                    # Skip rows without hierarchy
                    if pd.isna(row.iloc[1]):
                        continue
                    
                    # CORRECTED: Hierarchy is in column 1, not 0
                    hierarchy = str(row.iloc[1]).strip()
                    
                    # CORRECTED: Column positions based on the debugging output
                    division_code = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else ""
                    major_group_code = str(row.iloc[5]).strip() if pd.notna(row.iloc[5]) else ""
                    group_code = str(row.iloc[6]).strip() if pd.notna(row.iloc[6]) else ""
                    code_full = str(row.iloc[9]).strip() if pd.notna(row.iloc[9]) else ""
                    
                    # CORRECTED: Description is in column 10, not 9
                    description = str(row.iloc[10]).strip() if pd.notna(row.iloc[10]) else ""
                    
                    # Skip rows with missing key data
                    if not description or description == "nan":
                        continue
                    
                    # Skip non-data rows (often have '-' in division code)
                    if division_code == '-' and hierarchy == '0':
                        continue
                    
                    logger.info(f"Processing row {idx}: H={hierarchy}, Div={division_code}, Code={code_full}, Desc={description}")
                    
                    # Division level (hierarchy=1)
                    if hierarchy == '1' and division_code and division_code != '-':
                        divisions.append([division_code, description])
                        current_division = division_code
                        # logger.debug(f'Added division: {division_code} - {description}')
                        # Debug check for "oil" in description (case insensitive)
                        if 'oil' in description.lower():
                            logger.warning(f'H2 -> OIL FOUND in division: {division_code} - {description}')
                    
                    # Major group level (hierarchy=3)
                    elif hierarchy == '3' and code_full:
                        # Use current division or the most recent one
                        div_code = current_division if current_division else (divisions[-1][0] if divisions else "Unknown")
                        
                        # Add to major_groups collection
                        major_groups.append([code_full, description, div_code])
                        current_major_group = code_full
                        logger.info(f'Added major group: {code_full} - {description}')
                        
                        # IMPORTANT: ALSO add to industry_groups collection so they're searchable
                        # This is the key fix - these major groups contain important industry classifications
                        # Set itself as its own parent group since it doesn't have one
                        industry_groups.append([code_full, description, code_full, code_full, div_code])
                        logger.info(f'Also added as industry group: {code_full} - {description}')
                        
                        # Debug check for "oil" in description (case insensitive)
                        if 'oil' in description.lower():
                            logger.warning(f'H3 -> OIL FOUND in major group: {code_full} - {description}')
                            logger.warning(f'OIL ADDED TO INDUSTRY GROUPS: {code_full} - {description}')
                    
                    # Group level (hierarchy=4)
                    elif hierarchy == '4' and code_full:
                        # Add to groups collection
                        groups.append([code_full, description, current_major_group, current_division])
                        logger.info(f'Added group: {code_full} - {description}')
                        
                        # IMPORTANT FIX: Also add ALL groups to industry_groups so they're searchable by description
                        industry_groups.append([code_full, description, code_full, current_major_group, current_division])
                        logger.info(f'Also added group as industry group: {code_full} - {description}')
                        
                        # Debug check for "oil" in description (case insensitive)
                        if 'oil' in description.lower():
                            logger.warning(f'H4 -> OIL FOUND in group: {code_full} - {description}')
                            logger.warning(f'H4 -> GROUP ADDED TO INDUSTRY GROUPS: {code_full} - {description}')
                    
                    # Industry Group level (hierarchy=5)
                    elif hierarchy == '5' and code_full:
                        # Find the parent group - use the most recent group
                        if groups:
                            parent_group = groups[-1][0]
                            parent_major_group = groups[-1][2]
                            parent_division = groups[-1][3]
                            
                            industry_groups.append([code_full, description, parent_group, parent_major_group, parent_division])
                            logger.info(f'Added industry group (level 5): {code_full} - {description}')
                            # Debug check for "oil" in description (case insensitive)
                            if 'oil' in description.lower():
                                logger.warning(f'H5 -> OIL FOUND in industry group: {code_full} - {description}')
                    
                    # Add this new section to handle any unprocessed rows that might be industry groups
                    elif code_full and description:
                        logger.warning(f'Unhandled row: H={hierarchy}, Code={code_full}, Desc={description}')
                        
                        # Try to determine the best parent references
                        parent_group = None
                        parent_major_group = None
                        parent_division = None
                        
                        # If it has a major group code, use that
                        if major_group_code and major_group_code != "nan":
                            parent_major_group = major_group_code
                            # Find matching division for this major group
                            for mg in major_groups:
                                if mg[0] == major_group_code:
                                    parent_division = mg[2]
                                    break
                        
                        # If it has a division code, use that
                        if division_code and division_code != "nan":
                            parent_division = division_code
                        
                        # If we have groups, use the most recent as parent
                        if groups:
                            parent_group = groups[-1][0]
                            if not parent_major_group:
                                parent_major_group = groups[-1][2] if len(groups[-1]) > 2 else "Unknown"
                            if not parent_division:
                                parent_division = groups[-1][3] if len(groups[-1]) > 3 else "Unknown"
                        
                        # If we still don't have a parent major group, use the current one
                        if not parent_major_group:
                            parent_major_group = current_major_group if current_major_group else "Unknown"
                            
                        # If we still don't have a parent division, use the current one
                        if not parent_division:
                            parent_division = current_division if current_division else "Unknown"
                            
                        logger.warning(f'Adding as catch-all industry group: {code_full} - {description}')
                        industry_groups.append([code_full, description, 
                                               parent_group if parent_group else code_full, 
                                               parent_major_group, 
                                               parent_division])
                        
                        # Debug check for "oil" in description
                        if 'oil' in description.lower():
                            logger.warning(f'CATCH-ALL -> OIL FOUND in catch-all: {code_full} - {description}')
                
                except Exception as row_error:
                    logger.warning(f"Error processing row {idx}: {str(row_error)}")
                    continue
        
            logger.info(f'Successfully processed file')
            logger.info(f'Extracted {len(divisions)} divisions, {len(major_groups)} major groups, {len(groups)} groups, and {len(industry_groups)} industry groups')
            
            return {
                'divisions': divisions,
                'major_groups': major_groups,
                'groups': groups,
                'industry_groups': industry_groups
            }
            
        except Exception as e:
            logger.error(f'Error processing Japan SIC file: {str(e)}')
            import traceback
            logger.error(traceback.format_exc())
            
            return {
                'divisions': divisions,
                'major_groups': major_groups,
                'groups': groups,
                'industry_groups': industry_groups
            }

    def extract_data(self):
        """Load the Japan SIC data into objects that will be inserted into the database
        """
        logger.info('Loading Japan SIC data into objects that will be inserted into the database.')
        
        if not self.japan_sic_file:
            logger.error('No Japan SIC data file available for processing')
            return {
                'divisions': [],
                'major_groups': [],
                'groups': [],
                'industry_groups': []
            }
            
        # Return the extracted data
        return self._load_file(self.japan_sic_file)