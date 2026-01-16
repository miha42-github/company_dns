# company_dns Web Application

A modern, responsive single-page application (SPA) for exploring SEC EDGAR filings and industry classifications. Built with Alpine.js for reactive components and styled with a dark theme optimized for data exploration.

## Overview

The web application consists of three main explorers accessible via tabbed interface:

1. **Help Tab** — API documentation, endpoint reference, and feature walkthroughs
2. **Industry Classification Explorer** — Search and cross-reference industry codes across multiple classification systems (US SIC, UK SIC, EU NACE, ISIC, Japan SIC)
3. **EDGAR Explorer** — Search SEC filings by company name or CIK, with filtering and quick access to SEC resources

## Architecture

### Technology Stack

- **Frontend Framework**: Alpine.js 3.x — Lightweight reactive component framework
- **Styling**: Single unified CSS file (1533 lines) with CSS custom properties system
- **HTTP Client**: APIService class for consistent request handling and caching
- **Base Class**: ExplorerBase for shared pagination and keyboard navigation logic
- **Modal System**: JSON viewer modal for detailed data inspection

### File Structure

```
html/
├── index.html                    # Main application (788 lines)
├── styles.css                    # Unified styles (1533 lines)
├── 404.html                      # Error page
├── endpoint-data.js              # API endpoint metadata
├── favicon_sizes/                # App icons
├── js/
│   ├── alpine.min.js            # Alpine.js framework
│   ├── api-service.js           # API client with caching
│   ├── explorer-base.js         # Shared explorer logic
│   ├── functions.js             # Tab and utility functions
│   ├── global-search-alpine.js  # Industry search component (732 lines)
│   ├── edgar-explorer-alpine.js # EDGAR search component (404 lines)
│   └── feather.min.js           # Icon library
└── README.md                     # This file
```

## Features

### 1. Industry Classification Explorer

**Purpose**: Search industry codes across 5 classification systems simultaneously

**Features**:
- Full-text search by keyword (e.g., "manufacturing", "software")
- Results include all matching codes from:
  - US Standard Industrial Classification (SIC)
  - UK Standard Industrial Classification (SIC)
  - EU Statistical Classification of Economic Activities (NACE Rev 2.1)
  - UN International Standard Industrial Classification (ISIC Rev 5)
  - Japan Standard Industry Classification
- Expandable cards showing code details
- Filter results by classification system
- Pagination (10, 25, 50, or 100 items per page)
- Keyboard navigation (arrow keys for pagination, Home/End for first/last page)

**Search Example**:
```
Query: "banking"
Results: 100+ matches across all systems
├─ US SIC: 6022, 6029, 6081, 6082...
├─ UK SIC: 64.19, 64.99...
├─ EU NACE: 64.11, 64.19, 64.30...
├─ ISIC: 6419, 6499...
└─ Japan SIC: 6020, 6070, 6085...
```

**Implementation**: `global-search-alpine.js`
- Calls `/V3.0/global/sic/description/{query}` endpoint
- Results cached for 10 minutes
- Dynamic filter tabs update as results load
- State persisted in URL query parameters

### 2. EDGAR Explorer

**Purpose**: Search SEC EDGAR filings by company and access related resources

**Features**:
- Search by company name or CIK number
- Fast SQLite-cached results (2 seconds vs 118 seconds for API)
- Sidebar filters:
  - Has 10-K (annual reports)
  - Recent 10-Q (quarterly reports within 90 days)
  - Division filter (from SIC data)
  - Fiscal year end filter
- Compact result cards showing:
  - Company name, CIK, total filing count
  - Top 3 most recent forms as clickable pills
  - Quick action links to SEC resources
- Pagination with keyboard navigation

**Result Card Structure**:
```
┌─────────────────────────────────────────────────┐
│ Company: APPLE INC                   [View JSON]│
│ CIK: 320193  •  Total Filings: 2,471            │
├─────────────────────────────────────────────────┤
│ Recent Forms:                                   │
│ [10-Q 2025-5-30]  [10-Q 2025-3-1]  [10-K 2024]  │
├─────────────────────────────────────────────────┤
│ [Browse EDGAR] [Issuer Transactions] [Insider]. │
└─────────────────────────────────────────────────┘
```

