import glob
import logging
import os
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

def download_uk_sic_data(config):
    """Download the UK SIC data file from the UK Companies House website
    
    Args:
        config (dict): Configuration dictionary containing SIC data parameters
        
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
        download_link = None
        
        # Look for links that contain the specified text
        for link in soup.find_all('a'):
            if link.text and link_name in link.text:
                download_link = link.get('href')
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

def download_edgar_data(config):
    """Ensures the EDGAR data directory exists
    
    Args:
        config (dict): Configuration dictionary containing EDGAR data parameters
        
    Returns:
        str: Path to the EDGAR data directory
    """
    data_dir = config['edgar_data']['EDGAR_DATA_DIR']
    
    # Check to see if the directory exists if not create it
    logger.info('Checking for the existence of the directory %s.', data_dir)
    try:
        os.mkdir(data_dir)
        logger.info('%s does not exist creating it.', data_dir)
    except FileExistsError:
        logger.info('%s exists skipping creation.', data_dir)
    
    return data_dir

def download_international_sic_data(config):
    """Download the latest International SIC (ISIC) data from the UN Statistics Division
    
    Args:
        config (dict): Configuration dictionary containing SIC data parameters
        
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
        revision_links = []
        
        # 1. Look for links to revision pages with more flexible pattern matching
        for link in soup.find_all('a'):
            href = link.get('href', '')
            text = link.get_text().lower()
            # Look for any link that might point to a revision page
            if ('rev' in href.lower() or 'rev' in text) and 'isic' in href.lower():
                logger.debug(f"Found potential revision link: {href} with text: {text}")
                revision_links.append(urljoin(download_site, href))
        
        if revision_links:
            # Sort links to find the one with highest revision number
            def get_rev_number(link):
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
        download_link = None
        
        # First, look specifically for "Structure only" with CSV
        for li in rev_soup.find_all('li'):
            li_text = li.get_text().lower()
            if 'structure only' in li_text and 'csv' in li_text:
                csv_link = li.find('a', href=True)
                if csv_link:
                    download_link = csv_link['href'].strip()
                    logger.debug(f"Found structure CSV link in list item: {download_link}")
                    break
        
        # If not found, look for any CSV link related to structure
        if not download_link:
            for link in rev_soup.find_all('a', href=True):
                href = link['href'].lower()
                text = link.get_text().lower()
                if '.csv' in href and any(term in href or term in text for term in ['structure', 'english', 'isic_rev']):
                    download_link = link['href'].strip()
                    logger.debug(f"Found CSV link with structure/english/isic: {download_link}")
                    break
        
        # Last resort - try direct path construction if we can find a revision number
        if not download_link:
            # Log all links found on the page for debugging
            all_links = []
            for link in rev_soup.find_all('a', href=True):
                all_links.append(f"{link['href']} -> {link.get_text()}")
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