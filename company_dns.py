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
import asyncio

from lib.sic import SICQueries
from lib.edgar import EdgarQueries
from lib.wikipedia import WikipediaQueries
# from lib.wikipedia_async import WikipediaQueriesAsync as WikipediaQueries
from lib.firmographics import GeneralQueries
# from lib.firmographics_async import GeneralQueriesAsync as GeneralQueries
from lib.uk_sic import UKSICQueries
from lib.international_sic import InternationalSICQueries
from lib.eu_sic import EuSICQueries
from lib.japan_sic import JapanSICQueries
from lib.unified_sic import UnifiedSICQueries
    
# -------------------------------------------------------------- #
# BEGIN: Standard Idustry Classification (SIC) database cache functions
async def sic_description(request):
    return await _handle_request(request, sq, sq.get_all_sic_by_name, 'sic_desc')

async def sic_code(request):
    return await _handle_request(request, sq, sq.get_all_sic_by_no, 'sic_code')

async def division_code(request):
    return await _handle_request(request, sq, sq.get_division_desc_by_id, 'division_code')

async def industry_code(request):
    return await _handle_request(request, sq, sq.get_all_industry_group_by_no, 'industry_code')

async def major_code(request):
    return await _handle_request(request, sq, sq.get_all_major_group_by_no, 'major_code')
# END: Standard Idustry Classification (SIC) database cache functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: UK Standard Industry Classification (SIC) database cache functions
async def uk_sic_description(request):
    return await _handle_request(request, uksq, uksq.get_uk_sic_by_name, 'uk_sic_desc')

async def uk_sic_code(request):
    return await _handle_request(request, uksq, uksq.get_uk_sic_by_code, 'uk_sic_code')
# END: UK Standard Industry Classification (SIC) database cache functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: International Standard Industry Classification (ISIC) database cache functions
async def international_sic_section(request):
    return await _handle_request(request, isicsq, isicsq.get_section_by_code, 'section_code')

async def international_sic_division(request):
    return await _handle_request(request, isicsq, isicsq.get_division_by_code, 'division_code')

async def international_sic_group(request):
    return await _handle_request(request, isicsq, isicsq.get_group_by_code, 'group_code')

async def international_sic_class(request):
    return await _handle_request(request, isicsq, isicsq.get_class_by_code, 'class_code')

async def international_sic_class_description(request):
    return await _handle_request(request, isicsq, isicsq.get_class_by_description, 'class_desc')
# END: International Standard Industry Classification (ISIC) database cache functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: EU Standard Industry Classification (NACE) database cache functions
async def eu_sic_section(request):
    return await _handle_request(request, eusicsq, eusicsq.get_section_by_code, 'section_code')

async def eu_sic_division(request):
    return await _handle_request(request, eusicsq, eusicsq.get_division_by_code, 'division_code')

async def eu_sic_group(request):
    return await _handle_request(request, eusicsq, eusicsq.get_group_by_code, 'group_code')

async def eu_sic_class(request):
    return await _handle_request(request, eusicsq, eusicsq.get_class_by_code, 'class_code')

async def eu_sic_class_description(request):
    return await _handle_request(request, eusicsq, eusicsq.get_class_by_description, 'class_desc')
# END: EU Standard Industry Classification (NACE) database cache functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: Japan Standard Industry Classification database cache functions
async def japan_sic_division(request):
    return await _handle_request(request, japansicsq, japansicsq.get_division_by_code, 'division_code')

async def japan_sic_major_group(request):
    return await _handle_request(request, japansicsq, japansicsq.get_major_group_by_code, 'major_group_code')

async def japan_sic_group(request):
    return await _handle_request(request, japansicsq, japansicsq.get_group_by_code, 'group_code')

async def japan_sic_industry_group(request):
    return await _handle_request(request, japansicsq, japansicsq.get_industry_group_by_code, 'industry_code')

async def japan_sic_industry_group_description(request):
    return await _handle_request(request, japansicsq, japansicsq.get_industry_group_by_description, 'industry_desc')
