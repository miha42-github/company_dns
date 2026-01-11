# EDGAR Explorer — Planning Document

Status: Planning only (do not implement yet)

## Goals
- Provide a dedicated EDGAR Explorer to browse and query SEC filings (10‑K, 10‑Q, 8‑K, etc.) by Company Name or CIK.
- Reuse existing frontend stack and patterns from the Industry Classification Explorer.
- Use a list-only results view (no table) to match the Classification Explorer.
- Place filtering controls in the left sidebar only (none in the search bar).
- Include targeted filters like "Has 10‑K" and "Recent 10‑Q" (≤90 days), with centered pagination and a JSON modal viewer for raw responses.

## Dependencies & Integration
- CSS: `/static/styles.css` (use existing explorer/layout classes).
- Scripts (already loaded in `index.html`):
  - `/static/endpoint-data.js` (source of available endpoints; filter EDGAR-specific ones).
  - `/static/js/functions.js` (utilities: `openTab()`, `copyToClipboard()`, etc.).
  - `/static/js/api-service.js` (HTTP wrapper for calling API endpoints).
  - `/static/js/global-search-alpine.js` (reference patterns; do not depend on it).
  - `/static/js/alpine.min.js` (Alpine.js runtime).
- New script to be added later: `/static/js/edgar-explorer-alpine.js` providing `createEdgarExplorerComponent()`.

## New Tab & Page Structure
- Header button (menu): add a third explorer tab
  - `<button class="tabmenu" onclick="openTab(event, 'EdgarExplorer', 'explorer-pagecontent', 'tabmenu')">EDGAR Explorer</button>`
- Page content container (parity with GlobalSearch):
  - `<div id="EdgarExplorer" class="explorer-pagecontent" x-data="createEdgarExplorerComponent()" @load="init()"></div>`
- Two-phase layout:
  1. Initial centered search card (shown before first query)
  2. Post-search layout with sidebar filters + results area

## UX Overview
- Initial Search
  - Single input that accepts Company Name or CIK (auto-detect CIK if numeric).
  - No filtering controls in the search form (parity with the Industry Classification Explorer).
  - Search button reflects loading state.
- Results View
  - Sidebar Filters (left):
    - Checkbox: "Has 10‑K" — show items/companies with at least one 10‑K filing.
    - Checkbox: "Recent 10‑Q" — show 10‑Q filings with filing dates within the past 90 days.
    - Optional future filters can be added here without changing the search form.
  - Results List (no table):
    - Card-style list items similar to the Classification Explorer.
    - Prominent fields: Company, CIK, Filing Type, Filing Date.
    - Minimal secondary info: Accession No. (optional), primary Document link.
    - Actions: "View JSON" opens modal; "Open Document" in new tab.
  - Status header: “N results” + active filters + range label.
  - Centered pagination controls (First, Prev, numbered pages, Next, Last) using the simplified pattern.
  - JSON Modal Viewer
    - Reuse modal pattern: overlay + header close (no footer close), copy button centered with fixed width.
    - Content: pretty‑printed JSON from EDGAR response.

## Component Data Model (Alpine.js)
- `searchQuery`: string (company name or CIK)
- `filters`: { has10K: boolean, recent10Q: boolean }
- `pagination`: { currentPage: number, pageSize: number, totalPages: number }
- `isSearching`: boolean
- `errorMessage`: string|null
- `results`: Array<EdgarFiling>
- `hasResults`: boolean
- `modal`: { isOpen: boolean, json: object|null, title: string }
- `filterCounts`: optional counts (e.g., number of items matching has10K or recent10Q)

`EdgarFiling` (display model):
- `companyName`: string
- `cik`: string
- `filingType`: string (e.g., 10‑K, 10‑Q, 8‑K)
- `filingDate`: string (YYYY‑MM‑DD)
- `accessionNumber`: string (optional in list view)
- `documentUrl`: string
- `raw`: object (entire source for modal)

## API Contracts & Endpoint Selection
- Source of truth: `endpoint-data.js`. Filter EDGAR‑related endpoints for:
  - Company → filings by name/CIK
  - Filings → listing by type, date range
  - Documents → direct links or metadata for primary documents
- Request Pattern
  - Use `apiService.get(url)` and `apiService.buildUrl(base, params)` if available.
  - Compose EDGAR endpoints primarily from Company/CIK lookup; filters like "Has 10‑K" and "Recent 10‑Q" are computed client‑side based on returned filings.
