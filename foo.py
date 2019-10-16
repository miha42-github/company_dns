from typing import Dict, Any, Union

from pyedgar.utilities.indices import IndexMaker
from pyedgar.filing import Filing
from pyedgar.index import EDGARIndex
from pprint import pprint

import re

EDGARSERVER = "www.sec.gov"
EDGARARCHIVES = "Archives/edgar/data"
EDGARURI = "https://"


def my_idx(start_year):
    i = IndexMaker(use_tqdm=True)
    i.extract_indexes(start_year=2018)


def get_filing(my_cik, my_ascension):
    f = Filing()
    print(f.headers())


my_str = 'INTERNATIONAL BUSINESS MACHINE'
all = EDGARIndex()
all_10k = all['10-K']
all_10k.drop(['form', 'filedate'], axis=1)

foo = []

for key, value in all_10k['name'].str.contains(my_str).items():
    if value:
        foo.append(all_10k.loc[[key]].values.tolist())

companies: Dict[str, Union[Dict[Any, Any], Dict[str, Dict[Any, Any]]]] = dict()
to_skip = re.compile('company-conformed-name|state-of-incorporation|street1|zip|state|'
                     'standard-industrial-classification|form-type|fiscal-year-end|irs-number|filer|'
                     'city|business-phone|sec-act|sec-file-number|\<sec-document|\<sec-header')
to_mod = re.compile('accession-number')

for entry in foo:
    # print(entry)
    n = entry[0]
    cik = n[0]
    name = n[1]
    ascension = n[4]
    f = Filing(cik, ascension)
    # pprint(f.headers)
    my_cik = str(f.headers['central-index-key']).strip()
    my_report = str(f.headers['conformed-period-of-report']).strip()
    # print("---------- " + str(my_cik) + " -- " + str(my_report))
    if my_cik in companies:
        companies[my_cik].update({my_report: dict()})
    else:
        companies[my_cik] = dict()
        companies[my_cik] = {my_report: dict(),
                             'company_name': str(f.headers['company-conformed-name']).strip().lstrip("'"),
                             'country': 'United States of America',
                             'state': str(f.headers['state']).strip(),
                             'city': str(f.headers['city']).strip(),
                             'street': str(f.headers['street1']).strip(),
                             'zip_code': str(f.headers['zip']).strip(),
                             'business_phone': '+1' + str(f.headers['business-phone']).strip(),
                             'state_of_incorporation': str(f.headers['state-of-incorporation']).strip(),
                             'industry': str(f.headers['standard-industrial-classification']).strip(),
                             'form_type': str(f.headers['form-type']).strip(),
                             'fiscal_end': str(f.headers['fiscal-year-end']).strip(),
                             'irs_number': str(f.headers['irs-number']).strip(),
                             'sec_file_number': str(f.headers['sec-file-number']).strip(),
                             }

    for item in f.headers:
        if to_skip.match(item):
            continue
        elif to_mod.match(item):
            directory = my_cik + '/' + str(f.headers[item].replace('-', ''))
            full_extension = '-index.html'
            my_url = EDGARURI + EDGARSERVER + '/' + EDGARARCHIVES + '/' + directory + '/' + f.headers[item] + full_extension
            companies[my_cik][my_report].update({'url': my_url})
            root_url = EDGARURI + EDGARSERVER + '/' + EDGARARCHIVES + '/' + directory + '/'
            companies[my_cik][my_report].update({'directory_url': root_url})

        companies[my_cik][my_report].update({item: f.headers[item]})

pprint(companies)
