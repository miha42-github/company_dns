#!edgar/bin/python

"""Core RESTful service to retrieve EDGAR information about companies."""
from typing import List, Any

from flask import Flask, jsonify, abort, make_response
from flask_httpauth import HTTPBasicAuth
from flask_restful import Api, Resource, fields, marshal, reqparse
from pyedgar.utilities.indices import IndexMaker
from pyedgar.filing import Filing
from pyedgar.index import EDGARIndex
from os import path
import os.path
import re

# Setup the application name and basic operations
app = Flask(__name__, static_url_path="")
api = Api(app)
auth = HTTPBasicAuth()


# Perform the basics for authentication
@auth.get_password
def get_password(username):
    if username == 'edgar':
        return 'this_is_your_service'
    return None


# Produce a 403 error instead of 401 which will generate an authentication dialogue
@auth.error_handler
def unauthorized():
    return make_response(jsonify({'message': 'Unauthorized'}), 403)


def _initialize(my_file='.db_present', my_year=2017):
    """
    If the EDGAR index isn't available download the raw files and create the index.
    This is controlled by "my_file" which is created at the time of the initial
    download and indexing.  If the file exists the download and indexing won't
    execute.  Therefore if you want to reindex then what you do is remove the file
    as specified in the "my_file" variable below.

    Additionally, the default start year for download is 2017.

    :type my_year: str
    :type my_file: int
    """
    if path.exists(my_file):
        return True
    else:
        i = IndexMaker()
        i.extract_indexes(start_year=my_year)  # Download and create the index
        open(my_file, 'w').close()  # Create the file that controls the reindexing
        return True


def _get10ks() -> object:
    """
    Gather all of the various indexes available, filter down to only the 10-Ks,
    and return only a 10-K index.  This prepares for searching these metadata and
    getting the header information.

    :rtype: object
    """
    all_idxs = EDGARIndex()  # Instantiate the EDGAR indexes
    all_10ks = all_idxs['10-K']  # Pull in only the 10-K portion of the indexes
    # This is likely not needed: all_10ks.drop(['form', 'filedate'], axis=1)
    return all_10ks


companies_fields = {
    'name': fields.String,
    'headers': fields.Arbitrary,
    'abstract': fields.String,
    'done': fields.Boolean,
    'uri': fields.Url('filings')
}


class edgarFilingAPI(Resource):
    decorators = [auth.login_required]

    def __init__(self):
        self.reqparse = reqparse.RequestParser()
        self.index = _get10ks()
        self.reqparse.add_argument('name', required=True, help="No company name provided",
                                   location="json")
        super(edgarFilingAPI, self).__init__()

    def get(self, company):
        to_skip = re.compile('company-conformed-name|state-of-incorporation|street1|zip|state|'
                             'standard-industrial-classification|form-type|fiscal-year-end|irs-number|filer|'
                             'city|business-phone|sec-act|sec-file-number|\<sec-document|\<sec-header')
        to_mod = re.compile('accession-number')
        companies_list: List[Any] = []
        companies_dict: Dict[str, Union[Dict[Any, Any], Dict[str, Dict[Any, Any]]]] = dict()

        for key, value in self.index['name'].str.contains(company).items():
            if value:
                companies_list.append(self.index.loc[[key]].values.tolist())

        for entry in companies_list:
            n = entry[0]
            cik = n[0]
            name = n[1]
            ascension = n[4]
            f = Filing(cik, ascension)

            my_cik = str(f.headers['central-index-key']).strip()
            my_report = str(f.headers['conformed-period-of-report']).strip()
            if my_cik in companies_dict:
                companies_dict[my_cik].update({my_report: dict()})
            else:
                companies_dict[my_cik] = dict()
                companies_dict[my_cik] = {my_report: dict(),
                                     'company_name': str(f.headers['company-conformed-name']).strip().lstrip("'"),
                                     'country': 'United States of America',
                                     'state': str(f.headers['state']).strip(),
                                     'city': str(f.headers['city']).strip(),
                                     'street': str(f.headers['street1']).strip(),
                                     'zip_code': str(f.headers['zip']).strip(),
                                     'business_phone': '+1' + str(f.headers['business-phone']).strip(),
                                     'state_of_incorporation': str(f.headers['state-of-incorporation']).strip(),
                                     'industry': str(f.headers['standard-industrial-classification']).strip(),
                                     'form_type': str(f.headers['form-type']).strip(),
                                     'fiscal_end': str(f.headers['fiscal-year-end']).strip(),
                                     'irs_number': str(f.headers['irs-number']).strip(),
                                     'sec_file_number': str(f.headers['sec-file-number']).strip(),
                                     }

            for item in f.headers:
                if to_skip.match(item):
                    continue
                elif to_mod.match(item):
                    directory = my_cik + '/' + str(f.headers[item].replace('-', ''))
                    companies_dict[my_cik][my_report].update({'url': f.urls[1]})
                    root_url = EDGARURI + EDGARSERVER + '/' + EDGARARCHIVES + '/' + directory + '/'
                    companies_dict[my_cik][my_report].update({'directory_url': root_url})

                companies_dict[my_cik][my_report].update({item: f.headers[item]})

            if len(companies_dict) == 0:
                abort(404)
            return {'headers': marshal(companies_dict, companies_fields)}


class edgar10KAbstractAPI(Resource):
    decorators = [auth.login_required]

    def __init__(self):
        self.reqparse = reqparse.RequestParser()

    def get(self):
        pass


api.add_resource(edgarFilingAPI, '/edgar/api/v1.0/filings', endpoint="filings")
api.add_resource(edgar10KAbstractAPI, '/edgar/api/v1.0/abstracts', endpoint="abstract")

if __name__ == '__main__':
    _initialize()
    app.run(debug=True)
