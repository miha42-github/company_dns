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
from flask import Flask, jsonify, abort, make_response, render_template, send_from_directory
from flask_restful import Api, Resource, reqparse
from flask_cors import CORS
import lib.firmographics as firmographics
import lib.sic as sic
import pprint

#### Globals ####
# Setup the application name and basic operations
app = Flask(__name__)
api = Api(app)
CORS(app)
VERSION="2.0"
DB = './company_dns.db'

# Serve embedded help when the user hits '/' or '/help'
def serve_help(filename):
    return send_from_directory('templates',filename)

app.add_url_rule('/', 'root', serve_help, defaults={'filename': 'help.html'})
app.add_url_rule('/help', 'root', serve_help, defaults={'filename': 'help.html'})


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
        if results['code'] != 200:
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
        results = self.f.get_all_summaries()
        if results['code'] != 200:
            abort(404)
        return results, 200

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
        results = self.f.get_all_ciks()
        if results['code'] != 200:
            abort(404)
        return results, 200

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
        results = self.f.get_firmographics_edgar()
        if results['code'] != 200:
            abort(404)
        return results, 200

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

        # TODO pass in companyName
        filings = self.f.merge_data(wiki_data['data'], wiki_data['data']['cik'], )
        if len(filings) == 0:
            abort(404)
        return filings, 200

class standardIndustryDescAPI(Resource):

    def __init__(self):
        self.s = sic.SICQueries(db_file=DB)
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument(
            'sicDescription', 
            required=True, 
            help="No SIC description supplied to query the the database and return SIC information",
            location="json"
        )
        super(standardIndustryDescAPI, self).__init__()

    def get(self, sicDescription):
        self.s.query = sicDescription
        sic_data = self.s.get_all_sic_by_name()
        if sic_data['code'] != 200:
            abort(404, sic_data)

        if len(sic_data) == 0:
            abort(404)
        return sic_data, 200

class standardIndustryCodeAPI(Resource):

    def __init__(self):
        self.s = sic.SICQueries(db_file=DB)
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument(
            'sicCode', 
            required=True, 
            help="No SIC supplied to query the the database and return SIC information",
            location="json"
        )
        super(standardIndustryCodeAPI, self).__init__()

    def get(self, sicCode):
        self.s.query = sicCode
        sic_data = self.s.get_all_sic_by_no()
        if sic_data['code'] != 200:
            abort(404, sic_data)

        if len(sic_data) == 0:
            abort(404)
        return sic_data, 200

class sicDivisionCodeAPI(Resource):

    def __init__(self):
        self.s = sic.SICQueries(db_file=DB)
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument(
            'divisionId', 
            required=True, 
            help="No division id supplied to query the the database and return division information",
            location="json"
        )
        super(sicDivisionCodeAPI, self).__init__()

    def get(self, divisionId):
        self.s.query = divisionId
        division_data = self.s.get_division_desc_by_id()
        if division_data['code'] != 200:
            abort(404, sic_data)

        if len(division_data) == 0:
            abort(404)
        return division_data, 200

class sicIndustryCodeAPI(Resource):

    def __init__(self):
        self.s = sic.SICQueries(db_file=DB)
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument(
            'industryNo', 
            required=True, 
            help="No industry number supplied to query the the database and return industry group information",
            location="json"
        )
        super(sicIndustryCodeAPI, self).__init__()

    def get(self, industryNo):
        self.s.query = industryNo
        industry_data = self.s.get_all_industry_group_by_no()
        if industry_data['code'] != 200:
            abort(404, industry_data)

        if len(industry_data) == 0:
            abort(404)
        return industry_data, 200

class sicMajorCodeAPI(Resource):

    def __init__(self):
        self.s = sic.SICQueries(db_file=DB)
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument(
            'majorNo', 
            required=True, 
            help="No major group number supplied to query the the database and return major group information",
            location="json"
        )
        super(sicMajorCodeAPI, self).__init__()

    def get(self, majorNo):
        self.s.query = majorNo
        major_data = self.s.get_all_major_group_by_no()
        if major_data['code'] != 200:
            abort(404, major_data)

        if len(major_data) == 0:
            abort(404)
        return major_data, 200



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
api.add_resource(standardIndustryDescAPI, '/V2.0/sic/description/<string:sicDescription>')
api.add_resource(standardIndustryCodeAPI, '/V2.0/sic/code/<string:sicCode>')
api.add_resource(sicDivisionCodeAPI, '/V2.0/sic/division/<string:divisionId>')
api.add_resource(sicIndustryCodeAPI, '/V2.0/sic/industry/<string:industryNo>')
api.add_resource(sicMajorCodeAPI, '/V2.0/sic/major/<string:majorNo>')

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=6868)
