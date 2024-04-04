from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
import uvicorn
import logging

from lib.sic import SICQueries
from lib.edgar import EdgarQueries
from lib.wikipedia import WikipediaQueries
from lib.firmographics import GeneralQueries
    
# -------------------------------------------------------------- #
# BEGIN: Standard Idustry Classification (SIC) database cache functions
async def sic_description(request):
    sq.query = request.path_params['sic_desc']
    return JSONResponse(sq.get_all_sic_by_name())

async def sic_code(request):
    sq.query = request.path_params['sic_code']
    return JSONResponse(sq.get_all_sic_by_no())

async def division_code(request):
    sq.query = request.path_params['division_code']
    return JSONResponse(sq.get_division_desc_by_id())

async def industry_code(request):
    sq.query = request.path_params['industry_code']
    return JSONResponse(sq.get_all_industry_group_by_no())

async def major_code(request):
    sq.query = request.path_params['major_code']
    return JSONResponse(sq.get_all_major_group_by_no())
# END: Standard Idustry Classification (SIC) database cache functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: EDGAR dabase cache functions
async def edgar_detail(request):
    eq.company_or_cik = request.path_params['company_name']
    return JSONResponse(eq.get_all_details())

async def edgar_summary(request):
    eq.company_or_cik = request.path_params['company_name']
    return JSONResponse(eq.get_all_details(firmographics=False))

async def edgar_ciks(request):
    eq.company_or_cik = request.path_params['company_name']
    return JSONResponse(eq.get_all_ciks())

async def edgar_firmographics(request):
    return JSONResponse(eq.get_firmographics(request.path_params['cik_no']))
# END: EDGAR dabase cache functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: Wikipedia functions
async def wikipedia_firmographics(request):
    wq.company_name = request.path_params['company_name']
    return JSONResponse(wq.get_firmographics())
# END: Wikipedia functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: General query functions
async def general_query(request):
    gq.company_or_cik = request.path_params['company_name']
    company_wiki_data = gq.get_firmographics_wikipedia()
    general_company_data = gq.merge_data(company_wiki_data['data'], company_wiki_data['data']['cik'])
    return JSONResponse(general_company_data)
# END: General query functions
# -------------------------------------------------------------- #


def _prepare_logging():
    logging.basicConfig(format='%(levelname)s:     %(asctime)s [module: %(name)s] %(message)s', level=logging.INFO)
    return logging.getLogger(__file__)

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
global logger
logger = _prepare_logging()

app = Starlette(debug=True, routes=[
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
    Route('/V2.0/companies/edgar/firmographics/{cik_no}', edgar_firmographics),

    # EDGAR endpoints for V3.0
    Route('/V3.0/na/companies/edgar/detail/{company_name}', edgar_detail),
    Route('/V3.0/na/companies/edgar/summary/{company_name}', edgar_summary),
    Route('/V3.0/na/companies/edgar/ciks/{company_name}', edgar_ciks),
    Route('/V3.0/na/companies/edgar/firmographics/{cik_no}', edgar_firmographics),
    # -------------------------------------------------------------- #

    # -------------------------------------------------------------- #
    # Wikipedia endpoints for V2.0
    Route('/V2.0/companies/wikipedia/firmographics/{company_name}', wikipedia_firmographics),

    # Wikipedia endpoints for V3.0
    Route('/V3.0/global/companies/wikipedia/firmographics/{company_name}', wikipedia_firmographics),
    # -------------------------------------------------------------- #

    # -------------------------------------------------------------- #
    # General query endpoint for V2.0
    Route('/V2.0/companies/merged/firmographics/{company_name}', general_query),

    # General query endpoint for V3.0
    Route('/V3.0/global/companies/merged/firmographics/{company_name}', general_query),
    # -------------------------------------------------------------- #
    
    # Mount the local directory ./html to the /help
    Mount('/help', app=StaticFiles(directory='html' , html=True)),
])
# END: Define the Starlette app
# -------------------------------------------------------------- #

if __name__ == "__main__": 
    try:
        uvicorn.run(app, host='0.0.0.0', port=8000, log_level="info", lifespan='off')
    except KeyboardInterrupt:
        logger.info("Server was shut down by the user.")