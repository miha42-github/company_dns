// Company Explorer - the Merged, EDGAR and Wikipedia company lookups presented
// the way the Industry Classification Explorer is: one experience, a mode tab
// row, a pinned search bar. The three modes are still three pages (EDGAR's is an
// Alpine component, Merged and Wikipedia are plain scripts); this is the tab row
// between them. Switching tabs carries the current query across and runs it in
// the other mode unless that mode already shows it, so the tabs behave like the
// IC tabs do (the query follows you; it is not retyped).

const COMPANY_PAGES = {
  merged: "MergedCompany",
  edgar: "EdgarExplorer",
  wikipedia: "WikipediaResults",
};

function companyEdgarData() {
  try {
    return window.Alpine?.$data(document.getElementById("EdgarExplorer"));
  } catch {
    return null;
  }
}

// Which company mode is on screen right now (Home can open any of them directly).
function companyActiveMode() {
  return Object.keys(COMPANY_PAGES).find((m) => {
    const el = document.getElementById(COMPANY_PAGES[m]);
    return el && el.style.display !== "none";
  });
}

// The query currently in a mode's own search bar.
function companyQueryOf(mode) {
  if (mode === "edgar") return (companyEdgarData()?.searchQuery || "").trim();
  const id = mode === "merged" ? "mergedQuery" : "wikiQuery";
  return (document.getElementById(id)?.value || "").trim();
}

// Whether a mode is already showing results (or an answer) for `query`.
function companyModeShows(mode, query) {
  if (companyQueryOf(mode) !== query) return false;
  if (mode === "edgar") {
    const d = companyEdgarData();
    return !!(d && (d.hasResults || d.errorMessage));
  }
  const prefix = mode === "merged" ? "merged" : "wiki";
  const card = document.getElementById(`${prefix}ResultCard`);
  const status = document.getElementById(`${prefix}Status`);
  return !!(card && card.style.display !== "none") || !!(status && status.textContent);
}

function showCompanyMode(mode) {
  const from = companyActiveMode();
  const query = from && from !== mode ? companyQueryOf(from) : "";

  showContentTab(COMPANY_PAGES[mode]);
  if (!query || companyModeShows(mode, query)) return;

  if (mode === "edgar") {
    const d = companyEdgarData();
    if (d) {
      d.searchQuery = query;
      d.performSearch();
    }
  } else if (mode === "merged") {
    window.companyMerged?.search(query);
  } else {
    window.wikipediaLookup?.search(query);
  }
}
