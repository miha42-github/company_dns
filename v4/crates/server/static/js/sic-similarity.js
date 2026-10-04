// SIC Similarity Search tab - ported forward from
// experiments/ic-similarity-service/static/app.js (docs/plans/
// company-dns-ux.md sec4/sec10.2: "pull the existing prototype in as
// a baseline... iterate from there"). Logic unchanged; only the
// endpoints and response envelope differ, since this now talks to the
// real V4 server (ApiEnvelope-wrapped) instead of the spike's own
// bespoke /api/similar and /api/token-count routes.

const SIM_MODEL_ID = "all_minilm_l6_v2";

// Calibration anchors, measured directly against this corpus's real
// all-MiniLM-L6-v2 pairwise score distribution (see
// docs/plans/ic-similarity-search-poc.md sec5.1) - NOT a generic
// 0-100% assumption. Carried over unchanged from the spike.
const SIM_CALIBRATION = {
  median: 0.355,
  p95: 0.608,
  p99: 0.776,
};

function simSimilarityBand(sim) {
  if (sim < SIM_CALIBRATION.median) return { key: "unlikely", label: "Unlikely Match" };
  if (sim < SIM_CALIBRATION.p95) return { key: "possible", label: "Possible Match" };
  if (sim < SIM_CALIBRATION.p99) return { key: "likely", label: "Likely Match" };
  return { key: "verysimilar", label: "Very Similar" };
}

function simBarFillPercent(sim) {
  const t = (sim - SIM_CALIBRATION.median) / (SIM_CALIBRATION.p99 - SIM_CALIBRATION.median);
  return Math.max(0, Math.min(1, t)) * 100;
}

