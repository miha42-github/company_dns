// Only one model as of go-duckdb-rewrite.md sec7.8 (all-mpnet-base-v2
// dropped - lost on every quality metric and cost ~484MB extra memory
// for no benefit) - no dropdown needed, just use it directly.
const MODEL_ID = "all_minilm_l6_v2";

// Calibration anchors, measured directly against this corpus's real
// all-MiniLM-L6-v2 pairwise score distribution (see
// docs/plans/ic-similarity-search-poc.md sec5.1) - NOT a generic
// 0-100% assumption, and NOT the corpus-wide-percentile band wording
// tried first (sec5.5/5.6 - "Below Average" etc. read as a verdict on
// the result when it was really a statement about the whole corpus,
// mostly unrelated pairs). Option 1 from sec5.7's literature search:
// plain match-quality language, not statistics.
const CALIBRATION = {
  median: 0.355,
  p95: 0.608,
  p99: 0.776,
};

function similarityBand(sim) {
  if (sim < CALIBRATION.median) return { key: "unlikely", label: "Unlikely Match" };
  if (sim < CALIBRATION.p95) return { key: "possible", label: "Possible Match" };
  if (sim < CALIBRATION.p99) return { key: "likely", label: "Likely Match" };
  return { key: "verysimilar", label: "Very Similar" };
}

// Maps a raw score to a 0-100% bar fill using the median->p99 range as
// the visible scale (clamped) - deliberately NOT a per-query min-max
// rescale of the returned results, which would make a mediocre top
// result look identical to a genuinely excellent one. See sec5.4-5.5.
function barFillPercent(sim) {
  const t = (sim - CALIBRATION.median) / (CALIBRATION.p99 - CALIBRATION.median);
  return Math.max(0, Math.min(1, t)) * 100;
}

const tabSimple = document.getElementById("tabSimple");
const tabDetailed = document.getElementById("tabDetailed");
const panelSimple = document.getElementById("panelSimple");
const panelDetailed = document.getElementById("panelDetailed");
const querySimple = document.getElementById("querySimple");
const queryDetailed = document.getElementById("queryDetailed");
const kInput = document.getElementById("k");
const searchBtn = document.getElementById("searchBtn");
const statusEl = document.getElementById("status");
const resultsTable = document.getElementById("results");
const resultsBody = document.getElementById("resultsBody");
const calibrationNote = document.getElementById("calibrationNote");

let activeMode = "simple";

function setMode(mode) {
  activeMode = mode;
  const isSimple = mode === "simple";
  tabSimple.classList.toggle("active", isSimple);
  tabDetailed.classList.toggle("active", !isSimple);
  panelSimple.hidden = !isSimple;
  panelDetailed.hidden = isSimple;
  (isSimple ? querySimple : queryDetailed).focus();
}

tabSimple.addEventListener("click", () => setMode("simple"));
tabDetailed.addEventListener("click", () => setMode("detailed"));

function currentQuery() {
  return (activeMode === "simple" ? querySimple.value : queryDetailed.value).trim();
}

function renderPath(hit) {
  const parts = [
    hit.section_desc,
    hit.division_desc,
    hit.group_desc,
    hit.class_desc,
  ];
  if (hit.subclass_desc) parts.push(hit.subclass_desc);
  return parts
    .filter(Boolean)
    .map((p) => `<span>${p}</span>`)
    .join('<span class="sep">&gt;</span>');
}

function renderSimCell(sim) {
  const band = similarityBand(sim);
  const fillPct = barFillPercent(sim);
  // Label is the primary signal (plain language, sec5.7); raw score is
  // demoted to small/muted secondary text, not removed - still useful
  // for whoever is using this tool to judge the model itself, just not
  // the first thing the eye lands on.
  return `
    <div class="band-${band.key}" title="raw score: ${sim.toFixed(4)}">
      <span class="sim-band">${band.label}</span>
      <div class="sim-bar-track">
        <div class="sim-bar-fill" style="width:${fillPct}%"></div>
      </div>
      <span class="sim-raw">${(sim * 100).toFixed(1)}%</span>
    </div>`;
}

async function runSearch() {
  const q = currentQuery();
  if (!q) return;

  searchBtn.disabled = true;
  statusEl.className = "status";
  statusEl.textContent = "Searching...";
  resultsTable.style.display = "none";
  calibrationNote.style.display = "none";

  try {
    const params = new URLSearchParams({
      q,
      model: MODEL_ID,
      k: kInput.value || "10",
    });
    const res = await fetch(`/api/similar?${params}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${res.status}`);
    }
    const hits = await res.json();

    resultsBody.innerHTML = hits
      .map(
        (hit) => `
        <tr>
          <td class="rank">${hit.rank}</td>
          <td class="sim-cell">${renderSimCell(hit.similarity)}</td>
          <td class="path">${renderPath(hit)}</td>
        </tr>`
      )
      .join("");

    resultsTable.style.display = hits.length ? "table" : "none";
    calibrationNote.style.display = hits.length ? "block" : "none";
    statusEl.textContent = `${hits.length} result${hits.length === 1 ? "" : "s"} for "${q}"`;
  } catch (e) {
    statusEl.className = "status error";
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
