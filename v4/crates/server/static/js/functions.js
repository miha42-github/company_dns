// Programmatic content-tab switch (docs/plans/company-dns-ux.md
// sec10.1, centralized-search redesign). Replaces the old
// event-driven openTab()/navigateToTab() pair - with the top-level
// Industry Classification/EDGAR/SIC Similarity tabs removed from the
// nav (the Home search card is now the only way into them), there is
// no longer a real click event or visible tab-bar button behind most
// switches, so this takes just the target id. Still used for: the
// persistent "company_dns" brand link, the About item in the dropdown
// menu, and every tool handoff from home.js.
// Per-page title shown in the top bar next to "Home" (per direct
// feedback - replaces each page's own big in-page header). Empty on
// Home itself, where the wordmark already carries the branding.
const PAGE_TITLES = {
    GlobalSearch: "Industry Classification Explorer",
    MergedCompany: "Company Explorer",
    EdgarExplorer: "Company Explorer",
    SicSimilarity: "SIC Similarity (spike)",
    WikipediaResults: "Company Explorer",
    IndustryMatch: "Company Explorer",
    About: "About",
};

function showContentTab(tabName) {
    console.log(`Tab switch: ${tabName}`);

    const titleEl = document.getElementById("pageTitle");
    if (titleEl) titleEl.textContent = PAGE_TITLES[tabName] || "";

    const allTabContents = [
        ...document.getElementsByClassName("explorer-pagecontent"),
        ...document.getElementsByClassName("help-pagecontent")
    ];
    allTabContents.forEach((el) => { el.style.display = "none"; });

    const selectedTab = document.getElementById(tabName);
    if (selectedTab) {
        // This was the actual root cause behind an entire run of
        // Explorer layout bugs (nested scroll, overlapping pagination,
        // content growing past the footer with no way to reach it) -
        // not any of the CSS this was chased through at the time.
        // Every .explorer-pagecontent tab (Home, GlobalSearch,
        // EdgarExplorer, SicSimilarity, WikipediaResults) is a flex
        // container BY ITS OWN CSS (`.explorer-pagecontent { display:
        // flex }`), and their entire internal layouts - sidebar+
        // results scrolling independently while the search bar stays
        // put, in particular - depend on that. Hardcoding "block" here
        // for anything that wasn't .home-landing silently overrode
        // that flex display with an inline style (which always beats
        // a stylesheet rule), breaking the flex chain for GlobalSearch
        // and leaving the same latent bug sitting unnoticed in every
        // other .explorer-pagecontent tab. .help-pagecontent (About)
        // is the only tab that's actually meant to be a plain block
        // layout.
        selectedTab.style.display = selectedTab.classList.contains("explorer-pagecontent") ? "flex" : "block";
    } else {
        console.error(`Tab ${tabName} not found!`);
    }

    // Only the brand link still renders as a persistent nav element -
    // mark it active when it's the current tab, inactive otherwise.
    document.querySelectorAll('[data-tabname]').forEach((el) => {
        el.classList.toggle('active', el.dataset.tabname === tabName);
    });
}

// Back-compat alias - same thing, name used by earlier callers.
function navigateToTab(tabName) {
    showContentTab(tabName);
}

// About page's "API Versions" tabbed view (V4.0 current / V3.0
// compatibility aliases) - was a static side-by-side comparison,
// moved to a tab selector on request.
function selectVersionTab(which) {
    document.querySelectorAll('.version-tab').forEach(function (tab) {
        tab.classList.toggle('active', tab.getAttribute('data-version-tab') === which);
    });
    ['v4', 'v3', 'v2'].forEach(function (v) {
        const panel = document.getElementById('versionTab' + v.toUpperCase());
        if (panel) panel.hidden = v !== which;
    });
}

// Function to copy code examples to clipboard
function copyToClipboard(button) {
  // Get the element to copy from
  let targetId = button.getAttribute('data-copy-target');
  let textToCopy = '';
  
  if (targetId) {
    // For URL copying
    const targetElement = document.getElementById(targetId);
    textToCopy = targetElement.textContent;
  } else {
    // For code block copying (existing functionality)
    const codeBlock = button.previousElementSibling;
    textToCopy = codeBlock.textContent;
  }
  
  navigator.clipboard.writeText(textToCopy).then(() => {
    // Change button text temporarily
    const originalText = button.querySelector('.copy-text').textContent;
    button.querySelector('.copy-text').textContent = 'Copied!';
    
    setTimeout(() => {
      button.querySelector('.copy-text').textContent = originalText;
    }, 2000);
  }).catch(err => {
    console.error('Failed to copy text: ', err);
  });
}

