import re
from pprint import pprint as printer


def build_idx(file_name, company_name=None, report_type="10-K"):
    global entry
    header_re = re.compile('^\w+.*:', re.IGNORECASE)  # Detect the headers for the idx
    ignore_re = re.compile('^-.*$')  # Skip the separator which is '----'
    skip_re = re.compile('^\S+\|')  # Skip an entry if it has a | symbol
    idx = {}
    raw_data = []
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
            if form == report_type:   # Filter in only the report types we want to see, default is 10-k only
                if company_name.lower() in company.lower():  # TODO test this scenario including substrings
                    entry = {
                        'CIK': cik,
                        'Company Name': company,
                        'Form Type': form,
                        'Date Filed': date,
                        'File Name': fil
                    }
                    raw_data.append(entry)
                elif company is None:
                    entry = {
                        'CIK': cik,
                        'Company Name': company,
                        'Form Type': form,
                        'Date Filed': date,
                        'File Name': fil
                    }
                    raw_data.append(entry)
            else:
                continue
        else:
            continue

    idx['payload'] = raw_data
    return idx


f1 = open("master.idx")
index = build_idx(f1, "BAR")
printer(index)
