"""
Copyright 2021 mediumroast.io.  All rights reserved
Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
in compliance with the License. You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License
is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied. See the License for the specific language governing permissions and limitations under
the License.
"""

import sqlite3, re, requests
from pyedgar.filing import Filing
from bs4 import BeautifulSoup
from geopy.geocoders import ArcGIS

class EdgarUtilities:

    def __init__(self):
        self.PATH = "./"
        self.DB_CACHE = 'edgar_cache.db'
        self.COMPANY = 1
        self.CIK = 0
        self.YEAR = 2
        self.MONTH = 3
        self.DAY = 4
        self.ACCESSION = 5
        self.FORM = 6
        self.EDGARSERVER = "www.sec.gov"
        self.EDGARARCHIVES = "Archives/edgar/data"
        self.EDGARURI = "https://"
        self.BROWSEEDGAR = "/cgi-bin/browse-edgar?CIK="
        self.GETISSUER = "/cgi-bin/own-disp?action=getissuer&CIK="
        self.GETOWNER = "/cgi-bin/own-disp?action=getowner&CIK="
        self.EDGARSEARCH = "&action=getcompany"
        self.e_conn = sqlite3.connect(self.PATH + self.DB_CACHE)
        self.ec = self.e_conn.cursor()
        self.authors = ['Michael Hay', 'John Goodman']
        self.copyright = "Copyright 2020 and 2021 mediumroast.io. All rights reserved."
        self.locator = ArcGIS (timeout=2)
        self.API_KEY = 'YOUR API KEY'

    def locate (self, place):
        l = self.locator.geocode (place)
        return l.longitude, l.latitude, l.address

    def getAllCIKs (self, query_string):
        all_companies = {
            'companies': {},
            'totalCompanies': 0
        }
        tmp_companies = {}
        white_list = re.compile('10-K')  # Establish the white list of filing types to get
        for row in self.ec.execute("SELECT * FROM companies WHERE name LIKE '%" + query_string + "%'"): # TODO Improve the SQL selection criteria for flexibility
            if not white_list.match(row[self.FORM]): continue # punt on everything but 10K filings

            company_name = str(row[self.COMPANY])
            cik_no = str(row[self.CIK])

            if tmp_companies.get (company_name) == None:
                tmp_companies[company_name] = cik_no
            else:
                continue

        all_companies['companies'] = tmp_companies
        all_companies['totalCompanies'] = len (tmp_companies)
        return all_companies

    
    def getAllSummary (self, query_string):
        all_companies = {
            'companies': [],
            'totalCompanies': 0
        }
        tmp_companies = {}
        white_list = re.compile('10-K')  # Establish the white list of filing types to get
        for row in self.ec.execute("SELECT * FROM companies WHERE name LIKE '%" + query_string + "%'"): # TODO Improve the SQL selection criteria for flexibility
            if not white_list.match(row[self.FORM]): continue # punt on everything but 10K filings

            filing_dir = str(row[self.CIK]) + '/' + row[self.ACCESSION].replace('-', '') # Directory Listing for the filing
            filing_idx = self.EDGARURI + self.EDGARSERVER + '/' + self.EDGARARCHIVES + '/' + filing_dir + '/' # URL for the Directory Listing
            filing_idx_url = filing_idx + row[self.ACCESSION] + '-index.html'  # URL for the filing index HTML
            accession_no = str(row[self.ACCESSION])
            company_name = str(row[self.COMPANY])
            cik_no = str(row[self.CIK])
            form_type = str(row[self.FORM])
            form = {
                    'filingIndex': filing_idx_url, # TODO Consider moving this into the DB Cache
                    'year': row[self.YEAR],
                    'month': row[self.MONTH],
                    'day': row[self.DAY],
                    'formType': form_type
            }
            if tmp_companies.get (company_name) == None:
                tmp_companies[company_name] = {
                    'CIK': cik_no,
                    'companyName': company_name,
                    'companyFilings': self.EDGARURI + self.EDGARSERVER + self.BROWSEEDGAR + cik_no + self.EDGARSEARCH, # TODO Consider moving this into the DB Cache
                    'transactionsByIssuer': self.EDGARURI + self.EDGARSERVER + self.GETISSUER + cik_no, # TODO Consider moving this into the DB Cache
                    'transactionsByOwner': self.EDGARURI + self.EDGARSERVER + self.GETOWNER + cik_no, # TODO Consider moving this into the DB Cache
                    'forms': {accession_no: form},
                }
            else:
                tmp_companies[company_name]['forms'][accession_no] = form

        all_companies['companies'] = tmp_companies
        all_companies['totalCompanies'] = len (tmp_companies)
        return all_companies

    
    def getAll (self, query_string):
        all_companies = {
            'companies': [],
            'totalCompanies': 0
        }
        tmp_companies = {}
        white_list = re.compile('10-K')  # Establish the white list of filing types to get

        for row in self.ec.execute("SELECT * FROM companies WHERE name LIKE '%" + query_string + "%'"):
            if not white_list.match(row[self.FORM]): continue # punt on everything but 10K filings

            filing_dir = str(row[self.CIK]) + '/' + row[self.ACCESSION].replace('-', '') # Directory Listing for the filing
            filing_idx = self.EDGARURI + self.EDGARSERVER + '/' + self.EDGARARCHIVES + '/' + filing_dir + '/' # URL for the Directory Listing
            filing_idx_url = filing_idx + row[self.ACCESSION] + '-index.html'  # URL for the filing index HTML
            accession_no = str(row[self.ACCESSION])
            (tenK_filing_url, company_info) = self.get10kurl (filing_idx_url) # URL containing the actual 10K contents + intel on the company
            company_name = str(row[self.COMPANY])
            cik_no = str(row[self.CIK])
            form_type = str(row[self.FORM])
            form = {
                    'filingIndex': filing_idx_url,
                    'year': row[self.YEAR],
                    'month': row[self.MONTH],
                    'day': row[self.DAY],
                    'url': str(tenK_filing_url),
                    'formType': form_type
            }

            if tmp_companies.get (company_name) == None:
                if not company_info['rawAddress'] == 'BLANK': (long, lat, address) = self.locate (company_info['rawAddress'])
                tmp_companies[company_name] = {
                    """
                    TODOs
                        1. Some amount of the below could be entered into the cache making the process more streamlined for clients.
                           Specifically, we'd want to experiment with the lat/long data sets to see if that could be potentially stored or not.
                           The determining factor will be if ArcGIS or another geocoding service can support the number of calls needed to really
                           populate the Cache DB.
                        2. The SIC number and SIC string needs to be pulled into separate columns.  This should set up the potential for looking up
                           the SIC string and matching it to an overall structure.  Not sure where to get the SIC mapping structure.  Perhaps the 
                           OSHA site can provide some intelligence or maybe there is a python module.
                    """
                    'CIK': cik_no,
                    'companyName': company_name,
                    'companyFilings': self.EDGARURI + self.EDGARSERVER + self.BROWSEEDGAR + cik_no + self.EDGARSEARCH,
                    'transactionsByIssuer': self.EDGARURI + self.EDGARSERVER + self.GETISSUER + cik_no,
                    'transactionsByOwner': self.EDGARURI + self.EDGARSERVER + self.GETOWNER + cik_no,
                    'forms': {accession_no: form},
                    'phone': company_info['phone'],
                    'irsNumber': company_info['IRS No.'],
                    'stateOfIncorporation.': company_info['State of Incorp.'],
                    'fiscalYearEnd': company_info['Fiscal Year End'],
                    'antitrustAct': company_info['Act'],
                    'standardIndustryCode': company_info['SIC'],
                    'longitude': long,
                    'lattitude': lat,
                    'longAddress': address
                }
            else:
                tmp_companies[company_name]['forms'][accession_no] = form

        all_companies['companies'] = tmp_companies
        all_companies['totalCompanies'] = len (tmp_companies)
        return all_companies

    def get10kurl(self, l_url):
        company_info = {
            'phone': 'BLANK',
            'rawAddress': 'BLANK',
            'SIC': 'BLANK',
            'IRS No.': 'BLANK',
            'State of Incorp.': 'BLANK',
            'Fiscal Year End': 'BLANK',
            'Act': 'BLANK'
        }
        l_url: str
        l10k_url = ""
        t_url = self.EDGARURI + self.EDGARSERVER  # Establish the basic URL for the EDGAR service
        page = requests.get(l_url)
        html = page.content
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find_all('table')[0]  # Get the first table in the 10k HTML index
        rows = table.find_all('tr')  # Get all of the rows
        for row in rows:
            columns = row.find_all('td')  # Get all of the columns
            is_10k = 0  # A flag determining if we've found the columns associated to the 10K HTML
            for column in columns:
                if is_10k:
                    tags = column.find_all('a')  # Get the <a href... tag
                    for tag in tags: l10k_url = t_url + tag.get('href')
                    break
                elif column.find(text='10-K'):  # If we find the 10K columns turn on the flag
                    is_10k = 1
                    continue
    
        # Company address and phone number
        tmp_company=[]
        company_loc = soup.find_all (class_ = 'mailer')[1]
        for loc in company_loc:
            element = loc.string
            element = element.strip ()
            if not element: continue
            tmp_company.append (element)
        company_info['phone'] = tmp_company[-1]
        tmp_company=tmp_company[:-1]
        company_info['rawAddress'] = " ".join (tmp_company)
        
        # Company details like SIC, 
        tmp_details=""
        fiscal_year = re.compile ('^fiscal', re.IGNORECASE)
        film_no = re.compile ('^film', re.IGNORECASE)
        office_start = re.compile('^office', re.IGNORECASE)
        company_details = soup.find_all (class_ = 'identInfo')
        for detail in company_details[0].children:
            detail = detail.string
            if detail == None: continue
            if office_start.match (detail): detail = ", " + detail
            tmp_details += detail
        for detail in tmp_details.split ('|'):
            detail = detail.strip ()
            if fiscal_year.match(detail):
                detail = detail [:21]
            if film_no.match (detail):
                detail = detail.split ('SIC')[1]
                detail = "SIC" + detail
            (key, value) = detail.split (':')
            key = key.strip ()
            value = value.strip ()
            company_info[key] = value

        return l10k_url, company_info
    
    def getCompanyDetails (self, cik_no):
        filings_url = self.EDGARURI + self.EDGARSERVER + self.BROWSEEDGAR + cik_no + self.EDGARSEARCH
        page = requests.get(filings_url)
        html = page.content
        soup = BeautifulSoup(html, 'html.parser')

        company_info = {
            'companyName': 'BLANK',
            'CIK': cik_no,
            'phone': 'BLANK',
            'rawAddress': 'BLANK',
            'SIC': 'BLANK',
            'stateOfIncorporation': 'BLANK',
            'fiscalYearEnd': 'BLANK'
        }

        # Company address and phone number
        tmp_company=[]
        company_loc = soup.find_all (class_ = 'mailer')[1]
        for loc in company_loc:
            element = loc.string
            element = element.strip ()
            if not element: continue
            tmp_company.append (element)
        company_info['phone'] = tmp_company[-1]
        tmp_company=tmp_company[:-1]
        company_info['rawAddress'] = " ".join (tmp_company).split ('Business Address')[1].strip ()

        # Company details like SIC, 
        tmp_details=""
        fiscal_year = re.compile ('^fiscal', re.IGNORECASE)
        sic_no = re.compile ('^sic', re.IGNORECASE)
        state_start = re.compile('^state of inc.', re.IGNORECASE)
        company_details = soup.find_all (class_ = 'identInfo')
    
        for detail in company_details[0].children:
            detail = detail.string
            if detail == None: continue
            tmp_details += detail

        for detail in tmp_details.split ('|'):
            detail = detail.strip ()
            if fiscal_year.match(detail):
                detail = detail [:21]
                
            if sic_no.match (detail):
                (s, l) = detail.split ('State location')
                company_info['SIC'] = s.split(':')[1].strip () # No rewrite rules needed
                detail = "stateLocation" + l

            if fiscal_year.match (detail):
                detail = detail.split (':')[1]
                company_info['fiscalYearEnd'] = detail.strip ()
                continue

            if state_start.match (detail):
                detail = detail.split (':')[1]
                company_info['stateOfIncorporation'] = detail.strip ()
                continue

            (key, value) = detail.split (':')
            key = key.strip ()
            value = value.strip ()
            company_info[key] = value

        company_name = soup.find_all (class_ = 'companyName')
        names = []
        for detail in company_name[0].children:
            names.append (detail)
        company_info['companyName'] = names[0].strip ()
        if not company_info['rawAddress'] == 'BLANK': 
            (long, lat, address) = self.locate (company_info['rawAddress'])
            company_info['companyAddress'] = address
            company_info['lattitude'] = lat
            company_info['longitude'] = long

        return company_info