- Response Handling
  - Normalize to `EdgarFiling` display model.
  - Capture `total` and map pagination from server if provided; otherwise client‑side paginate.

## Interaction Flows
- Search Submit
  1. Validate `searchQuery` → detect CIK
  2. Build endpoint URL(s) based on name/CIK (no filter params in search)
  3. Fetch results via `apiService`
  4. Normalize + set `results`, `hasResults`, `pagination.totalPages`
- Apply Sidebar Filters
  - `has10K`: retain items where any filingType == "10‑K" for the company or item view.
  - `recent10Q`: retain items where filingType == "10‑Q" and `filingDate >= (today − 90 days)`.
  - Combine filters with AND logic when both are enabled.
- View JSON Modal
  - Set `modal.json = filing.raw`, `modal.title = "<Company> — <FilingType> (<Date>)"`, `modal.isOpen = true`
- Pagination
  - `firstPage()`, `prevPage()`, `goToPage(n)`, `nextPage()`, `lastPage()` functions
  - `getVisiblePages()` mirrors simplified centered controls

## UI Structure (DOM Outline)
- `#EdgarExplorer.explorer-pagecontent`
  - `#initialEdgarSearchContainer.explorer-search-container` (x-show `!showResults`)
    - Title + intro
    - Form: input (name/CIK) and submit button only
    - Hint text
  - `#edgarSearchResultsLayout.explorer-results-layout` (x-show `showResults`)
    - Top search bar (input + submit only)
    - `.explorer-content-wrapper`
      - `.explorer-results-filters` (sidebar)
        - Checkbox: Has 10‑K
        - Checkbox: Recent 10‑Q (≤90 days)
      - `.explorer-results-area` (list-only)
        - Status header + error message
        - Results container: card-style items with Company, CIK, Filing Type, Filing Date, actions
        - `.pagination-controls` (centered)
  - Modal elements (overlay + modal with header close + copy button)

## Styling
- Reuse classes from `styles.css`: `explorer-*`, `pagination-controls`, `dns-button`, `dns-textfield`.
- Keep top border only for pagination container; center buttons.
- Modal header: space-between layout; overlay restored as fixed.
- List items use existing card/list styles from the Classification Explorer; avoid table-specific CSS.

## Accessibility
- Labels for inputs; `aria-label` on pagination buttons.
- Keyboard support: Enter to search; ESC to close modal.
- Focus management: trap focus in modal; restore focus on close.

## Error Handling
- Display concise errors from `apiService` (network/server).
- Handle empty results with a friendly message and suggestions.
- Respect server rate‑limit messages; show hint to retry later.

## Performance
- Debounced validation on inputs.
- Client-side filtering for `has10K` and `recent10Q` after initial fetch.
- Lazy rendering for large result sets (paginate on server if possible).
- Avoid blocking UI during fetch; show loading states.

## Telemetry & Logging (Optional)
- Console logs in dev mode for key actions (search, pagination, modal open).
- Do not persist PII; keep client logs ephemeral.

## Implementation Tasks (for later)
1. Add menu tab button (header) and placeholder container in `index.html`.
2. Create `/static/js/edgar-explorer-alpine.js` with `createEdgarExplorerComponent()`.
3. Wire initial and post‑search layouts; bind inputs and actions (search form with input only).
4. Integrate `api-service.js` calls to EDGAR endpoints from `endpoint-data.js`.
5. Normalize responses into `EdgarFiling` and render results in a list-only view.
6. Implement sidebar filters (`has10K`, `recent10Q`) with client-side logic (90-day window for 10‑Q).
7. Implement modal viewer with copy action using `copyToClipboard()`.
8. Add centered pagination using the simplified control set.
9. Test across Chrome/Safari; validate keyboard and responsive behavior.
10. Polish styles with existing design tokens and classes.

## Non‑Goals
- No backend changes; strictly frontend integration with existing endpoints.
- No multi‑tab nested UI inside EDGAR Explorer.

## Open Questions
- Which EDGAR endpoints are canonical in `endpoint-data.js` for filings vs. company lookup? (Confirm exact paths and parameters.)
- Do server responses already include pagination metadata (page/total), or should the client paginate?
- Is "Has 10‑K" best evaluated per company result or per filing item collection from the endpoint? (Confirm server semantics.)

---

This plan defines the EDGAR Explorer structure, dependencies, UX, data model, and implementation steps. Do not implement yet; review and adjust endpoints/fields once confirmed from `endpoint-data.js`. 