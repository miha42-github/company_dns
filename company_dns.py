from starlette.applications import Starlette
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn
import logging

from lib.sic import SICQueries
from lib.edgar import EdgarQueries
from lib.wikipedia import WikipediaQueries
from lib.firmographics import GeneralQueries
    
# -------------------------------------------------------------- #
# BEGIN: Standard Idustry Classification (SIC) database cache functions
async def sic_description(request):
    return _handle_request(request, sq, sq.get_all_sic_by_name, 'sic_desc')

async def sic_code(request):
    return _handle_request(request, sq, sq.get_all_sic_by_no, 'sic_code')

async def division_code(request):
    return _handle_request(request, sq, sq.get_division_desc_by_id, 'division_code')

async def industry_code(request):
    return _handle_request(request, sq, sq.get_all_industry_group_by_no, 'industry_code')

async def major_code(request):
    return _handle_request(request, sq, sq.get_all_major_group_by_no, 'major_code')
# END: Standard Idustry Classification (SIC) database cache functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: EDGAR dabase cache functions
async def edgar_detail(request):
    return _handle_request(request, eq, eq.get_all_details, 'company_name')

async def edgar_summary(request):
    return _handle_request(request, eq, eq.get_all_details, 'company_name', firmographics=False)

async def edgar_ciks(request):
    return _handle_request(request, eq, eq.get_all_ciks, 'company_name')

async def edgar_firmographics(request):
    return _handle_request(request, eq, eq.get_firmographics, 'cik_no')
# END: EDGAR dabase cache functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: Wikipedia functions
async def wikipedia_firmographics(request):
    return _handle_request(request, wq, wq.get_firmographics, 'company_name')
# END: Wikipedia functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: General query functions
async def general_query(request):
    try:
        gq.query = request.path_params['company_name']
        # Log the query request as a debug message
        logger.debug(f'Performing general query for company name: [{request.path_params["company_name"]}]')
        company_wiki_data = gq.get_firmographics_wikipedia()
        # logger.debug(f'Company wiki data: {company_wiki_data}')
        if company_wiki_data['code'] != 200:
            logger.error(f'There were [0] results for resource [company_name].')
            return JSONResponse(company_wiki_data)
        
        general_company_data = gq.merge_data(company_wiki_data['data'], company_wiki_data['data']['cik'])
        # Call check_status_and_return to check the status of the data and return the data or an error message
        checked_data = _check_status_and_return(general_company_data, request.path_params['company_name'])
        if 'error' in checked_data:
            return JSONResponse(checked_data, status_code=checked_data['code'])
        return JSONResponse(checked_data)
    except Exception as e:
        logger.error(f'Error: {e}')
        general_company_data = {'error': 'A general or code error has occured', 'code': 500}
        return JSONResponse(general_company_data, status_code=general_company_data['code'])
# END: General query functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: Helper functions
# TODO: This function may not be needed as it is and the code could be moved into _handle_request.  Essentially we're checking for a 200 status code and returning the data that includes the error message.  The change would likely be to log the error message and return the data as is.  This would mean this funtion would be removed.
def _check_status_and_return(result_data, resource_name):
    return_code = result_data.get('code')
    result_count = result_data.get('total')
    return_msg = result_data.get('message')
    if return_code != 200:
        # Log the error message
        logger.error(f'There were [{result_count}] results for resource [{resource_name}].')
        # Return an error message that the data was not found using the resource name
        return {'message': return_msg, 'code': return_code, 'data': result_data}
    return result_data

def _prepare_logging(log_level=logging.INFO):
    logging.basicConfig(format='%(levelname)s:\t%(asctime)s [module: %(name)s] %(message)s', level=log_level)
    return logging.getLogger(__file__)

def _handle_request(request, handler, func, path_param, *args, **kwargs):
    handler.query = request.path_params.get(path_param)
    data = func(*args, **kwargs)
    checked_data = _check_status_and_return(data, path_param)
    if 'error' in checked_data:
        return JSONResponse(checked_data, status_code=checked_data['code'])
    return JSONResponse(data)
# END: Helper functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: Define query objects
global sq
sq = SICQueries()

global eq
eq = EdgarQueries()

global wq
wq = WikipediaQueries()

global gq
gq = GeneralQueries()
# END: Define query objects
# -------------------------------------------------------------- #


# -------------------------------------------------------------- #
# BEGIN: Define the Starlette app
class CatchAllMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if response.status_code == 404:
            return RedirectResponse(url='/help')
        return response

middleware = [
    Middleware(CatchAllMiddleware),
    Middleware(CORSMiddleware, allow_origins=['*'])
]

global logger
logger = _prepare_logging()

app = Starlette(debug=True, middleware=middleware, routes=[
    # -------------------------------------------------------------- #
    # SIC endpoints for V2.0
    Route('/V2.0/sic/description/{sic_desc}', sic_description),
    Route('/V2.0/sic/code/{sic_code}', sic_code),
    Route('/V2.0/sic/division/{division_code}', division_code),
    Route('/V2.0/sic/industry/{industry_code}', industry_code),
    Route('/V2.0/sic/major/{major_code}', major_code),

    # SIC endpoints for V3.0
    Route('/V3.0/na/sic/description/{sic_desc}', sic_description),
    Route('/V3.0/na/sic/code/{sic_code}', sic_code),
    Route('/V3.0/na/sic/division/{division_code}', division_code),
    Route('/V3.0/na/sic/industry/{industry_code}', industry_code),
    Route('/V3.0/na/sic/major/{major_code}', major_code),
    # -------------------------------------------------------------- #

    # -------------------------------------------------------------- #
    # EDGAR endpoints for V2.0
    Route('/V2.0/companies/edgar/detail/{company_name}', edgar_detail),
    Route('/V2.0/companies/edgar/summary/{company_name}', edgar_summary),
    Route('/V2.0/companies/edgar/ciks/{company_name}', edgar_ciks),
    Route('/V2.0/company/edgar/firmographics/{cik_no}', edgar_firmographics),

    # EDGAR endpoints for V3.0
    Route('/V3.0/na/companies/edgar/detail/{company_name}', edgar_detail),
    Route('/V3.0/na/companies/edgar/summary/{company_name}', edgar_summary),
    Route('/V3.0/na/companies/edgar/ciks/{company_name}', edgar_ciks),
    Route('/V3.0/na/company/edgar/firmographics/{cik_no}', edgar_firmographics),
    # -------------------------------------------------------------- #

    # -------------------------------------------------------------- #
    # Wikipedia endpoints for V2.0
    Route('/V2.0/company/wikipedia/firmographics/{company_name}', wikipedia_firmographics),

    # Wikipedia endpoints for V3.0
    Route('/V3.0/global/company/wikipedia/firmographics/{company_name}', wikipedia_firmographics),
    # -------------------------------------------------------------- #

    # -------------------------------------------------------------- #
    # General query endpoint for V2.0
    Route('/V2.0/company/merged/firmographics/{company_name}', general_query),

    # General query endpoint for V3.0
    Route('/V3.0/global/company/merged/firmographics/{company_name}', general_query),
    # -------------------------------------------------------------- #

    # Serve the local directory ./html at the /help
    Mount('/help', app=StaticFiles(directory='html', html=True)),    
])
# END: Define the Starlette app
# -------------------------------------------------------------- #

if __name__ == "__main__": 
    try:
        uvicorn.run(app, host='0.0.0.0', port=8000, log_level='info', lifespan='off')
    except KeyboardInterrupt:
        logger.info("Server was shut down by the user.")