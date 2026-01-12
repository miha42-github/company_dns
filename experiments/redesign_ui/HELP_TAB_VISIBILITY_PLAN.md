# Help Tab Visibility Plan

## Issue
- Home's help section (see guidance around `<!-- EDGAR Explorer Tab -->` and `<!-- Code Examples Tab -->`) renders the content in the markup but the EDGAR Explorer and Code Examples panes stay hidden when their buttons are clicked.
- The selector `openHelpTab` currently only removes/sets the `active` class, but all help panes have `display: none` by default, so the browser never shows the later tabs unless their `display` is explicitly updated.

## Hypothesis
1. The inline `openHelpTab` handler (lines 65-69 in `html/index.html`) lacks an explicit `display` toggle, so the default CSS continues to hide the target panel.
2. Initialization trusts the first help button to be active only via the `active` class, which may desynchronize if the markup changes or if there is a missing class in the HTML.
3. This leads to two symptoms: non-visible EDGAR/Code Examples panels despite present content, and the entire help tab area freezing once the user interacts with it.

## Proposed Plan
1. Annotate each help tab button with a `data-help-tab` attribute to pair a stable identifier with every pane without relying on parsing inline handler strings.
2. Build `activateHelpTabContent` in `html/js/functions.js` that toggles both the `active` class and the inline `style.display`, guaranteeing that the clicked pane becomes visible while all others stay hidden.
3. Call the helper from `openHelpTab` (still wired to the inline `onclick` hooks) and from a DOMContentLoaded initializer that activates the first pane so the default overview tab is visible immediately.
4. Keep the existing inline handlers as a fallback for browsers that may load the script later; the helper ensures the `display` logic works the same way regardless of how the event was fired.

## Next Steps
- Confirm the new helper keeps the overview pane open by default even after tab switches or page reloads.
- Smoke-test each help button (Overview, API Documentation, Industry Classification Explorer, EDGAR Explorer, Code Examples) in the browser to verify their content renders.
- If the problem persists, use the browser inspector to verify no extra CSS (e.g., `overflow` containers) interferes.
