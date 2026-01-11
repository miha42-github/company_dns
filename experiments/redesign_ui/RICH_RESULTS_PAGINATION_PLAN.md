# Rich Results & Pagination Plan
**Date:** January 11, 2026  
**Target branch:** feature/V3.2/hardening  
**Constraint:** Single-container, zero build step, no new frontend deps, actions limited to “View JSON”.

---

## Executive Summary
This plan fixes UI regressions and enriches the Industry Code Explorer:
1. Align the results status bar with the sidebar title and add a clear “showing X–Y of N” + active filters summary.
2. Restore/upgrade client pagination in the results column (first/prev/numbered/next/last, page-size select, jump-to-page) with URL/state/keyboard support.
3. Enrich result cards with conditional metadata per classification system, keeping only the “View JSON” action.

**Key Principle:** Improve clarity and navigation without adding dependencies or new actions beyond the existing modal.

---

## Current State (problems)
- Status text is misaligned and smaller than “Filter Results”; no secondary summary line.
- Pagination controls are either missing or rendered in the wrong place; page-size and jump are not usable.
- Result cards are too sparse: no system-specific metadata; long descriptions lack a readable toggle.

---

## Work Breakdown

### A) Status / Header (index.html + styles.css)
- Wrap status text in a flex container inside the results column, aligned to match sidebar title size/weight.
- Add secondary line: “Showing X–Y of N” and “Filters: …”.
- Style: shared font-size/weight with sidebar title; compact padding/margins for tight vertical rhythm.

**Planned code (illustrative):**
- Markup in index.html, inside results column:
   ```html
   <div class="results-status">
      <div class="status-top">Results</div>
      <div class="status-meta">Showing {{rangeText}} of {{total}} · Filters: {{filtersText}}</div>
   </div>
   ```
- Styles in styles.css:
   ```css
   .results-status { display: flex; flex-direction: column; gap: 0.15rem; }
   .status-top { font-size: 1.1rem; font-weight: 600; color: #ca703f; }
   .status-meta { font-size: 0.95rem; color: rgb(152, 144, 139); }
   ```

### B) Pagination (index.html + global-search-alpine.js + styles.css)
- Placement: pagination bar directly under the results list (full width of results column).
- Markup: first / prev / numbered pages / next / last; page-size select (10/25/50/100); jump-to-page input + Go.
- Logic (Alpine):
   - Wire buttons to currentPage/totalPages/resultsPerPage.
   - Validate jump input (1..totalPages); recalc totals on page-size change.
   - URL sync: read/write q, page, perPage, filters; restore on load; update on page/filter/page-size changes.
   - Keyboard: left/right arrows change pages when focus is not in input/textarea/select.
- Styles: bar background and border; hover/active/disabled states; select/input styling; min 40px hit area.

**Planned code (illustrative):**
- Markup in index.html (results column):
   ```html
   <div class="pagination-controls" x-show="totalPages > 1">
      <button class="pagination-btn" @click="firstPage" :disabled="currentPage === 1">⏮</button>
      <button class="pagination-btn" @click="prevPage" :disabled="currentPage === 1">◀</button>
      <template x-for="page in visiblePages" :key="page">
         <button class="pagination-btn" :class="{ 'active': page === currentPage }" @click="goToPage(page)">{{ page }}</button>
      </template>
      <button class="pagination-btn" @click="nextPage" :disabled="currentPage === totalPages">▶</button>
      <button class="pagination-btn" @click="lastPage" :disabled="currentPage === totalPages">⏭</button>

      <select class="page-size-selector" x-model.number="resultsPerPage" @change="changePageSize">
         <option value="10">10</option>
         <option value="25">25</option>
         <option value="50">50</option>
         <option value="100">100</option>
      </select>

      <div class="pagination-jump">
         <label for="pageJump">Go to:</label>
         <input id="pageJump" type="number" min="1" :max="totalPages" x-model.number="pageJump" @keydown.enter.prevent="jumpToPage">
         <button class="pagination-btn" @click="jumpToPage">Go</button>
      </div>
   </div>
   ```
- Styles in styles.css (lifted from UI_IMPROVEMENT_PLAN pagination example):
   ```css
   .pagination-controls {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 1rem;
      margin: 2rem 0;
      padding: 1rem;
      background-color: #1a1718;
      border-radius: 0.5rem;
      border: 1px solid #3c3b3b;
   }
   .pagination-btn {
      padding: 0.5rem 1rem;
      border: 1px solid rgb(104, 95, 88);
      background-color: #0F0D0E;
      color: #1696c8;
      cursor: pointer;
      border-radius: 0.3rem;
      transition: all 0.2s;
      min-width: 2.5rem;
      min-height: 40px;
   }
   .pagination-btn:hover:not(:disabled) { background-color: #1a1718; border-color: #1696c8; }
   .pagination-btn:disabled { opacity: 0.3; cursor: not-allowed; }
   .pagination-btn.active { border-color: #ca703f; color: #ca703f; font-weight: 600; }
   .pagination-info { display: flex; align-items: center; gap: 0.3rem; font-size: 1rem; color: #ca703f; }
   .page-current { font-weight: bold; color: #1696c8; }
   .result-count { margin-left: 0.5rem; color: rgb(104, 95, 88); font-size: 0.9rem; }
   .page-size-selector { margin-left: 1rem; padding: 0.3rem 0.5rem; background: #0F0D0E; color: #e3dfdc; border: 1px solid #3c3b3b; }
   .pagination-jump { display: flex; align-items: center; gap: 0.5rem; margin-left: 1rem; }
   .pagination-jump input { width: 4rem; padding: 0.3rem; text-align: center; background: #0F0D0E; color: #e3dfdc; border: 1px solid #3c3b3b; }
   ```
