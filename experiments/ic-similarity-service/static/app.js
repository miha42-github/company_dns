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
const truncationWarning = document.getElementById("truncationWarning");
const tokenCountNote = document.getElementById("tokenCountNote");

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

// Input-layer truncation check (moved here per feedback that a
// post-search warning is too late in the process - by then the user
// has already searched with truncated input). Debounced so it's not
// hitting the server on every keystroke; real token counts from the
// actual tokenizer server-side (embed.rs Embedders::token_info), not
// an estimate.
let tokenCheckTimer = null;
let tokenCheckSeq = 0;

function scheduleTokenCheck() {
  clearTimeout(tokenCheckTimer);
  tokenCheckTimer = setTimeout(checkTokenCount, 350);
}

async function checkTokenCount() {
  const q = currentQuery();
  const seq = ++tokenCheckSeq; // guards against a slow older request overwriting a newer result

  if (!q) {
    truncationWarning.style.display = "none";
    tokenCountNote.style.display = "none";
    return;
  }

  try {
    const params = new URLSearchParams({ q, model: MODEL_ID });
    const res = await fetch(`/api/token-count?${params}`);
    if (seq !== tokenCheckSeq) return; // a newer keystroke has already superseded this
    if (!res.ok) return; // don't nag the user over a transient check failure

    const { actual_tokens, max_tokens, truncated } = await res.json();

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
  // truncationWarning/tokenCountNote deliberately left alone here - they're
  // driven by the live input-layer check (checkTokenCount), not by the
  // search response. The user already saw this warning before clicking
  // Search, if it applied.

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
    const data = await res.json();
    const hits = data.results;

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
    const qPreview = q.length > 60 ? `${q.slice(0, 60)}…` : q;
    statusEl.textContent = `${hits.length} result${hits.length === 1 ? "" : "s"} for "${qPreview}"`;
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
