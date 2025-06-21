import glob
import logging
import os
import re
import requests
from bs4 import BeautifulSoup, Tag
from typing import Dict, Optional, List, Union
from urllib.parse import urljoin
import configparser

logger = logging.getLogger(__name__)

def download_uk_sic_data(config: Union[Dict[str, Dict[str, str]], configparser.ConfigParser]) -> Optional[str]:
    """Download the UK SIC data file from the UK Companies House website
    
    Args:
        config: Configuration dictionary or ConfigParser containing SIC data parameters
        
    Returns:
        str: Path to the downloaded file or None if download failed
    """
    # Get the configuration values
    download_site = config['sic_data']['UK_SIC_DOWNLOAD_SITE']
    link_name = config['sic_data']['UK_SIC_DOWNLOAD_LINK_NAME']
    data_dir = config['sic_data']['UK_SIC_DATA_DIR']
    data_file = data_dir + '/' + config['sic_data']['UK_SIC_DATA']
    
    # Create the directory if it doesn't exist
    if not os.path.exists(data_dir):
        logger.info('Creating directory %s', data_dir)
        os.makedirs(data_dir)
    
    # Check if the file already exists
    if os.path.exists(data_file):
        logger.info('File %s already exists. Skipping download.', data_file)
        return data_file
    
    # Download the page and find the link
    logger.info('Downloading UK SIC data from %s', download_site)
    try:
        response = requests.get(download_site)
        response.raise_for_status()  # Raise exception for HTTP errors
        
        # Parse the HTML and find the link
        soup = BeautifulSoup(response.text, 'html.parser')
        download_link: Optional[str] = None
        
        # Look for links that contain the specified text
        for link in soup.find_all('a'):
            if isinstance(link, Tag) and link.text and link_name in link.text:
                href_attr = link.get('href')
                if href_attr:
                    download_link = str(href_attr)  # Explicitly convert to string
                    # Make sure we have an absolute URL
                    download_link = urljoin(download_site, download_link)
                    break
        
        if not download_link:
            logger.error('Could not find download link for UK SIC data on %s', download_site)
            return None
        
        # Download the file
        logger.info('Downloading UK SIC data from %s', download_link)
        file_response = requests.get(download_link)
        file_response.raise_for_status()
        
        # Save the file
        with open(data_file, 'wb') as f:
            f.write(file_response.content)
        
        logger.info('Successfully downloaded UK SIC data to %s', data_file)
        return data_file
        
    except requests.exceptions.RequestException as e:
        logger.error('Error downloading UK SIC data: %s', str(e))
        return None

def download_edgar_data(config: Union[Dict[str, Dict[str, str]], configparser.ConfigParser]) -> str:
    """Ensures the EDGAR data directory exists
    
    Args:
        config: Configuration dictionary or ConfigParser containing EDGAR data parameters
        
    Returns:
        str: Path to the EDGAR data directory
    """
    # Get the configuration values - handle both dict and ConfigParser
    if isinstance(config, configparser.ConfigParser):
        data_dir = config['edgar_data']['EDGAR_DATA_DIR']
    else:
        data_dir = config['edgar_data']['EDGAR_DATA_DIR']
    
    # Check to see if the directory exists if not create it
    logger.info('Checking for the existence of the directory %s.', data_dir)
    try:
        os.mkdir(data_dir)
        logger.info('%s does not exist creating it.', data_dir)
    except FileExistsError:
        logger.info('%s exists skipping creation.', data_dir)
    
    return data_dir

