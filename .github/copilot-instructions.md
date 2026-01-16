# Company DNS - Copilot Instructions

## Project Overview

**company_dns** is a FastAPI service synthesizing corporate data from SEC EDGAR and Wikipedia with built-in security hardening (rate limiting, malicious request blocking, request validation). It provides REST APIs for company information lookup, SIC/NACE/ISIC classification queries, and a modern web SPA for interactive exploration.

- **Core entry**: `company_dns.py` (FastAPI app with 550+ lines, 30+ endpoints)
- **Architecture**: Query classes per domain (`EdgarQueries`, `SICQueries`, `WikipediaQueries`, `GeneralQueries`, etc.)
- **Web UI**: Alpine.js SPA with three explorers (Industry Classification, EDGAR, Help tabs)
- **Deployment**: Docker (Python 3.13-alpine) + `svc_ctl.sh` orchestration

## Architecture & Data Flow

### Core Query Classes Pattern (`lib/`)
Each data domain has a dedicated query class with consistent interface:

```python
class DomainQueries:
    def __init__(self, database=None, name='', description=''):
        self.database = database  # Optional SQLite connection
    
    def method_name(self, param) -> dict:
        # Always return: {"code": 200, "message": "...", "module": "...", "data": {...}, "dependencies": {...}}
        pass
```

**Key classes**:
- `EdgarQueries` (`edgar.py`): SEC filing lookups via pyedgar, caches CIK data in SQLite
- `SICQueries` (`sic.py`): US Standard Industrial Classification codes (4-digit hierarchy)
- `UKSICQueries`, `EuSICQueries`, `InternationalSICQueries`, `JapanSICQueries`: Regional classification variants
- `UnifiedSICQueries` (`unified_sic.py`): Cross-system classification matching
- `GeneralQueries` (`firmographics.py`): Merged company data from Wikipedia + EDGAR + geolocation
- `WikipediaQueries` (`wikipedia.py`): Wikipedia page fetching via wptools

### Response Format (Universal)
All endpoints return this structure (defined in `lib/models.py` as `BaseAPIResponse`):
```json
{
  "code": 200,
  "message": "Success",
  "module": "ModuleName->method_name",
  "data": { /* endpoint-specific */ },
  "dependencies": {
    "modules": { "module_name": "source_url" },
    "data": { "dataset_name": "source_url" }
  }
}
```

### FastAPI Endpoint Convention (`company_dns.py`)
- **Route structure**: `/V3.0/{domain}/{resource_type}/{query_type}/{value}`
- **Generic handler** `_handle_request()`: converts sync/async query methods to HTTP responses
- **Error handling**: `_check_status_and_return()` raises HTTPException on non-200 codes
- **Path validation**: Security middleware blocks 70+ malicious patterns (WordPress probes, SQL injection, etc.) before reaching handlers

## Critical Workflows

### Database Management
- **Cache file**: `companies.db` (SQLite)
- **Creation**: `python makedb.py` runs `lib/prepare_*.py` scripts to populate tables
- **Docker**: Dockerfile auto-runs `makedb.py` during build
- **Rebuild**: `./svc_ctl.sh rebuild` rebuilds image + restarts container

### Service Control (`./svc_ctl.sh`)
```bash
./svc_ctl.sh build       # Build Docker image
./svc_ctl.sh start       # Start container in background
./svc_ctl.sh foreground  # Run in foreground (interactive)
./svc_ctl.sh rebuild     # Full rebuild + restart
./svc_ctl.sh tail        # View container logs
./svc_ctl.sh stop        # Graceful shutdown
./svc_ctl.sh cleanup     # Remove stopped containers
```

### Data Preparation
- `prepare_*.py` scripts populate SQLite from CSV/TSV source data (in `source_data/`)
- Runs once during `makedb.py`, loaded into memory at startup
- **Example**: `prepare_sic_data.py` → loads `sic-codes.csv`, `divisions.csv`, etc.

## Security Implementation

**Three-layer protection**:

1. **Security Middleware** (`lib/security_middleware.py`, 212 lines)
   - Blocks requests with blocked patterns (returns 403)
   - Examples: `/wp-login.php`, `xmlrpc`, `../etc/passwd`, SQL injection syntax
   - Must run **before** rate limiting (see middleware order in `company_dns.py`)

2. **Rate Limiting** (`lib/rate_limiter.py`)
   - IP-based limiting via slowapi: `/docs` (1000/min), `/sic/` (200/min), firmographics (100/min)
   - Custom error handler returns 429 with retry info
   - Applied per-endpoint with `@limiter.limit()` decorator

3. **Input Validation** (`lib/models.py`)
   - All responses validated against `BaseAPIResponse` Pydantic model
   - FastAPI auto-validates request Path/Query parameters (min_length, regex, etc.)

