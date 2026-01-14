from fastapi import FastAPI, Path, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi.errors import RateLimitExceeded
import uvicorn
import logging
import asyncio
import os
from pathlib import Path as PathLib
from datetime import datetime

from lib.sic import SICQueries
from lib.edgar import EdgarQueries
from lib.wikipedia import WikipediaQueries
from lib.firmographics import GeneralQueries
from lib.uk_sic import UKSICQueries
from lib.international_sic import InternationalSICQueries
from lib.eu_sic import EuSICQueries
from lib.japan_sic import JapanSICQueries
from lib.unified_sic import UnifiedSICQueries
from lib.security_middleware import security_middleware
from lib.logging_config import logging_middleware, logger
from lib.rate_limiter import limiter, rate_limit_error_handler
from lib.models import (
    SICResponse, DivisionResponse, UKSICResponse, ISICResponse,
    EUSICResponse, JapanSICResponse, UnifiedSICResponse,
    EdgarCIKResponse, EdgarDetailResponse, WikipediaResponse,
    MergedFirmographicsResponse
)

# -------------------------------------------------------------- #
# BEGIN: Define query objects
sq = SICQueries()
eq = EdgarQueries()
wq = WikipediaQueries()
gq = GeneralQueries()
uksq = UKSICQueries()
isicsq = InternationalSICQueries()
eusicsq = EuSICQueries()
japansicsq = JapanSICQueries()
unified_sic_q = UnifiedSICQueries()
# END: Define query objects
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: Helper functions
def _check_status_and_return(result_data, resource_name):
    """Check status code and return appropriate response"""
    return_code = result_data.get('code')
    result_count = result_data.get('total')
    return_msg = result_data.get('message')
    if return_code != 200:
        logger.error(f'There were [{result_count}] results for resource [{resource_name}].')
        raise HTTPException(
            status_code=return_code,
            detail=return_msg or f"Error retrieving {resource_name}"
        )
    return result_data

async def _handle_request(handler, func, query_value, *args, **kwargs):
    """Generic request handler for all endpoints"""
    handler.query = query_value
    
    # If the function is async, await it, otherwise call it directly
    if asyncio.iscoroutinefunction(func):
        data = await func(*args, **kwargs)
    else:
        data = func(*args, **kwargs)
        
    checked_data = _check_status_and_return(data, query_value)
    return checked_data

def get_abs_path(relative_path):
    """Convert relative paths to absolute paths based on script location"""
    base_dir = PathLib(__file__).resolve().parent
    return os.path.join(base_dir, relative_path)
# END: Helper functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: Initialize FastAPI app
app = FastAPI(
    title="company_dns API",
    description="Company firmographics and SIC code lookup service",
    version="3.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=True,
    expose_headers=["Content-Type", "X-Custom-Header"]
)

# Add security middleware
app.middleware("http")(security_middleware)

# Add logging middleware
app.middleware("http")(logging_middleware)

# Add rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_error_handler)

# Add custom 404 handler for HTTPExceptions
@app.exception_handler(StarletteHTTPException)
async def not_found_handler(request: Request, exc: StarletteHTTPException):
    # Only handle 404 errors
    if exc.status_code != 404:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail}
        )
    
    # Always serve the HTML 404 page
    try:
        # Use relative path so get_abs_path resolves within the project
        with open(get_abs_path('html/404.html'), 'r') as f:
            html_content = f.read()
        return HTMLResponse(
            content=html_content,
            status_code=404
        )
    except Exception as e:
        # Log full stack trace so the server console shows the root cause
        logger.error(f"Failed to serve custom 404 page: {e}", exc_info=True)
        # Fallback to JSON if file not found
        return JSONResponse(
            status_code=404,
            content={
                "detail": "Not found, invalid endpoint, fallback response",
                "code": 404,
                "path": str(request.url.path),
                "help": "Visit /docs for API documentation",
            }
        )
# END: Initialize FastAPI app
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: Standard Industry Classification (SIC) database cache functions
@app.get(
    "/V2.0/sic/description/{sic_desc}",
    response_model=SICResponse,
    tags=["SIC - US (V2.0)"],
    summary="Get SIC codes by description"
)
@app.get(
    "/V3.0/na/sic/description/{sic_desc}",
    response_model=SICResponse,
    tags=["SIC - US (V3.0)"],
    summary="Get SIC codes by description"
)
async def sic_description(sic_desc: str = Path(..., min_length=2, description="SIC description to search")):
    return await _handle_request(sq, sq.get_all_sic_by_name, sic_desc)

