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
from flask import Flask, jsonify, abort, make_response, render_template
from flask_restful import Api, Resource, reqparse
from flask_cors import CORS
import lib.firmographics as firmographics

#### Globals ####
# Setup the application name and basic operations
app = Flask(__name__)
api = Api(app)
CORS(app)
VERSION="2.0"
DB = './edgar_cache.db'

class edgarDetailAPI(Resource):

    def __init__(self):
        self.f = firmographics.Query(DB)
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument(
            'companyName', 
            required=True, 
            help="No company name or search string provided to query EDGAR for firmographics detail data.",
            location="json"
        )
        super(edgarDetailAPI, self).__init__()
        
    def get(self, companyName):
        self.f.company_or_cik = companyName
        results = self.f.get_all_details()
        if len(results) == 0:
            abort(404)
        return results, 200

class edgarSummaryAPI(Resource):

    def __init__(self):
        self.f = firmographics.Query(DB)
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument(
            'companyName', 
            required=True, 
            help="No company name or search string provided to query EDGAR for firmographics summary data.",
            location="json"
        )
        super(edgarSummaryAPI, self).__init__()
        
    def get(self, companyName):
        self.f.company_or_cik = companyName
        filings = self.f.get_all_summaries()
        if len(filings) == 0:
            abort(404)
        return filings, 200

class edgarCIKAPI(Resource):

    def __init__(self):
        self.f = firmographics.Query(DB)
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument(
            'companyName', 
            required=True, 
            help="No company name or search string provided to query EDGAR for name to CIK mapping data.",
            location="json"
        )
        super(edgarCIKAPI, self).__init__()
        
    def get(self, companyName):
        self.f.company_or_cik = companyName
        filings = self.f.get_all_ciks()
        if len(filings) == 0:
            abort(404)
        return filings, 200

class edgarFirmographicAPI(Resource):

    def __init__(self):
        self.f = firmographics.Query(DB)
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument(
            'cik', 
            required=True, 
            help="No CIK string provided to query EDGAR for the company associated to the CIK.",
            location="json"
        )
        super(edgarFirmographicAPI, self).__init__()
        
    def get(self, cik):
        self.f.company_or_cik = cik
        filings = self.f.get_firmographics_edgar()
        if len(filings) == 0:
            abort(404)
        return filings, 200

class wikipediaFirmographicAPI(Resource):

    def __init__(self):
        self.f = firmographics.Query(DB)
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument(
            'companyName', 
            required=True, 
            help="No company name or search string provided to query Wikipedia to gather firmographic details.",
            location="json"
        )
        super(wikipediaFirmographicAPI, self).__init__()
        
    def get(self, companyName):
        self.f.company_or_cik = companyName
        filings = self.f.get_firmographics_wikipedia()
        if len(filings) == 0:
            abort(404)
        return filings, 200

class mergedFirmographicAPI(Resource):

    def __init__(self):
        self.f = firmographics.Query(DB)
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument(
            'companyName', 
            required=True, 
            help="No company name or search string provided to query both Wikipedia and EDGAR to gather firmographic details.",
            location="json"
        )
        super(mergedFirmographicAPI, self).__init__()
        
    def get(self, companyName):
        self.f.company_or_cik = companyName
        wiki_data = self.f.get_firmographics_wikipedia()
        if wiki_data['code'] != 200:
            abort(404, wiki_data)

        filings = self.f.merge_data(wiki_data['data'], wiki_data['data']['cik'])
        if len(filings) == 0:
            abort(404)
        return filings, 200



class helpAPI(Resource):

    def __init__(self):
        pass
    
    def get(self):
        headers = {'Content-Type': 'text/html'}
        return make_response(render_template('help.html'), 200)


api.add_resource(edgarDetailAPI, '/V2.0/companies/edgar/detail/<string:companyName>')
api.add_resource(edgarSummaryAPI, '/V2.0/companies/edgar/summary/<string:companyName>')
api.add_resource(edgarCIKAPI, '/V2.0/companies/edgar/ciks/<string:companyName>')
api.add_resource(edgarFirmographicAPI, '/V2.0/company/edgar/firmographics/<string:cik>')
api.add_resource(wikipediaFirmographicAPI, '/V2.0/company/wikipedia/firmographics/<string:companyName>')
api.add_resource(mergedFirmographicAPI, '/V2.0/company/merged/firmographics/<string:companyName>')
api.add_resource(helpAPI, '/V2.0/help')

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=6868)
