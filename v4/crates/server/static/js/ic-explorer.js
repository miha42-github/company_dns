// Industry Classification Explorer - Combined/Semantic modes
// (docs/plans/company-dns-ux.md sec10.2, redesign step 2). Keyword
// mode is the pre-existing Alpine component (global-search-alpine.js),
// untouched. This file only owns mode switching and the two new
// modes. First iteration - to be refined.

// Keyword mode's query is the Alpine component's own reactive state
// (global-search-alpine.js's searchQuery, already kept in sync with
// the ?q= URL param). Read directly off it rather than re-deriving
// from the URL or an input field, so this always matches whatever
// Keyword mode actually last searched - including a query that
// arrived via deep link and was never typed into any input here.
function icGetActiveQuery() {
  try {
    const data = window.Alpine?.$data(document.getElementById("GlobalSearch"));
    return (data?.searchQuery || "").trim();
  } catch {
    return "";
  }
}

// Last query each mode has actually run a search for (set inside
// icRunSemanticSearch/icRunCombinedSearch/icRunHybridSearch, not just here) - lets
// switching modes auto-run Keyword's current query without re-running
// it on every tab click, and without clobbering text the user is
// mid-typing into Semantic/Combined's own box if it hasn't changed.
let icSemanticLastQuery = null;
let icCombinedLastQuery = null;
let icHybridLastQuery = null;

function selectIcExplorerMode(mode) {
  document.querySelectorAll('.home-search-tab[data-ic-explorer-mode]').forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.icExplorerMode === mode);
  });
  document.getElementById("icModeKeyword").hidden = mode !== "keyword";
  document.getElementById("icModeSemantic").hidden = mode !== "semantic";
  document.getElementById("icModeCombined").hidden = mode !== "combined";
  document.getElementById("icModeHybrid").hidden = mode !== "hybrid";

  const query = icGetActiveQuery();
  if (!query) return;

  if (mode === "semantic" && query !== icSemanticLastQuery) {
    icRunSemanticSearch(query);
  } else if (mode === "combined" && query !== icCombinedLastQuery) {
    icRunCombinedSearch(query);
  } else if (mode === "hybrid" && query !== icHybridLastQuery) {
    icRunHybridSearch(query);
  }
}

async function icFetchSimilar(query, k) {
  // docs/plans/sic-global-search.md: global/multi-system endpoint,
  // same as Keyword's icFetchKeyword - fans out across every
  // registered classification system (today: US SIC, Japan SIC),
  // merged and re-ranked by similarity server-side. Used by both the
  // main Semantic tab and Compare mode's Semantic column.
  const params = new URLSearchParams({ model: "all_minilm_l6_v2", k: String(k) });
  const res = await fetch(`/V4.0/global/sic/similarity/${encodeURIComponent(query)}?${params}`);
  const envelope = await res.json();
  if (!res.ok) throw new Error(envelope.message || `HTTP ${res.status}`);
  return envelope.data || [];
}

async function icFetchKeyword(query) {
  // docs/plans/sic-global-search.md: same global/multi-system endpoint
  // the main Keyword tab uses (global-search-alpine.js), not the
  // US-only /V4.0/na/sic/description - Compare mode's Keyword column
  // was still pointed at the old one until this was flagged directly
  // ("Is the UI's keyword focused on global?"), an inconsistency with
  // the main Keyword tab rather than a deliberate choice.
  //
  // Plain fetch, not apiService.get() - a keyword miss is a real 404
  // from the server (not_found(), not an error condition), and
  // apiService.get() throws on any non-2xx status with a generic
  // "API Error" message. A 404 here just means zero keyword matches,
  // same as Semantic mode showing "0 results" - not a fetch failure.
  const res = await fetch(`/V4.0/global/sic/description/${encodeURIComponent(query)}`);
  if (res.status === 404) return [];
  const envelope = await res.json();
  if (!res.ok) throw new Error(envelope.message || `HTTP ${res.status}`);
  return Array.isArray(envelope.data) ? envelope.data : [];
}

