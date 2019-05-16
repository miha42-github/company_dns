import re
import sqlite3
import http.client
import html.parser

# TODO change the name of the file and create a package
# TODO create an option to run this like a CLI as well as a package
# TODO consider the right security context including permissions on the file
# TODO consider how to handle and catch various error conditions
# TODO consider logging
# TODO capture statistics about the number of entries for logging, debugging, etc.
# TODO consider how to not create the DB if it exists, or be clean about things like delete and then create
# TODO test substrings to create smaller db files
# TODO Should we think about a housekeeping DB table describing the last time things were loaded
# TODO should we consider a housekeeping DB table that has other statistics, etc.

EDGARSERVER = "www.sec.gov"
EDGARPATH = "/Archives/edgar/full-index/"
FILETYPE = "master.gz"
FILENAME = "master"
FILEEXT = ".gz"


def get_masters(years, quarters=[1, 2, 3, 4]):
    session = http.client.HTTPSConnection(EDGARSERVER)
    idxs = []
    for year in years:
        for quarter in quarters:
            # TODO Add try statement to account for failed connections where directories don't exist
            session.request("GET", EDGARPATH + '/' + str(year) + '/QTR' + str(quarter) + '/' + FILETYPE)
            resp = session.getresponse()
            print(resp.status, resp.reason)
            if resp.status is 200: # If the directory exists we'll get a 200 status otherwise we need to continue
                fil_name = FILENAME + '-' + str(year) + '-' + 'QTR' + str(quarter) + FILEEXT
                dat = resp.read()
                fil = open(fil_name, 'ab')
                fil.write(dat)
                fil.close()
                idxs.append(fil_name)
            else:
                continue
    session.close()
    return idxs


def build_idx(file_name, company_name=None, report_type="10-K"):
    """

    :param file_name:
    :param company_name:
    :param report_type:
    """
    global entry_dict
    global entry_array
    header_re = re.compile('^\w+.*:', re.IGNORECASE)  # Detect the headers for the idx
    ignore_re = re.compile('^-.*$')  # Skip the separator which is '----'
    skip_re = re.compile('^\S+\|')  # Skip an entry if it has a | symbol
    idx = {}
    raw_dict = []
    raw_array = []
    for line in file_name.readlines():
        line = line.rstrip()
        line = line.strip()
        if line:
            # Used to generate the header of the file specific index
            if header_re.match(line) and not skip_re.match(line):
                (key, value) = line.split(':', 1)
                idx[key] = value
                continue
            elif ignore_re.match(line):
                continue
            (cik, company, form, date, fil) = line.split('|')
            if form == report_type:  # Filter in only the report types we want to see, default is 10-k only
                if company_name is None:
                    entry_dict = {
                        'CIK': cik,
                        'Company Name': company,
                        'Form Type': form,
                        'Date Filed': date,
                        'File Name': fil
                    }
                    raw_array.append((cik, company, form, date, fil))
                    raw_dict.append(entry_dict)
                elif company_name.lower() in company.lower():
                    entry_dict = {
                        'CIK': cik,
                        'Company Name': company,
                        'Form Type': form,
                        'Date Filed': date,
                        'File Name': fil
                    }
                    raw_dict.append(entry_dict)
                    raw_array.append((cik, company, form, date, fil))
            else:
                continue
        else:
            continue

    idx['payload_dict'] = raw_dict
    idx['payload_array'] = raw_array
    return idx


def create_db(idx, db_name="edgar_idx"):
    """

    :param db_name:
    :param idx:
    """
    conn = sqlite3.connect(db_name + '.db')
    c = conn.cursor()
    c.execute('CREATE TABLE companies (cik int, name text, form text, date text, file text)')
    c.executemany('INSERT INTO companies VALUES (?,?,?,?,?)', idx['payload_array'])
    conn.commit()
    conn.close()


# f1 = open("master.idx")
# index = build_idx(f1)
# f1.close()
# create_db(index)
y = [2019, 2018]
indexes = get_masters([2018, 2019])
