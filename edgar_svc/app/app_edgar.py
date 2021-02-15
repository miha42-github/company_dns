"""
Copyright 2021 mediumroast.io.  All rights reserved
Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
in compliance with the License. You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License
is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied. See the License for the specific language governing permissions and limitations under
the License.
"""

"""Core RESTful service to retrieve EDGAR information about companies."""
from flask import Flask, jsonify, abort, make_response
from flask_restful import Api, Resource, reqparse
from apputils import EdgarUtilities as EU
from flask_cors import CORS

# Setup the application name and basic operations
app = Flask(__name__)
api = Api(app)
CORS(app)
VERSION="1"

class edgarCompanyAPI(Resource):

    def __init__(self):
        self.e = EU()
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument('query', required=True, help="No company name provided",
                                   location="json")
        super(edgarCompanyAPI, self).__init__()
    
    
    def get(self, query):
        filings = self.e.getAll(query)
        if len(filings) == 0:
            abort(404)
        return filings, 200


class helpAPI(Resource):

    def __init__(self):
        self.reqparse = reqparse.RequestParser()
        super(helpAPI, self).__init__()

    
    def get(self):
        help_string = {'version': VERSION,
                'Search Companies': '/V1/edgar/company/'}
        return help_string, 200
    
api.add_resource(edgarCompanyAPI, '/V1/edgar/company/<string:query>')
api.add_resource(helpAPI, '/V1/help')

if __name__ == '__main__':
    app.run(debug=True)
