import sqlite3
from pprint import pprint as printer

# TODO make this a simple CLI allowing for searching based upon company name without needing SQL
# TODO implement an ability to download the file referenced in the entry
# TODO add the appropriate configuration data as a JSON string in the DB
# TODO when we're looking at downloading files from edgar create hashes and store the result in the DB for update track
# TODO turn this into an API service with flask or keep this separate?
# TODO download the file and parse the results into something that is readable and usable

conn = sqlite3.connect('edgar_idx.db')
c = conn.cursor()
for row in c.execute("SELECT * FROM companies WHERE name LIKE '%PET%'"):
    printer (row)

