# Motivation for the company_dns
To enable a more automated approach to gathering information about companies `company_dns` was created.  This release enables the synthesis of data from the [SEC EDGAR repository](https://www.sec.gov/edgar/searchedgar/companysearch.html) and [Wikipedia](https://wikipedia.org).  A [Medium](https://medium.com) article entitled "[A case for API based open company firmographics](https://medium.com/@michaelhay_90395/a-case-for-api-based-open-company-firmographics-145e4baf121b)" is available discussing the process and motivation behind the creation of this service.

# Introducing V3.0.0
The V3.0.0 release of the `company_dns` is a significant update to the service.  The primary changes are:
1. Shift from Flask to Starlette with Uvicorn.
2. Automated monthly container builds, from the main branch of the repository, using GitHub Actions.
3. Simplification of all aspects of the service including code structure, shift towards simpler Docker, and a more streamlined service control script.
4. Vastly improved embedded help with a query console to test queries.
We were motivated to make these changes to the service making it easier to improve, maintain and use.


# Installation & Setup
The install and setup process is either for users or developers.  Instructions for both are provided below.

## For users via docker
New from `V3.0.0` are automated docker builds providing a fresh image on a monthly basis.  There are three reasons for this:

1. Gets the latest information from EDGAR such that when the service is queried the user can access the latest quarterly and yearly filings.
2. As the code progresses, and is checked into main, users will automatically get the latest improvements and fixes.
3. Creates images for both x86 and ARM architectures.

The image can be pulled using `docker pull ghcr.io/miha42-github/company_dns/company_dns:latest`.  With the image pulled you can run it using `docker run -m 1G -p 8000:8000 company_dns:latest` which will run the image in the foreground, and running the image in the background `docker run -d -m 1G -p 8000:8000 company_dns:latest`.  GitHub's container registry is used to store the images, and more information on this package can be found at [company_dns/company_dns](https://github.com/miha42-github/company_dns/pkgs/container/company_dns%2Fcompany_dns).

## For developers via GitHub with docker and without docker
Assuming you have setup access to GitHub and a Linux or MacOS system of some kind, you'll need to get the repository.

1. Create a directory that will contain the code: `mkdir ~/dev`
2. Enter the directory: `cd ~/dev/`
3. Clone the repository: `git clone git@github.com:miha42-github/company_dns.git`

### With docker
Since the docker build process takes care of data cache creation, Python requirements installation and other items getting company_dns running is relatively straight forward.  To simplify the process further the `svc_ctl.sh` script is provided.

#### Service Control Script
`svc_ctl.sh` automates build, run, and log observations for company_dns removing many manual steps.  To start the system follow these steps:
1. Assuming you've cloned the code into `~/dev/company_dns` run `cd ~/dev/company_dns`
2. `./svc_ctl.sh build` to build the image
3. `./svc_ctl.sh foreground` to run the image in the foreground or `svc_ctl.sh start` to run the image in the background
   
If the service is running in the background you can run `./svc_ctl.sh tail` to watch the image logs.  Finally, stopping the image when it is running the background can be achieved with `./svc_ctl.sh stop`.

##### Service control usage information
Usage for the service control script follows:
```
NAME:
    ./svc_ctl.sh <sub-command>

DESCRIPTION:
    Control functions to run the company_dns

COMMANDS:
    help start stop build foreground tail

    help - call up this help text
    start - start the service using docker-compose 
    stop - stop the docker service
    build - build the docker images for the server
    foreground - run the server in the foreground to watch for output
    tail - tail the logs for a server running in the background
```

### Without docker
Depending upon the intention for getting the code it could be running in a Python virtual environment or in a vanilla file system.  Regardless the steps below can be followed to get the service up and running.

#### Pre-execution
Before you get started it is important to install all prequisites and then create the cache database.

1. Enter the directory with the service bits (assuming you're using ~/dev): `cd ~/dev/company_dns/company_dns`
2. Install all prerequsites: `pip3 install -r ./requirements.txt`
3. Create the database cache `python3 ./makedb.py`

#### Execution
If everything above completed successfully then running company_dns can be performed via `python3 ./company_dns.py` this will run the service in the foreground.

## Verify that the service is working
Regardless of the approach taken to run the company_dns checking to see if it is operating is important.  A quick way to check on service availability when running on localhost is to follow this link: [http://localhost:8000/help](http://localhost:8000/help). If this is successful the embedded help will display (see screenshot below) describing available endpoints, examples with `curl`, and some helpful links to the company_dns GitHub repository.  Additionally, new in V3.0.0 is the query console which can be used to test key functions of the system.

### Screenshot of the embedded help

<img width="1242" alt="company_dns - embedded_help" src="https://github.com/miha42-github/company_dns/assets/10818650/1f789771-bb55-47da-b21b-cea421921090">

### Screenshot of the query console

<img width="1242" alt="company_dns - query_console" src="https://github.com/miha42-github/company_dns/assets/10818650/6f880d10-1143-4889-998f-9adae8d9717e">

# Checkout a live system
A live system is available for Mediuroast efforts and for anyone to try out, relevant links are below.
- Embedded help and query console - [https://company-dns.mediumroast.io/help](https://company-dns.mediumroast.io/help)
- Company search for IBM - [https://company-dns.mediumroast.io/V3.0/global/company/merged/firmographics/IBM](https://company-dns.mediumroast.io/V3.0/global/company/merged/firmographics/IBM)
- Standard industry code search for `Oil` - [https://www.mediumroast.io/company_dns/V3.0/na/sic/description/oil](https://www.mediumroast.io/company_dns/V2.0/sic/description/oil)

# How can I contribute?

## Bugs
If you encounter a problem with the company_dns please first review existing open [issues](https://github.com/miha42-github/company_dns/issues), and if you find a match then please add a comment with any detail you might deem relevant.  If you're unable to find an issue that matches the behavior you're seeing please open a new issue. 

## Improvements
We try to keep high level Todos and Improvements in a list contained in a section below, and as we begin to work on things we will create a corresponding issue, link to it, progress and close it.  However, if there is a change in design, major improvement, and so on something may fall off the list below.  If something isn't on the list then please create a new issue and we will evaluate.  We'll let you know if we pick up your request and progress to working on it.

### Future work/Todos
Here are the things that are likely to be worked but without any strict deadline:

1. Determine if feasible to talk to the companies house API for gathering data from the UK
    1. Initial feasibility has been checked, but the value of the data is still being evaluated
2. Research other pools of public data which can serve to enrich 
    1. There are additional data pools including NAICS and UK SIC codes which could be added. Additional Industry Code data sources by country are likely a first target to add. The deeper question is how to merge these data sources for a kind of universal classification.
3. Evaluate if financial data can be added from EDGAR, Wikipedia and Companies House
4. Provide instructions/details for running on a Pi or Arm based system
    1. Since one of the target docker images is for ARM, the next logical step is to provide instructions for running on a Pi.

### The Lagniappe 
Run on a RasberryPi: To be reauthored

# License
Since this code falls under a liberal Apache-V2 license it is provided as is, without warranty or guarantee of support.  Feel free to fork the code, but please provide attribution to the authors.

# Key Dependencies
- [PyEdgar](https://github.com/gaulinmp/pyedgar) - used to interface with the SEC's EDGAR repository
- [SQLite](https://www.sqlite.org/index.html) - helps all utilities and the RESTful service quickly and expressively respond to interactions with the other elements to find appropriate company data
- [Starlette](https://www.starlette.io) - used to create the RESTful service
- [Uvicorn](https://www.uvicorn.org) - used to run the RESTful service
- [GeoPy with ArcGIS](https://github.com/geopy/geopy) - Enables proper address formatting and reporting of lat-long pairs for companies
- [wptools](https://github.com/siznax/wptools/) - provides access to MediaWiki data for company search
