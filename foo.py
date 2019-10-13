from pyedgar.utilities.indices import IndexMaker
from pyedgar.filing import Filing
from pyedgar.index import EDGARIndex
from pprint import pprint


def my_idx(start_year):
    i = IndexMaker(use_tqdm=True)
    i.extract_indexes(start_year=2018)


def get_filing(my_cik, my_ascension):
    f = Filing()
    print(f.headers())


my_str = 'DAYBREAK OIL'
all = EDGARIndex()
all_10k = all['10-K']
all_10k.drop(['form', 'filedate'], axis=1)

foo = []

for key, value in all_10k['name'].str.contains(my_str).items():
    if value:
        foo.append(all_10k.loc[[key]].values.tolist())

for entry in foo:
    n = entry[0]
    cik = n[0]
    name = n[1]
    ascension = n[4]
    f = Filing(cik, ascension)
    pprint(f.headers)