function initSicSimilarityTab() {
  const tabSimple = document.getElementById("simTabSimple");
  const tabDetailed = document.getElementById("simTabDetailed");
  const panelSimple = document.getElementById("simPanelSimple");
  const panelDetailed = document.getElementById("simPanelDetailed");
  const querySimple = document.getElementById("simQuerySimple");
  const queryDetailed = document.getElementById("simQueryDetailed");
  const kInput = document.getElementById("simK");
  const searchBtn = document.getElementById("simSearchBtn");
  const statusEl = document.getElementById("simStatus");
  const resultsTable = document.getElementById("simResults");
  const resultsBody = document.getElementById("simResultsBody");
  const calibrationNote = document.getElementById("simCalibrationNote");
  const truncationWarning = document.getElementById("simTruncationWarning");
  const tokenCountNote = document.getElementById("simTokenCountNote");

  if (!tabSimple) return; // tab markup not present on this page

  let activeMode = "simple";

  function setMode(mode) {
    activeMode = mode;
    const isSimple = mode === "simple";
    tabSimple.classList.toggle("active", isSimple);
    tabDetailed.classList.toggle("active", !isSimple);
    panelSimple.hidden = !isSimple;
    panelDetailed.hidden = isSimple;
    (isSimple ? querySimple : queryDetailed).focus();
    checkTokenCount();
  }

  tabSimple.addEventListener("click", () => setMode("simple"));
  tabDetailed.addEventListener("click", () => setMode("detailed"));

  function currentQuery() {
    return (activeMode === "simple" ? querySimple.value : queryDetailed.value).trim();
  }

  let tokenCheckTimer = null;
  let tokenCheckSeq = 0;

  function scheduleTokenCheck() {
    clearTimeout(tokenCheckTimer);
    tokenCheckTimer = setTimeout(checkTokenCount, 350);
  }

  async function checkTokenCount() {
    const q = currentQuery();
    const seq = ++tokenCheckSeq;

    if (!q) {
      truncationWarning.style.display = "none";
      tokenCountNote.style.display = "none";
      return;
    }

    try {
      const params = new URLSearchParams({ q, model: SIM_MODEL_ID });
      const res = await fetch(`/V4.0/na/sic/similarity-check?${params}`);
      if (seq !== tokenCheckSeq) return;
      if (!res.ok) return;

      const envelope = await res.json();
      const { actual_tokens, max_tokens, truncated } = envelope.data || {};
      if (actual_tokens === undefined) return;

      if (truncated) {
        const dropped = actual_tokens - max_tokens;
        const pct = Math.round((dropped / actual_tokens) * 100);
        truncationWarning.textContent =
          `⚠ This text is too long for the model: only the first ${max_tokens} of ${actual_tokens} ` +
          `tokens will be used (the last ${pct}% will be ignored if you search now). Shorten it, or ` +
          `search anyway knowing the tail won't be seen.`;
        truncationWarning.style.display = "block";
        tokenCountNote.style.display = "none";
      } else {
        truncationWarning.style.display = "none";
        tokenCountNote.textContent = `${actual_tokens} / ${max_tokens} tokens`;
        tokenCountNote.style.display = "block";
      }
    } catch {
      // network hiccup on a live-typing check - not worth surfacing as an error
    }
  }

  querySimple.addEventListener("input", scheduleTokenCheck);
  queryDetailed.addEventListener("input", scheduleTokenCheck);

  function renderPath(hit) {
    const parts = [hit.section_desc, hit.division_desc, hit.group_desc, hit.class_desc];
    if (hit.subclass_desc) parts.push(hit.subclass_desc);
    return parts
      .filter(Boolean)
      .map((p) => `<span>${p}</span>`)
      .join('<span class="sic-sim-sep">&gt;</span>');
  }

  function renderSimCell(sim) {
    const band = simSimilarityBand(sim);
    const fillPct = simBarFillPercent(sim);
    return `
      <div class="sic-sim-band-${band.key}" title="raw score: ${sim.toFixed(4)}">
        <span class="sic-sim-band-label">${band.label}</span>
        <div class="sic-sim-bar-track">
          <div class="sic-sim-bar-fill" style="width:${fillPct}%"></div>
        </div>
        <span class="sic-sim-raw">${(sim * 100).toFixed(1)}%</span>
      </div>`;
  }

  async function runSearch() {
    const q = currentQuery();
    if (!q) return;

    searchBtn.disabled = true;
    statusEl.className = "sic-sim-status";
    statusEl.textContent = "Searching...";
    resultsTable.style.display = "none";
    calibrationNote.style.display = "none";

    try {
      const params = new URLSearchParams({
        model: SIM_MODEL_ID,
        k: kInput.value || "10",
      });
      const res = await fetch(`/V4.0/na/sic/similarity/${encodeURIComponent(q)}?${params}`);
      const envelope = await res.json();
      if (!res.ok) {
        throw new Error(envelope.message || `HTTP ${res.status}`);
      }
      const hits = envelope.data || [];

      resultsBody.innerHTML = hits
        .map(
          (hit) => `
          <tr>
            <td class="sic-sim-rank">${hit.rank}</td>
            <td class="sic-sim-cell">${renderSimCell(hit.similarity)}</td>
            <td class="sic-sim-path">${renderPath(hit)}</td>
          </tr>`
        )
        .join("");

      resultsTable.style.display = hits.length ? "table" : "none";
      calibrationNote.style.display = hits.length ? "block" : "none";
      const qPreview = q.length > 60 ? `${q.slice(0, 60)}…` : q;
      statusEl.textContent = `${hits.length} result${hits.length === 1 ? "" : "s"} for "${qPreview}"`;
    } catch (e) {
      statusEl.className = "sic-sim-status sic-sim-status-error";
      statusEl.textContent = `Error: ${e.message}`;
    } finally {
      searchBtn.disabled = false;
    }
  }

  searchBtn.addEventListener("click", runSearch);
  querySimple.addEventListener("keydown", (e) => {
    if (e.key === "Enter") runSearch();
  });
  queryDetailed.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) runSearch();
  });

  // Public hook for the Home landing page's search block (home.js) -
  // company-dns-ux.md sec5: the landing search "hooks up" to the real
  // tools rather than reimplementing search a third time. Always
  // lands in Simple mode - the landing box is a single-line input,
  // same shape as Simple's.
  window.sicSimilarity = {
    search(query) {
      setMode("simple");
      querySimple.value = query;
      checkTokenCount();
      runSearch();
    },
  };
}

document.addEventListener("DOMContentLoaded", initSicSimilarityTab);
