#!/usr/bin/env python3

"""
Copyright 2021 mediumroast.io.  All rights reserved.
Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
in compliance with the License. You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License
is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied. See the License for the specific language governing permissions and limitations under
the License.
"""


import cmd
import lib.edgar as edgar
from pprint import pprint as printer
# from .lib import edgar
# from .lib import firmographics
# from .lib import wikipedia

class FalshCmd(cmd.Cmd):
 
    prompt = 'company_dns> '
    intro = 'A shell to retrieve company demographics from several source repositories including SEC EDGAR and Wikipedia'
    ruler = '_'

    def __init__(self):
        self.controller = edgar.EdgarQueries()
        super(FalshCmd, self).__init__()

    def do_getall (self, query):
        e = edgar.EdgarQueries()
        all_companies = e.get_all_details(query)
        printer (all_companies)

    def help_getall (self):
        print("\ngetall [company name OR string]\nQuery either a company name or partial name, \n and return full details.")

    def do_getsummary (self, query):
        all_companies = self.controller.get_all_details(query, firmographics=False)
        printer (all_companies)

    def help_getsummary (self):
        print("\ngetsummary [company name OR string]\nQuery either a company name or partial name, \n and return a summary.")

    def do_getfirmographics (self, cik):
        all_companies = self.controller.get_firmographics(cik)
        printer (all_companies)

    def help_getfirmographics (self):
        print("\ngetdetails [company cik]\nQuery a company's CIK, \n and return demographic details about the company.")

    def do_getciks (self, query):
        all_companies = self.controller.get_all_ciks(query)
        printer (all_companies)

    def help_getciks(self):
        print("\ngetciks [company name OR string]\nQuery either a company name or partial name, \n and return a list of CIKs.")
    
    def emptyline(self):
        pass

    def do_exit(self, line):
        return True

    def help_exit(self):
        print("\nExit the shell")


if __name__ == '__main__':
    FalshCmd().cmdloop()



