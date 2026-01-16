# EDGAR Result Card Redesign Plan

## Current State

The existing EDGAR result card is space-consuming with the following structure:

```
┌─────────────────────────────────────────────────────┐
│ [10-K  2025-3-12] [10-Q  2025-5-30]  [View JSON]    │ ← Form pills + action button
├─────────────────────────────────────────────────────┤
│ Company: AUSTRALIAN OILSEEDS HOLDINGS LTD            │
│ CIK: 1959994                                         │
│ Total Filings: 6                                     │
├─────────────────────────────────────────────────────┤
│ Recent Forms                                         │
│ ├─ 10-Q    2025-5-30                               │
│ ├─ 10-Q    2025-3-31                               │
│ ├─ 10-K/A  2025-3-12                               │
│ ├─ 10-Q    2025-2-10                               │
│ ├─ 10-K/A  2024-12-6                               │
│ └─ 10-K    2024-12-3                               │
└─────────────────────────────────────────────────────┘
```

**Problems:**
- Recent Forms box is redundant with pills at top
- Tall card takes up excessive vertical space
- No quick links to related EDGAR data
- Not using available firmographics URLs effectively

---

## Proposed Compact Redesign

### Structure

```
┌─────────────────────────────────────────────────────┐
│ Company: AUSTRALIAN OILSEEDS HOLDINGS LTD            │
│ CIK: 1959994   │   Total Filings: 6                  │
├─────────────────────────────────────────────────────┤
│ Recent Forms:                                        │
│ [10-Q 2025-5-30]  [10-Q 2025-3-31]  [10-K/A 2025-3] │
├─────────────────────────────────────────────────────┤
│ [Browse EDGAR] [Company Facts] [Transactions]        │
│ [Insider Trades] [View JSON]                         │
└─────────────────────────────────────────────────────┘
```

**Key Changes:**
1. **Top 3 Forms Only**: Display as pills showing form type + date
2. **Remove Scrollable List**: Delete the "Recent Forms" box entirely
3. **Add Action Links**: Quick access links to:
   - Browse EDGAR (company filings browser)
   - Company Facts (XBRL data)
   - Issuer Transactions
   - Insider Trades (beneficial owner transactions)
   - View JSON (existing)

---

## URI Patterns from edgar.py `get_firmographics()`

Based on [edgar.py](lib/edgar.py#L317-L476), the function constructs these URLs:

```python
# SEC EDGAR company filings browser
firmographics['filingsURL'] = 
  f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={my_cik}&action=getcompany"

# XBRL company facts (structured financial data)
firmographics['companyFactsURL'] = 
  f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_with_padding}.json"

# SEC insider transactions - by issuer (company-side view)
firmographics['transactionsByIssuer'] = 
  f"https://www.sec.gov/cgi-bin/own-disp?action=getissuer&CIK={my_cik}"

# SEC insider transactions - by owner (beneficial owner view)
firmographics['transactionsByOwner'] = 
  f"https://www.sec.gov/cgi-bin/own-disp?action=getowner&CIK={my_cik}"
```

---

## Implementation Details

### 1. Data Transformation in JavaScript

The `edgar-explorer-alpine.js` component already receives `item.cik`. We need to add URL construction:

```javascript
// In the data transformation / display logic
function buildEdgarUrls(cik) {
  const paddedCik = String(cik).padStart(10, '0');
  return {
    browse: `https://www.sec.gov/cgi-bin/browse-edgar?CIK=${cik}&action=getcompany`,
    facts: `https://data.sec.gov/api/xbrl/companyfacts/CIK${paddedCik}.json`,
    issuerTransactions: `https://www.sec.gov/cgi-bin/own-disp?action=getissuer&CIK=${cik}`,
    ownerTransactions: `https://www.sec.gov/cgi-bin/own-disp?action=getowner&CIK=${cik}`
  };
}
```

### 2. HTML Structure

**Current (to be removed):**
```html
<div class="explorer-result-card">
  <div class="explorer-result-header">
    <!-- Form pills -->
  </div>
  <div class="explorer-result-body">
    <!-- Company info -->
  </div>
  <div class="explorer-result-recent-forms">
    <!-- Scrollable list of all recent forms -->
  </div>
</div>
```

**New (proposed):**
```html
<div class="explorer-result-card">
  <!-- Company header line -->
  <div class="explorer-result-header">
    <div class="edgar-company-info">
      <strong>Company:</strong> AUSTRALIAN OILSEEDS HOLDINGS LTD
      <span class="edgar-meta">CIK: 1959994</span>
      <span class="edgar-meta">Total Filings: 6</span>
    </div>
  </div>

  <!-- Top 3 recent forms as pills -->
  <div class="edgar-recent-forms-compact">
    <span class="edgar-forms-label">Recent Forms:</span>
    <div class="edgar-pill-group">
      <a href="#" class="edgar-pill" target="_blank">10-Q 2025-5-30</a>
      <a href="#" class="edgar-pill" target="_blank">10-Q 2025-3-31</a>
      <a href="#" class="edgar-pill" target="_blank">10-K/A 2025-3-12</a>
    </div>
  </div>

  <!-- Quick action links -->
  <div class="edgar-quick-links">
    <a href="#" class="edgar-quick-link" target="_blank">Browse EDGAR</a>
    <a href="#" class="edgar-quick-link" target="_blank">Company Facts</a>
    <a href="#" class="edgar-quick-link" target="_blank">Issuer Transactions</a>
    <a href="#" class="edgar-quick-link" target="_blank">Insider Trades</a>
    <button class="dns-button edgar-view-json">View JSON</button>
  </div>
