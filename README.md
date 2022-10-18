# Introduction to the company_dns
To enable a more automated approach to gathering information about companies, a utility (dbcontrol.py) and a RESTful service (company_dns/app/main.py) have been created.  This release enables the sysnthesis of data from the [SEC EDGAR repository](https://www.sec.gov/edgar/searchedgar/companysearch.html) and [Wikipedia](https://wikipedia.org).

# License
Since this code falls under a liberal Apache-V2 license it is provided as is, without warranty or guarantee of support.  Feel free to fork the code, but please provide attribution to the authors.

# Key Dependencies
- [PyEdgar](https://github.com/gaulinmp/pyedgar) - used to interface with the SEC's EDGAR repository
- [SQLite](https://www.sqlite.org/index.html) - helps all utilities and the RESTful service quickly and expressively respond to interactions with the other elements to find appropriate company data
- [Flask](https://www.palletsprojects.com/p/flask/) and associated utilities - used to realize the RESTful service
- [nginx](http://nginx.org) - enables hosting of the RESTful service
- Docker & Docker Compose - Container and server framework
- [GeoPy with ArcGIS](https://github.com/geopy/geopy) - Enables proper address formatting and reporting of lat-long pairs for companies
- [wptools](https://github.com/siznax/wptools/) - provides access to MediaWiki data for company search

# Utilities
- dbcontrol.py - through PyEdgar interacts withe SEC EDGAR repository, and generates a SQLite database cache file which can be used by other utilities

# RESTful Service
- main.py - implements a RESTful service with 2 endpoints: `/V1/help` & `/V1/edgar/company/<string:query>`. In this case `<string:query>` is any string, properly URL encoded which matches a company the user is looking for.

# Usage for dbcontrol.py
```
usage: dbcontrol.py [-h] [--cleanall] [--cleandb] [--cleancache] [--getmaster]
                    [--year Y] [--verbose {50,40,30,20,10}]

A utility to create a db cache for select SEC edgar data.

optional arguments:
  -h, --help            show this help message and exit
  --cleanall, -a        Clean up the cache files and db cache and exit.
  --cleandb, -d         Clean up the db cache only and exit.
  --cleancache, -c      Clean up the cache files only and exit.
  --getmaster, -g       Get the master.gz files only and exit.
  --year Y, -y Y        Define the year to start from, defaults to 2018.
  --verbose {50,40,30,20,10}, -v {50,40,30,20,10}
                        Set the logging verbosity.

```

# Installation
The follwing basic steps are provided for the purposes of getting the tool running.
## Download the code
Assming you have setup access to GitHub, you'll need to clone the repository. Here we assume you're on a Linux box of some kind and will follow the steps below.

1. If you're performing development create a directory that will contain the code: `mkdir ~/dev`
2. Enter the directory: `cd ~/dev/`
3. Clone the repository: `git clone git@github.com:miha42-github/company_dns.git`

Once downloaded you should see the following directory structure:  
```
company_dns/
          |
          LICENSE
          docker-compose.yml
          README.md
          company_dns/
                    |
                    Dockerfile
                    requirements.txt
                    app/
                        |
                        main.py
                        dbcontrol.py
                        pyedgar.conf
                        lib/
                            |
                            edgar.py
                            firmographics.py
                            wikipedia.py
                        templates/
                                  |
                                  help.html
          nginx/
                |
                default.conf
```  
## Pre-execution
Before you get started it is important to install all prequisites and then create the cache database.

1. Enter the directory with the service bits (assuming you're using ~/dev): `cd ~/dev/company_dns/company_dns`
2. Install all prerequsites: `pip3 install -r ./requirements.txt`
3. Change the USER_AGENT setting in `~/dev/company_dns/company_dns/app/pyedgar.conf` to your own user agent definition.  If you don't the SEC downloads may fail.
3. Create the cache database: `cd app;./dbcontrol.py`

The utility (dbcontrol.py) will, download EDGAR data, process it, and then create a  database which both modes of execution will utilize.

## Mode 1 - Run in the foreground using python
Running in this mode is especially handy for development and debugging.  This will run the Flask based service in the foreground using the embedded HTTP server.  This approach is not recommended for production.

1. Enter the app/ directory: `cd ~/dev/company_dns/company_dns/app`
2. Run the service in the foreground: `python3 ./main.py`

At this point the service will start listening on TCP/6868. The output from running in the foreground will look something like the following:

```
mediumroast@coffee:~/company_dns/company_dns/app$ python3 ./main.py 
 * Serving Flask app 'main'
 * Debug mode: on
WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:6868
 * Running on http://192.168.10.102:6868
Press CTRL+C to quit
 * Restarting with stat
 * Debugger is active!
 * Debugger PIN: 483-527-614
```

To stop the service from running in the foreground just press CTRL-C.

## Mode 2 - Execute as a microservice
We use docker-compose to create a run the company_dns as a service listening on TCP/6868.  The following steps should help you run the service in that manner:

1. Enter the top level directory for the service: `cd ~/dev/company_dns`
2. Build the image: `docker-compose build`
3. Run the service in the background: `docker-compose up -d`

If you need to stop the service you should run `docker-compose stop`.  This will halt the service, but keep all of the images intact.

## Verify that the service is working
Regardless of the approach you've taken to run the company_dns checking to see if it is operating is important.  Therefore you can point a browser to the server running the service.  If you're running on localhost then the following link should work [http://localhost:6868/V2.0/help](http://localhost:6868/V2.0/help) however if you're on another server then you'll need to change the server name to the one you're using.  If this is successful you will be able to see the embedded help which describes the available set of
endpoints, and provides and example query to the service.  A screenshot of the help screen can be found below.

![Screen Shot 2022-10-16 at 8 18 57 PM](https://user-images.githubusercontent.com/10818650/196084425-6fd9d724-1f59-4eed-9548-c553168bf387.png)

# How can I contribute?

## Bugs
If you encounter a problem with the company_dns please first review existing open [issues](https://github.com/miha42-github/company_dns/issues), and if you find a match then please add a comment with any detail you might deem relevant.  If you're unable to find an issue that matches the behavior you're seeing please open a new issue. 

## Improvements
We try to keep high level Todos and Improvements in a list contained in a section below, and as we begin to work on things we will create a corresponding issue, link to it, progress and close it.  However, if there is a change in design, major improvement, and so on something may fall off the list below.  If something isn't on the list then please create a new issue and we will evaluate.  We'll let you know if we pick up your request and progress to working on it.

### Future work/Todos
Here are the things that are likely to be worked but without any strict deadline:
1. Create a simple wrapping script to operationalize service behaviors, [see issue #4](https://github.com/miha42-github/company_dns/issues/4)
2. Incrementally refactor the repository and the code
3. Enable TLS on nginx or provide instructions to do so, [see issue #10](https://github.com/miha42-github/company_dns/issues/10)
4. Determine if feasible to talk to the companies house API for gathering data from the UK
5. Research other pools of public data which can serve to enrich 
6. Evaluate if financial data can be added from EDGAR, Wikipedia and Companies House
7. ~~Clean up stale EDGAR URLs~~
8. Provide instructions/details for running on a Pi or Arm based system, see Lagniappe below
9. ~~Update README.md with the appropriate language, etc.~~, [see issue #9](https://github.com/miha42-github/company_dns/issues/9)
10. ~~Add additional URLs for news, stock, patents, etc. to the merged response~~, [see issue #11](https://github.com/miha42-github/company_dns/issues/11)
11. ~~Add ticker information from Wikipedia into the response~~, [see issue #7](https://github.com/miha42-github/company_dns/issues/7)

### The Lagniappe 
If you would like to run this on a RasberryPi I'll be adding a couple of configuration files and appropriate instructions later, but until then I suggest you check out [Matt's](https://www.raspberrypi-spy.co.uk/author/matt/) guide to [getting Nginx, UWSGI and Flask running on a Pi](https://www.raspberrypi-spy.co.uk/2018/12/running-flask-under-nginx-raspberry-pi/).  At some point if someone would like to create a docker image for these elements running on the Pi that would be great.