@app.get(
    "/V2.0/sic/code/{sic_code}",
    response_model=SICResponse,
    tags=["SIC - US (V2.0)"],
    summary="Get SIC by code"
)
@app.get(
    "/V3.0/na/sic/code/{sic_code}",
    response_model=SICResponse,
    tags=["SIC - US (V3.0)"],
    summary="Get SIC by code"
)
async def sic_code(sic_code: str = Path(..., description="SIC code number")):
    return await _handle_request(sq, sq.get_all_sic_by_no, sic_code)

@app.get(
    "/V2.0/sic/division/{division_code}",
    response_model=DivisionResponse,
    tags=["SIC - US (V2.0)"],
    summary="Get division by code"
)
@app.get(
    "/V3.0/na/sic/division/{division_code}",
    response_model=DivisionResponse,
    tags=["SIC - US (V3.0)"],
    summary="Get division by code"
)
async def division_code(division_code: str = Path(..., description="Division code")):
    return await _handle_request(sq, sq.get_division_desc_by_id, division_code)

@app.get(
    "/V2.0/sic/industry/{industry_code}",
    response_model=SICResponse,
    tags=["SIC - US (V2.0)"],
    summary="Get industry group by code"
)
@app.get(
    "/V3.0/na/sic/industry/{industry_code}",
    response_model=SICResponse,
    tags=["SIC - US (V3.0)"],
    summary="Get industry group by code"
)
async def industry_code(industry_code: str = Path(..., description="Industry code")):
    return await _handle_request(sq, sq.get_all_industry_group_by_no, industry_code)

@app.get(
    "/V2.0/sic/major/{major_code}",
    response_model=SICResponse,
    tags=["SIC - US (V2.0)"],
    summary="Get major group by code"
)
@app.get(
    "/V3.0/na/sic/major/{major_code}",
    response_model=SICResponse,
    tags=["SIC - US (V3.0)"],
    summary="Get major group by code"
)
async def major_code(major_code: str = Path(..., description="Major group code")):
    return await _handle_request(sq, sq.get_all_major_group_by_no, major_code)
# END: Standard Industry Classification (SIC) database cache functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: UK Standard Industry Classification (SIC) database cache functions
@app.get(
    "/V3.0/uk/sic/description/{uk_sic_desc}",
    response_model=UKSICResponse,
    tags=["SIC - UK (V3.0)"],
    summary="Get UK SIC by description"
)
async def uk_sic_description(uk_sic_desc: str = Path(..., min_length=2, description="UK SIC description")):
    return await _handle_request(uksq, uksq.get_uk_sic_by_name, uk_sic_desc)

@app.get(
    "/V3.0/uk/sic/code/{uk_sic_code}",
    response_model=UKSICResponse,
    tags=["SIC - UK (V3.0)"],
    summary="Get UK SIC by code"
)
async def uk_sic_code(uk_sic_code: str = Path(..., description="UK SIC code")):
    return await _handle_request(uksq, uksq.get_uk_sic_by_code, uk_sic_code)
# END: UK Standard Industry Classification (SIC) database cache functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: International Standard Industry Classification (ISIC) database cache functions
@app.get(
    "/V3.0/international/sic/section/{section_code}",
    response_model=ISICResponse,
    tags=["SIC - International (V3.0)"],
    summary="Get ISIC section by code"
)
async def international_sic_section(section_code: str = Path(..., description="ISIC section code")):
    return await _handle_request(isicsq, isicsq.get_section_by_code, section_code)

@app.get(
    "/V3.0/international/sic/division/{division_code}",
    response_model=ISICResponse,
    tags=["SIC - International (V3.0)"],
    summary="Get ISIC division by code"
)
async def international_sic_division(division_code: str = Path(..., description="Division code")):
    return await _handle_request(isicsq, isicsq.get_division_by_code, division_code)

@app.get(
    "/V3.0/international/sic/group/{group_code}",
    response_model=ISICResponse,
    tags=["SIC - International (V3.0)"],
    summary="Get ISIC group by code"
)
async def international_sic_group(group_code: str = Path(..., description="Group code")):
    return await _handle_request(isicsq, isicsq.get_group_by_code, group_code)

@app.get(
    "/V3.0/international/sic/class/{class_code}",
    response_model=ISICResponse,
    tags=["SIC - International (V3.0)"],
    summary="Get ISIC class by code"
)
async def international_sic_class(class_code: str = Path(..., description="ISIC class code")):
    return await _handle_request(isicsq, isicsq.get_class_by_code, class_code)

@app.get(
    "/V3.0/international/sic/description/{class_desc}",
    response_model=ISICResponse,
    tags=["SIC - International (V3.0)"],
    summary="Get ISIC by description"
)
async def international_sic_class_description(class_desc: str = Path(..., min_length=2, description="Industry description")):
    return await _handle_request(isicsq, isicsq.get_class_by_description, class_desc)
