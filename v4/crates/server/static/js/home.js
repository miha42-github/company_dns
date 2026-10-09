// Home landing page - the single, centralized search block
// (docs/plans/company-dns-ux.md sec5/sec10.1). Deliberately thin: it
// owns no search logic of its own, it just routes a query to whichever
// real tool already implements it (Industry Classification Explorer,
// SIC Similarity spike, EDGAR Explorer, or the Wikipedia lookup), then
// switches to that panel so the real results render in the real,
// already-working UI. With the top-level tool tabs removed from the
// nav, this page is now the only entry point into any of them.

let homeIcMode = "hybrid";
let homeCompanyMode = "edgar";

function selectHomeSearchTab(tab) {
  const isIc = tab === "ic";
  document.getElementById("homeSearchTabIc").classList.toggle("active", isIc);
  document.getElementById("homeSearchTabCompany").classList.toggle("active", !isIc);
  document.getElementById("homeSearchPanelIc").hidden = !isIc;
  document.getElementById("homeSearchPanelCompany").hidden = isIc;
}

function selectIcMode(mode) {
  homeIcMode = mode;
  document.getElementById("homeIcModeHybrid").classList.toggle("active", mode === "hybrid");
  document.getElementById("homeIcModeCombined").classList.toggle("active", mode === "combined");
  document.getElementById("homeIcModeKeyword").classList.toggle("active", mode === "keyword");
  document.getElementById("homeIcModeSemantic").classList.toggle("active", mode === "semantic");
}

function selectCompanyMode(mode) {
  homeCompanyMode = mode;
  document.getElementById("homeCompanyModeMerged").classList.toggle("active", mode === "merged");
  document.getElementById("homeCompanyModeEdgar").classList.toggle("active", mode === "edgar");
  document.getElementById("homeCompanyModeWikipedia").classList.toggle("active", mode === "wikipedia");
  document.getElementById("homeCompanyModeIndustryMatch").classList.toggle("active", mode === "industry-match");

  const input = document.getElementById("homeCompanyQuery");
  if (mode === "merged") {
    input.placeholder = "Company name, e.g. Apple Inc.";
  } else if (mode === "edgar") {
    input.placeholder = "Company name or CIK, e.g. Apple";
  } else if (mode === "wikipedia") {
    input.placeholder = "Company name, e.g. Apple Inc.";
  } else {
    input.placeholder = "A company name, or paste a description of what it makes and sells: its products, services, or both.";
  }
}

function submitHomeIcSearch(evt) {
  evt.preventDefault();
  const query = document.getElementById("homeIcQuery").value.trim();
  if (!query) return false;

  showContentTab("GlobalSearch");
  selectIcExplorerMode(homeIcMode);

  if (homeIcMode === "keyword") {
    const data = window.Alpine.$data(document.getElementById("GlobalSearch"));
    data.searchQuery = query;
    data.performSearch();
  } else if (homeIcMode === "semantic") {
    icRunSemanticSearch(query);
  } else if (homeIcMode === "hybrid") {
    icRunHybridSearch(query);
  } else {
    icRunCombinedSearch(query);
  }
  return false;
}

function submitHomeCompanySearch(evt) {
  evt.preventDefault();
  const query = document.getElementById("homeCompanyQuery").value.trim();
  if (!query) return false;

  if (homeCompanyMode === "merged") {
    showContentTab("MergedCompany");
    if (window.companyMerged) window.companyMerged.search(query);
  } else if (homeCompanyMode === "edgar") {
    showContentTab("EdgarExplorer");
    const data = window.Alpine.$data(document.getElementById("EdgarExplorer"));
    data.searchQuery = query;
    data.performSearch();
  } else if (homeCompanyMode === "wikipedia") {
    showContentTab("WikipediaResults");
    if (window.wikipediaLookup) window.wikipediaLookup.search(query);
  } else {
    // Industry Match: a company name (its description is fetched) or a pasted
    // description goes to the Company Explorer's Industry Match tab, which
    // returns a recommended SET of codes per system (docs/plans/company-sic-match.md).
    showContentTab("IndustryMatch");
    if (window.industryMatch) window.industryMatch.open(query);
  }
  return false;
}

// Enter searches; Shift+Enter adds a line (the company box is a growable textarea).
document.addEventListener("DOMContentLoaded", () => {
  const box = document.getElementById("homeCompanyQuery");
  if (box) {
    box.addEventListener("keydown", (evt) => {
      if (evt.key === "Enter" && !evt.shiftKey) {
        evt.preventDefault();
        box.form.requestSubmit();
      }
    });
  }
});
