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
from pprint import pprint as printer
from apputils import EdgarUtilities as EU

class FalshCmd(cmd.Cmd):
 
    prompt = 'edgar> '
    intro = 'A shell to retrieve company demographics from the SEC Edgar related to public companies'
    ruler = '_'

    def __init__(self):
        self.authors = ['Michael Hay', 'John Goodman']
        self.copyright = "Copyright 2020 and 2021 mediumroast.io. All rights reserved."
        self.locator = ArcGIS (timeout=2)

    def do_getall (self, query):
        e = EU()
        all_companies = e.getAll(query)
        printer (all_companies)

    def help_getall (self):
        print("\ngetall [company name OR string]\nQuery either a company name or partial name.")

    def emptyline(self):
        pass

    def do_exit(self, line):
        return True

    def help_exit(self):
        print("\nExit the shell")


if __name__ == '__main__':
    FalshCmd().cmdloop()