# END: International Standard Industry Classification (ISIC) database cache functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: EU Standard Industry Classification (NACE) database cache functions
@app.get(
    "/V3.0/eu/sic/section/{section_code}",
    response_model=EUSICResponse,
    tags=["SIC - EU/NACE (V3.0)"],
    summary="Get EU NACE section by code"
)
async def eu_sic_section(section_code: str = Path(..., description="NACE section code")):
    return await _handle_request(eusicsq, eusicsq.get_section_by_code, section_code)

@app.get(
    "/V3.0/eu/sic/division/{division_code}",
    response_model=EUSICResponse,
    tags=["SIC - EU/NACE (V3.0)"],
    summary="Get EU NACE division by code"
)
async def eu_sic_division(division_code: str = Path(..., description="EU NACE division code")):
    return await _handle_request(eusicsq, eusicsq.get_division_by_code, division_code)

@app.get(
    "/V3.0/eu/sic/group/{group_code}",
    response_model=EUSICResponse,
    tags=["SIC - EU/NACE (V3.0)"],
    summary="Get EU NACE group by code"
)
async def eu_sic_group(group_code: str = Path(..., description="NACE group code")):
    return await _handle_request(eusicsq, eusicsq.get_group_by_code, group_code)

@app.get(
    "/V3.0/eu/sic/class/{class_code}",
    response_model=EUSICResponse,
    tags=["SIC - EU/NACE (V3.0)"],
    summary="Get EU NACE by class code"
)
async def eu_sic_class(class_code: str = Path(..., description="NACE class code")):
    return await _handle_request(eusicsq, eusicsq.get_class_by_code, class_code)

@app.get(
    "/V3.0/eu/sic/description/{class_desc}",
    response_model=EUSICResponse,
    tags=["SIC - EU/NACE (V3.0)"],
    summary="Get EU NACE by description"
)
async def eu_sic_class_description(class_desc: str = Path(..., min_length=2, description="Class description")):
    return await _handle_request(eusicsq, eusicsq.get_class_by_description, class_desc)
# END: EU Standard Industry Classification (NACE) database cache functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: Japan Standard Industry Classification database cache functions
@app.get(
    "/V3.0/japan/sic/division/{division_code}",
    response_model=JapanSICResponse,
    tags=["SIC - Japan (V3.0)"],
    summary="Get Japan SIC division by code"
)
async def japan_sic_division(division_code: str = Path(..., description="Division code")):
    return await _handle_request(japansicsq, japansicsq.get_division_by_code, division_code)

@app.get(
    "/V3.0/japan/sic/major_group/{major_group_code}",
    response_model=JapanSICResponse,
    tags=["SIC - Japan (V3.0)"],
    summary="Get Japan SIC major group by code"
)
async def japan_sic_major_group(major_group_code: str = Path(..., description="Major group code")):
    return await _handle_request(japansicsq, japansicsq.get_major_group_by_code, major_group_code)

@app.get(
    "/V3.0/japan/sic/group/{group_code}",
    response_model=JapanSICResponse,
    tags=["SIC - Japan (V3.0)"],
    summary="Get Japan SIC group by code"
)
async def japan_sic_group(group_code: str = Path(..., description="Group code")):
    return await _handle_request(japansicsq, japansicsq.get_group_by_code, group_code)

@app.get(
    "/V3.0/japan/sic/industry_group/{industry_code}",
    response_model=JapanSICResponse,
    tags=["SIC - Japan (V3.0)"],
    summary="Get Japan SIC industry group by code"
)
async def japan_sic_industry_group(industry_code: str = Path(..., description="Industry code")):
    return await _handle_request(japansicsq, japansicsq.get_industry_group_by_code, industry_code)

@app.get(
    "/V3.0/japan/sic/description/{industry_desc}",
    response_model=JapanSICResponse,
    tags=["SIC - Japan (V3.0)"],
    summary="Get Japan SIC industry by description"
)
async def japan_sic_industry_group_description(industry_desc: str = Path(..., min_length=2, description="Industry description")):
    return await _handle_request(japansicsq, japansicsq.get_industry_group_by_description, industry_desc)
# END: Japan Standard Industry Classification database cache functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: Unified Standard Industry Classification database cache functions
@app.get(
    "/V3.0/global/sic/description/{query_string}",
    response_model=UnifiedSICResponse,
    tags=["SIC - Unified Global (V3.0)"],
    summary="Search all SIC systems by description"
)
async def unified_sic_description(query_string: str = Path(..., min_length=2, description="Search query across all SIC systems")):
    return await _handle_request(unified_sic_q, unified_sic_q.search_all_descriptions, query_string)