def download_international_sic_data(config: Union[Dict[str, Dict[str, str]], configparser.ConfigParser]) -> Optional[str]:
    """Download the latest International SIC (ISIC) data from the UN Statistics Division
    
    Args:
        config: Configuration dictionary or ConfigParser containing SIC data parameters
        
    Returns:
        str: Path to the downloaded file or None if download failed
    """
    # Get the configuration values
    download_site = config['sic_data']['INTERNATIONAL_SIC_DATA_SITE']
    data_dir = config['sic_data']['INTERNATIONAL_SIC_DATA_DIR']
    
    # Create the directory if it doesn't exist
    if not os.path.exists(data_dir):
        logger.info('Creating directory %s', data_dir)
        os.makedirs(data_dir)
    
    # Check if any ISIC files already exist
    existing_files = glob.glob(os.path.join(data_dir, 'ISIC_Rev_*_english_structure.csv'))
    if existing_files:
        latest_file = max(existing_files)
        logger.info('Found existing ISIC data file: %s', latest_file)
        return latest_file
    
    # Download the page and find the latest revision
    logger.info('Checking for International SIC data at %s', download_site)
    try:
        response = requests.get(download_site)
        response.raise_for_status()  # Raise exception for HTTP errors
        
        # Parse the HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # First approach: Try to find revision links directly on the main page
        revision_links: List[str] = []
        
        # 1. Look for links to revision pages with more flexible pattern matching
        for link in soup.find_all('a'):
            if isinstance(link, Tag):
                href_attr = link.get('href', '')
                # Explicitly convert to string before using string methods
                href_str = str(href_attr) if href_attr else ""
                text = link.get_text().lower() if hasattr(link, 'get_text') else ""
                # Look for any link that might point to a revision page
                if ('rev' in href_str.lower() or 'rev' in text) and 'isic' in href_str.lower():
                    logger.debug(f"Found potential revision link: {href_str} with text: {text}")
                    revision_links.append(urljoin(download_site, href_str))
        
        if revision_links:
            # Sort links to find the one with highest revision number
            def get_rev_number(link: str) -> int:
                match = re.search(r'rev[-._]?(\d+)', link.lower())
                return int(match.group(1)) if match else 0
            
            revision_links.sort(key=get_rev_number, reverse=True)
            latest_rev_link = revision_links[0]
            logger.info('Found latest revision link: %s', latest_rev_link)
            
            # Visit the revision page
            rev_response = requests.get(latest_rev_link)
            rev_response.raise_for_status()
            rev_soup = BeautifulSoup(rev_response.text, 'html.parser')
        else:
            # Second approach: If we can't find revision links, look for structure CSV directly
            logger.warning('Could not find revision links, looking for CSV directly on main page')
            rev_soup = soup
            latest_rev_link = download_site
            
        # Look for the CSV download link
        download_link: Optional[str] = None
        
        # First, look specifically for "Structure only" with CSV
        for li in rev_soup.find_all('li'):
            if isinstance(li, Tag):
                li_text = li.get_text().lower() if hasattr(li, 'get_text') else ""
                if 'structure only' in li_text and 'csv' in li_text:
                    csv_link = li.find('a', href=True)
                    if csv_link and isinstance(csv_link, Tag):
                        href_attr = csv_link.get('href')
                        if href_attr:
                            download_link = str(href_attr).strip()  # Convert to string explicitly
                            logger.debug(f"Found structure CSV link in list item: {download_link}")
                            break
        
        # If not found, look for any CSV link related to structure
        if not download_link:
            for link in rev_soup.find_all('a', href=True):
                if isinstance(link, Tag):
                    href_attr = link.get('href')
                    if href_attr:
                        href = str(href_attr).lower()  # Convert to string explicitly
                        text = link.get_text().lower() if hasattr(link, 'get_text') else ""
                        if '.csv' in href and any(term in href or term in text for term in ['structure', 'english', 'isic_rev']):
                            download_link = str(href_attr).strip()  # Convert to string explicitly
                            logger.debug(f"Found CSV link with structure/english/isic: {download_link}")
                            break
        
        # Last resort - try direct path construction if we can find a revision number
        if not download_link:
            # Log all links found on the page for debugging
            all_links: List[str] = []
            for link in rev_soup.find_all('a', href=True):
                if isinstance(link, Tag):
                    href_attr = link.get('href')
                    text = link.get_text() if hasattr(link, 'get_text') else ""
                    if href_attr:
                        all_links.append(f"{str(href_attr)} -> {text}")  # Convert to string explicitly
            logger.debug(f"All links found on page: {all_links}")
            
            # Try to extract a revision number from the page content
            rev_match = None
            for text in rev_soup.stripped_strings:
                match = re.search(r'ISIC\s+Rev\.?\s*(\d+)', text, re.IGNORECASE)
                if match:
                    rev_match = match
                    break
            
            if rev_match:
                rev_num = rev_match.group(1)
                # Construct a direct download URL based on common patterns
                fallback_url = f"https://unstats.un.org/unsd/classifications/Econ/Download/In%20Text/ISIC_Rev_{rev_num}_english_structure.csv"
                logger.warning(f"Using fallback URL: {fallback_url}")
                download_link = fallback_url
        
        # If still no link, use a hardcoded fallback as absolute last resort
        if not download_link:
            logger.warning("No download link found, using hardcoded fallback for ISIC Rev 5")
            download_link = "https://unstats.un.org/unsd/classifications/Econ/Download/In%20Text/ISIC_Rev_5_english_structure.csv"
        
        # Make sure we have an absolute URL
        download_link = urljoin(latest_rev_link, download_link)
        
        # Fix URL encoding if needed (replace spaces with %20)
        if ' ' in download_link:
            download_link = download_link.replace(' ', '%20')
        
        # Download the file
        logger.info('Downloading International SIC data from %s', download_link)
        file_response = requests.get(download_link)
        file_response.raise_for_status()
        
        # Extract filename from the URL
        filename = os.path.basename(download_link.replace('%20', '_'))
        
        # If filename doesn't have the expected pattern, create a proper one
        if not (filename.startswith('ISIC_Rev_') and filename.endswith('.csv')):
            # Extract revision number if possible
            rev_match = re.search(r'Rev[_.]?(\d+)', download_link, re.IGNORECASE)
            rev_num = rev_match.group(1) if rev_match else '5'  # Default to Rev 5
            filename = f"ISIC_Rev_{rev_num}_english_structure.csv"
        
        # Save the file
        data_file = os.path.join(data_dir, filename)
        with open(data_file, 'wb') as f:
            f.write(file_response.content)
        
        logger.info('Successfully downloaded International SIC data to %s', data_file)
        return data_file
        
    except requests.exceptions.RequestException as e:
        logger.error('Error downloading International SIC data: %s', str(e))
        return None
    except Exception as e:
        logger.error('Unexpected error downloading International SIC data: %s', str(e))
        import traceback
        logger.error(traceback.format_exc())
        return None