# END: Japan Standard Industry Classification database cache functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: Unified Standard Industry Classification database cache functions
async def unified_sic_description(request):
    return await _handle_request(request, unified_sic_q, unified_sic_q.search_all_descriptions, 'query_string')

# END: Unified Standard Industry Classification database cache functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: EDGAR dabase cache functions
async def edgar_detail(request):
    return await _handle_request(request, eq, eq.get_all_details, 'company_name')

async def edgar_summary(request):
    return await _handle_request(request, eq, eq.get_all_details, 'company_name', firmographics=False)

async def edgar_ciks(request):
    return await _handle_request(request, eq, eq.get_all_ciks, 'company_name')

async def edgar_firmographics(request):
    return await _handle_request(request, eq, eq.get_firmographics, 'cik_no')
# END: EDGAR dabase cache functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: Wikipedia functions
async def wikipedia_firmographics(request):
    return await _handle_request(request, wq, wq.get_firmographics, 'company_name')
# END: Wikipedia functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: General query functions
# 
async def general_query(request):
    return await _handle_request(request, gq, gq.get_firmographics, 'company_name')

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

async def _handle_request(request, handler, func, path_param, *args, **kwargs):
    handler.query = request.path_params.get(path_param)
    
    # If the function is async, await it, otherwise call it directly
    if asyncio.iscoroutinefunction(func):
        data = await func(*args, **kwargs)
    else:
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

global uksq
uksq = UKSICQueries()

global isicsq
isicsq = InternationalSICQueries()

global eusicsq 
eusicsq = EuSICQueries()

global japansicsq
japansicsq = JapanSICQueries()

global unified_sic_q
unified_sic_q = UnifiedSICQueries()
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
    Middleware(
        CORSMiddleware, 
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=True,
        expose_headers=["Content-Type", "X-Custom-Header"]
    )
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

    # -------------------------------------------------------------- #
    # UK SIC endpoints
    Route('/V3.0/uk/sic/description/{uk_sic_desc}', uk_sic_description),
    Route('/V3.0/uk/sic/code/{uk_sic_code}', uk_sic_code),
    # -------------------------------------------------------------- #

    # -------------------------------------------------------------- #
    # International SIC endpoints
    Route('/V3.0/international/sic/section/{section_code}', international_sic_section),
    Route('/V3.0/international/sic/division/{division_code}', international_sic_division),
    Route('/V3.0/international/sic/group/{group_code}', international_sic_group),
    Route('/V3.0/international/sic/class/{class_code}', international_sic_class),
    Route('/V3.0/international/sic/description/{class_desc}', international_sic_class_description),
    # -------------------------------------------------------------- #

     # -------------------------------------------------------------- #
    # EU SIC endpoints
    Route('/V3.0/eu/sic/section/{section_code}', eu_sic_section),
    Route('/V3.0/eu/sic/division/{division_code}', eu_sic_division),
    Route('/V3.0/eu/sic/group/{group_code}', eu_sic_group),
    Route('/V3.0/eu/sic/class/{class_code}', eu_sic_class),
    Route('/V3.0/eu/sic/description/{class_desc}', eu_sic_class_description),
    # -------------------------------------------------------------- #


    # -------------------------------------------------------------- #
    # Japan SIC endpoints
    Route('/V3.0/japan/sic/division/{division_code}', japan_sic_division),
    Route('/V3.0/japan/sic/major_group/{major_group_code}', japan_sic_major_group),
    Route('/V3.0/japan/sic/group/{group_code}', japan_sic_group),
    Route('/V3.0/japan/sic/industry_group/{industry_code}', japan_sic_industry_group),
    Route('/V3.0/japan/sic/description/{industry_desc}', japan_sic_industry_group_description),
    # -------------------------------------------------------------- #


    # -------------------------------------------------------------- #
    # Unified SIC endpoints
    Route('/V3.0/global/sic/description/{query_string}', unified_sic_description),
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