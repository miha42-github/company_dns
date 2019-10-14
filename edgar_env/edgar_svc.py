#!edgar/bin/python

"""Core RESTful service to retrieve EDGAR information about companies."""

from flask import Flask, jsonify, abort, make_response
from flask_httpauth import HTTPBasicAuth
from flask_restful import Api, Resource, fields, marshal, reqparse
from pyedgar.utilities.indices import IndexMaker
from pyedgar.filing import Filing
from pyedgar.index import EDGARIndex
from os import path
import os.path

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


def initialize(my_file='.db_present', my_year=2017):
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


class edgarFilingAPI(Resource):
    decorators = [auth.login_required]

    def __init__(self):
        self.reqparse = reqparse.RequestParser()

    def get(self):
        pass


class edgar10KAbstractAPI(Resource):
    decorators = [auth.login_required]

    def __init__(self):
        self.reqparse = reqparse.RequestParser()

    def get(self):
        pass


api.add_resource(edgarFilingAPI, '/edgar/api/v1.0/filings', endpoint="filings")
api.add_resource(edgar10KAbstractAPI, '/edgar/api/v1.0/abstracts', endpoint="abstract")

if __name__ == '__main__':
    initialize()
    app.run(debug=True)
