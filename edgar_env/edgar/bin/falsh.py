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
import cmd
import re
import requests
from pprint import pprint as printer
from pyedgar.filing import Filing
from bs4 import BeautifulSoup

__author__ = "Michael Hay"
__copyright__ = "Copyright 2019, Cameron Solutions"
__license__ = "ASF 2.0"
__version__ = "1.0.0"
__maintainer__ = "Michael Hay"
__status__ = "Prototype"
__id__ = "$Id$"

# Constants
PATH = "./"
DB_CACHE = 'edgar_cache.db'
COMPANY = 1
CIK = 0
YEAR = 2
MONTH = 3
DAY = 4
ACCESSION = 5
FORM = 6
EDGARSERVER = "www.sec.gov"
EDGARARCHIVES = "Archives/edgar/data"
EDGARURI = "https://"


# Set up the connection and cursor to the DB Cache
e_conn = sqlite3.connect(PATH + DB_CACHE)
ec = e_conn.cursor()


class FalshCmd(cmd.Cmd):

    prompt = 'falsh> '
    intro = 'A shell to retrieve firmalitics from the SEC Edgar related to public companies'
    ruler = '_'

    def do_getcompanies(self, query):
        companies = {}
        white_list = re.compile('10-K')  # Establish the white list of filing types to get
        for row in ec.execute("SELECT * FROM companies WHERE name LIKE '%" + query + "%'"):   # Perform the SQL Query
            if not white_list.match(row[FORM]):  # Move along if we're not on the white list
                continue
            l_dir = str(row[CIK]) + '/' + row[ACCESSION].replace('-', '')
            doc_url = EDGARURI + EDGARSERVER + '/' + EDGARARCHIVES + '/' + l_dir + '/'
            l_file = doc_url + row[ACCESSION] + '-index.html'  # Create the URLs for the 10k index and directory
            my_row = [row[MONTH], row[DAY], row[YEAR], row[ACCESSION], doc_url, l_file]  # Set up a row for every 10k
            if row[CIK] in companies:
                if str(row[FORM]) in companies[row[CIK]]:
                    companies[row[CIK]][row[FORM]].append(my_row)
                else:
                    companies[row[CIK]][row[FORM]] = []
                    companies[row[CIK]][row[FORM]].append(my_row)
            else:
                companies[row[CIK]]={'name': row[COMPANY], row[FORM]: []}
                companies[row[CIK]][row[FORM]].append(my_row)
        printer(companies)

    def help_getcompanies(self):
        print("\ngetcompanies [company name OR string]\nQuery either a company name or partial name.")

    def do_getheaders(self, cik_accession):
        accession: str
        (cik, accession) = cik_accession.split(':')
        f = Filing(cik, accession)  # Using PyEdgar get the header information for a specific 10k instance
        printer(f.headers)

    def help_getheaders(self):
        print("\ngetheaders [cik:accession]\nRetrieve and print the headers for the document described by\n" +
              "CIK:Accession.")

    def do_get10kurl(self, l_url):
        l_url: str
        t_url = EDGARURI + EDGARSERVER  # Establish the basic URL for the EDGAR service
        page = requests.get(l_url)
        html = page.content
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find_all('table')[0]  # Get the first table in the 10k HTML index
        rows = table.find_all('tr')  # Get all of the rows
        for row in rows:
            columns = row.find_all('td') # Get all of the columns
            is_10k = 0  # A flag determining if we've found the columns associated to the 10K HTML
            for column in columns:
                if is_10k:
                    tags = column.find_all('a') # Get the <a href... tag
                    for tag in tags: print(t_url + tag.get('href'))  # Finally print the complete URL
                    break
                elif column.find(text='10-K'):  # If we find the 10K columns turn on the flag
                    is_10k = 1
                    continue


    def help_get10kurl(self):
        print("\nget10kurl [https://...html]\nRetrieve and print the URL for the 10k filing taking in the\n" +
              "URL from the 10k index HTML file.")


    def emptyline(self):
        pass

    def do_exit(self, line):
        return True

    def help_exit(self):
        print("\nExit the shell")


if __name__ == '__main__':
    FalshCmd().cmdloop()
    e_conn.close()  # Close the DB cache connection