**Card Elements**:
- **Browse EDGAR**: Opens company filings browser on sec.gov
- **Issuer Transactions**: Insider transactions filed by the company
- **Insider Trades**: Insider transactions by beneficial owner
- **View JSON**: Opens JSON modal with full raw data

**Implementation**: `edgar-explorer-alpine.js`
- Uses `/V3.0/na/companies/edgar/summary/` endpoint (SQLite cache)
- Falls back to `/V3.0/na/company/edgar/firmographics/` for CIK lookups
- Transforms API response to flat company items with recent forms
- Constructs SEC URLs via `buildEdgarUrls()` function

### 3. Help Tab

**Content Sections**:
- API Reference with endpoint documentation
- Version-specific endpoint tables (V3.0, V2.0)
- Feature walkthroughs for both explorers
- Code examples with copy-to-clipboard buttons
- Additional resources links (GitHub, Apache License)

## CSS Architecture

### Design Principles

1. **CSS Custom Properties**: Centralized color, spacing, and typography system
2. **Explicit Height Constraints**: Flexbox hierarchy uses `calc(100vh - X)` heights
3. **Scrolling Model**: Single scroll container per explorer with pagination fixed at bottom
4. **Dark Theme**: Optimized for data exploration with high contrast

### Color System

```css
--color-bg-primary:      #0F0D0E  /* Base background */
--color-bg-secondary:    #1a1718  /* Cards, panels */
--color-bg-tertiary:     #3c3b3b  /* Borders, separators */

--color-text-primary:    #e0dede  /* Main text */
--color-text-secondary:  #a8a0a0  /* Secondary text */
--color-text-accent:     #1696c8  /* Links, highlights */

--color-link-primary:    #1696c8  /* Blue links (industry) */
--color-orange:          #ca703f  /* Orange (EDGAR) */
--color-brown:           #924e29  /* Brown (action buttons) */
```

### Height Constraint Hierarchy

The explorer layout uses explicit viewport-relative heights to prevent overflow:

```
.explorer-pagecontent
  max-height: calc(100vh - 100px)  ← Top-level cap
  
  .explorer-results-filters
    height: calc(100vh - 290px)    ← Middle container
    
    .explorer-sidebar
      height: calc(100vh - 290px)  ← Sidebar with scroll
      overflow-y: auto
    
    .explorer-results-area
      flex: 1 1 auto               ← Flexible results
      
      .explorer-results-container
        height: calc(100vh - 360px) ← Content container
        overflow-y: auto            ← Internal scroll
    
    .pagination-controls
      flex: 0 0 auto               ← Fixed at bottom
      min-height: 50px
```

This ensures:
- Content scrolls within results area
- Pagination always remains visible at bottom
- Title never hidden by results overflow

## JavaScript Components

### APIService (api-service.js)

**Purpose**: Centralized HTTP client with caching and error handling

**Methods**:
- `get(endpoint, options)` — Fetch with timeout and cache support
- `searchIndustryCodes(query)` — Industry search endpoint
- `getSICDetails(code)` — SIC code details
- `getHealth()` — Service health check
- `clearCache()` / `clearCacheFor(endpoint)` — Cache management

**Features**:
- 30-second default timeout (configurable per request)
- Automatic request/response logging
- Persistent caching with expiration
- Consistent error handling via APIError class

### ExplorerBase (explorer-base.js)

**Purpose**: Shared base class for all explorer components

**Pagination Methods**:
- `firstPage()`, `prevPage()`, `nextPage()`, `lastPage()`
- `goToPage(pageNum)` — Jump to specific page
- `getVisiblePages()` — Returns 5-button window around current page

**Helpers**:
- `getResultsHeadline()` — "42 results" or status message
- `getResultsRangeLabel()` — "Showing 1-10 of 42"
- `getActiveFiltersLabel()` — Filter summary (overridden by subclasses)

**Keyboard Navigation**:
- ArrowLeft/Right — Previous/Next page
- Home/End — First/Last page
- Ignores input in form fields

**Display Management**:
- `scrollToResults(elementId)` — Smooth scroll to results
- `showResultsLayout()` / `showSearchLayout()` — Toggle views

**Modal Integration**:
- `showJsonModal(resultData)` — Opens JSON viewer

### Global Search Component (global-search-alpine.js)

**Alpine.js Component** created via `createGlobalSearchComponent()`