// Every classification system the server can currently return, in
// facet-row order (docs/plans/sic-global-search.md). `label` is the
// server's source_type, `idKey` is the suffix on this system's facet
// checkbox/count element ids in index.html (e.g.
// icSemanticFilter<idKey>), `pill` its colour class (styles.css). Adding
// a system = one entry here plus its checkbox markup in index.html's
// Keyword/Semantic sidebars and Compare columns - the filter/count
// logic below is driven off this list, not hardcoded per system.
const IC_SOURCES = [
  { label: "US SIC", idKey: "UsSic", pill: "pill-us_sic" },
  { label: "Japan SIC", idKey: "JapanSic", pill: "pill-japan_sic" },
  { label: "EU NACE", idKey: "EuNace", pill: "pill-eu_nace" },
  { label: "ISIC", idKey: "Isic", pill: "pill-isic" },
];
const IC_SOURCE_LABELS = IC_SOURCES.map((s) => s.label);

function icSourceIdKey(label) {
  return IC_SOURCES.find((s) => s.label === label).idKey;
}

function icSourcePillClass(sourceType) {
  return IC_SOURCES.find((s) => s.label === sourceType)?.pill ?? "pill-us_sic";
}

function icRenderKeywordCard(match, opts = {}) {
  const cardClass = opts.compact ? "explorer-result-card compact" : "explorer-result-card";
  const sourceType = match.source_type || "US SIC";
  return `
    <div class="${cardClass}">
      <div class="explorer-result-header">
        <div class="explorer-result-heading">
          <span class="explorer-result-code">${match.class_id}</span>
          <span class="explorer-source-pill ${icSourcePillClass(sourceType)}">${sourceType}</span>
        </div>
        ${
          opts.compact
            ? `<div class="explorer-result-actions"><button class="explorer-view-json-btn" onclick="icViewCombinedKeywordJson(${opts.index})">View JSON</button></div>`
            : ""
        }
      </div>
      <p class="explorer-result-description">${match.class_desc}</p>
    </div>`;
}

// -------------------------------------------------------------- //
// Combined (hybrid) mode - docs/plans/sic-hybrid-search.md.
//
// One fused ranking of keyword + semantic results across every system
// (Reciprocal Rank Fusion, done server-side by /V4.0/global/sic/hybrid).
// The visible tab label is "Combined"; everything here is named "hybrid"
// because Compare mode's code already owns the name "combined"
// (icCombined*, #icModeCombined).
//
// The endpoint is called once with its maximum k (50) and the results are
// paged here in the browser. System facets filter the full set first, and
// every count and "Showing a-b of N" figure refers to the full filtered set,
// never to the visible page.

const HYBRID_FETCH_K = 50;
let icHybridHits = [];
let icHybridActiveSources = new Set(IC_SOURCE_LABELS);
let icHybridPage = 1;
const HYBRID_PAGE_SIZE = 10;

async function icFetchHybrid(query, k) {
  const params = new URLSearchParams({ model: "all_minilm_l6_v2", k: String(k) });
  const res = await fetch(`/V4.0/global/sic/hybrid/${encodeURIComponent(query)}?${params}`);
  const envelope = await res.json();
  if (!res.ok) throw new Error(envelope.message || `HTTP ${res.status}`);
  return envelope.data || [];
}

async function submitIcExplorerHybridSearch(evt) {
  evt.preventDefault();
  const query = document.getElementById("icHybridQuery").value.trim();
  if (!query) return false;
  await icRunHybridSearch(query);
  return false;
}

function icSetHybridStatus(text) {
  icSetStatusText(document.getElementById("icHybridStatus"), text);
}

function icSyncHybridAllCheckbox() {
  document.getElementById("icHybridFilterAll").checked = icHybridActiveSources.size === IC_SOURCE_LABELS.length;
}
function icToggleHybridAll(checked) {
  icHybridActiveSources = checked ? new Set(IC_SOURCE_LABELS) : new Set();
  for (const source of IC_SOURCE_LABELS) {
    document.getElementById(`icHybridFilter${icSourceIdKey(source)}`).checked = checked;
  }
  icHybridPage = 1;
  icRenderHybridResults();
}
function icToggleHybridSource(source, checked) {
  if (checked) icHybridActiveSources.add(source);
  else icHybridActiveSources.delete(source);
  icSyncHybridAllCheckbox();
  icHybridPage = 1;
  icRenderHybridResults();
}
function icHybridGoTo(page) {
  icHybridPage = page;
  icRenderHybridResults();
  document.getElementById("icHybridResultsList")?.closest(".explorer-results-container")?.scrollTo?.({ top: 0 });
}

function icSetHybridFilterCounts(hits) {
  document.getElementById("icHybridFilterCountAll").textContent = String(hits.length);
  for (const source of IC_SOURCE_LABELS) {
    document.getElementById(`icHybridFilterCount${icSourceIdKey(source)}`).textContent = String(
      hits.filter((h) => h.source_type === source).length
    );
  }
}

