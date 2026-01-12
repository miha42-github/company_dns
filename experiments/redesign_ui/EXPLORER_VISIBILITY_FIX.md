# Explorer Visibility Fix Notes

## Symptom
- In the Industry Classification Explorer, the status row (e.g., “Showing 1–10 of 15 • Filters: all systems”) and the left sidebar “Classification System:” label were partially hidden.

## Root Cause
- Parent containers were using `overflow: hidden`, which clipped the header and the top of the sidebar when pagination or content height changed.
- The header section had no explicit padding/z-index, so adjacent container borders visually overlapped with its content.

## Changes
- `.explorer-results-filters`: set `overflow: visible` to avoid clipping the top of the sidebar.
- `.explorer-results-area`: set `overflow: visible` to ensure the status/header displays fully.
- Added `.explorer-header-section` with padding and `z-index: 1` to clearly render the header above adjacent container borders.

## References
- Styles moved/updated in `html/styles.css` under the Explorer section.
- Markup uses `.explorer-header-section` containing `.results-status` and the error message.

## Follow-ups
- If minor overlap persists on certain viewports, consider increasing `padding-top` on `.explorer-header-section` or the `.explorer-sidebar`.