</div>
```

### 3. CSS Changes

**Remove:**
- `.explorer-result-recent-forms` (the scrollable box)
- `.explorer-result-body` (company info box - merge into header)

**Add:**
```css
.edgar-company-info {
  display: inline;
  font-size: 1em;
  line-height: 1.4;
}

.edgar-meta {
  margin-left: 1.5rem;
  color: #ca703f;
  font-size: 0.95em;
}

.edgar-recent-forms-compact {
  display: flex;
  align-items: center;
  gap: 0.8rem;
  margin: 0.8rem 0;
  flex-wrap: wrap;
  padding: 0.5rem 0;
}

.edgar-forms-label {
  font-weight: bold;
  color: #ca703f;
  min-width: 100px;
}

.edgar-pill-group {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.edgar-pill {
  display: inline-block;
  padding: 0.4rem 0.8rem;
  background-color: transparent;
  border: 1px solid #1696c8;
  color: #1696c8;
  text-decoration: none;
  border-radius: 20px;
  font-size: 0.9em;
  white-space: nowrap;
  transition: all 0.2s;
}

.edgar-pill:hover {
  background-color: #1696c8;
  color: #0F0D0E;
}

.edgar-quick-links {
  display: flex;
  gap: 0.6rem;
  flex-wrap: wrap;
  margin-top: 0.8rem;
  padding-top: 0.8rem;
  border-top: 1px solid #3c3b3b;
}

.edgar-quick-link {
  padding: 0.4rem 0.8rem;
  background-color: transparent;
  border: 1px solid #924e29;
  color: #924e29;
  text-decoration: none;
  border-radius: 4px;
  font-size: 0.9em;
  transition: all 0.2s;
}

.edgar-quick-link:hover {
  background-color: #924e29;
  color: #fff;
}
```

---

## Card Size Comparison

| Aspect | Current | Proposed |
|--------|---------|----------|
| **Height** | ~200-250px (6 forms listed) | ~120-140px |
| **Scrollable Content** | Yes (Recent Forms box) | No |
| **Quick Actions** | None (only View JSON) | 5 quick links |
| **Vertical Space Saved** | — | ~40-50% reduction |
| **Usability** | Good for detail view | Better for browsing |

---

## Data Dependencies

**Backend (Python):**
- No changes needed; `get_firmographics()` already constructs these URLs
- Frontend will replicate the URL construction logic

**Frontend (JavaScript):**
- Modify `edgar-explorer-alpine.js` data transformation
- Add `buildEdgarUrls()` helper function
- Pass URL object to template

**API Response:**
- Current: Returns summary data (company, recent forms, CIK)
- Needed: Ensure CIK is available for URL construction (✅ already present)

---

## Implementation Steps

1. **Update JavaScript** (`html/js/edgar-explorer-alpine.js`)
   - Add `buildEdgarUrls(cik)` function
   - Enhance data transformation to include URL object

2. **Update HTML** (`html/index.html`)
   - Replace card structure for EDGAR explorer section
   - Bind URLs to quick link anchors
   - Bind top 3 forms to pills with proper href attributes

3. **Update CSS** (`html/styles.css`)
   - Remove `.explorer-result-body` and `.explorer-result-recent-forms` styles
   - Add new classes: `.edgar-company-info`, `.edgar-recent-forms-compact`, `.edgar-quick-links`, etc.
   - Ensure responsive behavior on mobile

4. **Test**
   - Verify links open correct SEC pages
   - Check mobile responsiveness (pills wrap properly)
   - Confirm View JSON still works
   - Validate with multiple company searches

---

## Benefits

✅ **Space Efficiency**: 40-50% height reduction per card
✅ **Accessibility**: Quick links to related SEC data
✅ **Usability**: Shows most recent filings without scrolling
✅ **Mobile-Friendly**: Pills wrap naturally on narrow screens
✅ **Consistency**: Follows existing pill design pattern

---

## Open Questions

1. Should the form pills be clickable (linking to EDGAR filing)?
   - **Suggestion**: Yes, link to the filing detail page
   
2. Should "Company Facts" button link to JSON or web viewer?
   - **Suggestion**: Link to data.sec.gov API endpoint (JSON) for technical users
   
3. Should we show filing count breakdown (10-K, 10-Q, etc.)?
   - **Suggestion**: No, keep it minimal; users can use "Browse EDGAR" for details

4. Should insider trades be two separate buttons or one?
   - **Suggestion**: Combined "SEC Filings" button with submenu, or keep separate for clarity

