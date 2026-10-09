// Company Explorer - Merged tab. One company record built from EDGAR and
// Wikipedia together, backed by
//   GET /V4.0/global/company/merged/firmographics/{company_name}
// (docs/plans/v4-server-prototype.md 8.2). The endpoint looks the company up on
// Wikipedia first, then finds its EDGAR filings by the CIK Wikipedia reports
// (or, with no CIK, a whole-word name match that must pick out one company). Its
// answer says which sources contributed:
//   data.source      "edgar+wikipedia" | "wikipedia-only" | "edgar-only" | "none"
//   data.edgar_match "cik" | "name" (only when EDGAR contributed)
//   data.note        why a source is missing, when one is
//   data.edgar       the matched company's 10-x filing rows, newest first
//   data.wikipedia   the Wikipedia/Wikidata profile

function initCompanyMerged() {
  const form = document.getElementById("mergedSearchForm");
  if (!form) return; // panel markup not present on this page

  const queryInput = document.getElementById("mergedQuery");
  const searchBtn = document.getElementById("mergedSearchBtn");
  const countEl = document.getElementById("mergedCount");
  const statusEl = document.getElementById("mergedStatus");
  const emptyHint = document.getElementById("mergedEmptyHint");
  const card = document.getElementById("mergedResultCard");
  let lastData = null;

  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  function setStatus(text) {
    statusEl.textContent = text || "";
    statusEl.style.display = text ? "" : "none";
  }

  function metaItem(label, value) {
    if (value === undefined || value === null || value === "" || (Array.isArray(value) && !value.length)) return "";
    const text = Array.isArray(value) ? value.join(", ") : value;
    return `<div class="meta-item"><div class="meta-label">${esc(label)}</div><div class="meta-value">${esc(text)}</div></div>`;
  }

  // The SEC's own pages, the same ones the EDGAR tab links to.
  const filingUrl = (cik, accession) =>
    `https://www.sec.gov/Archives/edgar/data/${cik}/${accession.replace(/-/g, "")}/${accession}-index.html`;
  const pad = (n) => String(n).padStart(2, "0");
  const dateOf = (r) => `${r.year}-${pad(r.month)}-${pad(r.day)}`;

  function render(data) {
    const wiki = data.wikipedia || null;
    const filings = Array.isArray(data.edgar) ? data.edgar : [];
    const hasEdgar = filings.length > 0;
    const cik = hasEdgar ? filings[0].cik : wiki && /^\d+$/.test(wiki.cik || "") ? parseInt(wiki.cik, 10) : null;
    const name = (wiki && wiki.name) || (hasEdgar && filings[0].company_name) || data.query;

    document.getElementById("mergedName").textContent = name;

    // Which sources contributed: lit in their own colour, dim when absent.
    document.getElementById("mergedSources").innerHTML =
      `<span class="ic-sys-chip src-edgar${hasEdgar ? " on" : ""}">EDGAR</span>` +
      `<span class="ic-sys-chip src-wikipedia${wiki ? " on" : ""}">Wikipedia</span>`;

    const matchEl = document.getElementById("mergedMatch");
    if (hasEdgar && data.edgar_match === "cik") matchEl.textContent = `EDGAR matched by CIK ${cik}`;
    else if (hasEdgar) matchEl.textContent = "EDGAR matched by name";
    else matchEl.textContent = "Wikipedia only";
    matchEl.className = `explorer-engine-badge ${hasEdgar ? "engine-both" : "engine-semantic"}`;

    const noteEl = document.getElementById("mergedNote");
    noteEl.hidden = !data.note;
    noteEl.textContent = data.note || "";

    document.getElementById("mergedDescription").textContent = (wiki && wiki.description) || "";

    // EDGAR facts from the loaded filing window.
    // Exact form types: a 10-K/A amendment is not "the latest 10-K" (the Recent
    // Filings pills below list amendments under their own type).
    const latest = (type) => filings.find((r) => r.form_type === type);
    const k = latest("10-K");
    const q = latest("10-Q");
    document.getElementById("mergedMetaGrid").innerHTML = [
      metaItem("Industry", wiki && wiki.industry),
      metaItem("Country", wiki && wiki.country),
      metaItem("City", wiki && wiki.city),
      metaItem("Exchanges", wiki && wiki.exchanges),
      metaItem("Tickers", wiki && wiki.tickers),
      metaItem("ISIN", wiki && wiki.isin),
      metaItem("CIK", cik),
      metaItem("EDGAR name", hasEdgar && filings[0].company_name),
      metaItem("10-x filings on file", hasEdgar && filings.length),
      metaItem("Latest 10-K", k && dateOf(k)),
      metaItem("Latest 10-Q", q && dateOf(q)),
    ].join("");

    const formsRow = document.getElementById("mergedFormsRow");
    formsRow.style.display = hasEdgar ? "" : "none";
    document.getElementById("mergedForms").innerHTML = filings
      .slice(0, 5)
      .map(
        (r) =>
          `<a class="edgar-pill" href="${esc(filingUrl(r.cik, r.accession))}" target="_blank" rel="noopener">` +
          `<i class="external-link-icon"></i><span>${esc(r.form_type)} ${esc(dateOf(r))}</span></a>`
      )
      .join("");

    const links = [];
    if (cik) {
      links.push(["Browse EDGAR", `https://www.sec.gov/cgi-bin/browse-edgar?CIK=${cik}&action=getcompany`]);
      links.push(["Issuer Transactions", `https://www.sec.gov/cgi-bin/own-disp?action=getissuer&CIK=${cik}`]);
      links.push(["Insider Trades", `https://www.sec.gov/cgi-bin/own-disp?action=getowner&CIK=${cik}`]);
    }
    if (wiki && wiki.wikipediaURL) links.push(["Wikipedia", wiki.wikipediaURL]);
    document.getElementById("mergedLinks").innerHTML = links
      .map(([label, href]) => `<a href="${esc(href)}" target="_blank" rel="noopener" class="edgar-quick-link">${esc(label)}</a>`)
      .join("");

    card.style.display = "block";
  }

  async function search(companyName) {
    // Keep the bar showing the query being run, whether typed here or carried
    // over from Home or another Company tab.
    queryInput.value = companyName;
    searchBtn.disabled = true;
    setStatus(`Looking up "${companyName}" on EDGAR and Wikipedia...`);
    countEl.textContent = "No results";
    emptyHint.style.display = "none";
    card.style.display = "none";
    lastData = null;

    try {
      const envelope = await apiService.get(
        `/V4.0/global/company/merged/firmographics/${encodeURIComponent(companyName)}`,
        { timeout: 60000 }
      );
      const data = envelope.data;
      if (envelope.code !== 200 || !data) {
        setStatus(envelope.message || `Nothing found for "${companyName}".`);
        return;
      }
      // Neither source found it: the endpoint still answers 200 and says why.
      if (data.source === "none") {
        setStatus(data.note || `Nothing found for "${companyName}".`);
        return;
      }
      lastData = data;
      render(data);
      countEl.textContent = "1 result";
      setStatus("");
    } catch (e) {
      setStatus(`Error: ${e.message}`);
    } finally {
      searchBtn.disabled = false;
    }
  }

  form.addEventListener("submit", (evt) => {
    evt.preventDefault();
    const q = queryInput.value.trim();
    if (q) search(q);
  });

  document.getElementById("mergedViewJsonBtn").addEventListener("click", () => {
    if (lastData && window.showJsonModal) showJsonModal(lastData);
  });

  window.companyMerged = { search };
}

document.addEventListener("DOMContentLoaded", initCompanyMerged);