// Which engine(s) found the hit. The fused score is deliberately not shown
// as a percentage (RRF scores sit around 0.01-0.03); the rank order is the
// signal, with the raw numbers in the tooltip and the JSON.
function icHybridEngineBadge(hit) {
  const kw = hit.keyword_rank;
  const sem = hit.semantic_rank;
  const label =
    kw != null && sem != null ? `Keyword #${kw} \u00b7 Semantic #${sem}`
    : kw != null ? `Keyword only \u00b7 #${kw}`
    : `Semantic only \u00b7 #${sem}`;
  const cls = kw != null && sem != null ? "both" : kw != null ? "keyword" : "semantic";
  const tip =
    `fused score ${hit.rrf_score.toFixed(4)}` +
    (hit.similarity != null ? ` \u00b7 raw similarity ${hit.similarity.toFixed(4)}` : "");
  return `<span class="explorer-engine-badge engine-${cls}" title="${tip}">${label}</span>`;
}

function icRenderHybridCard(hit) {
  const k = icParseUniqueKey(hit.unique_key);
  const levels = icSemanticLevels(hit, k)
    .map(
      (level) => `
          <div class="meta-item">
            <div class="meta-label">${level.label}</div>
            <div class="meta-value">${level.code}</div>
            <div class="meta-sub">${level.desc}</div>
          </div>`
    )
    .join("");
  return `
    <div class="explorer-result-card">
      <div class="explorer-result-header">
        <div class="explorer-result-heading">
          <span class="explorer-result-code">${k.classId}</span>
          <span class="explorer-source-pill ${icSourcePillClass(hit.source_type)}">${hit.source_type}</span>
        </div>
        <div class="explorer-result-header-middle">${icHybridEngineBadge(hit)}</div>
        <div class="explorer-result-actions">
          <button class="explorer-view-json-btn" onclick="icViewHybridJson(${hit.rank})">View JSON</button>
        </div>
      </div>
      <p class="explorer-result-description">${hit.class_desc}</p>
      <div class="explorer-result-meta"><div class="meta-grid">${levels}</div></div>
    </div>`;
}

function icViewHybridJson(rank) {
  const hit = icHybridHits.find((h) => h.rank === rank);
  if (!hit) return;
  const k = icParseUniqueKey(hit.unique_key);
  const additional_data = {};
  for (const level of icSemanticLevels(hit, k)) {
    additional_data[level.key] = level.code;
    additional_data[`${level.key}_desc`] = level.desc;
  }
  showJsonModal({
    source_type: hit.source_type,
    code: k.classId,
    description: hit.class_desc,
    rank: hit.rank,
    rrf_score: hit.rrf_score,
    keyword_rank: hit.keyword_rank,
    semantic_rank: hit.semantic_rank,
    similarity_score: hit.similarity,
    engines: hit.engines,
    additional_data,
  });
}

// Same visible-page window as the Keyword tab's pager (5 buttons).
function icHybridVisiblePages(total) {
  const max = 5;
  let start = Math.max(1, icHybridPage - Math.floor(max / 2));
  const end = Math.min(total, start + max - 1);
  start = Math.max(1, end - max + 1);
  const pages = [];
  for (let p = start; p <= end; p++) pages.push(p);
  return pages;
}

function icRenderHybridPager(totalPages) {
  const el = document.getElementById("icHybridPagination");
  if (totalPages <= 1) {
    el.innerHTML = "";
    return;
  }
  const first = icHybridPage === 1;
  const last = icHybridPage === totalPages;
  el.innerHTML =
    `<button class="pagination-btn" ${first ? "disabled" : ""} onclick="icHybridGoTo(1)" aria-label="First page">\u23ee</button>` +
    `<button class="pagination-btn" ${first ? "disabled" : ""} onclick="icHybridGoTo(${icHybridPage - 1})" aria-label="Previous page">\u25c0</button>` +
    icHybridVisiblePages(totalPages)
      .map((p) => `<button class="pagination-btn${p === icHybridPage ? " active" : ""}" onclick="icHybridGoTo(${p})">${p}</button>`)
      .join("") +
    `<button class="pagination-btn" ${last ? "disabled" : ""} onclick="icHybridGoTo(${icHybridPage + 1})" aria-label="Next page">\u25b6</button>` +
    `<button class="pagination-btn" ${last ? "disabled" : ""} onclick="icHybridGoTo(${totalPages})" aria-label="Last page">\u23ed</button>`;
}

