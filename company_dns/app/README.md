# Database Control Utility
A utility that creates a database cache combining data from the SEC EDGAR repository and US Standard Industry Code (SIC) data sourced from OSHA. The PyEdgar Python module enables connectivity to EDGAR and facilitiates the downloading of appropriate data for usage in the database cache.

## Usage for dbcontrol.py
```
usage: dbcontrol.py [-h] [--force] [--cleanall] [--cleandb] [--cleancache] [--getmaster] [--year Y] [--path P] [--config P] [--verbose {50,40,30,20,10}]

A utility to create a db cache for select SEC edgar data.

options:
  -h, --help            show this help message and exit
  --force, -f           Force the creation of the db cache
  --cleanall, -a        Clean up the cache files and db cache and exit.
  --cleandb, -d         Clean up the db cache only and exit.
  --cleancache, -c      Clean up the cache files only and exit.
  --getmaster, -g       Get the master.gz files only and exit.
  --year Y, -y Y        Define the year to start from, defaults to three years prior to the current year.
  --path P, -p P        Set up the base path.
  --config P            Define the location of the configuration file
  --verbose {50,40,30,20,10}, -v {50,40,30,20,10}
                        Set the logging verbosity.

```