def download_eu_sic_data(config: Union[Dict[str, Dict[str, str]], configparser.ConfigParser]) -> Optional[str]:
    """Download the EU SIC (NACE) data from the European Commission website
    
    Args:
        config: Configuration dictionary or ConfigParser containing SIC data parameters
        
    Returns:
        str: Path to the downloaded file or None if download failed

    Note:
        This function means to download the NACE Rev. 2.1 data from the European Commission's showvoc.op.europa.eu site.
        It constructs the download URL based on the dataset name and target filename specified in the config. However, 
        the call to this function in makedb.py is not currently used, because the site this resource is downloaded from
        seems to use an event to enable the download.  This results in an on demand URL that cannot be discovered or
        constructed in advance.  Therefore, this function is not currently used.
    """
    # Get the configuration values
    data_dir = config['sic_data']['EU_SIC_DATA_DIR']
    
    # Check if EU_SIC_DOWNLOAD_SITE exists, otherwise use default
    if 'EU_SIC_DOWNLOAD_SITE' in config['sic_data']:
        download_base = config['sic_data']['EU_SIC_DOWNLOAD_SITE']
    else:
        download_base = "https://showvoc.op.europa.eu/download/"
        logger.info(f"EU_SIC_DOWNLOAD_SITE not found in config, using default: {download_base}")
    
    # Get the filename from config or use default
    if 'EU_SIC_DATA' in config['sic_data']:
        target_filename = config['sic_data']['EU_SIC_DATA']
    else:
        target_filename = "NACE_Rev2.1_Heading_All_Languages.tsv"
        logger.info(f"EU_SIC_DATA not found in config, using default: {target_filename}")
    
    # Create the directory if it doesn't exist
    if not os.path.exists(data_dir):
        logger.info('Creating directory %s', data_dir)
        os.makedirs(data_dir)
    
    # Check if file already exists
    data_file = os.path.join(data_dir, target_filename)
    if os.path.exists(data_file):
        logger.info('Found existing EU SIC data file: %s', data_file)
        return data_file
    
    # Construct the download URL - using the correct pattern for showvoc.op.europa.eu
    dataset_name = "ESTAT_Statistical_Classification_of_Economic_Activities_in_the_European_Community_Rev._2.1._(NACE_2.1)"
    
    try:
        # URL encode the dataset name properly
        import urllib.parse
        encoded_dataset = urllib.parse.quote(dataset_name, safe='')
        download_url = f"{download_base}{encoded_dataset}/{target_filename}"
        
        logger.info(f'Attempting to download from: {download_url}')
        
        # Download the file
        file_response = requests.get(download_url)
        file_response.raise_for_status()
        
        # Save the file
        with open(data_file, 'wb') as f:
            f.write(file_response.content)
        
        logger.info('Successfully downloaded EU SIC data to %s', data_file)
        return data_file
        
    except requests.exceptions.RequestException as e:
        logger.error(f'Error downloading EU SIC data: {str(e)}')
        return None
    except Exception as e:
        logger.error(f'Unexpected error downloading EU SIC data: {str(e)}')
        import traceback
        logger.error(traceback.format_exc())
        return None