function icRenderHybridResults() {
  const all = icHybridHits;
  const filtered = all.filter((h) => icHybridActiveSources.has(h.source_type));
  const totalPages = Math.max(1, Math.ceil(filtered.length / HYBRID_PAGE_SIZE));
  icHybridPage = Math.min(Math.max(1, icHybridPage), totalPages);
  const startIdx = (icHybridPage - 1) * HYBRID_PAGE_SIZE;
  const page = filtered.slice(startIdx, startIdx + HYBRID_PAGE_SIZE);
  document.getElementById("icHybridResultsList").innerHTML = page.map(icRenderHybridCard).join("");
  icRenderHybridPager(totalPages);

  document.getElementById("icHybridResultsCount").textContent = all.length
    ? `${all.length} result${all.length === 1 ? "" : "s"}`
    : "No results";
  document.getElementById("icHybridRangeLabel").textContent = filtered.length
    ? `Showing ${startIdx + 1}-${startIdx + page.length} of ${filtered.length}`
    : "Showing 0-0 of 0";
  document.getElementById("icHybridFiltersLabel").textContent =
    icHybridActiveSources.size === IC_SOURCE_LABELS.length
      ? "Filters: all systems"
      : icHybridActiveSources.size === 0
        ? "Filters: none selected"
        : `Filters: ${[...icHybridActiveSources].join(", ")}`;

  // When keyword matched nothing the fused list is just the semantic list;
  // say so, so identical-looking results are not a mystery.
  const note = document.getElementById("icHybridNote");
  const noKeyword = all.length > 0 && all.every((h) => h.keyword_rank == null);
  note.hidden = !noKeyword;
  note.textContent = noKeyword ? "No keyword matches; showing semantic results" : "";
}

async function icRunHybridSearch(query) {
  icHybridLastQuery = query.trim();
  document.getElementById("icHybridQuery").value = query;
  icSetHybridStatus(`Searching for "${query}"...`);
  try {
    icHybridHits = await icFetchHybrid(query, HYBRID_FETCH_K);
    icHybridActiveSources = new Set(IC_SOURCE_LABELS);
    icHybridPage = 1;
    document.getElementById("icHybridFilterAll").checked = true;
    for (const source of IC_SOURCE_LABELS) {
      document.getElementById(`icHybridFilter${icSourceIdKey(source)}`).checked = true;
    }
    icSetHybridFilterCounts(icHybridHits);
    icRenderHybridResults();
    icSetHybridStatus("");
  } catch (e) {
    icSetHybridStatus(`Error: ${e.message}`);
  }
}

// -------------------------------------------------------------- //
// Semantic mode

async function submitIcExplorerSemanticSearch(evt) {
  evt.preventDefault();
  const query = document.getElementById("icSemanticQuery").value.trim();
  if (!query) return false;
  await icRunSemanticSearch(query);
  return false;
}

// unique_key is "us-{division letter}-{major group}-{industry group}-
// {class/SIC code}" (docs/plans/ic-similarity-search-poc.md sec2,
// e.g. "us-D-29-299-2992") - the same 4-level hierarchy Keyword mode's
// result cards show, just named section/division/group/class here
// instead of division/major_group/industry_group/class_id. Parsed out
// so the Semantic card can show the same code + meta-grid shape.
function icParseUniqueKey(uniqueKey) {
  const parts = (uniqueKey || "").split("-");
  return {
    division: parts[1] || "",
    majorGroup: parts[2] || "",
    industryGroup: parts[3] || "",
    classId: parts[4] || "",
  };
}

// The calibrated band label carries the plain-English judgment; the
// number is the raw evidence behind it, labeled "Score" and shown as
// a rounded-up 0-100 integer (direct feedback) rather than the 0-1
// decimal. Single line, score in parens, same pill shape/height as
// the US SIC chip (earlier direct feedback) - not a two-line stacked
// badge.
function icSimilarityPillHtml(similarity) {
  const band = simSimilarityBand(similarity);
  const score = Math.ceil(similarity * 100);
  return `
    <span class="explorer-similarity-pill sic-sim-band-${band.key}" title="raw score: ${similarity.toFixed(4)}">
      ${band.label} (Score ${score})
    </span>`;
}

let icSemanticHitsByRank = new Map();

