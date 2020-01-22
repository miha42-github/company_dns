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


import cmd
from pprint import pprint as printer
from apputils import EdgarUtilities as EU

__author__ = "Michael Hay"
__copyright__ = "Copyright 2019, Cameron Solutions"
__license__ = "ASF 2.0"
__version__ = "1.0.0"
__maintainer__ = "Michael Hay"
__status__ = "Prototype"

class FalshCmd(cmd.Cmd):

    prompt = 'falsh> '
    intro = 'A shell to retrieve firmalitics from the SEC Edgar related to public companies'
    ruler = '_'

    def do_getfilings(self, query):
        e = EU()
        filings = e.get10kfilings(query)
        printer(filings)

    def help_getfilings(self):
        print("\ngetcompanies [company name OR string]\nQuery either a company name or partial name.")

    def do_getheaders(self, cik_accession):
        e = EU()
        headers = e.get10kheaders(cik_accession)
        printer(headers)

    def help_getheaders(self):
        print("\ngetheaders [cik:accession]\nRetrieve and print the headers for the document described by\n" +
              "CIK:Accession.")

    def do_get10kurl(self, l_url):
        e = EU()
        print(e.get10kurl(l_url))


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



