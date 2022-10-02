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
from .edgar import EdgarUtilities as EU
from flask_cors import CORS

# Setup the application name and basic operations
app = Flask(__name__)
api = Api(app)
CORS(app)
VERSION="2.0"

class edgarDetailAPI(Resource):

    def __init__(self):
        self.e = EU()
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument(
            'query', 
            required=True, 
            help="No company name provided",
            location="json"
        )
        super(edgarDetailAPI, self).__init__()
        
    def get(self, query):
        filings = self.e.getAll(query)
        if len(filings) == 0:
            abort(404)
        return filings, 200

class edgarSummaryAPI(Resource):

    def __init__(self):
        self.e = EU()
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument(
            'query', 
            required=True, 
            help="No company name provided",
            location="json"
        )
        super(edgarSummaryAPI, self).__init__()
        
    def get(self, query):
        filings = self.e.getAllSummary(query)
        if len(filings) == 0:
            abort(404)
        return filings, 200

class edgarCompanyAPI(Resource):

    def __init__(self):
        self.e = EU()
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument(
            'cik', 
            required=True, 
            help="No CIK provided",
            location="json"
        )
        super(edgarCompanyAPI, self).__init__()
        
    def get(self, cik):
        details = self.e.getCompanyDetails(cik)
        if len(details) == 0:
            abort(404)
        return details, 200

class edgarCIKAPI(Resource):

    def __init__(self):
        self.e = EU()
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument(
            'query', 
            required=True, 
            help="No company name provided",
            location="json"
        )
        super(edgarCIKAPI, self).__init__()
        
    def get(self, query):
        filings = self.e.getAllCIKs(query)
        if len(filings) == 0:
            abort(404)
        return filings, 200

class helpAPI(Resource):

    def __init__(self):
        self.reqparse = reqparse.RequestParser()
        super(helpAPI, self).__init__()
    
    def get(self):
        help_string = {
                'API Version': VERSION,
                'Description': "RESTful endpoints that gathers company firmographics from SEC EDGAR and Wikipedia.",
                'Search details': "/" + VERSION+ "/company_dns/companies/detail/<string:query>",
                'Search summaries': "/" + VERSION+ "/company_dns/companies/summary/<string:query>",
                'Search companies and return CIKs': "/" + VERSION+ "company_dns/companies/ciks/<string:query>",
                'Return the details for a single company': "/" + VERSION+ "company_dns/company/details/<string:cik>"
                }
        return help_string, 200

# TODO need to think about how to pass company names, look up stock ticker and then get the CIK maybe ISIN
api.add_resource(edgarDetailAPI, '/V2.0/company_dns/companies/detail/<string:query>')
api.add_resource(edgarSummaryAPI, '/V2.0/company_dns/companies/summary/<string:query>')
api.add_resource(edgarCompanyAPI, '/V2.0/company_dns/company/details/<string:cik>')
api.add_resource(edgarCIKAPI, '/V2.0/edgar/company_dns/ciks/<string:query>')
api.add_resource(helpAPI, '/V2.0/help')

if __name__ == '__main__':
    app.run(debug=True)