## Web Application Architecture (`html/`)

### Structure
- **index.html** (788 lines): Main SPA, loads tabs dynamically
- **styles.css** (1533 lines): Unified dark theme with CSS variables
- **js/** directory:
  - `api-service.js`: HTTP client with 10-min caching
  - `explorer-base.js`: Shared pagination + keyboard nav (arrow keys, Home/End)
  - `global-search-alpine.js` (732 lines): Industry code search across 5 systems
  - `edgar-explorer-alpine.js` (404 lines): Company/filing search
  - `functions.js`: Tab switching, utility helpers

### Three Main Explorers
1. **Help Tab**: API docs, endpoint reference
2. **Industry Classification Explorer**: Search SIC/NACE/ISIC codes, results cached 10 min
3. **EDGAR Explorer**: Search companies by name/CIK, links to SEC resources

### Alpine.js Pattern
Components use `x-data` for reactive state, `@click` for events, `x-show`/`x-if` for conditionals:
```javascript
// In HTML: x-data="globalSearch()"
function globalSearch() {
  return {
    query: '',
    results: [],
    async search() { /* calls /V3.0/global/sic/description/{query} */ }
  }
}
```

## File Organization

```
lib/
  ├── models.py              # Pydantic BaseAPIResponse + aliases
  ├── db_functions.py        # SQLite open/close/create
  ├── security_middleware.py # 70+ malicious pattern blocking
  ├── rate_limiter.py        # IP-based rate limiting config
  ├── logging_config.py      # Structured logging setup
  ├── edgar.py               # SEC EDGAR queries (481 lines)
  ├── sic.py                 # US SIC classification
  ├── uk_sic.py, eu_sic.py, international_sic.py, japan_sic.py
  ├── unified_sic.py         # Cross-system matching
  ├── firmographics.py       # Merged company data (669 lines)
  ├── wikipedia.py           # Wikipedia fetching
  └── prepare_*.py           # Data initialization scripts

scripts/
  └── entrypoint.sh          # Container startup

source_data/
  ├── edgar_data/            # EDGAR TAB file (cached monthly)
  ├── sic_data/              # US classification CSVs
  ├── uk_sic_data/, eu_sic_data/, international_sic_data/, japan_sic_data/
  └── (All converted to SQLite by prepare_*.py)
```

## Adding New Features

### New SIC Classification System
1. Add `prepare_xx_sic_data.py` to load source data → SQLite
2. Create `lib/xx_sic.py` with query class following `SICQueries` pattern
3. Add endpoints in `company_dns.py`: `@app.get("/V3.0/xx-sic/{type}/{value}")`
4. Use `@limiter.limit("200/minute")` for SIC-style endpoints

### New API Endpoint
1. Determine if it uses existing query class or needs new one
2. Define Pydantic response model (or reuse `BaseAPIResponse`)
3. Create endpoint handler with `@app.get()`, `@limiter.limit()`, type hints
4. Use `_handle_request()` for error standardization
5. Test with FastAPI auto-docs at `/docs`

## Testing & Debugging

### Local Development
1. `pip install -r requirements.txt`
2. `python makedb.py` (creates `companies.db`)
3. `python company_dns.py` (starts uvicorn on 0.0.0.0:8000)
4. Visit `http://localhost:8000/docs` for Swagger UI

### Logging
- Configured in `lib/logging_config.py`
- Severity-based with request ID tracking
- Check `svc_ctl.sh tail` for Docker logs

### Database State
- Check `db.exists` file existence (created by `makedb.py`)
- Recreate DB: `rm companies.db db.exists && python makedb.py`

## Key Dependencies & Integration Points

| Dependency | Purpose | Integration |
|---|---|---|
| `fastapi` | ASGI framework | All endpoints |
| `pydantic` | Request/response validation | `lib/models.py` |
| `slowapi` | Rate limiting | `@limiter.limit()` decorators |
| `pyedgar` | SEC EDGAR API | `EdgarQueries` class |
| `wptools` | Wikipedia scraping | `WikipediaQueries` class |
| `geopy.ArcGIS` | Geolocation | `GeneralQueries.firmographics()` |
| `sqlite3` | Caching database | All prepare_*.py, query classes |

## Common Pitfalls

- **Response format**: Must match `BaseAPIResponse` or client SPA breaks; always include `code`, `message`, `data`, `dependencies`
- **Rate limiting order**: Security middleware MUST run before rate limiter in middleware stack
- **Database availability**: Query classes expect tables created by `prepare_*.py`; missing tables return 500 errors
- **Path parameters**: Must use `Path(...)` in endpoint signature with validation rules (e.g., `min_length=2`)
- **Async handling**: `_handle_request()` auto-detects sync vs async query methods; no manual awaiting needed