**State Properties**:
- `searchQuery` — Current search term
- `allResults` — All results from API
- `filteredResults` — After filter application
- `filters` — Boolean for each classification system
- `filterCounts` — Result count per system
- `currentPage`, `resultsPerPage`, `totalPages` — Pagination state
- `expandedCards` — Which result cards are expanded
- `pageSizes` — [10, 25, 50, 100]

**Methods**:
- `performSearch()` — Execute search, transform results
- `applyFilters()` — Filter by selected systems
- `toggleExpanded(key)` — Expand/collapse card
- `changePageSize(size)` — Update resultsPerPage
- `loadStateFromUrl()` — Restore state from URL params
- `updateUrlState()` — Persist state to URL

**Search Results Format**:
```javascript
{
  code: "6020",                    // Code in that system
  description: "Banking services", // Full description
  system: "US SIC",                // Classification system
  url: "...",                      // Link to details
  expandedDescription: "..."       // Detailed info
}
```

### EDGAR Component (edgar-explorer-alpine.js)

**Alpine.js Component** created via `createEdgarExplorerComponent()`

**State Properties**:
- `searchQuery` — Company name or CIK
- `allItems` — All companies from search
- `filteredResults` — After filter application
- `filters` — Checkboxes for Has 10K, Recent 10Q, plus dropdowns for Division/FYE
- `availableDivisions`, `availableFiscalYearEnds` — Dynamic filter options
- Pagination state (inherited from base pattern)

**Key Methods**:
- `performSearch()` — Search endpoint, handle timeouts
- `transformSummaryToItems(data)` — API response to company items
- `buildEdgarUrls(cik)` — Construct SEC resource URLs
- `applyFilters()` — Filter by 10K/10Q/division/FYE
- `updateFilterOptions()` — Discover available divisions
- `getCurrentPageResults()` — Slice for current page

**Search Timeouts**:
- 60 seconds for summary endpoint (SQLite cache)
- Fallback to farmographics if CIK→name lookup needed

**URL Construction** via `buildEdgarUrls(cik)`:
```javascript
{
  browse: "https://www.sec.gov/cgi-bin/browse-edgar?CIK={cik}&action=getcompany",
  facts: "https://data.sec.gov/api/xbrl/companyfacts/CIK{paddedCik}.json",
  issuerTransactions: "https://www.sec.gov/cgi-bin/own-disp?action=getissuer&CIK={cik}",
  ownerTransactions: "https://www.sec.gov/cgi-bin/own-disp?action=getowner&CIK={cik}"
}
```

## Tab System

### Main Tabs

The page uses HTML `id` attributes for tab content and `.tabmenu` class for buttons:

```html
<button class="tabmenu" onclick="openTab(event, 'Home', 'help-pagecontent', 'tabmenu')">
  Help
</button>
<button class="tabmenu" onclick="openTab(event, 'GlobalSearch', 'explorer-pagecontent', 'tabmenu')">
  Industry Explorer
</button>
<button class="tabmenu" onclick="openTab(event, 'EdgarExplorer', 'explorer-pagecontent', 'tabmenu')">
  EDGAR Explorer
</button>
```

**Tab Function** (`functions.js`):
- `openTab(evt, tabName, tabContentClass, tabLinks)` — Hide all tabs of specified class, show selected

### Inner Tabs (API Documentation)

The Help tab has secondary tabs for API versions:

```html
<button class="tab" onclick="openInnerTab(event, 'V3', 'tabcontent', 'tab')">
  V3.0
</button>
```

**Function**: `openInnerTab()` — Same pattern as main tabs, scoped to inner class

## Styling Key Classes

### Explorer Layout

- `.explorer-pagecontent` — Main explorer container
- `.explorer-results-layout` — Post-search layout (initially hidden)
- `.explorer-search-container` — Initial centered search
- `.explorer-search-card` — Search input card
- `.explorer-results-filters` — Sidebar + results wrapper
- `.explorer-sidebar` — Left sidebar with filters
- `.explorer-results-area` — Results + header + pagination
- `.explorer-results-container` — Scrollable results content
- `.pagination-controls` — Pagination buttons

### Result Cards

#### Industry Results
- `.explorer-result-card` — Main card wrapper
- `.explorer-industry-row` — Single code with description
- `.industry-code-column` — Left column (codes by system)
- `.industry-description-column` — Right column (cross-references)

