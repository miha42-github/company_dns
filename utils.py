import re
import gzip


def create_logger(file_name=None):

    pass


string = "edgar/data/1000045/0001104659-19-005360.txt"
sub_str = re.sub('\d+\-\d+\-\d+\.txt', '', string)
print (sub_str)

f = gzip.open('master-2018-QTR3.gz')
