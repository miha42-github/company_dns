#  Copyright 2019 Cameron Solutions
#  Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
#  in compliance with the License. You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software distributed under the License
#  is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
#  or implied. See the License for the specific language governing permissions and limitations under
#  the License.
#
#


import sqlite3
import re
import requests
from pyedgar.filing import Filing
from bs4 import BeautifulSoup

__author__ = "Michael Hay"
__copyright__ = "Copyright 2019, Cameron Solutions"
__license__ = "ASF 2.0"
__version__ = "1.0.0"
__maintainer__ = "Michael Hay"
__status__ = "Prototype"
__id__ = "$Id$"


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
        self.e_conn = sqlite3.connect(self.PATH + self.DB_CACHE)
        self.ec = self.e_conn.cursor()

    def get10kfilings(self, query_string):
        companies = {}
        white_list = re.compile('10-K')  # Establish the white list of filing types to get
        for row in self.ec.execute("SELECT * FROM companies WHERE name LIKE '%" + query_string + "%'"):
            if not white_list.match(row[self.FORM]):  # Move along if we're not on the white list
                continue
            l_dir = str(row[self.CIK]) + '/' + row[self.ACCESSION].replace('-', '')
            doc_url = self.EDGARURI + self.EDGARSERVER + '/' + self.EDGARARCHIVES + '/' + l_dir + '/'
            l_file = doc_url + row[self.ACCESSION] + '-index.html'  # Create the URLs for the 10k index and directory
            my_row = [row[self.MONTH], row[self.DAY], row[self.YEAR], row[self.ACCESSION], doc_url, l_file]
            if row[self.CIK] in companies:
                if str(row[self.FORM]) in companies[row[self.CIK]]:
                    companies[row[self.CIK]][row[self.FORM]].append(my_row)
                else:
                    companies[row[self.CIK]][row[self.FORM]] = []
                    companies[row[self.CIK]][row[self.FORM]].append(my_row)
            else:
                companies[row[self.CIK]] = {'name': row[self.COMPANY], row[self.FORM]: []}
                companies[row[self.CIK]][row[self.FORM]].append(my_row)
        return companies

    def get10kheaders(self, cik_accession):
        accession: str
        (cik, accession) = cik_accession.split(':')
        f = Filing(cik, accession)  # Using PyEdgar get the header information for a specific 10k instance
        return f.headers

    def get10kurl(self, l_url):
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
        return l10k_url


