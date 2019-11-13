# Introduction to edgar_svc
To enable a more automated approach to gathering information about public companies,
a set of utilities (mkdbcache.py and falsh.py) and a RESTful service (edgar_scv.py)
have been created.  This initial focus is related to the [SEC's EDGAR repository](https://www.sec.gov/edgar/searchedgar/companysearch.html),
which keeps data on public companies who are listed on stock exchanges in the 
United states.  The intention of these utilities and the associated micro-service
is to enable other portions of Medium Roast to have ready access to public information
about firms in a more automated fashion.

# Key Dependencies
- [PyEdgar](https://github.com/gaulinmp/pyedgar) - used to interface with the SEC's EDGAR repository
- [SQLite](https://www.sqlite.org/index.html) - helps all utilities and the RESTful service quickly and expressively
respond to interactions with the other elements to find appropriate company data
- [Flask](https://www.palletsprojects.com/p/flask/) and associated utilities - used to realize the RESTful service
- [nginx](http://nginx.org) - enables hosting of the RESTful service

# Utilities
- mkdbcache.py - through PyEdgar interacts withe SEC EDGAR repository, and 
generates a SQLite database cache file which can be used by other utilities
- falsh.py - allows a command shell interaction with the SQLite database
cache file enabling from simple to expressive queries.
- cutils.py - a set of common helper functions and utilities used by other functions

# RESTful Service
- edgar_svc.py - implements a RESTful service with 3 API calls available to ensure that
an eventual end user can find information about a potential company they are interested in.

# Usage for mkdbcache.py
```
usage: mkdbcache.py [-h] [--cleanall] [--cleandb] [--cleancache] [--getmaster]
                    [--year Y] [--verbose {50,40,30,20,10}]

A utility to create a db cache for select SEC edgar data.

optional arguments:
  -h, --help            show this help message and exit
  --cleanall, -a        Clean up the cache files and db cache and exit.
  --cleandb, -d         Clean up the db cache only and exit.
  --cleancache, -c      Clean up the cache files only and exit.
  --getmaster, -g       Get the master.gz files only and exit.
  --year Y, -y Y        Define the year to start from, defaults to 2010.
  --verbose {50,40,30,20,10}, -v {50,40,30,20,10}
                        Set the logging verbosity.

```
# Example syntax and usage for falsh.py
```
falsh> help

Documented commands (type help <topic>):
________________________________________
exit  get10kurl  getfilings  getheaders  help

falsh> help getfilings

getcompanies [company name OR string]
Query either a company name or partial name.
falsh> help get10kurl

get10kurl [https://...html]
Retrieve and print the URL for the 10k filing taking in the
URL from the 10k index HTML file.
falsh> help getheaders

getheaders [cik:accession]
Retrieve and print the headers for the document described by
CIK:Accession.
falsh> 
```
Example 'getfilings' query and result for the company "google".
```
falsh> getfilings google
{1288776: {'10-K': [[2,
                     11,
                     2016,
                     '0001652044-16-000012',
                     'https://www.sec.gov/Archives/edgar/data/1288776/000165204416000012/',
                     'https://www.sec.gov/Archives/edgar/data/1288776/000165204416000012/0001652044-16-000012-index.html']],
           '10-K/A': [[3,
                       29,
                       2016,
                       '0001193125-16-520367',
                       'https://www.sec.gov/Archives/edgar/data/1288776/000119312516520367/',
                       'https://www.sec.gov/Archives/edgar/data/1288776/000119312516520367/0001193125-16-520367-index.html']],
           'name': 'GOOGLE INC.'}}
```
Example 'getheaders' query for the 2016 10-K filing.
```
falsh>  getheaders 1288776:0001652044-16-000012
{'<sec-document>0001652044-16-000012.txt': '20160211',
 '<sec-header>0001652044-16-000012.hdr.sgml': '20160211',
 'accession-number': '0001652044-16-000012',
 'business-phone': '650-253-0000',
 'central-index-key': '0001652044',
 'city': 'MOUNTAIN VIEW',
 'company-conformed-name': 'Alphabet Inc.',
 'conformed-period-of-report': '20151231',
 'conformed-submission-type': '10-K',
 'date-as-of-change': '20160211',
 'date-of-name-change': '20040428',
 'filed-as-of-date': '20160211',
 'filer': {'business-address': {'business-phone': '650-253-0000',
                                'city': 'MOUNTAIN VIEW',
                                'state': 'CA',
                                'street1': '1600 AMPHITHEATRE PARKWAY',
                                'zip': '94043'},
           'company-data': {'central-index-key': '0001652044',
                            'company-conformed-name': 'Alphabet Inc.',
                            'fiscal-year-end': '1231',
                            'irs-number': '611767919',
                            'standard-industrial-classification': 'SERVICES-COMPUTER '
                                                                  'PROGRAMMING, '
                                                                  'DATA '
                                                                  'PROCESSING, '
                                                                  'ETC. [7370]',
                            'state-of-incorporation': 'DE'},
           'filing-values': {'film-number': '161412149',
                             'form-type': '10-K',
                             'sec-act': '1934 Act',
                             'sec-file-number': '001-37580'},
           'mail-address': {'city': 'MOUNTAIN VIEW',
                            'state': 'CA',
                            'street1': '1600 AMPHITHEATRE PARKWAY',
                            'zip': '94043'}},
 'filer_0': {'business-address': {'business-phone': '650 253-0000',
                                  'city': 'MOUNTAIN VIEW',
                                  'state': 'CA',
                                  'street1': '1600 AMPHITHEATRE PARKWAY',
                                  'zip': '94043'},
             'company-data': {'central-index-key': '0001288776',
                              'company-conformed-name': 'GOOGLE INC.',
                              'fiscal-year-end': '1231',
                              'irs-number': '770493581',
                              'standard-industrial-classification': 'SERVICES-COMPUTER '
                                                                    'PROGRAMMING, '
                                                                    'DATA '
                                                                    'PROCESSING, '
                                                                    'ETC. '
                                                                    '[7370]',
                              'state-of-incorporation': 'DE'},
             'filing-values': {'film-number': '161412150',
                               'form-type': '10-K',
                               'sec-act': '1934 Act',
                               'sec-file-number': '001-36380'},
             'former-company': {'date-of-name-change': '20040428',
                                'former-conformed-name': 'Google Inc.'},
             'mail-address': {'city': 'MOUNTAIN VIEW',
                              'state': 'CA',
                              'street1': '1600 AMPHITHEATRE PARKWAY',
                              'zip': '94043'}},
 'film-number': '161412149',
 'fiscal-year-end': '1231',
 'flat': False,
 'form-type': '10-K',
 'former-conformed-name': 'Google Inc.',
 'irs-number': '611767919',
 'public-document-count': '119',
 'sec-act': '1934 Act',
 'sec-file-number': '001-37580',
 'standard-industrial-classification': 'SERVICES-COMPUTER PROGRAMMING, DATA '
                                       'PROCESSING, ETC. [7370]',
 'state': 'CA',
 'state-of-incorporation': 'DE',
 'street1': '1600 AMPHITHEATRE PARKWAY',
 'zip': '94043'}
```
Example response for 'get10kurl'.
```
falsh> get10kurl https://www.sec.gov/Archives/edgar/data/51143/000104746919000712/0001047469-19-000712-index.html
https://www.sec.gov/Archives/edgar/data/51143/000104746919000712/a2237254z10-k.htm
```