# END: Unified Standard Industry Classification database cache functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: EDGAR database cache functions
@app.get(
    "/V2.0/companies/edgar/detail/{company_name}",
    response_model=EdgarDetailResponse,
    tags=["EDGAR (V2.0)"],
    summary="Get detailed EDGAR company information"
)
@app.get(
    "/V3.0/na/companies/edgar/detail/{company_name}",
    response_model=EdgarDetailResponse,
    tags=["EDGAR (V3.0)"],
    summary="Get detailed EDGAR company information"
)
async def edgar_detail(company_name: str = Path(..., min_length=1, description="Company name to search")):
    return await _handle_request(eq, eq.get_all_details, company_name)

@app.get(
    "/V2.0/companies/edgar/summary/{company_name}",
    response_model=EdgarDetailResponse,
    tags=["EDGAR (V2.0)"],
    summary="Get EDGAR company summary"
)
@app.get(
    "/V3.0/na/companies/edgar/summary/{company_name}",
    response_model=EdgarDetailResponse,
    tags=["EDGAR (V3.0)"],
    summary="Get EDGAR company summary"
)
async def edgar_summary(company_name: str = Path(..., min_length=1, description="Company name")):
    return await _handle_request(eq, eq.get_all_details, company_name, firmographics=False)

@app.get(
    "/V2.0/companies/edgar/ciks/{company_name}",
    response_model=EdgarCIKResponse,
    tags=["EDGAR (V2.0)"],
    summary="Get CIK numbers for company"
)
@app.get(
    "/V3.0/na/companies/edgar/ciks/{company_name}",
    response_model=EdgarCIKResponse,
    tags=["EDGAR (V3.0)"],
    summary="Get CIK numbers for company"
)
async def edgar_ciks(company_name: str = Path(..., min_length=1, description="Company name")):
    return await _handle_request(eq, eq.get_all_ciks, company_name)

@app.get(
    "/V2.0/company/edgar/firmographics/{cik_no}",
    response_model=EdgarDetailResponse,
    tags=["EDGAR (V2.0)"],
    summary="Get firmographics by CIK number"
)
@app.get(
    "/V3.0/na/company/edgar/firmographics/{cik_no}",
    response_model=EdgarDetailResponse,
    tags=["EDGAR (V3.0)"],
    summary="Get firmographics by CIK number"
)
async def edgar_firmographics(cik_no: str = Path(..., description="10-digit CIK number")):
    return await _handle_request(eq, eq.get_firmographics, cik_no)
# END: EDGAR database cache functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: Wikipedia functions
@app.get(
    "/V2.0/company/wikipedia/firmographics/{company_name}",
    response_model=WikipediaResponse,
    tags=["Wikipedia (V2.0)"],
    summary="Get company firmographics from Wikipedia"
)
@app.get(
    "/V3.0/global/company/wikipedia/firmographics/{company_name}",
    response_model=WikipediaResponse,
    tags=["Wikipedia (V3.0)"],
    summary="Get company firmographics from Wikipedia"
)
async def wikipedia_firmographics(company_name: str = Path(..., min_length=1, description="Company name")):
    return await _handle_request(wq, wq.get_firmographics, company_name)
# END: Wikipedia functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: General query functions (merged data from all sources)
@app.get(
    "/V2.0/company/merged/firmographics/{company_name}",
    response_model=MergedFirmographicsResponse,
    tags=["Merged Data (V2.0)"],
    summary="Get merged firmographics from all sources"
)
@app.get(
    "/V3.0/global/company/merged/firmographics/{company_name}",
    response_model=MergedFirmographicsResponse,
    tags=["Merged Data (V3.0)"],
    summary="Get merged firmographics from all sources"
)
async def general_query(company_name: str = Path(..., min_length=1, description="Company name")):
    return await _handle_request(gq, gq.get_firmographics, company_name)
# END: General query functions
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: Utility endpoints
@app.get("/", include_in_schema=False)
async def root():
    """Serve the main UI"""
    return FileResponse(get_abs_path('html/index.html'))

@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint for monitoring"""
    return {
        "status": "healthy",
        "version": "3.2.0",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
# END: Utility endpoints
# -------------------------------------------------------------- #

# -------------------------------------------------------------- #
# BEGIN: Mount static files
# Serve static assets (CSS, JS, etc.)
app.mount("/static", StaticFiles(directory=get_abs_path('html')), name="static")
# -------------------------------------------------------------- #

if __name__ == "__main__": 
    try:
        # In development (local)
        if os.environ.get('ENVIRONMENT') == 'dev':
            host = '127.0.0.1'
        else:
            # In production (container)
            host = '0.0.0.0'  # Accept connections from any IP
            
        uvicorn.run(
            app, 
            host=host,
            port=8000, 
            log_level='info',
            access_log=True
        )
    except KeyboardInterrupt:
        logger.info("Server was shut down by the user.")