// Semantic now hits the global/multi-system endpoint (icFetchSimilar)
// - real per-source filtering, same Set-based shape Compare mode's
// columns use (icCombinedActiveSources).
const SEMANTIC_SOURCES = IC_SOURCE_LABELS;
let icSemanticActiveSources = new Set(SEMANTIC_SOURCES);

function icSyncSemanticAllCheckbox() {
  document.getElementById("icSemanticFilterAll").checked =
    icSemanticActiveSources.size === SEMANTIC_SOURCES.length;
}

function icToggleSemanticAll(checked) {
  icSemanticActiveSources = checked ? new Set(SEMANTIC_SOURCES) : new Set();
  for (const source of SEMANTIC_SOURCES) {
    document.getElementById(`icSemanticFilter${icSourceIdKey(source)}`).checked = checked;
  }
  icRenderSemanticResults();
}

function icToggleSemanticSource(source, checked) {
  if (checked) icSemanticActiveSources.add(source);
  else icSemanticActiveSources.delete(source);
  icSyncSemanticAllCheckbox();
  icRenderSemanticResults();
}

function icSetSemanticFilterCounts(hits) {
  document.getElementById("icSemanticFilterCountAll").textContent = String(hits.length);
  for (const source of SEMANTIC_SOURCES) {
    const count = hits.filter((h) => h.source_type === source).length;
    document.getElementById(`icSemanticFilterCount${icSourceIdKey(source)}`).textContent = String(count);
  }
}

function icRenderSemanticResults() {
  const list = document.getElementById("icSemanticResultsList");
  const all = [...icSemanticHitsByRank.values()];
  const hits = all.filter((h) => icSemanticActiveSources.has(h.source_type));
  list.innerHTML = hits.map((h) => icRenderSemanticCard(h)).join("");

  const total = all.length;
  document.getElementById("icSemanticResultsCount").textContent =
    total ? `${total} result${total === 1 ? "" : "s"}` : "No results";
  document.getElementById("icSemanticRangeLabel").textContent = hits.length
    ? `Showing 1-${hits.length} of ${total}`
    : "Showing 0-0 of 0";
  document.getElementById("icSemanticFiltersLabel").textContent =
    icSemanticActiveSources.size === SEMANTIC_SOURCES.length
      ? "Filters: all systems"
      : icSemanticActiveSources.size === 0
        ? "Filters: none selected"
        : `Filters: ${[...icSemanticActiveSources].join(", ")}`;
}

function icViewSemanticJson(rank) {
  icShowSemanticJson(icSemanticHitsByRank.get(rank));
}
// Compare mode keeps its own hit list (ranks collide with the Semantic tab's).
function icViewCombinedSemanticJson(rank) {
  icShowSemanticJson(icCombinedSemanticHits.find((h) => h.rank === rank));
}
function icViewCombinedKeywordJson(index) {
  const match = icCombinedKeywordMatches[index];
  if (match) showJsonModal(window.icBuildKeywordResult(match));
}
function icShowSemanticJson(hit) {
  if (!hit) return;
  const k = icParseUniqueKey(hit.unique_key);
  const additional_data = {};
  for (const level of icSemanticLevels(hit, k)) {
    additional_data[level.key] = level.code;
    additional_data[`${level.key}_desc`] = level.desc;
  }
  showJsonModal({
    source_type: hit.source_type || "US SIC",
    code: k.classId,
    description: hit.class_desc,
    similarity_score: hit.similarity,
    additional_data,
  });
}

// The hierarchy levels worth showing for a hit, per system. US SIC and
// Japan SIC use the same three (the labels the Keyword tab's templates
// use). EU NACE uses its own names - Section / Division / Group - the
// real NACE Rev. 2 / ISIC Rev. 4 levels (same three-level shape) (the class code is the headline on the card).
// unique_key is "<module>-<section>-<division>-<group>-<class>" for all
// of them (icParseUniqueKey), mapped here to each system's own level
// names.
function icSemanticLevels(hit, k) {
  if (hit.source_type === "EU NACE" || hit.source_type === "ISIC") {
    return [
      { key: "section", label: "Section", code: k.division, desc: hit.section_desc },
      { key: "division", label: "Division", code: k.majorGroup, desc: hit.division_desc },
      { key: "group", label: "Group", code: k.industryGroup, desc: hit.group_desc },
    ];
  }
  return [
    { key: "division", label: "Division", code: k.division, desc: hit.section_desc },
    { key: "major_group", label: "Major Group", code: k.majorGroup, desc: hit.division_desc },
    { key: "industry_group", label: "Industry Group", code: k.industryGroup, desc: hit.group_desc },
  ];
}

