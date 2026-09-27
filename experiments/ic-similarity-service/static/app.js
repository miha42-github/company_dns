const queryInput = document.getElementById("query");
const modelSelect = document.getElementById("model");
const kInput = document.getElementById("k");
const searchBtn = document.getElementById("searchBtn");
const statusEl = document.getElementById("status");
const resultsTable = document.getElementById("results");
const resultsBody = document.getElementById("resultsBody");

async function loadModels() {
  const res = await fetch("/api/models");
  const models = await res.json();
  modelSelect.innerHTML = models
    .map((m) => `<option value="${m.id}">${m.label}</option>`)
    .join("");
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

async function runSearch() {
  const q = queryInput.value.trim();
  if (!q) return;

  searchBtn.disabled = true;
  statusEl.className = "status";
  statusEl.textContent = "Searching...";
  resultsTable.style.display = "none";

  try {
    const params = new URLSearchParams({
      q,
      model: modelSelect.value,
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
          <td class="sim">${(hit.similarity * 100).toFixed(1)}%</td>
          <td class="path">${renderPath(hit)}</td>
        </tr>`
      )
      .join("");

    resultsTable.style.display = hits.length ? "table" : "none";
    statusEl.textContent = `${hits.length} result${hits.length === 1 ? "" : "s"} for "${q}"`;
  } catch (e) {
    statusEl.className = "status error";
    statusEl.textContent = `Error: ${e.message}`;
  } finally {
    searchBtn.disabled = false;
  }
}

searchBtn.addEventListener("click", runSearch);
queryInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") runSearch();
});

loadModels();
