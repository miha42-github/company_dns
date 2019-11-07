#!edgar/bin/python

"""Core RESTful service to retrieve EDGAR information about companies."""
from typing import List, Any
from pprint import pprint as printer
from flask import Flask, jsonify, abort, make_response
from flask_httpauth import HTTPBasicAuth
from flask_restful import Api, Resource, reqparse
from flask_restplus import fields, marshal
from cutils import EdgarUtilities as EU
import re


# Setup the application name and basic operations
app = Flask(__name__, static_url_path="")
api = Api(app)
auth = HTTPBasicAuth()


# Perform the basics for authentication
@auth.get_password
def get_password(username):
    if username == 'edgar':
        return 'foo'
    return None


# Produce a 403 error instead of 401 which will generate an authentication dialogue
@auth.error_handler
def unauthorized():
    return make_response(jsonify({'message': 'Unauthorized'}), 403)


class edgarFilingAPI(Resource):
    decorators = [auth.login_required]

    def __init__(self):
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument('query', required=True, help="No company name provided",
                                   location="json")
        super(edgarFilingAPI, self).__init__()

    def get(self, query):
        e = EU()
        filings = e.get10kfilings(query)
        if len(filings) == 0:
            abort(404)
        return filings, 200


class edgar10KHeaderAPI(Resource):
    decorators = [auth.login_required]

    def __init__(self):
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument('cikaccession', required=True, help="No CIK:Accession combo provided",
                                   location="json")
        super(edgar10KHeaderAPI, self).__init__()

    def get(self, cikaccession):
        e = EU()
        headers = e.get10kheaders(cikaccession)
        return headers, 200


class edgar10KURLAPI(Resource):
    decorators = [auth.login_required]

    def __init__(self):
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument('l_url', required=True, help="No 10K URL provided",
                                   location="json")
        super(edgar10KURLAPI, self).__init__()

    def get(self, l_url):
        e = EU()
        m_url = e.get10kurl(l_url)
        print(m_url)
        return {'url': m_url}, 200


api.add_resource(edgarFilingAPI, '/edgar/api/v1.0/filings/<string:query>')
api.add_resource(edgar10KHeaderAPI, '/edgar/api/v1.0/header/<string:cikaccession>')
api.add_resource(edgar10KURLAPI, '/edgar/api/v1.0/10kurl/<path:l_url>')

if __name__ == '__main__':
    app.run(debug=True)
