// Wikipedia company lookup - backs the Home Company panel's Wikipedia
// mode (docs/plans/company-dns-ux.md sec10.1). Thin: one real endpoint
// (GET /V4.0/global/company/wikipedia/firmographics/{company_name}),
// rendered into the #WikipediaResults panel already in index.html.
// No dedicated top-level tab - reached via Home's search card, and it has its
// own search bar so another lookup does not mean going back to Home.

function initWikipediaLookup() {
  const statusEl = document.getElementById("wikiStatus");
  const countEl = document.getElementById("wikiCount");
  const emptyHint = document.getElementById("wikiEmptyHint");
  const card = document.getElementById("wikiResultCard");
  const nameEl = document.getElementById("wikiName");
  const typeEl = document.getElementById("wikiType");
  const descEl = document.getElementById("wikiDescription");
  const metaGrid = document.getElementById("wikiMetaGrid");
  const urlEl = document.getElementById("wikiUrl");
  const viewJsonBtn = document.getElementById("wikiViewJsonBtn");
  const form = document.getElementById("wikiSearchForm");
  const queryInput = document.getElementById("wikiQuery");
  const searchBtn = document.getElementById("wikiSearchBtn");

  if (!statusEl) return; // panel markup not present on this page

  let lastData = null;

  // The results header carries the count; the status line is for messages
  // (searching, errors, hints) and is hidden when empty.
  function setStatus(text) {
    statusEl.textContent = text || "";
    statusEl.style.display = text ? "" : "none";
  }

  function metaItem(label, value) {
    if (!value) return "";
    const text = Array.isArray(value) ? value.join(", ") : value;
    return `
      <div class="meta-item">
        <div class="meta-label">${label}</div>
        <div class="meta-value">${text}</div>
      </div>`;
  }

  async function search(companyName) {
    // Keep the bar showing the query being run, whether it was typed here or
    // came from the Home page.
    queryInput.value = companyName;
    searchBtn.disabled = true;
    setStatus(`Searching Wikipedia for "${companyName}"...`);
    countEl.textContent = "No results";
    emptyHint.style.display = "none";
    card.style.display = "none";
    lastData = null;

    try {
      const envelope = await apiService.get(
        `/V4.0/global/company/wikipedia/firmographics/${encodeURIComponent(companyName)}`,
        { timeout: 30000 }
      );

      if (envelope.code !== 200 || !envelope.data) {
        setStatus(envelope.message || `No Wikipedia match for "${companyName}".`);
        return;
      }

      const data = envelope.data;
      lastData = data;

      nameEl.textContent = data.name || companyName;
      typeEl.textContent = data.type || "Wikipedia";
      descEl.textContent = data.description || "";
      metaGrid.innerHTML = [
        metaItem("Industry", data.industry),
        metaItem("Country", data.country),
        metaItem("City", data.city),
        metaItem("Exchanges", data.exchanges),
        metaItem("Tickers", data.tickers),
        metaItem("ISIN", data.isin),
        metaItem("CIK", data.cik),
      ].join("");

      if (data.wikipediaURL) {
        urlEl.href = data.wikipediaURL;
        urlEl.textContent = data.wikipediaURL;
        urlEl.style.display = "inline";
      } else {
        urlEl.style.display = "none";
      }

      card.style.display = "block";
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

  viewJsonBtn.addEventListener("click", () => {
    if (lastData && window.showJsonModal) showJsonModal(lastData);
  });

  window.wikipediaLookup = { search };
}

document.addEventListener("DOMContentLoaded", initWikipediaLookup);
