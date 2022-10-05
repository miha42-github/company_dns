import sqlite3
import re
import requests

__author__ = "Michael Hay"
__copyright__ = "Copyright 2022, Mediumroast, Inc. All rights reserved."
__license__ = "Apache 2.0"
__version__ = "2.0.0"
__maintainer__ = "Michael Hay"
__status__ = "Alpha"
__date__ = '2022-October-4'

#### Globals ####
# Used for setting attributes consistently when unknown
UKN = "Unknown"

# Fields from the SQL Select results
COMPANY = 1
CIK = 0
YEAR = 2
MONTH = 3
DAY = 4
ACCESSION = 5
FORM = 6

# Helper strings to reach various EDGAR resources
EDGARDATA = "https://data.sec.gov/submissions/"
EDGARFACTS= "https://data.sec.gov/api/xbrl/companyfacts/"
EDGARSERVER = "www.sec.gov"
EDGARARCHIVES = "Archives/edgar/data"
EDGARURI = "https://"
BROWSEEDGAR= "/cgi-bin/browse-edgar?CIK="
GETISSUER = "/cgi-bin/own-disp?action=getissuer&CIK="
GETOWNER = "/cgi-bin/own-disp?action=getowner&CIK="
EDGARSEARCH = "&action=getcompany"

class EdgarQueries:
    """A core set of methods designed to interact with both locally cached and remote SEC EDGAR data.

    The design point is to enable key data to be retrieved from EDGAR and supplied back to a calling program.
    For the company_dns service this class enables the finding of data about individual or even sets of 
    companies to be used in other applications.

    Import and Construct the class:
        import edgar
        controller = edgar.EdgarQueries()

    Methods:
        get_all_ciks(query_string) - Using a query string return pairs of company names and CIKs
        get_all_details(query_string, firmographics) - Get additional form details and firmographics details based upon query_string
        get_firmographics(cik) - Using the CIK get firmographic details for a specific company
    """

    def __init__(self, db_file='./edgar_cache.db', agent='Mediumroast, Inc. help@mediumroast.io'):
        # The SQLite database connection and cursor
        self.e_conn = sqlite3.connect(db_file)
        self.ec = self.e_conn.cursor()

        # User agent to talk to EDGAR services
        self.headers = {
            'User-Agent': agent,
            'Accept-Encoding': 'gzip, deflate'
        }
        


    def get_all_ciks(self, query_string):
        """Using a query string find and return a dictionary containing all formal company names and their associated CIKs. 

        A CIK lookup tool enabling a user to specify a query string and obtain a dictionary containing a key value pair including
        the formal company name and the associated Central Index Key (CIK).  Notice, presently there is a limitation of only returning
        CIKs from companies who have filed one of the following forms: 10-K, 10-K/A and 10-Q.
        
        An example of the returned dictionary is below:
        {
            'companies': {
                'IBM CREDIT LLC': '1225307'
            }, 
            'totalCompanies': 1
        }

        Args:
            query_string (string): A full or partial company name used to search for CIKs 

        Returns:
            final_companies (dict): An object containing a list of all company CIK pairs and the total number of company objects processed
        """
        final_companies = {
            'companies': {},
            'totalCompanies': 0
        }
        tmp_companies = {}
        
        # Establish the white list to filter in only 10-K, 10-K/A and 10-Q
        white_list = re.compile('10-')

        # Select all companies from the table that match the query string  
        for row in self.ec.execute(
            "SELECT * FROM companies WHERE name LIKE '%" + 
            query_string + 
            "%'"):

            # Skip it if we're not on the white list
            if not white_list.findall(row[FORM]): continue # punt on everything but 10K & 10-Q filings

            # Company name
            company_name = str(row[COMPANY])

            # CIK number
            cik_no = str(row[CIK])

            # Should the company_name not already be stored in the dict then store it otherwise continue
            if tmp_companies.get(company_name) == None:
                tmp_companies[company_name] = cik_no
            else:
                continue

        # Store the companies dist into the final dict
        final_companies['companies'] = tmp_companies
        
        # Count the results
        final_companies['totalCompanies'] = len(tmp_companies)
        
        # Return
        return final_companies

    
    def get_all_details (self, query_string, firmographics=True):
        """Using a supplied query string retrieve all matching company data including from the cache DB and EDGAR.

        This method synthesizes stored cache data from the cache database, which is largely about filed forms, and
        recent data from the SEC EDGAR open RESTful API which supplies intel about specific companies.  If the
        firmographics argument is false then only data from the cache is retrieved.

        Args:
            query_string (string): A full or partial company name 
            firmographics (boolean): Defaults to true, and if false the method will not reach out to EDGAR to get full company detail

        Returns:
            final_companies (dict): An object containing a list of all companies' details from the cache and EDGAR
        """
        final_companies = {
            'companies': [],
            'totalCompanies': 0
        }
        tmp_companies = {}

        # Establish the white list of filing types to get
        white_list = re.compile('10-')  

        for row in self.ec.execute("SELECT * FROM companies WHERE name LIKE '%" + query_string + "%'"):
            # punt on everything but 10K/10Q filings
            if not white_list.match(row[FORM]): continue 
            
            # Directory Listing for the filing
            filing_dir = str(row[CIK]) + '/' + row[ACCESSION].replace('-', '')

            # URL for the Directory Listing
            filing_idx = EDGARURI + EDGARSERVER + '/' + EDGARARCHIVES + '/' + filing_dir + '/' 

            # URL for the filing index HTML
            filing_idx_url = filing_idx + row[ACCESSION] + '-index.html'  

            # Unique report accession number and accession key to be used for keeping intel on the report
            accession_no = str(row[ACCESSION]).replace('-', '')
            accession_key = "-".join([str(row[YEAR]), str(row[MONTH]), str(row[DAY]), accession_no]) 

            # Formal company name
            company_name = str(row[COMPANY])

            # Central Index Key number
            cik_no = str(row[CIK])

            # URL for the report
            report_filing_url = EDGARURI + EDGARSERVER + '/' + EDGARARCHIVES + '/' + cik_no + '/' + accession_no + '-index.html'

            # Get all relevant company data either from EDGAR or just use what is in the cache DB
            company_info = {'cik': cik_no, 'companyName': company_name}
            if firmographics: company_info = self.get_firmographics(cik_no)

            # Pull in the form type and define the specific form object
            form_type = str(row[FORM])
            form = {
                    'filingIndex': filing_idx_url,
                    'url': str(report_filing_url),
                    'formType': form_type
            }

            # If we've seen this company before then add the form, otherwise include both firmographics and the initial form definition
            if tmp_companies.get (company_name) == None:
                tmp_companies[company_name] = company_info
                tmp_companies[company_name]['forms'] = {accession_key: form}
            else:
                tmp_companies[company_name]['forms'][accession_key] = form

        # Store tmp into final
        final_companies['companies'] = tmp_companies
        final_companies['totalCompanies'] = len(tmp_companies)

        # Return to the caller
        return final_companies

    def _transform_raw_firmographics(self, final, raw):
        """An internal helper function for get_firmographics to select only what is needed and fill in blanks.

        Args:
            final (dict): A dictionary containing the intended target data
            raw (dict): The dictionary with data from EDGAR 

        Returns:
            final (dict): The dictionary with extracted and transformed data
        """
        for firmographic in final:
            final[firmographic] = raw[firmographic] if raw[firmographic] else UKN
        return final

    def get_firmographics(self, cik):
        """Create firmographics details, using the supplied cik argument, and return the.

        Using a RESTful call to the SEC's EDGAR database (example: for International Business Machines 
        https://data.sec.gov/submissions/CIK0000051143.json) gather key firmographic information and return to the caller.  
        When there is blank data in the response it will be filled in with the string 'Unknown'.

        Args:
            cik (string): The CIK for the requested company 

        Returns:
            firmographics (dict): An object containing an individual company's firmographic details

        """
        # Define the CIK and the CIK file name
        cik_padding_needed = 10 - len(cik)
        cik_with_padding = '0' * cik_padding_needed + cik

        cik_file = 'CIK' + cik_with_padding + '.json'

        # Define the full URL for the RESTful call
        my_url = EDGARDATA + cik_file

        # Define the full URL for the companyFacts
        fact_url = EDGARFACTS+ cik_file

        # Predefine the final_object
        firmographics = {
            'name': None,
            'cik': None,
            'sic': None,
            'sicDescription': None,
            'addresses': None,
            'tickers': None,
            'exchanges': None,
            'ein': None,
            'description': None,
            'website': None,
            'category': None,
            'fiscalYearEnd': None,
            'stateOfIncorporation': None,
            'phone': None,
            'entityType': None,
            'category': None
        }

        # TODO need try/except
        # Get the object via REST
        resp_obj = requests.get(my_url, headers=self.headers)

        # Raw firmographics which need to be massaged
        raw_firmographics = resp_obj.json()
        del raw_firmographics['filings']

        # Transform the raw into the final
        firmographics = self._transform_raw_firmographics(firmographics, raw_firmographics)

        # Enrich with some additional URLs to better access EDGAR data
        firmographics['companyFactsURL'] = fact_url
        firmographics['firmographicsURL'] = my_url
        firmographics['filingsURL'] = EDGARURI + EDGARSERVER + BROWSEEDGAR+ cik + EDGARSEARCH
        firmographics['transactionsByIssuer'] = EDGARURI + EDGARSERVER + GETISSUER + cik
        firmographics['transactionsByOwner'] = EDGARURI + EDGARSERVER + GETOWNER + cik

        # Cleanup stock information
        firmographics['exchanges'] = firmographics['exchanges'][0]
        firmographics['tickers'] = firmographics['tickers'][0]

        # Flatten the address information
        firmographics['city'] = firmographics['addresses']['mailing']['city']
        firmographics['stateProvince'] = firmographics['addresses']['mailing']['stateOrCountry']
        firmographics['zipPostal'] = firmographics['addresses']['mailing']['zipCode']
        firmographics['address'] = firmographics['addresses']['mailing']['street1'] \
            if not firmographics['addresses']['mailing']['street2'] \
            else firmographics['addresses']['mailing']['street1'] + " " + firmographics['addresses']['mailing']['street2']
        del firmographics['addresses']

        # Return the company details
        return firmographics

# TODO in the next version transform this into a CLI which should include:
#   CLI options for all methods and the location of the cache DB
#   The ability to execute the code from the command line
#   uses argparse to enable the command line switches




