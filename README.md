# Introduction to the company_dns
To enable a more automated approach to gathering information about companies `company_dns` was created.  This release enables the synthesis of data from the [SEC EDGAR repository](https://www.sec.gov/edgar/searchedgar/companysearch.html) and [Wikipedia](https://wikipedia.org).  A [Medium](https://medium.com) article entitled "[A case for API based open company firmographics](https://medium.com/@michaelhay_90395/a-case-for-api-based-open-company-firmographics-145e4baf121b)" is available discussing the process and motivation behind the creation of this service.

# Installation & Setup
The follwing basic steps are provided for the purposes of getting the tool running.
## Get the code
Assming you have setup access to GitHub, you'll need to clone the repository. Here we assume you're on a Linux box of some kind and will follow the steps below.

1. If you're performing development create a directory that will contain the code: `mkdir ~/dev`
2. Enter the directory: `cd ~/dev/`
3. Clone the repository: `git clone git@github.com:miha42-github/company_dns.git`

## Pre-execution
Before you get started it is important to install all prequisites and then create the cache database.

1. Enter the directory with the service bits (assuming you're using ~/dev): `cd ~/dev/company_dns/company_dns`
2. Install all prerequsites: `pip3 install -r ./requirements.txt`
3. Change the `USER_AGENT` setting in `~/dev/company_dns/company_dns/app/pyedgar.conf` to your own user agent definition.  If you don't the SEC downloads will fail.

The utility `dbcontrol.py` will download EDGAR data, process it, and then create a database for the `company_dns`.  Note that you do not need to directly run this utility as the service control script will handle it for you.  For more information on the database control utility please checkout the [readme](company_dns/app/README.md) for it.

## Service Control Script
A service control script, `svc_ctl.sh` is provided to wrap build, run, and log tailing functions as of V2.3.0.  Compared to past versions this script significantly simplifies working with the `company_dns` removing many manual steps to getting it running. As a result there is only one step needed to get the service running `cd ~dev/company_dns;svc_ctl.sh up`.  This script will:
1. Clean up any past instances of the cache database
2. Create the cache database by running `dbcontrol.py`
3. Build the docker image that includes Python, Flask and Nginix
4. Start the service in a container detached from the console
Should you need to debug the service the `svc_ctl.sh` script contains a sub-command to tail the log file of the correct container.  By running `svc_ctl.sh tail` the user can see what's happening inside the container as work is processed.
### Service control usage
Usage for the service control script follows:
```
NAME:
    ./svc_ctl.sh <sub-command>

DESCRIPTION:
    Control functions to run the company_dns

COMMANDS:
    help up down start stop create_db build delete_db foreground tail

    help - call up this help text
    up - bring up the service including building and pulling the docker image
    down - bring down the service and remove the docker image
    start - start the service using docker-compose 
    stop - stop the docker service
    create_db - create a new database cache for the company_dns
    delete_db - delete the database cache for the company_dns
    build - build the docker images for the server
    foreground - run the server in the foreground to watch for output
    tail - tail the logs for a server running in the background
```

## Verify that the service is working
Regardless of the approach you've taken to run the `company_dns` checking to see if it is operating is important.  Therefore you can point a browser to the server running the service.  If you're running on localhost then the following link should work [http://localhost:6868/V2.0/help](http://localhost:6868/V2.0/help) however if you're on another server then you'll need to change the server name to the one you're using.  If this is successful you will be able to see the embedded help which describes the available set of endpoints, and provides and example query to the service.  A screenshot of the help screen can be found below.

![Screen Shot 2022-10-16 at 8 18 57 PM](https://user-images.githubusercontent.com/10818650/196084425-6fd9d724-1f59-4eed-9548-c553168bf387.png)

## Checkout a live system
We're hosting an instance of the `company_dns` on our website for our usage and your exploration.  Below are several example queries and access to embedded help to get you a better view of the system.
- Embedded help - [https://www.mediumroast.io/company_dns/help](https://www.mediumroast.io/company_dns/help){:target="_blank"}
- Company search for IBM - [https://www.mediumroast.io/company_dns/V2.0/company/merged/firmographics/IBM](https://www.mediumroast.io/company_dns/V2.0/company/merged/firmographics/IBM){:target="_blank"}
- Standard industry code search for `Oil` - [https://www.mediumroast.io/company_dns/V2.0/sic/description/oil](https://www.mediumroast.io/company_dns/V2.0/sic/description/oil){:target="_blank"}

# How can I contribute?

## Bugs
If you encounter a problem with the company_dns please first review existing open [issues](https://github.com/miha42-github/company_dns/issues), and if you find a match then please add a comment with any detail you might deem relevant.  If you're unable to find an issue that matches the behavior you're seeing please open a new issue. 

## Improvements
We try to keep high level Todos and Improvements in a list contained in a section below, and as we begin to work on things we will create a corresponding issue, link to it, progress and close it.  However, if there is a change in design, major improvement, and so on something may fall off the list below.  If something isn't on the list then please create a new issue and we will evaluate.  We'll let you know if we pick up your request and progress to working on it.

### Future work/Todos
Here are the things that are likely to be worked but without any strict deadline:
1. ~~Create a simple wrapping script to operationalize service behaviors~~ [see issue #4](https://github.com/miha42-github/company_dns/issues/4)
2. ~~Incrementally refactor the repository and the code~~
3. ~~Enable TLS on nginx or provide instructions to do so~~, [see issue #10](https://github.com/miha42-github/company_dns/issues/10)
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
