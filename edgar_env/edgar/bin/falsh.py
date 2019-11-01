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
from pprint import pprint as printer
from pyedgar.filing import Filing

__author__ = "Michael Hay"
__copyright__ = "Copyright 2019, Cameron Solutions"
__license__ = "ASF 2.0"
__version__ = "1.0.0"
__maintainer__ = "Michael Hay"
__status__ = "Prototype"
__id__ = "$Id$"

PATH = "./"
DB_CACHE = 'edgar_cache.db'
COMPANY = 1
CIK = 0
YEAR = 4
MONTH = 2
DAY = 3
ACCESSION = 5

# TODO make this a simple CLI allowing for searching based upon company name without needing SQL
# TODO surface the 10K HTML URLs
# TODO pull in PyEdgar to print out the header information
# TODO pull in PyEdgar to print out a company description from an 10K or similar
# TODO try a query to something other than a 10k

e_conn = sqlite3.connect(PATH + DB_CACHE)
ec = e_conn.cursor()


class FalshCmd(cmd.Cmd):

    prompt = 'falsh> '
    intro = 'A shell to retrieve firmalitics from various databases like SEC Edgar'
    ruler = '_'

    def do_cquery(self, query):
        for row in ec.execute("SELECT * FROM companies WHERE name LIKE '%" + query + "%'"):
            printer({
                'Company': row[COMPANY],
                'CIK': row[CIK],
                'Year': row[YEAR],
                'Month': row[MONTH],
                'Day': row[DAY],
                'Accession': row[ACCESSION]
            })


    def help_cquery(self):
        print("\ncquery [company name OR string]\nQuery either a company name or partial name.")

    def do_cikquery(self, query):
        for row in ec.execute("SELECT * FROM companies WHERE cik is '" + query + "'"):
            printer(row[1] + '(CIK: ' + str(row[0]) + "): " + row[5])

    def do_10kheaders(self, cik_accession):
        (cik, accession) = cik_accession.split(':')
        f = Filing (cik, accession)
        printer(f.headers)

    def do_get10kfile(self, query):
        pass

    def emptyline(self):
        pass

    def do_exit(self, line):
        return True

    def help_exit(self):
        print("\nExit the shell")


if __name__ == '__main__':
    FalshCmd().cmdloop()
    e_conn.close()



