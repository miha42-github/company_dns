from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
import uvicorn
import requests
import re
from bs4 import BeautifulSoup
import wikipediaapi
import logging
import sys

from lib.sic import SICQueries

wiki_wiki = wikipediaapi.Wikipedia('company_dns')

def get_infobox(company_name):
    S = requests.Session()
    URL = "https://en.wikipedia.org/w/api.php"
    PARAMS = {
        "action": "parse",
        "page": company_name,
        "format": "json",
        "prop": "text"
    }
    R = S.get(url=URL, params=PARAMS)
    DATA = R.json()
    raw_html = DATA["parse"]["text"]["*"]
    soup = BeautifulSoup(raw_html, 'html.parser')
    infobox = soup.find('table', {'class': 'infobox vcard'})
    infobox_data = {}
    if infobox:
        for row in infobox.find_all('tr'):
            if row.th and row.td:
                key = row.th.text.strip()
                if key == 'Traded as':
                    # Special case for "Traded as" key: extract only the "Exchange:Ticker" part
                    text = next((s for s in row.td.stripped_strings if re.match(r'\w+:\s*\w+', s)), '')
                else:
                    # Remove HTML tags and join the text with "|"
                    text = ' | '.join(t.strip() for t in row.td.stripped_strings)
                infobox_data[key] = text
    return infobox_data

async def homepage(request):
    company_name = request.query_params.get('company')
    if company_name:
        page = wiki_wiki.page(company_name)
        section_titles = [section.title for section in page.sections]
        if page.exists():
            return JSONResponse(
                {
                    'summary': page.summary,
                    'title': page.title,
                    'fullurl': page.fullurl,
                    'company': company_name,
                    # 'categories': list(page.categories.keys()),
                    'sections': section_titles,
                    'infobox': get_infobox(company_name)
                }
            )
        else:
            return JSONResponse({'error': 'Company not found'}, status_code=404)
    else:
        return JSONResponse({'error': 'No company provided'}, status_code=400)
    
# -------------------------------------------------------------- #
# BEGIN: Standard Idustry Classification (SIC) database cache functions
async def sic_description(request):
    sic_desc = request.path_params['sic_desc']
    q.query = sic_desc
    return JSONResponse(q.get_all_sic_by_name())

async def sic_code(request):
    sic_code = request.path_params['sic_code']
    q.query = sic_code
    return JSONResponse(q.get_all_sic_by_no())

async def division_code(request):
    division_code = request.path_params['division_code']
    q.query = division_code
    return JSONResponse(q.get_division_desc_by_id())

async def industry_code(request):
    industry_code = request.path_params['industry_code']
    q.query = industry_code
    return JSONResponse(q.get_all_industry_group_by_no())

async def major_code(request):
    major_code = request.path_params['major_code']
    q.query = major_code
    return JSONResponse(q.get_all_major_group_by_no())
# END: Standard Idustry Classification (SIC) database cache functions
# -------------------------------------------------------------- #

def _prepare_logging():
    logging.basicConfig(format='%(asctime)s | %(levelname)s | %(name)s | %(message)s', level=logging.INFO)
    return logging.getLogger(__file__)

global q
q = SICQueries()
logger = _prepare_logging()
app = Starlette(debug=True, routes=[
    # SIC endpoints
    Route('/V2.0/sic/description/{sic_desc}', sic_description),
    Route('/V2.0/sic/code/{sic_code}', sic_code),
    Route('/V2.0/sic/division/{division_code}', division_code),
    Route('/V2.0/sic/industry/{industry_code}', industry_code),
    Route('/V2.0/sic/major/{major_code}', major_code),
    
    # Mount the local directory ./html to the /help
    Mount('/help', app=StaticFiles(directory='html' , html=True)),
])

if __name__ == "__main__": 
    uvicorn.run(app, host='0.0.0.0', port=8000, log_level="info")