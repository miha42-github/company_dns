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

__author__ = "Michael Hay"
__copyright__ = "Copyright 2019, Cameron Solutions"
__license__ = "ASF 2.0"
__version__ = "1.0.0"
__maintainer__ = "Michael Hay"
__status__ = "Prototype"
__id__ = "$Id$"

EDGARDB = 'edgar_idx.db'

# TODO make this a simple CLI allowing for searching based upon company name without needing SQL
# TODO implement an ability to download the file referenced in the entry
# TODO add the appropriate configuration data as a JSON string in the DB
# TODO when we're looking at downloading files from edgar create hashes and store the result in the DB for update track
# TODO turn this into an API service with flask or keep this separate?
# TODO download the file and parse the results into something that is readable and usable

e_conn = sqlite3.connect(EDGARDB)
ec = e_conn.cursor()


class FalshCmd(cmd.Cmd):

    prompt = 'falsh>'
    intro = 'A shell to retrieve firmalitics from various databases like SEC Edgar'
    ruler = '_'

    def do_cquery(self, query):
        for row in ec.execute("SELECT * FROM companies WHERE name LIKE '%" + query + "%'"):
            printer(row[1] + ' has CIK: ' + str(row[0]))

    def help_cquery(self):
        print("\ncquery [company name OR string]\nQuery either a company name or partial name.")

    def do_cikquery(self, query):
        for row in ec.execute("SELECT * FROM companies WHERE cik is '" + query + "'"):
            printer(row[1] + '(CIK: ' + str(row[0]) + "): "+ row[6])

    def emptyline(self):
        pass

    def do_exit(self, line):
        return True

    def help_exit(self):
        print("\nExit the shell")


if __name__ == '__main__':
    FalshCmd().cmdloop()
    e_conn.close()



