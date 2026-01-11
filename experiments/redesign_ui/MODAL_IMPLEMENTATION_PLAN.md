# Modal Implementation Analysis & Plan

## Problem Statement
The JSON modal in the Alpine.js search component (feature/V3.2/hardening) is not displaying when "View JSON" button is clicked, despite the state (`showJsonModal`) changing to true.

## Root Cause Analysis

### What Worked in V3.1
- Used vanilla JavaScript with `createJsonModal()` that dynamically creates DOM elements
- Modal elements created in JavaScript, appended to `document.body`
- Visibility controlled via `style.display = 'flex'` (show) / `'none'` (hide)
- Event listeners attached directly to buttons
- Robust because it didn't depend on Alpine's reactivity

### What's Broken in V3.2/hardening
- Attempted to use declarative HTML with Alpine.js directives (`x-show`, `x-model`, `@click`)
- Modal HTML exists statically in the DOM inside the Alpine component
- Uses `x-show` directive to toggle visibility (adds/removes `display: none`)
- Multiple conflicting CSS rules attempted (inline styles, base class with `display: flex`, x-show overrides)
- Problem: Something in the Alpine/CSS interaction prevents modal from appearing

## Solutions to Consider

### Option 1: Revert to V3.1 Vanilla JS Approach (RECOMMENDED)
**Pros:**
- Known to work from V3.1
- Simpler to debug - no Alpine reactivity issues
- Modal created dynamically, easier to manage lifecycle
- No CSS conflicts with base styles

**Cons:**
- Less "modern" than Alpine.js declarative approach
- Mix of Alpine.js and vanilla JS in same component

**Implementation:**
1. Keep HTML modal HTML in Alpine component but add `style="display: none;"` for initial state
2. Modify `viewResultJson()` in global-search-alpine.js to call vanilla showJsonModal() function
3. Implement `showJsonModal()`, `hideJsonModal()`, `createJsonModal()` functions in global-search-alpine.js
4. Update copy-to-clipboard and close handlers to use vanilla JS approach

### Option 2: Fix Alpine.js Implementation
**Pros:**
- Pure Alpine.js, consistent architecture
- Cleaner HTML structure

**Cons:**
- Harder to debug - interaction between Alpine reactivity, CSS, and x-show is unclear
- May have deeper issues with Alpine configuration

**Investigation Needed:**
- Check if Alpine is properly initialized
- Verify CSS specificity isn't blocking x-show
- Test if Alpine needs explicit data binding confirmation

### Option 3: Hybrid Approach
Create modal dynamically in Alpine component initialization (in `init()` method), then use Alpine state for visibility control.

## Recommendation
**Use Option 1 (Revert to V3.1 vanilla JS)** because:
1. It's proven to work
2. Modal is UI-specific, not core search logic
3. Reduces complexity and debugging burden
4. Easier to test and maintain
5. Clear separation of concerns

## Implementation Steps

1. Remove static HTML modal from index.html (lines 578-598)
2. In global-search-alpine.js:
   - Remove `showJsonModal` state property
   - Remove `selectedJsonResult` state property (use parameter instead)
   - Replace `viewResultJson()`, `closeJsonModal()`, `copyJsonToClipboard()` with vanilla JS versions
   - Keep Alpine component focused on search/filter logic only
   - Call vanilla functions from Alpine component when needed
3. Add vanilla JS functions:
   - `createJsonModal()` - create modal HTML and append to body
   - `showJsonModal(jsonData)` - populate and show modal
   - `hideJsonModal()` - hide modal
   - `copyJsonToClipboard()` - copy displayed JSON
4. Rebuild and test

## Expected Outcome
- View JSON button works and displays modal
- Modal can be closed by clicking X, clicking outside, or Close button
- Copy to Clipboard works
- All functionality matches V3.1 behavior
