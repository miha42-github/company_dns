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


e_conn = sqlite3.connect(PATH + DB_CACHE)
ec = e_conn.cursor()


class FalshCmd(cmd.Cmd):

    prompt = 'falsh> '
    intro = 'A shell to retrieve firmalitics from the SEC Edgar related to public companies'
    ruler = '_'

    def do_cquery(self, query):
        companies = {}
        white_list = re.compile('10-K|10-Q')
        for row in ec.execute("SELECT * FROM companies WHERE name LIKE '%" + query + "%'"):
            if not white_list.match(row[FORM]):
                continue
            l_dir = str(row[CIK]) + '/' + row[ACCESSION].replace('-', '')
            doc_url = EDGARURI + EDGARSERVER + '/' + EDGARARCHIVES + '/' + l_dir + '/'
            l_file = doc_url + row[ACCESSION] + '-index.html'
            my_row = [row[MONTH], row[DAY], row[YEAR], row[ACCESSION], doc_url, l_file]
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

    def help_cquery(self):
        print("\ncquery [company name OR string]\nQuery either a company name or partial name.")

    def do_getheaders(self, cik_accession):
        accession: str
        (cik, accession) = cik_accession.split(':')
        f = Filing(cik, accession)
        printer(f.headers)

    # TODO pull in PyEdgar to print out a company description from an 10K or similar
    # TODO we may need to parse from item 1. to item 1.a in a case insensitive form.  Merely getting all HTML could be ok
    def do_getdesc(self, l_url):
        page = requests.get(l_url)
        item_1 = re.compile('item 1.', re.IGNORECASE)
        item_1a = re.compile('item 1a.', re.IGNORECASE)
        html = page.content
        l_string = ""
        flag = 0
        for l in html:
            line = str(l)
            if item_1.match(line):
                flag = 1
            elif item_1a.match(line):
                flag = 0
            elif flag == 1:
                l_string += line
            else:
                continue
        print(html)



    def emptyline(self):
        pass

    def do_exit(self, line):
        return True

    def help_exit(self):
        print("\nExit the shell")


if __name__ == '__main__':
    FalshCmd().cmdloop()
    e_conn.close()



