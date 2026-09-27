# Motivation for the company_dns
To enable a more automated approach to gathering information about companies `company_dns` was created.  This release enables the synthesis of data from the [SEC EDGAR repository](https://www.sec.gov/edgar/searchedgar/companysearch.html) and [Wikipedia](https://wikipedia.org).  A [Medium](https://medium.com) article entitled "[A case for API based open company firmographics](https://medium.com/@michaelhay_90395/a-case-for-api-based-open-company-firmographics-145e4baf121b)" is available discussing the process and motivation behind the creation of this service.

## Web Application Documentation

The embedded web interface is a modern single-page application for exploring SEC EDGAR filings and industry classifications. For detailed documentation on features, architecture, and usage, see [html/README.md](html/README.md).

# Changes

## Introducing V3.3.0
The V3.3.0 release is a substantial performance pass across the whole service, covering the `companies` DB cache, request concurrency, replica capacity, comparison tooling, EDGAR connection reuse, and — the largest single win — a rewritten Wikipedia backend. See [docs/plans/performance-improvements.md](docs/plans/performance-improvements.md) for the full investigation, findings, and measured before/after numbers behind each item below.

1. **`companies` DB full-table-scan fix**: filters to `10-%` filing forms at ingest time instead of querying a ~2M-row unfiltered table, fixing a hidden bottleneck behind `edgar_ciks`/`edgar_detail` that had nothing to do with live SEC calls.
2. **Blocking I/O moved off the event loop**: handler objects are now constructed fresh per request (fixing a latent shared-singleton correctness risk) and blocking query methods run via `run_in_threadpool`, so requests actually execute concurrently instead of serializing on a single event loop.
3. **Replica count bumped to 4** (from 2), multiplying the throughput gained from item 2 — the service now handles concurrency=16 cleanly where it previously crashed at that level on 2 replicas.
4. **Before/after comparison tooling** (`perf_tests/baseline.py`, `perf_tests/compare.py`): measures sequential and concurrent latency against the live deployment and flags regressions/improvements, so every change above was verified with real numbers rather than assumed.
5. **HTTP connection reuse to SEC EDGAR**: a shared `requests.Session()` instead of a new connection per call.
6. **Wikipedia backend rewritten** (`lib/wikipedia_v2.py`): replaces `wptools` with narrowed, direct MediaWiki/Wikidata HTTP requests (no more fetching entire parse trees or the full multi-hop wikidata-label cascade `wptools` triggered internally), plus a real, ToS-compliant User-Agent and 429/503 retry handling `wptools` never had. Validated against production with `perf_tests/shadow_compare.py` over multiple days before cutover. Now the default backend for the `wikipedia`/`merged` endpoints — **median latency down 80%** for both (`wikipedia_firmographics`: 3851ms → 773ms; `merged_firmographics`: 6095ms → 1199ms). The old `wptools`-based backend is still reachable at `/V3.0/global/company/wikipedia/v1/firmographics/{company_name}` and `/V3.0/global/company/merged/v1/firmographics/{company_name}` for reference/rollback.

### Previous Releases
For release notes prior to V3.3.0 (including V3.2.0, V3.1.0, and V3.0.0), see the consolidated changelog: [CHANGELOG.md](CHANGELOG.md).

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
`svc_ctl.sh` automates build/run/log tasks for company_dns. Common workflows:

1. From `~/dev/company_dns`: `./svc_ctl.sh build` then `./svc_ctl.sh start` (background) or `./svc_ctl.sh foreground` (interactive).
2. Watch logs: `./svc_ctl.sh tail`.
3. Stop or kill: `./svc_ctl.sh stop` (graceful) or `./svc_ctl.sh kill` (forceful).
4. Rebuild and restart: `./svc_ctl.sh rebuild`.
5. Check status or dependencies: `./svc_ctl.sh status` or `./svc_ctl.sh check-deps`.
6. Cleanup stopped containers/images: `./svc_ctl.sh cleanup`.

##### Service control usage information
```
NAME:
    ./svc_ctl.sh <sub-command>

COMMANDS:
    help         - Display help
    check-deps   - Validate docker and required files
    start        - Start the service in the background
    stop         - Stop the running container gracefully
    kill         - Forcefully stop the running container
    build        - Build the Docker image
    rebuild      - Rebuild image and restart the service
    foreground   - Run the service in the foreground
    tail         - View logs of the running container
    status       - Check container status and port
    cleanup      - Remove stopped containers and dangling images
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
Regardless of the approach taken to run the company_dns checking to see if it is operating is important.  A quick way to check on service availability when running on localhost is to follow this link: [http://localhost:8000/](http://localhost:8000/). If this is successful the embedded web interface will display (see screenshot below) describing core capabilities and function, examples with `curl`, and some helpful links to the company_dns GitHub repository.

# Checkout a live system
A live system is available for Mediuroast efforts and for anyone to try out, relevant links are below.
- Embedded background - [https://company-dns.mediumroast.io/](https://company-dns.mediumroast.io/)
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
2. Evaluate if financial data can be added from EDGAR, Wikipedia and Companies House
4. Provide instructions/details for running on a Pi or Arm based system
    1. Since one of the target docker images is for ARM, the next logical step is to provide instructions for running on a Pi.

# License
Since this code falls under a liberal Apache-V2 license it is provided as is, without warranty or guarantee of support.  Feel free to fork the code, but please provide attribution to the authors.

# Key Dependencies
- [PyEdgar](https://github.com/gaulinmp/pyedgar) - used to interface with the SEC's EDGAR repository
- [SQLite](https://www.sqlite.org/index.html) - helps all utilities and the RESTful service quickly and expressively respond to interactions with the other elements to find appropriate company data
- [FastAPI](https://fastapi.tiangolo.com) - used to create the RESTful service
- [Uvicorn](https://www.uvicorn.org) - used to run the RESTful service
- [GeoPy with ArcGIS](https://github.com/geopy/geopy) - Enables proper address formatting and reporting of lat-long pairs for companies
- `requests` - direct MediaWiki/Wikidata HTTP calls power the default Wikipedia backend (`lib/wikipedia_v2.py`) as of V3.3.0
- [wptools](https://github.com/siznax/wptools/) - powers the legacy `/v1/` Wikipedia backend only, kept for reference/rollback; no longer used by the default endpoints


