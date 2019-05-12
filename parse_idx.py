import re

f1 = open("company.20190401.idx")

# TODO separate the header from the body of the idx, remove the '----' separator in appropriate regex instances
header_re = re.compile('\w+\s*:\s*\w+\s*', re.IGNORECASE)
ignore_re = re.compile('^-.*$')
idx = {}
raw_data = []
for line in f1.readlines():
    line.strip()
    if header_re.match(line):
        (key, value) = line.split(':')
        idx[key] = value.strip()
        continue
    elif ignore_re.match(line):
        continue

# TODO stuff a dict with appropriate company data into an array

    #line_dict=dict(line.split())
    #raw_data.append(line_dict)

#print (raw_data)
print (idx)