function icRenderSemanticCard(hit, opts = {}) {
  const compact = !!opts.compact;
  const k = icParseUniqueKey(hit.unique_key);
  const cardClass = compact ? "explorer-result-card compact" : "explorer-result-card";

  // Compact (Combined mode) drops the Division/Major Group/Industry Group
  // meta-grid - direct feedback: copy the card look but shrink it and
  // remove detail, two full cards side by side is too much. It keeps View
  // JSON (same modal as the other tabs); Compare has its own hit list, so
  // it uses its own handler.
  const jsonHandler = compact ? "icViewCombinedSemanticJson" : "icViewSemanticJson";
  const actions = `<div class="explorer-result-actions">
          <button class="explorer-view-json-btn" onclick="${jsonHandler}(${hit.rank})">View JSON</button>
        </div>`;
  const meta = compact
    ? ""
    : `<div class="explorer-result-meta">
        <div class="meta-grid">
          ${icSemanticLevels(hit, k)
            .map(
              (level) => `
          <div class="meta-item">
            <div class="meta-label">${level.label}</div>
            <div class="meta-value">${level.code}</div>
            <div class="meta-sub">${level.desc}</div>
          </div>`
            )
            .join("")}
        </div>
      </div>`;

  const sourceType = hit.source_type || "US SIC";
  return `
    <div class="${cardClass}">
      <div class="explorer-result-header">
        <div class="explorer-result-heading">
          <span class="explorer-result-code">${k.classId}</span>
          <span class="explorer-source-pill ${icSourcePillClass(sourceType)}">${sourceType}</span>
        </div>
        <div class="explorer-result-header-middle">
          ${icSimilarityPillHtml(hit.similarity)}
        </div>
        ${actions}
      </div>
      <p class="explorer-result-description">${hit.class_desc}</p>
      ${meta}
    </div>`;
}

// .sic-sim-status reserves margin/min-height even when empty (it's
// shared with the standalone SIC Similarity tab, where it's always
// showing something) - that's what was opening up the extra gap
// between the Results header and the first card here, vs. Keyword
// mode which has no such element at all. Only in-flight/error text
// needs it, so keep it collapsed the rest of the time. Shared with
// Combined mode's two column statuses too.
function icSetStatusText(el, text) {
  el.textContent = text;
  el.style.display = text ? "block" : "none";
}

function icSetSemanticStatus(text) {
  icSetStatusText(document.getElementById("icSemanticStatus"), text);
}

async function icRunSemanticSearch(query) {
  icSemanticLastQuery = query.trim();
  document.getElementById("icSemanticQuery").value = query;

  // Result count lives in the Results header (icRenderSemanticResults),
  // not repeated here too.
  icSetSemanticStatus(`Searching for "${query}"...`);

  try {
    const hits = await icFetchSimilar(query, 10);
    icSemanticHitsByRank = new Map(hits.map((hit) => [hit.rank, hit]));
    icSemanticActiveSources = new Set(SEMANTIC_SOURCES);
    document.getElementById("icSemanticFilterAll").checked = true;
    for (const source of SEMANTIC_SOURCES) {
      document.getElementById(`icSemanticFilter${icSourceIdKey(source)}`).checked = true;
    }
    icSetSemanticFilterCounts(hits);
    icRenderSemanticResults();
    icSetSemanticStatus("");
  } catch (e) {
    icSetSemanticStatus(`Error: ${e.message}`);
  }
}

// -------------------------------------------------------------- //
// Combined mode

async function submitIcExplorerCombinedSearch(evt) {
  evt.preventDefault();
  const query = document.getElementById("icCombinedQuery").value.trim();
  if (!query) return false;
  await icRunCombinedSearch(query);
  return false;
}

// Both columns cap at 10 entries (direct feedback) - Semantic already
// does via icFetchSimilar's k=10 nearest-neighbor search; Keyword's
// endpoint returns every match, so it's sliced here, and the status
// line reflects the capped count actually shown, not the full match
// count.
const COMBINED_COLUMN_LIMIT = 10;