def download_japan_sic_data(config: Union[Dict[str, Dict[str, str]], configparser.ConfigParser]) -> Optional[str]:
    """Download the Japan SIC data file from the Statistics Bureau of Japan website
    
    Args:
        config: Configuration dictionary or ConfigParser containing SIC data parameters
        
    Returns:
        str: Path to the downloaded file or None if download failed
    """
    # Get the configuration values
    download_site = config['sic_data']['JAPAN_SIC_DATA_SITE']
    link_name = config['sic_data']['JAPAN_SIC_DOWNLOAD_LINK_NAME']
    data_dir = config['sic_data']['JAPAN_SIC_DATA_DIR']
    
    # Create the directory if it doesn't exist
    if not os.path.exists(data_dir):
        logger.info('Creating directory %s', data_dir)
        os.makedirs(data_dir)
    
    # Check if any Japan SIC files already exist
    existing_files = glob.glob(os.path.join(data_dir, '*.xls*'))
    if existing_files:
        latest_file = max(existing_files)
        logger.info('Found existing Japan SIC data file: %s', latest_file)
        return latest_file
    
    # Download the page and find the link
    logger.info('Downloading Japan SIC data from %s', download_site)
    try:
        response = requests.get(download_site)
        response.raise_for_status()  # Raise exception for HTTP errors
        
        # Parse the HTML and find the link
        soup = BeautifulSoup(response.text, 'html.parser')
        download_link: Optional[str] = None
        
        # Log all links for debugging
        all_links = []
        for a_tag in soup.find_all('a'):
            if isinstance(a_tag, Tag):
                href = a_tag.get('href', '')
                text = a_tag.get_text() if hasattr(a_tag, 'get_text') else ""
                all_links.append(f"{href} -> {text}")
                
                # Improved link matching - more flexible to handle the actual HTML structure
                if isinstance(text, str) and "Industrial Classification" in text and "Excel" in text:
                    logger.debug(f"Found matching link: {href} -> {text}")
                    href_attr = a_tag.get('href')
                    if href_attr:
                        download_link = str(href_attr)  # Explicitly convert to string
                        # Make sure we have an absolute URL
                        if download_link.startswith('/'):
                            # Extract the base URL (protocol + domain) from the download_site
                            from urllib.parse import urlparse
                            parsed_url = urlparse(download_site)
                            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                            download_link = base_url + download_link
                        else:
                            download_link = urljoin(download_site, download_link)
                        logger.debug(f"Constructed download URL: {download_link}")
                        break
        
        # If no link found, log all links for debugging
        if not download_link:
            logger.debug(f"All links found on the page: {all_links}")
            
            # Fallback: Try to construct the URL directly based on the known structure
            # Based on the HTML, we know the URL is: /english/data/e-census/2021/zuhyou/r3classification.xlsx
            from urllib.parse import urlparse
            parsed_url = urlparse(download_site)
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
            fallback_url = base_url + "/english/data/e-census/2021/zuhyou/r3classification.xlsx"
            
            logger.warning(f"Could not find download link. Trying direct URL: {fallback_url}")
            download_link = fallback_url
        
        # Download the file
        logger.info('Downloading Japan SIC data from %s', download_link)
        file_response = requests.get(download_link)
        file_response.raise_for_status()
        
        # Extract filename from the URL
        filename = os.path.basename(download_link)
        if not filename or '?' in filename:  # Handle URLs without filenames or with query parameters
            filename = 'japan_sic.xlsx'
        
        # Save the file
        data_file = os.path.join(data_dir, filename)
        with open(data_file, 'wb') as f:
            f.write(file_response.content)
        
        logger.info('Successfully downloaded Japan SIC data to %s', data_file)
        return data_file
        
    except requests.exceptions.RequestException as e:
        logger.error('Error downloading Japan SIC data: %s', str(e))
        return None
    except Exception as e:
        logger.error('Unexpected error downloading Japan SIC data: %s', str(e))
        import traceback
        logger.error(traceback.format_exc())
        return None

def ensure_source_data_dir(base_dir: str = "./source_data") -> str:
    """Ensures the source_data parent directory exists
    
    Args:
        base_dir: Path to the source data directory
        
    Returns:
        str: Path to the source data directory
    """
    logger.info(f'Checking for the existence of the source data directory {base_dir}')
    if not os.path.exists(base_dir):
        logger.info(f'Creating source data directory {base_dir}')
        os.makedirs(base_dir)
    else:
        logger.info(f'Source data directory {base_dir} already exists')
    
    return base_dir