function activateHelpTabContent(tabName, buttonElement) {
  const tabContents = document.querySelectorAll('.help-tab-content');
  let targetContent = null;
  tabContents.forEach((content) => {
    const isTarget = content.id === tabName;
    content.classList.toggle('active', isTarget);
    content.style.display = isTarget ? 'block' : 'none';
    if (isTarget) {
      targetContent = content;
    }
  });

  if (!targetContent) {
    console.warn(`Help tab content not found: ${tabName}`);
    return;
  }

  const tabButtons = document.querySelectorAll('.help-tab-button');
  const activeButton = buttonElement || document.querySelector(`.help-tab-button[data-help-tab="${tabName}"]`);
  tabButtons.forEach((button) => {
    button.classList.toggle('active', button === activeButton);
  });
}

function openHelpTab(evt, tabName) {
  if (evt && typeof evt.preventDefault === 'function') {
    evt.preventDefault();
  }
  activateHelpTabContent(tabName, evt.currentTarget);
}

// Initialize the help section on page load
document.addEventListener('DOMContentLoaded', function() {
  const initialHelpButton = document.querySelector('.help-tab-button[data-help-tab]');
  if (initialHelpButton) {
    activateHelpTabContent(initialHelpButton.dataset.helpTab, initialHelpButton);
  }
});

// Add this function to handle copying the response JSON

function copyResponseToClipboard() {
  const responseElement = document.getElementById('queryResults');
  let textToCopy = '';
  
  // Check if the results contain a pre element (formatted JSON)
  const preElement = responseElement.querySelector('pre');
  if (preElement) {
    textToCopy = preElement.textContent;
  } else {
    textToCopy = responseElement.textContent;
  }
  
  // Only copy if there's content
  if (textToCopy.trim() && !textToCopy.includes('Execute a request to see results')) {
    navigator.clipboard.writeText(textToCopy).then(() => {
      const button = document.getElementById('copyResponseButton');
      const originalText = button.querySelector('.copy-text').textContent;
      button.querySelector('.copy-text').textContent = 'Copied!';
      
      setTimeout(() => {
        button.querySelector('.copy-text').textContent = originalText;
      }, 2000);
    }).catch(err => {
      console.error('Failed to copy text: ', err);
    });
  }
}

// Add this new function specifically for inner tabs
function openInnerTab(evt, tabName, tabContentClass, tabLinks) {
    console.log(`Inner tab switch: ${tabName}, content class: ${tabContentClass}`);
    
    // Only hide tabs of the specified content class
    const tabContents = document.getElementsByClassName(tabContentClass);
    for (let i = 0; i < tabContents.length; i++) {
        tabContents[i].style.display = "none";
    }
    
    // Remove active class from specified tab buttons
    const tablinks = document.getElementsByClassName(tabLinks);
    for (let i = 0; i < tablinks.length; i++) {
        tablinks[i].className = tablinks[i].className.replace(" active", "");
    }
    
    // Show the selected tab and mark button as active
    const selectedTab = document.getElementById(tabName);
    if (selectedTab) {
        selectedTab.style.display = "block";
        console.log(`Showing inner tab: ${tabName}`);
    } else {
        console.error(`Inner tab ${tabName} not found!`);
    }
    
    evt.currentTarget.className += " active";
}
// Top-right dropdown menu (company-dns-ux.md step-1 redesign): holds
// the "Report Issues"/"Source Repository" links that used to live
// inline in the About page's Additional Resources section. Closes on
// an outside click or Escape, not just on re-toggle.
function toggleMoreMenu(evt) {
    if (evt) evt.stopPropagation();
    const menu = document.getElementById('moreMenuDropdown');
    if (!menu) return;
    menu.classList.toggle('open');
}

document.addEventListener('click', (evt) => {
    const menu = document.getElementById('moreMenuDropdown');
    if (!menu || !menu.classList.contains('open')) return;
    if (!menu.contains(evt.target)) menu.classList.remove('open');
});

document.addEventListener('keydown', (evt) => {
    if (evt.key !== 'Escape') return;
    const menu = document.getElementById('moreMenuDropdown');
    if (menu) menu.classList.remove('open');
});