// Last fetch per column, cached so the facet row can re-render on
// toggle without re-fetching. Both columns hit the global/multi-system
// endpoints now (icFetchKeyword/icFetchSimilar - docs/plans/
// sic-global-search.md), so both get the same real per-source Set-
// based filtering rather than a single "All Results" mirror.
const COMBINED_SOURCES = IC_SOURCE_LABELS;
let icCombinedKeywordMatches = [];
let icCombinedSemanticHits = [];
let icCombinedActiveSources = {
  keyword: new Set(COMBINED_SOURCES),
  semantic: new Set(COMBINED_SOURCES),
};

function icCombinedRenderFn(column) {
  return column === "keyword" ? icRenderKeywordCard : icRenderSemanticCard;
}

function icCombinedData(column) {
  return column === "keyword" ? icCombinedKeywordMatches : icCombinedSemanticHits;
}

// Keyword matches arrive from the server in no particular order (a
// UNION ALL over the systems, capped at 50), so taking the first N would
// show whichever systems happened to come first and hide the rest. Take
// them round-robin across the active systems instead (each system's own
// order kept), so every ticked system gets a fair share of the N slots.
function icInterleaveBySource(items, limit) {
  const queues = new Map();
  for (const item of items) {
    if (!queues.has(item.source_type)) queues.set(item.source_type, []);
    queues.get(item.source_type).push(item);
  }
  const out = [];
  while (out.length < limit && [...queues.values()].some((q) => q.length)) {
    for (const q of queues.values()) {
      if (q.length && out.length < limit) out.push(q.shift());
    }
  }
  return out;
}

function icRenderCombinedColumn(column) {
  const resultsEl = document.getElementById(
    column === "keyword" ? "icCombinedKeywordResults" : "icCombinedSemanticResults"
  );
  const render = icCombinedRenderFn(column);
  const active = icCombinedActiveSources[column];
  icRenderCombinedChips(column);
  const matching = icCombinedData(column).filter((item) => active.has(item.source_type));
  const shown = column === "keyword" ? icInterleaveBySource(matching, COMBINED_COLUMN_LIMIT) : matching;
  const all = icCombinedData(column);
  resultsEl.innerHTML = shown.map((item) => render(item, { compact: true, index: all.indexOf(item) })).join("");
  if (column === "keyword" && icCombinedKeywordMatches.length) {
    icSetStatusText(
      document.getElementById("icCombinedKeywordStatus"),
      matching.length > shown.length
        ? `Showing ${shown.length} of ${matching.length} results for "${icCombinedLastQuery}"`
        : `${shown.length} result${shown.length === 1 ? "" : "s"} for "${icCombinedLastQuery}"`
    );
  }
}

function icCombinedCheckboxId(column, source) {
  const suffix = column === "keyword" ? "Keyword" : "Semantic";
  if (source === "all") return `icCombined${suffix}FilterAll`;
  return `icCombined${suffix}Filter${icSourceIdKey(source)}`;
}

function icSyncCombinedAllCheckbox(column) {
  document.getElementById(icCombinedCheckboxId(column, "all")).checked =
    icCombinedActiveSources[column].size === COMBINED_SOURCES.length;
}

function icToggleCombinedAll(column, checked) {
  icCombinedActiveSources[column] = checked ? new Set(COMBINED_SOURCES) : new Set();
  for (const source of COMBINED_SOURCES) {
    document.getElementById(icCombinedCheckboxId(column, source)).checked = checked;
  }
  icRenderCombinedColumn(column);
}

function icToggleCombinedSource(column, source, checked) {
  if (checked) icCombinedActiveSources[column].add(source);
  else icCombinedActiveSources[column].delete(source);
  icSyncCombinedAllCheckbox(column);
  icRenderCombinedColumn(column);
}

function icToggleCombinedKeywordAll(checked) {
  icToggleCombinedAll("keyword", checked);
}
function icToggleCombinedKeywordSource(source, checked) {
  icToggleCombinedSource("keyword", source, checked);
}
function icToggleCombinedSemanticAll(checked) {
  icToggleCombinedAll("semantic", checked);
}
function icToggleCombinedSemanticSource(source, checked) {
  icToggleCombinedSource("semantic", source, checked);
}

