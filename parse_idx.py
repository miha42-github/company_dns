import re
import pprint

f1 = open("master.idx")

header_re = re.compile('^\w+.*:', re.IGNORECASE)  # Detect the headers for the idx
ignore_re = re.compile('^-.*$')  # Skip the separator which is '----'
idx = {}
raw_data = []
for line in f1.readlines():
    line = line.rstrip()
    if line:
        # Used to generate the header of the file specific index
        if header_re.match(line):
            (key, value) = line.split(':', 1)
            idx[key] = value
            continue
        elif ignore_re.match(line):
            continue
        entry = {}
        (cik, company, form, date, fil) = line.split('|')
        if form == '10-K':
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
pprint.pprint(idx)