- JS hooks in global-search-alpine.js (functions to add/ensure): `firstPage()`, `prevPage()`, `nextPage()`, `lastPage()`, `goToPage(page)`, `changePageSize()`, `jumpToPage()`, URL sync on load/update, arrow-key handler guarding against inputs.

### C) Result Cards (index.html + styles.css + global-search-alpine.js)
- Header row: code + source pill; only action is “View JSON”.
- Description: support long text with per-card show more/less (state keyed by source+code).
- Metadata (render only when present):
   - US SIC: division, major_group, industry_group + their descriptions.
   - EU NACE / ISIC / Japan: section/division/group codes.
   - UK SIC: minimal; if none, omit block gracefully.
- Styling: muted labels, stronger values, responsive metadata grid, per-system pill colors; preserve modal styles.

**Planned code (illustrative):**
- Markup in index.html (per card):
   ```html
   <div class="result-card">
      <div class="card-head">
         <div class="card-title">{{ code }}</div>
         <span class="pill pill-{{ source }}">{{ sourceLabel }}</span>
         <button class="view-json" @click="openJson(result)">View JSON</button>
      </div>
      <p class="card-desc" x-show="!isExpanded(key)">{{ truncatedDesc }}</p>
      <p class="card-desc" x-show="isExpanded(key)">{{ fullDesc }}</p>
      <button class="show-more" @click="toggleExpand(key)">{{ isExpanded(key) ? 'Show less' : 'Show more' }}</button>

      <div class="metadata-grid" x-show="hasMetadata(result)">
         <!-- Example US SIC fields -->
         <div class="meta" x-show="result.division">
            <div class="meta-label">Division</div>
            <div class="meta-value">{{ result.division }} — {{ result.division_desc }}</div>
         </div>
         <div class="meta" x-show="result.major_group">
            <div class="meta-label">Major Group</div>
            <div class="meta-value">{{ result.major_group }} — {{ result.major_group_desc }}</div>
         </div>
         <div class="meta" x-show="result.industry_group">
            <div class="meta-label">Industry Group</div>
            <div class="meta-value">{{ result.industry_group }} — {{ result.industry_group_desc }}</div>
         </div>
         <!-- Similar blocks for EU/ISIC/Japan/UK as available -->
      </div>
   </div>
   ```
- Styles in styles.css:
   ```css
   .result-card { border: 1px solid #272525; border-radius: 0.5rem; padding: 1rem; background: #0F0D0E; }
   .card-head { display: flex; align-items: center; gap: 0.5rem; justify-content: space-between; }
   .card-title { font-weight: 700; color: #e3dfdc; }
   .pill { padding: 0.2rem 0.5rem; border-radius: 999px; font-size: 0.85rem; }
   .pill-us_sic { background: rgba(202, 112, 63, 0.18); color: #ca703f; }
   .pill-eu_nace { background: rgba(22, 150, 200, 0.18); color: #1696c8; }
   .pill-isic { background: rgba(104, 95, 88, 0.18); color: rgb(152, 144, 139); }
   .pill-japan_sic { background: rgba(132, 186, 120, 0.18); color: #84ba78; }
   .pill-uk_sic { background: rgba(173, 129, 202, 0.18); color: #ad81ca; }
   .card-desc { color: #d7d2cf; margin: 0.5rem 0; }
   .show-more { background: none; color: #1696c8; border: none; cursor: pointer; padding: 0; }
   .metadata-grid { display: grid; gap: 0.5rem; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); margin-top: 0.75rem; }
   .meta-label { font-size: 0.85rem; color: rgb(152, 144, 139); }
   .meta-value { color: #e3dfdc; font-weight: 600; }
   ```
- JS hooks in global-search-alpine.js (functions to add/ensure): `isExpanded(key)`, `toggleExpand(key)`, `hasMetadata(result)`, plus per-system guards when rendering metadata.

### D) QA Checklist
- Search “oil”: mixed-system cards show correct metadata; “View JSON” works.
- Pagination: page-size change recalculates totals; jump validates bounds; URL back/forward retains state; arrows navigate pages when not in inputs.
- Empty state shows guidance; no overlap between sidebar, results, pagination.

---

## Files to Change
- html/index.html — status block, pagination placement, card template (show-more, metadata, single action).
- html/js/global-search-alpine.js — pagination/jump wiring, URL sync, show-more state, metadata guards, keyboard nav.
- html/styles.css — status bar alignment, pagination styles, pills, metadata grid, card spacing, show-more link.

---

## Acceptance Criteria
- Status bar aligned and sized to sidebar title; shows “Showing X–Y of N” and active filters.
- Pagination fully functional (buttons, page-size, jump, URL sync, keyboard arrows) and visually contained in the results column.
- Result cards render conditional metadata per system, with only “View JSON” as the action; long text is readable via toggle.
- No regressions to modal, filters, or search flow.
