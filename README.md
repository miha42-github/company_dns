# Introduction to edgar_svc
To enable a more automated approach to gathering information about public companies, a set of utilities (mkdbcache.py and dbshell.py) and a RESTful service (edgar_svc.py) have been created.  This initial focus is related to the [SEC's EDGAR repository](https://www.sec.gov/edgar/searchedgar/companysearch.html), which keeps data on public companies who are listed on stock exchanges in the United states.  Over time additions, including other open repositories like the UK, will be considered.  While there are other EDGAR API overlays available, at a cost, for the purposes of the authors had in mind an open source alternative was preferred.

# Motivation
The intention of these utilities, and the associated RESTful service, is to enable open access, Apache Software Foundation V2 License, to open data maintained by the SEC.   We hope that you will review and potentially work with us a we improve this tool set over time.  There are certainly a few things we'll be working on soonish as we pull this tool into our developing application.  
## Design Principals
As the tool was being built the following thinking was progressed.  The authors had a very specific purpose in mind when creating the tool and these choices reflect that thinking.
- This tool is meant to be a very thin overlay on top of the EDGAR data and is intent upon providing a kind of naming service for publicly listed companies in the US.  Therefore, the system can be completely blown away and quickly regenerated.  
- As of now there isn't any authentication either HTTP, JWT or API-key based again there's nothing proprietary about the dataset or the service itself and the system can be completely regenerated in say 15-20 minutes depending on how much EDGAR data you want to represent.
- Relative data completeness and associated functionaliites were favored over performance.  The implication is that less data could boost performance, and certainly if more data was put into the cache or a full fledged DB was used with more local data the performance could be better. (More on this in Future Work below.)
- The emphasis of the present tool is on 10K and related reports for the listing of reports in the response.  While the DB cache includes other SEC filing metadata, like 8K, the wrapping API presently excludes it.

# License
Since this code falls under a liberal ASF 2 license it is provided as is, without warranty or guarantee of support.  Feel free to fork the code, but please provide attribution to the authors.

# Notice
A significant update for the code has been pursued and completed making it ready for usage beyond the maintainers.  We will likely be continuing to progress a bit over time including taking care of some of the items listed below in Future Work.  If we're in the mood for an adventure we might look at the UK and apparently the Japanese government might have some data/structure similar to the SEC's EDGAR. 

# Future work
Here are the things that are likelly to be worked but without any strict deadline:
1. Create some super simple wrapping scripts to operationalize the service
2. Have fun refactoring the code, and potentially invite other developers in to particpate
3. Consider a new endpoints that purely pull from the DB Cache.  This would likely result in performance speedups as no external services like GeoPy would be called.

# Key Dependencies
- [PyEdgar](https://github.com/gaulinmp/pyedgar) - used to interface with the SEC's EDGAR repository
- [SQLite](https://www.sqlite.org/index.html) - helps all utilities and the RESTful service quickly and expressively
respond to interactions with the other elements to find appropriate company data
- [Flask](https://www.palletsprojects.com/p/flask/) and associated utilities - used to realize the RESTful service
- [nginx](http://nginx.org) - enables hosting of the RESTful service
- Docker & Docker Compose - Container and server framework
- GeoPy with ArcGIS - Enables proper address formatting and reporting of lat-long pairs
- BeautifulSoup - Used for light parsing of EDGAR data served by the SEC

# Utilities
- mkdbcache.py - through PyEdgar interacts withe SEC EDGAR repository, and 
generates a SQLite database cache file which can be used by other utilities
- dbshell.py - allows a command shell interaction with the SQLite database
cache file enabling from simple to expressive queries.
- apputils.py - a set of common helper functions and utilities used by other functions

# RESTful Service
- edgar_svc.py - implements a RESTful service with 2 endpoints: `/V1/help` & `/V1/edgar/company/<string:query>`. In this case `<string:query>` is any string, properly URL encoded which matches a company the user is looking for.

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
# Example syntax and usage for dbshell.py
```
A shell to retrieve company demographics from the SEC Edgar related to public companies
edgar> help

Documented commands (type help <topic>):
________________________________________
exit  getall  help

edgar> 
```
# Example 'getall' query and result for the company "google".
```
edgar> getall alphabet
{'companies': {'Alphabet Inc.': {'CIK': '1652044',
                                 'antitrustAct': '34',
                                 'companyFilings': 'https://www.sec.gov/cgi-bin/browse-edgar?CIK=1652044&action=getcompany',
                                 'companyName': 'Alphabet Inc.',
                                 'fiscalYearEnd': '1231',
                                 'forms': {'0001193125-19-028757': {'day': 6,
                                                                    'filingIndex': 'https://www.sec.gov/Archives/edgar/data/1652044/000119312519028757/0001193125-19-028757-index.html',
                                                                    'formType': '10-K/A',
                                                                    'month': 2,
                                                                    'url': '',
                                                                    'year': 2019},
                                           '0001652044-18-000007': {'day': 6,
                                                                    'filingIndex': 'https://www.sec.gov/Archives/edgar/data/1652044/000165204418000007/0001652044-18-000007-index.html',
                                                                    'formType': '10-K',
                                                                    'month': 2,
                                                                    'url': '',
                                                                    'year': 2018},
                                           '0001652044-19-000004': {'day': 5,
                                                                    'filingIndex': 'https://www.sec.gov/Archives/edgar/data/1652044/000165204419000004/0001652044-19-000004-index.html',
                                                                    'formType': '10-K',
                                                                    'month': 2,
                                                                    'url': 'https://www.sec.gov/Archives/edgar/data/1652044/000165204419000004/goog10-kq42018.htm',
                                                                    'year': 2019},
                                           '0001652044-20-000008': {'day': 4,
                                                                    'filingIndex': 'https://www.sec.gov/Archives/edgar/data/1652044/000165204420000008/0001652044-20-000008-index.html',
                                                                    'formType': '10-K',
                                                                    'month': 2,
                                                                    'url': 'https://www.sec.gov/ix?doc=/Archives/edgar/data/1652044/000165204420000008/goog10-k2019.htm',
                                                                    'year': 2020},
                                           '0001652044-21-000010': {'day': 3,
                                                                    'filingIndex': 'https://www.sec.gov/Archives/edgar/data/1652044/000165204421000010/0001652044-21-000010-index.html',
                                                                    'formType': '10-K',
                                                                    'month': 2,
                                                                    'url': 'https://www.sec.gov/ix?doc=/Archives/edgar/data/1652044/000165204421000010/goog-20201231.htm',
                                                                    'year': 2021}},
                                 'irsNumber': '611767919',
                                 'lattitude': 37.42239799696132,
                                 'longAddress': '1600 Amphitheatre Pkwy, '
                                                'Mountain View, California, '
                                                '94043',
                                 'longitude': -122.08421196885604,
                                 'phone': '650-253-0000',
                                 'standardIndustryCode': '7370 '
                                                         'Services-Computer '
                                                         'Programming, Data '
                                                         'Processing, Etc., '
                                                         'Office of Technology',
                                 'stateOfIncorporation.': 'DE'}},
 'totalCompanies': 1}
edgar> 
```
# Installation
The follwing basic steps are provided for the purposes of getting the tool running.  There are two basic paths:
1. Run as a tool using the dbshell and the SQLite DB built by dbcontrol
2. Operate this as a RESTful service called edgar_svc which will front end the SQLite DB
## Download the code
Pull or clone the repo using your GitHub account or by other means.  We'll not repeat the steps needed to setup GitHub connectivity, but you'll need to do all of that work and then pull the code.  Once downloaded you should see the following directory structure:
'''
edgar_svc/
          |
          LICENSE
          docker-compose.yml
          README.md
          edgar_svc/
                    |
                    Dockerfile
                    requirements.txt
                    app/
                        |
                        app_edgar.py
                        apputils.py
                        dbcontrol.py
                        dbshell.py
                        pyedgar.conf
                        uwsgi.ini
          nginx/
                |
                default.conf
'''
## Pre-execution
Enter into `edgar_svc/edgar_svc/app` and execute dbshell.py.  This has the effect of creating the SQLite DB cache with a default start data for the cache of 2018.  The utility will download EDGAR data, process it, and then create a predefined DB which both modes of execution will leverage.
## Mode 1 - dbshell
At this point when the `edgar_svc/edgar_svc/app/edgar_cache.db` has been created all you will need to do is run `edgar_svc/edgar_svc/app/dbshell.py`.  This will start the shell and allow you to interact with the cache with a single command `getall`.
## Mode 2 - app_edgar
From `edgar_svc` run `docker-compose build` which will cause the image to be built.  Once the build successfull completes run `docker-compose up` which will start the service running on port TCP/4200. To test the service you will need some kind of a RESTful client generally the format of the query should be: `http://host:4200/V1/company/<string:query>`.  The query can be any properly encoded string which correlates to the company you're looking to find.  An example output from an in development application that is being worked can be found below.  

![RESTful call to http://host:4200/V1/company/oil](https://github.com/miha42-github/edgar_svc/blob/master/images/restful_example.png)