#### EDGAR Results
- `.explorer-result-card` — Main card wrapper
- `.edgar-company-header` — Company info + View JSON button
- `.edgar-company-info` — Name, CIK, filing count
- `.edgar-meta` — CIK/count labels
- `.edgar-recent-forms-compact` — Top 3 forms as pills
- `.edgar-pill-group` — Flex container for pills
- `.edgar-pill` — Individual form pill (blue/teal)
- `.edgar-quick-links` — Action button group
- `.edgar-quick-link` — Individual action button (orange/brown)

### Status & Messages

- `.results-status` — Results headline + range
- `.status-top` — "Results" label + count
- `.status-meta` — Range + filter summary
- `.explorer-error-message` — Error message display
- `.explorer-search-hint` — Help text below search

### Form Controls

- `.explorer-input` — Text input field
- `.explorer-button` — Search button
- `.explorer-filter-checkbox` — Checkbox with label
- `.explorer-filter-label` — Filter section header
- `.pagination-btn` — Pagination button

## Responsive Design

**Breakpoints**:
- `@media (max-width: 768px)` — Tablet/mobile adjustments
  - Pagination buttons change size/spacing
  - Text fields reduce padding
  - Cards stack better on small screens

**Key Responsive Classes**:
- `.explorer-input-group` — Uses flexbox for responsive layout
- `.pagination-controls` — Wraps buttons on narrow screens
- `.edgar-quick-links` — Flex-wrap for compact display

## Modal System

### JSON Viewer Modal

**Function**: `createJsonModal()` (created in `init()`)

**Features**:
- Displays raw JSON data for any result
- Syntax highlighting (styled as code block)
- Copy-to-clipboard button
- Close button (click outside or button)
- Dark theme styling

**Trigger**:
```javascript
viewItemJson(item)  // Called by View JSON button
```

## Performance Optimizations

### Caching Strategy

**Industry Search**:
- Cache duration: 10 minutes
- Invalidates after expiry
- Useful for repeated searches

**SIC Details**:
- Cache duration: 24 hours
- Static data changes rarely
- Reduces API load

**Health Checks**:
- No caching
- Direct API call each time

### API Endpoints Used

**Industry Explorer**:
- `GET /V3.0/global/sic/description/{query}` — Search all systems

**EDGAR Explorer**:
- `GET /V3.0/na/companies/edgar/summary/{company_name}` — Fast search (SQLite)
- `GET /V3.0/na/company/edgar/firmographics/{cik}` — CIK lookup

## Known Limitations

### Current Implementation

1. **EDGAR Recent Forms**: Limited to top 10 forms in database (summary endpoint constraint)
2. **Filter Discovery**: EDGAR filters based on available data in current index
3. **Mobile UX**: Optimized for desktop/tablet, small phone screens may be crowded
4. **Search Cache**: No cache invalidation signal from backend (24-hour maximum staleness)

## Future Enhancement Possibilities

1. **Favorite/Bookmark Feature** — Save frequent searches or companies
2. **Export Results** — CSV/JSON export of search results
3. **Advanced Filters** — Date range, filing type combinations, multi-value dropdowns
4. **Company Comparison** — Side-by-side EDGAR data for 2+ companies
5. **Watchlist** — Track specific companies for new filings
6. **Mobile App** — React Native version for mobile

## Developer Notes

### Testing Changes

After modifying JavaScript or CSS:

1. **Hard refresh** in browser 
2. **Docker rebuild** if serving from container: `./svc_ctl.sh rebuild`
3. **Check console** for JavaScript errors (F12 → Console tab)

### Adding New Explorers

To add a new explorer type:

1. Create Alpine.js component function in `js/{name}-explorer-alpine.js`
2. Extend `ExplorerBase` or implement pagination/keyboard handling
3. Add HTML structure in `index.html` with explorer tabs
4. Add tab button in header
5. Import JavaScript file in `<head>` of `index.html`
6. Add CSS classes to `styles.css` as needed

### Modifying CSS

All styles are in single `styles.css` file:

1. Update existing class or add new class
2. Use CSS custom properties for colors/spacing
3. Hard refresh browser to see changes
4. Test both explorers for layout consistency

## Related Files

- `../README.md` — Main project documentation
