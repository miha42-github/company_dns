# Explorer Unification Plan

**Date:** January 14, 2026  
**Status:** Planning (NOT IMPLEMENTED)  
**Goal:** Unify the Industry Classification Explorer and EDGAR Explorer implementations to share common architecture while preserving unique behaviors

---

## 1. Current Implementation Analysis

### 1.1 Architecture Overview

Both explorers follow a similar two-phase layout:
1. **Initial Search Container** — Full-page centered search input (hidden after search)
2. **Post-Search Results Layout** — Three-section layout (header + sidebar filters + results area)

**Files Involved:**
- [html/index.html](html/index.html#L318-L780) — HTML structure (dual explorer definitions)
- [html/js/global-search-alpine.js](html/js/global-search-alpine.js) — Industry Classification Explorer component (~756 lines)
- [html/js/edgar-explorer-alpine.js](html/js/edgar-explorer-alpine.js) — EDGAR Explorer component (~270 lines)
- [html/styles.css](html/styles.css#L610-L1200) — Shared styling for both explorers

### 1.2 HTML Structure Comparison

#### Similarity: Three-Phase Layout Pattern
Both explorers follow the same wrapper structure:

```
.explorer-pagecontent (Alpine.js container)
├─ .explorer-search-container (initial search, hidden after search)
└─ .explorer-results-layout (post-search, initially hidden)
   ├─ .explorer-search-wrapper (top search re-entry)
   └─ .explorer-content-wrapper (main content area)
      ├─ .explorer-sidebar (filters — UNIQUE CONTENT)
      └─ .explorer-results-area (results — UNIQUE CONTENT)
         ├─ .explorer-header-section (title + status)
         ├─ .explorer-container-wrapper (scrollable results)
         │  └─ .explorer-results-container (result cards — UNIQUE CONTENT)
         └─ .pagination-controls (pagination buttons)
```

#### Differences: Filter & Card Content
- **Industry Explorer:** 5 checkbox filters (US SIC, UK SIC, EU NACE, ISIC, Japan SIC) + description cards with metadata
- **EDGAR Explorer:** 2 checkboxes + 2 dropdowns (division, fiscal year end) + company filing cards

---

## 2. Root Cause Analysis: Pagination Title Shift Issue

### 2.1 Problem Description
**Industry Classification Explorer:** When advancing pages, the title "Industry Classification Explorer" and "Filter Results" sidebar header shift upward and disappear under the parent `.explorer-results-layout`.

**EDGAR Explorer:** This issue does NOT occur; pagination works smoothly without title shifting.

### 2.2 Root Cause Identified

**CSS Layout Issue in styles.css (lines 616-770):**

```css
.explorer-results-layout {
  height: calc(100vh - 140px);  /* ← FIXED HEIGHT */
  overflow: visible;            /* ← ALLOWS CONTENT TO ESCAPE */
}

.explorer-content-wrapper {
  flex: 1 1 auto;
  height: auto;                 /* ← CONFLICTS WITH PARENT FIXED HEIGHT */
  overflow: visible;            /* ← ALLOWS INTERNAL OVERFLOW */
}

.explorer-results-container {
  overflow-y: auto;             /* ← SCROLLS INTERNALLY */
  flex: 1;
}
```

**Problem Flow:**
1. `.explorer-results-layout` has fixed `height: calc(100vh - 140px)` and `overflow: visible`
2. `.explorer-content-wrapper` is set to `flex: 1 1 auto` and `height: auto`
3. When results scroll internally (`.explorer-results-container`), the fixed parent container does NOT recalculate
4. The title in `.explorer-header-section` is outside the scrolling container, so it gets clipped by the parent's fixed height
5. Internal scrolling causes the header to be pushed out of the visible viewport

**Why EDGAR Works:**
The EDGAR Explorer may work because:
- Fewer results per page (potentially shorter content)
- Different filter dropdown heights
- Different card heights (EDGAR cards have 2-row metadata vs. variable-height classification cards)

### 2.3 CSS Architecture Issues

**Current CSS has overlapping/conflicting properties:**

| Class | Height | Overflow | Issue |
|-------|--------|----------|-------|
| `.explorer-results-layout` | `calc(100vh - 140px)` fixed | `visible` | Clips child content |
| `.explorer-content-wrapper` | `auto` | `visible` | Conflicts with parent height |
| `.explorer-results-container` | implicit from flex | `auto` | Internal scroll doesn't resize parent |
| `.explorer-header-section` | unset | `visible` | Gets hidden when content scrolls |

---

## 3. Shared vs. Unique Components

### 3.1 Fully Shared (Identical Implementations)

**HTML Structure:**
- `.explorer-pagecontent` wrapper
- `.explorer-search-container` (initial centered search)
- `.explorer-results-layout` container
- `.explorer-search-wrapper` (top search re-entry)
- `.explorer-header-section` (title + status display)
- `.pagination-controls` (button layout)

**Alpine.js Logic:**
- Pagination methods: `firstPage()`, `prevPage()`, `nextPage()`, `lastPage()`, `goToPage()`
- Pagination UI helpers: `getVisiblePages()`, `getResultsHeadline()`, `getResultsRangeLabel()`
- State variables: `currentPage`, `resultsPerPage`, `totalPages`, `isSearching`, `showResults`
- JSON modal creation and display

**CSS Styling:**
- `.pagination-controls` styles
- `.pagination-btn` styles
- `.explorer-header-section` styles
- `.explorer-results-layout` styles
- `.explorer-content-wrapper` styles

### 3.2 Unique to Industry Classification Explorer

**HTML Structure:**
- Filter content: 5 checkboxes (All, US SIC, UK SIC, EU NACE, ISIC, Japan SIC)
- Filter counts display
- Result cards: Include `explorer-result-code`, `explorer-source-pill`, `explorer-result-meta` with dynamic metadata per SIC type

**Alpine.js Logic:**
- State: `filters` (6 boolean properties), `filterCounts` (6 numeric properties), `expandedCards` object
- Methods: `updateFilterCounts()`, `toggleAllFilters()`, `toggleFilter()`, `getSelectedSources()`
- Card expansion logic: `isExpanded()`, `toggleDescription()`, `shouldShowToggle()`
- Search: `searchIndustryCodes()` via API
- Description truncation: `getTruncatedDescription()`
- Source classification: `getSourceClass()`
- Metadata detection: `hasMetadata()`, `hasUkMetadata()`
- URL state persistence: `updateUrlState()`, `loadStateFromUrl()`
- Keyboard navigation: `handleKeyboard()`

**CSS:**
- `.explorer-filter-checkbox`, `.explorer-filter-label`, `.explorer-filter-guide` styles
- `.explorer-result-card`, `.explorer-result-meta`, `.explorer-source-pill` styles
- `.explorer-show-more`, `.explorer-result-description` styles
- `scrollToResults()` with `$nextTick()` smooth scroll

### 3.3 Unique to EDGAR Explorer

**HTML Structure:**
- Filter content: 2 checkboxes (Has 10-K, Recent 10-Q) + 2 dropdowns (Division, Fiscal Year End)
- Result cards: Include `edgar-pill-group-header`, `explorer-result-body`, `edgar-meta-row` (2 rows of metadata)
- Company metadata layout: Company name, CIK, SIC, Division, Ticker, FYE, Location

**Alpine.js Logic:**
- State: `filters` (object with has10K, recent10Q, division, fiscalYearEnd), `availableDivisions`, `availableFiscalYearEnds`
- Methods: `applyFilters()` (with 90-day logic for 10-Q), `updateFilterOptions()` (dynamic filter discovery)
- Search: `performSearch()` handles CIK vs. company name distinction, dual API calls
- Transform: `transformDetailToItems()` (complex data mapping from EDGAR API structure)
- Formatters: `formatFYE()`, `displayFYE()`
- Computation: `computeLatest()` (finds latest 10-K and 10-Q with date recency checking)
- **Notably: NO scrollToResults() or keyboard navigation**
- **Notably: NO URL state persistence**

---

## 4. Unification Strategy

### 4.1 Phase 1: Fix the CSS Layout Issue (Foundation)

**Objective:** Resolve the title-shifting pagination bug by correcting the flex/height conflicts.

**Changes:**

**File:** [html/styles.css](html/styles.css#L610-L770)

1. **Fix `.explorer-results-layout`** (line 616):
   - Remove fixed `height: calc(100vh - 140px)`
   - Change to `min-height: calc(100vh - 140px)` to allow growth
   - Change `overflow: visible` to `overflow: hidden` to contain children
   - Add `max-height: calc(100vh - 140px)` as fallback constraint

   ```css
   .explorer-results-layout {
     display: flex;
     flex-direction: column;
     min-height: calc(100vh - 140px);  /* Allow growth beyond viewport */
     max-height: calc(100vh - 140px);  /* Cap at viewport height */
     overflow: hidden;                  /* Contain children, don't escape */
     /* ... rest unchanged */
   }
   ```

2. **Fix `.explorer-content-wrapper`** (line 644):
   - Change `height: auto` to `min-height: 0` (flexbox requirement for scrolling)
   - Keep `overflow: visible` only on header
   - Ensure flex growth works correctly

   ```css
   .explorer-content-wrapper {
     flex: 1 1 auto;
     min-height: 0;  /* Critical for flex scrolling */
     overflow: hidden;  /* Contain children */
   }
   ```

3. **Ensure `.explorer-results-area` can scroll properly**:
   ```css
   .explorer-results-area {
     flex: 1 1 auto;
     min-height: 0;  /* Critical for nested flex scroll */
     overflow: hidden;  /* Contain children */
   }
   ```

4. **Ensure `.explorer-container-wrapper` scrolls content**:
   ```css
   .explorer-container-wrapper {
     flex: 1 1 auto;
     min-height: 0;
     overflow: auto;  /* Allow scrolling */
   }
   ```

**Impact:**
- ✅ Fixes Industry Classification Explorer pagination title shift
- ✅ Maintains EDGAR Explorer functionality
- ✅ Both explorers remain independent from CSS changes

---

### 4.2 Phase 2: Create Shared Explorer Base Component

**Objective:** Extract common pagination and layout logic into a reusable base.

**New File:** `html/js/explorer-base.js` (~150-200 lines)

**Contains:**
```javascript
/**
 * Base Explorer Component
 * Shared pagination, layout, and utility logic for all explorer types
 */
class ExplorerBase {
  constructor(containerIds = {}) {
    // Pagination state
    this.currentPage = 1;
    this.resultsPerPage = 10;
    this.totalPages = 1;
    
    // UI state
    this.isSearching = false;
    this.hasResults = false;
    this.errorMessage = '';
    this.statusMessage = '';
    this.showResults = false;
    
    // Container references for scroll/display
    this.containerIds = containerIds; // { searchContainer, resultsLayout, resultsContainer }
  }
  
  // ============ Pagination Methods ============
  
  /**
   * Navigate to first page
   */
  firstPage() {
    if (this.currentPage !== 1) {
      this.currentPage = 1;
      this.updateUrlState?.();
      this.scrollToResults?.();
    }
  }
  
  /**
   * Navigate to previous page
   */
  prevPage() {
    if (this.currentPage > 1) {
      this.currentPage--;
      this.updateUrlState?.();
      this.scrollToResults?.();
    }
  }
  
  /**
   * Navigate to next page
   */
  nextPage() {
    if (this.currentPage < this.totalPages) {
      this.currentPage++;
      this.updateUrlState?.();
      this.scrollToResults?.();
    }
  }
  
  /**
   * Navigate to last page
   */
  lastPage() {
    if (this.currentPage !== this.totalPages) {
      this.currentPage = this.totalPages;
      this.updateUrlState?.();
      this.scrollToResults?.();
    }
  }
  
  /**
   * Navigate to specific page
   */
  goToPage(pageNum) {
    if (pageNum >= 1 && pageNum <= this.totalPages) {
      this.currentPage = pageNum;
      this.updateUrlState?.();
      this.scrollToResults?.();
    }
  }
  
  // ============ Pagination UI Helpers ============
  
  /**
   * Get visible page numbers for pagination button group
   */
  getVisiblePages() {
    const maxButtons = 5;
    let start = Math.max(1, this.currentPage - Math.floor(maxButtons / 2));
    let end = Math.min(this.totalPages, start + maxButtons - 1);
    if (end - start + 1 < maxButtons) {
      start = Math.max(1, end - maxButtons + 1);
    }
    const pages = [];
    for (let p = start; p <= end; p++) {
      pages.push(p);
    }
    return pages;
  }
  
  /**
   * Get headline summary (e.g., "42 results")
   */
  getResultsHeadline() {
    if (!this.hasResults) {
      return this.statusMessage || 'No results';
    }
    return `${this.filteredResults?.length || 0} results`;
  }
  
  /**
   * Get range label (e.g., "Showing 1-10 of 42")
   */
  getResultsRangeLabel() {
    if (!this.hasResults || !this.filteredResults?.length) {
      return 'Showing 0-0 of 0';
    }
    const start = (this.currentPage - 1) * this.resultsPerPage + 1;
    const end = Math.min(this.filteredResults.length, start + this.resultsPerPage - 1);
    return `Showing ${start}-${end} of ${this.filteredResults.length}`;
  }
  
  /**
   * Get active filters summary label
   * Subclasses override to provide type-specific label
   */
  getActiveFiltersLabel() {
    return 'Filters: none';
  }
  
  // ============ Keyboard Navigation ============
  
  /**
   * Handle keyboard shortcuts for pagination
   */
  handleKeyboard(event) {
    if (!this.showResults || !this.filteredResults?.length) return;
    const tag = event.target?.tagName?.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    
    switch (event.key) {
      case 'ArrowLeft':
        event.preventDefault();
        this.prevPage();
        break;
      case 'ArrowRight':
        event.preventDefault();
        this.nextPage();
        break;
      case 'Home':
        event.preventDefault();
        this.firstPage();
        break;
      case 'End':
        event.preventDefault();
        this.lastPage();
        break;
    }
  }
  
  // ============ Scroll & Display Management ============
  
  /**
   * Scroll results container into view
   * Must be called with Alpine's $nextTick in Alpine components
   */
  scrollToResults(elementId) {
    const resultsDiv = document.getElementById(elementId);
    if (resultsDiv) {
      resultsDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }
  
  /**
   * Show search results layout, hide initial search
   */
  showResultsLayout(initialContainerId, resultsLayoutId) {
    const initialContainer = document.getElementById(initialContainerId);
    const resultsLayout = document.getElementById(resultsLayoutId);
    
    if (initialContainer) initialContainer.style.display = 'none';
    if (resultsLayout) resultsLayout.style.display = 'block';
  }
  
  /**
   * Show initial search layout, hide results
   */
  showSearchLayout(initialContainerId, resultsLayoutId) {
    const initialContainer = document.getElementById(initialContainerId);
    const resultsLayout = document.getElementById(resultsLayoutId);
    
    if (initialContainer) initialContainer.style.display = 'block';
    if (resultsLayout) resultsLayout.style.display = 'none';
  }
  
  // ============ JSON Modal Integration ============
  
  /**
   * Show JSON modal for a result
   */
  showJsonModal(resultData) {
    showJsonModal(resultData);
  }
}

// Export for use in Alpine components
window.ExplorerBase = ExplorerBase;
```

**Updates to Alpine Components:**
- Industry Classification Explorer: Extend ExplorerBase or mix in shared methods
- EDGAR Explorer: Extend ExplorerBase or mix in shared methods
- Each component retains its unique state and methods
- Removes code duplication in pagination logic

---

### 4.3 Phase 3: Unified HTML Structure Template

**Objective:** Standardize HTML structure so both explorers use identical layout wrapper.

**Current Redundancy:**
- Both explorers define their own `.explorer-results-layout` (lines 381-574 for Industry, 607-783 for EDGAR)
- Only the filter content and result cards differ

**Template Approach (Optional Refactoring):**

Create a reusable template structure:
```html
<!-- Universal Explorer Results Layout -->
<div id="{explorerId}ResultsLayout" class="explorer-results-layout" x-show="showResults">
  <h1>{explorerTitle}</h1>
  
  <div class="explorer-search-wrapper">
    <!-- Search form input (identical structure) -->
  </div>
  
  <div class="explorer-content-wrapper">
    <!-- Filters Sidebar (UNIQUE PER EXPLORER) -->
    <div class="explorer-sidebar">
      <!-- Injected filter HTML here -->
    </div>
    
    <!-- Results Area (SHARED STRUCTURE, UNIQUE CARDS) -->
    <div class="explorer-results-area">
      <div class="explorer-header-section">
        <!-- Shared status display -->
      </div>
      
      <div class="explorer-container-wrapper">
        <div id="{explorerId}Results" class="explorer-results-container">
          <!-- UNIQUE: Result card template -->
        </div>
      </div>
      
      <!-- Shared pagination -->
      <div class="pagination-controls"><!-- buttons --></div>
    </div>
  </div>
</div>
```

**Impact:**
- Reduces HTML duplication from ~200 lines to ~40 lines per explorer
- Makes structural changes in one place affect all explorers
- Easier to maintain consistency

---

### 4.4 Phase 4: Enhance EDGAR Explorer to Match Industry Explorer Features

**Objective:** Bring EDGAR Explorer to feature parity where applicable.

**Proposed Enhancements (Optional):**

1. **Add URL State Persistence** (already in Industry Explorer):
   - Preserve search query, current page, and filters in URL
   - Allow users to share result links
   - Auto-load previous search on revisit

2. **Add Keyboard Navigation** (already in Industry Explorer):
   - Arrow Left/Right for previous/next page
   - Home/End for first/last page
   - Makes EDGAR usability match Industry Explorer

3. **Add Scrolling on Pagination** (already in Industry Explorer):
   - Call `scrollToResults()` after page changes
   - Ensures user sees new results immediately
   - Better UX on large result sets

**Implementation:** ~50-75 lines of JavaScript additions to edgar-explorer-alpine.js

---

## 5. Implementation Roadmap

### Step 1: Fix CSS Layout (PRIORITY 1 — Blocking Bug)
**Timeline:** 30 minutes
**Files:** [html/styles.css](html/styles.css#L610-L770)
**Outcome:** Fixes pagination title shift in Industry Explorer

### Step 2: Create Explorer Base Class (PRIORITY 2 — Foundation)
**Timeline:** 45 minutes
**Files:** New file `html/js/explorer-base.js`
**Outcome:** Shared pagination logic, reduced duplication

### Step 3: Refactor Alpine Components to Use Base (PRIORITY 3 — Consolidation)
**Timeline:** 1 hour
**Files:** [html/js/global-search-alpine.js](html/js/global-search-alpine.js), [html/js/edgar-explorer-alpine.js](html/js/edgar-explorer-alpine.js)
**Outcome:** Both components use shared methods, but retain unique state/filters/cards

### Step 4: Unify HTML Structure (PRIORITY 4 — Optional)
**Timeline:** 1 hour
**Files:** [html/index.html](html/index.html#L318-L780)
**Outcome:** Single template for both explorers, only filter/card content varies

### Step 5: Enhance EDGAR Features (PRIORITY 5 — Polish)
**Timeline:** 45 minutes
**Files:** [html/js/edgar-explorer-alpine.js](html/js/edgar-explorer-alpine.js)
**Outcome:** EDGAR gains URL persistence, keyboard nav, smart scrolling

**Total Estimated Time:** 3.5 hours  
**Risk Level:** Medium (CSS changes affect both explorers, require testing)

---

## 6. Testing Strategy

### 6.1 Regression Testing (Must Pass)

**Industry Classification Explorer:**
- [ ] Search returns results
- [ ] Pagination forward/backward works
- [ ] Filters (checkboxes) update counts correctly
- [ ] Title and filters stay visible during pagination (FIX VERIFICATION)
- [ ] Result expansion (show/hide details) works
- [ ] View JSON modal displays
- [ ] Keyboard navigation works (arrow keys, Home, End)
- [ ] URL state persists across page navigation

**EDGAR Explorer:**
- [ ] Search by company name returns results
- [ ] Search by CIK returns results
- [ ] Pagination works
- [ ] Has 10-K filter works
- [ ] Recent 10-Q filter works (90-day logic)
- [ ] Division dropdown populates and filters
- [ ] Fiscal Year End dropdown populates and filters
- [ ] View JSON modal displays
- [ ] Filing links (10-K, 10-Q) are accessible

### 6.2 New Functionality Testing

**After implementing Phase 2-5:**
- [ ] EDGAR keyboard navigation works
- [ ] EDGAR scrolls to results on page change
- [ ] EDGAR URL state persists (if added)
- [ ] CSS layout survives both explorer types

---

## 7. Shared Code Metrics

### 7.1 Current Duplication

**Pagination Methods (8 methods, ~150 lines):**
- Industry: `nextPage()`, `prevPage()`, `firstPage()`, `lastPage()`, `goToPage()`, `getVisiblePages()`, etc.
- EDGAR: Same 4 methods but without scroll/update calls (~50 lines)
- **Duplication:** ~40-50% of pagination code

**UI Helpers (~80 lines):**
- Industry: `getResultsHeadline()`, `getResultsRangeLabel()`, `getActiveFiltersLabel()`
- EDGAR: Same 3 methods with minor differences
- **Duplication:** ~70% of helper code

**HTML Structure (~300 lines):**
- Industry: Results layout wrapper (lines 381-574)
- EDGAR: Results layout wrapper (lines 607-783)
- **Duplication:** ~75% of layout structure (filters and cards vary)

**Total Shared Potential:** ~450-500 lines (62% of global-search-alpine.js + 75% of edgar-explorer-alpine.js)

### 7.2 Post-Unification Reduction

**After Phase 2-3:**
- Remove ~200 lines from both components (shared methods moved to base)
- Maintain ~150 lines of unique logic per component
- Add ~150-200 lines to new `explorer-base.js`
- **Net Reduction:** ~150-200 lines overall (smaller components, easier to maintain)

**After Phase 4:**
- Remove ~100 additional lines of HTML duplication
- **Total Reduction:** ~250-300 lines

---

## 8. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ html/index.html                                                 │
│ ├─ GlobalSearch Tab (Alpine.js: createGlobalSearchComponent)   │
│ │  └─ Uses: explorer-base.js (pagination, keyboard, scroll)    │
│ │           + unique filters + unique result cards             │
│ │                                                               │
│ └─ EdgarExplorer Tab (Alpine.js: createEdgarExplorerComponent) │
│    └─ Uses: explorer-base.js (pagination, keyboard, scroll)    │
│             + unique filters + unique result cards             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ html/js/explorer-base.js                          [NEW FILE]    │
│ ├─ ExplorerBase class                                           │
│ │  ├─ Pagination: firstPage, prevPage, nextPage, lastPage      │
│ │  ├─ UI Helpers: getResultsHeadline, getActiveFiltersLabel    │
│ │  ├─ Navigation: handleKeyboard, scrollToResults              │
│ │  └─ Display: showResultsLayout, showSearchLayout             │
│ └─ Exported: window.ExplorerBase                                │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ html/js/global-search-alpine.js                                 │
│ ├─ createGlobalSearchComponent()                                │
│ │  ├─ SHARED (from base): pagination, keyboard, scroll         │
│ │  ├─ UNIQUE: filters (6 bool), expandedCards, URL state       │
│ │  ├─ UNIQUE: updateFilterCounts, toggleAllFilters             │
│ │  ├─ UNIQUE: searchIndustryCodes, getTruncatedDescription     │
│ │  └─ UNIQUE: getSourceClass, hasMetadata                      │
│ └─ Uses: apiService, global-search-alpine.js                    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ html/js/edgar-explorer-alpine.js                                │
│ ├─ createEdgarExplorerComponent()                               │
│ │  ├─ SHARED (from base): pagination, keyboard, scroll         │
│ │  ├─ UNIQUE: filters (obj: has10K, division, etc.)            │
│ │  ├─ UNIQUE: updateFilterOptions, availableDivisions          │
│ │  ├─ UNIQUE: transformDetailToItems, computeLatest            │
│ │  └─ UNIQUE: formatFYE, displayFYE                            │
│ └─ Uses: apiService, api-service.js                             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ html/styles.css                                                 │
│ ├─ FIXED: .explorer-results-layout (Phase 1)                   │
│ ├─ FIXED: .explorer-content-wrapper (Phase 1)                  │
│ ├─ SHARED: .pagination-controls, .pagination-btn                │
│ ├─ SHARED: .explorer-header-section, .explorer-results-area    │
│ ├─ UNIQUE: .explorer-filter-checkbox, .explorer-source-pill    │
│ ├─ UNIQUE: .edgar-pill-group-header, .edgar-meta-row           │
│ └─ UNIQUE: .explorer-result-card variations                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 9. Risk Assessment & Mitigation

### 9.1 Risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| CSS changes break pagination in one explorer | HIGH | Phase 1 testing both explorers thoroughly; revert if necessary |
| Alpine.js binding issues when refactoring | MEDIUM | Keep component state and methods clearly separated; incremental refactoring |
| URL state persistence conflicts | LOW | Ensure unique URL parameter naming per explorer |
| Performance regression on pagination | LOW | Monitor with DevTools; optimize if needed |

### 9.2 Testing Checklist (Before Merge)

**Phase 1 (CSS Fix):**
- [ ] Industry Explorer: Pagination forward/backward without title shift
- [ ] EDGAR Explorer: Pagination still works as before
- [ ] Both explorers: Responsive layout on mobile/tablet

**Phase 2-3 (Base Class):**
- [ ] No regression in any pagination feature
- [ ] No console errors from Alpine.js
- [ ] All unique features still work (filters, expansion, etc.)

**Phase 4 (HTML Unification):**
- [ ] Both explorers render correctly
- [ ] No visual changes to users
- [ ] All interactive features work

**Phase 5 (EDGAR Enhancements):**
- [ ] EDGAR keyboard navigation works correctly
- [ ] EDGAR URL state persists across navigation
- [ ] No conflicts with existing EDGAR logic

---

## 10. Conclusion

### Current State
- ✅ Both explorers work independently
- ❌ Significant code duplication (~450-500 lines)
- ❌ Pagination title shift bug in Industry Explorer
- ❌ EDGAR missing convenience features (keyboard nav, URL state)
- ❌ CSS architecture has conflicting properties causing layout issues

### Post-Unification State (All Phases)
- ✅ Single pagination logic shared between explorers
- ✅ CSS properly structured with clear separation of concerns
- ✅ Both explorers have full feature parity where applicable
- ✅ Easier to add new explorers in future
- ✅ Reduced codebase by ~250-300 lines
- ✅ Improved maintainability and consistency

### Recommendation
**Proceed with Phase 1 immediately** (CSS fix is blocking and low-risk). Then reassess whether to pursue Phases 2-5 based on bandwidth and priorities. Phase 1 alone will resolve the reported pagination issue.

---

## Appendix: File Line References

| File | Component | Lines | Status |
|------|-----------|-------|--------|
| html/index.html | GlobalSearch (Industry) | 318-574 | Reviewed |
| html/index.html | EdgarExplorer | 580-783 | Reviewed |
| html/js/global-search-alpine.js | createGlobalSearchComponent | 1-756 | Reviewed |
| html/js/edgar-explorer-alpine.js | createEdgarExplorerComponent | 1-270 | Reviewed |
| html/styles.css | Explorer layout & pagination | 371-1200 | Reviewed |

---

**Document Status:** PLANNING COMPLETE - AWAITING APPROVAL FOR IMPLEMENTATION