// Chips: one per system, lit in the system's own pill colour when it is
// included in this column, dimmed when not; clicking one toggles it
// (through the same checkbox the dropdown holds, so both stay in sync).
function icRenderCombinedChips(column) {
  const el = document.getElementById(column === "keyword" ? "icCombinedKeywordChips" : "icCombinedSemanticChips");
  if (!el) return;
  const data = icCombinedData(column);
  el.innerHTML = IC_SOURCES.map((src) => {
    const on = icCombinedActiveSources[column].has(src.label);
    const count = data.filter((item) => item.source_type === src.label).length;
    return `<button type="button" class="ic-sys-chip ${src.pill}${on ? " on" : ""}" aria-pressed="${on}" ` +
      `title="${on ? "Included - click to exclude" : "Excluded - click to include"} ${src.label}" ` +
      `onclick="icToggleChip('${column}', '${src.label}')">${src.label}` +
      `<span class="ic-sys-chip-count">${count}</span></button>`;
  }).join("");
}
function icToggleChip(column, source) {
  const on = !icCombinedActiveSources[column].has(source);
  document.getElementById(icCombinedCheckboxId(column, source)).checked = on;
  icToggleCombinedSource(column, source, on);
}
function icToggleSystemsMenu(column, event) {
  event.stopPropagation();
  const cap = column === "keyword" ? "Keyword" : "Semantic";
  const menu = document.getElementById(`icCombined${cap}Menu`);
  const open = menu.hidden;
  icCloseSystemsMenus();
  menu.hidden = !open;
  document.getElementById(`icCombined${cap}MenuBtn`).setAttribute("aria-expanded", String(open));
}
function icCloseSystemsMenus() {
  for (const cap of ["Keyword", "Semantic"]) {
    const menu = document.getElementById(`icCombined${cap}Menu`);
    if (menu) menu.hidden = true;
    const btn = document.getElementById(`icCombined${cap}MenuBtn`);
    if (btn) btn.setAttribute("aria-expanded", "false");
  }
}
document.addEventListener("click", (e) => {
  if (!e.target.closest(".ic-sys-dropdown")) icCloseSystemsMenus();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") icCloseSystemsMenus();
});
document.addEventListener("DOMContentLoaded", () => {
  icRenderCombinedChips("keyword");
  icRenderCombinedChips("semantic");
});

function icSetCombinedFilterCounts(column, items) {
  document.getElementById(icCombinedCheckboxId(column, "all").replace("Filter", "FilterCount")).textContent =
    String(items.length);
  for (const source of COMBINED_SOURCES) {
    const count = items.filter((item) => item.source_type === source).length;
    const id = icCombinedCheckboxId(column, source).replace("Filter", "FilterCount");
    document.getElementById(id).textContent = String(count);
  }
}

async function icRunCombinedSearch(query) {
  icCombinedLastQuery = query.trim();
  document.getElementById("icCombinedQuery").value = query;
  const kwStatus = document.getElementById("icCombinedKeywordStatus");
  const semStatus = document.getElementById("icCombinedSemanticStatus");

  icSetStatusText(kwStatus, "Searching...");
  icCombinedKeywordMatches = [];
  icRenderCombinedColumn("keyword");
  icSetStatusText(semStatus, "Searching...");
  icCombinedSemanticHits = [];
  icRenderCombinedColumn("semantic");

  await Promise.all([
    icFetchKeyword(query)
      .then((matches) => {
        icCombinedKeywordMatches = matches;
        icCombinedActiveSources.keyword = new Set(COMBINED_SOURCES);
        for (const source of ["all", ...COMBINED_SOURCES]) {
          document.getElementById(icCombinedCheckboxId("keyword", source)).checked = true;
        }
        icSetCombinedFilterCounts("keyword", icCombinedKeywordMatches);
        icRenderCombinedColumn("keyword");
        if (!icCombinedKeywordMatches.length) icSetStatusText(kwStatus, `No results for "${query}"`);
      })
      .catch((e) => {
        icSetStatusText(kwStatus, `Error: ${e.message}`);
      }),
    icFetchSimilar(query, COMBINED_COLUMN_LIMIT)
      .then((hits) => {
        icCombinedSemanticHits = hits;
        icCombinedActiveSources.semantic = new Set(COMBINED_SOURCES);
        for (const source of ["all", ...COMBINED_SOURCES]) {
          document.getElementById(icCombinedCheckboxId("semantic", source)).checked = true;
        }
        icSetCombinedFilterCounts("semantic", hits);
        icRenderCombinedColumn("semantic");
        icSetStatusText(
          semStatus,
          hits.length ? `${hits.length} result${hits.length === 1 ? "" : "s"} for "${query}"` : `No results for "${query}"`
        );
      })
      .catch((e) => {
        icSetStatusText(semStatus, `Error: ${e.message}`);
      }),
  ]);
}
