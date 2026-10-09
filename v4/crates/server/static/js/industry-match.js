// Company Explorer - Industry Match: a compact stepper (docs/plans/company-sic-match.md).
//   1 Describe   the company description (always editable) and the system to start in
//   2 Codes      the text as segments (switch some off, re-match) beside the codes in
//                the starting system (keep 2-5); choose which systems to find next
//   3.. one step per chosen target system: its codes, found by similarity to the ones kept
//   Report       everything chosen, per system, with hierarchy
// Backed by
//   POST /V4.0/global/sic/match  { text | chunks, systems:[start] }
//   POST /V4.0/global/sic/map    { from, codes, to, description }
// The user's choices live in this page's memory only; nothing is stored.

function initIndustryMatch() {
  const form = document.getElementById("imLookupForm");
  if (!form) return; // markup not present

  const $ = (id) => document.getElementById(id);
  const nameInput = $("imCompanyName");
  const textArea = $("imText");
  const startSelect = $("imStartSystem");
  const SYSTEMS = ["US SIC", "ISIC", "EU NACE", "Japan SIC"];
  const CLS = { "US SIC": "pill-us_sic", "EU NACE": "pill-eu_nace", ISIC: "pill-isic", "Japan SIC": "pill-japan_sic" };
  const NAME = { "US SIC": "US SIC", ISIC: "ISIC Rev. 4", "EU NACE": "EU NACE Rev. 2", "Japan SIC": "Japan SIC" };
  const MIN_SET = 1;
  const MAX_SET = 5;

  const state = {
    source: "typed", // "typed" | "wikipedia"
    company: "", // the company's name, when known (looked up)
    start: "US SIC",
    data: null, // last /sic/match response (start system)
    enabled: new Set(), // segment indexes kept
    picked: new Set(), // unique_keys kept in the start system
    entries: {},
    targets: [], // chosen target systems, in order
    mapped: null, // last /sic/map response
    mapDirty: true,
    tPicked: {}, // system -> Set(unique_key)
    tEntries: {}, // system -> { unique_key: entry }
    step: "1",
  };

  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  function setStatus(text, ...ids) {
    (ids.length ? ids : ["imStatus", "imStatus2"]).forEach((id) => {
      const el = $(id);
      if (!el) return;
      el.textContent = text || "";
      el.style.display = text ? "" : "none";
    });
  }

  // ----- the step rail ---------------------------------------------------------
  function stepList() {
    return [
      { id: "1", label: "Describe" },
      { id: "2", label: "Codes" },
      ...state.targets.map((t) => ({ id: `t:${t}`, label: NAME[t] })),
      { id: "r", label: "Report" },
    ];
  }

  function codesOk() {
    return state.picked.size >= MIN_SET && state.picked.size <= MAX_SET;
  }

  function renderRail() {
    const steps = stepList();
    const at = steps.findIndex((s) => s.id === state.step);
    $("imRail").innerHTML = steps
      .map((s, i) => {
        const reachable = i === 0 || (!!state.data && (i === 1 || codesOk()));
        return `<li><button type="button" data-step="${esc(s.id)}" class="${i === at ? "active" : i < at ? "done" : ""}" ${reachable ? "" : "disabled"}><span class="im-n">${i + 1}</span>${esc(s.label)}</button></li>`;
      })
      .join("");
    $("imRail").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => go(b.dataset.step)));
  }

  async function go(step) {
    // anything past the codes needs a current mapping
    if ((step.startsWith("t:") || step === "r") && state.targets.length) {
      const ok = await ensureMap();
      if (!ok) return;
    }
    state.step = step;
    $("imStep1").hidden = step !== "1";
    $("imStep2").hidden = step !== "2";
    $("imStepT").hidden = !step.startsWith("t:");
    $("imStepR").hidden = step !== "r";
    if (step.startsWith("t:")) renderTarget(step.slice(2));
    if (step === "r") renderReport();
    renderRail();
    $("companyIndustryPanel").scrollTop = 0;
  }
  document.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => go(b.dataset.go)));

  // ----- 1 Describe -------------------------------------------------------------------
  function updateTextMeta() {
    const words = (textArea.value.trim().match(/\S+/g) || []).length;
    $("imTextMeta").textContent = words ? `${words} words` : "";
  }
  textArea.addEventListener("input", () => {
    state.source = "typed";
    updateTextMeta();
  });

  async function lookup(name) {
    nameInput.value = name;
    setStatus(`Looking up "${name}"...`, "imStatus");
    $("imLookupBtn").disabled = true;
    try {
      const env = await apiService.get(`/V4.0/global/company/merged/firmographics/${encodeURIComponent(name)}`, { timeout: 60000 });
      const wiki = env.data && env.data.wikipedia;
      if (!wiki || !wiki.description) {
        setStatus(`No Wikipedia description for "${name}". Paste one below.`, "imStatus");
        return false;
      }
      textArea.value = wiki.description;
      state.company = wiki.name || name;
      state.source = "wikipedia";
      updateTextMeta();
      setStatus(`Loaded from Wikipedia (${wiki.name || name}). Edit freely.`, "imStatus");
      return true;
    } catch (e) {
      setStatus(`Error: ${e.message}`, "imStatus");
      return false;
    } finally {
      $("imLookupBtn").disabled = false;
    }
  }
  form.addEventListener("submit", (evt) => {
    evt.preventDefault();
    const q = nameInput.value.trim();
    if (q) lookup(q);
  });
  nameInput.addEventListener("input", () => {
    state.company = "";
  });

  async function post(path, body) {
    const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    return res.json();
  }

  async function callMatch(body, statusIds) {
    setStatus("Matching...", ...statusIds);
    $("imAnalyzeBtn").disabled = true;
    $("imRematchBtn").disabled = true;
    try {
      const env = await post("/V4.0/global/sic/match", { ...body, systems: [state.start] });
      if (env.code !== 200 || !env.data) {
        setStatus(env.message || "Something went wrong.", ...statusIds);
        return false;
      }
      setStatus("", ...statusIds);
      state.data = env.data;
      state.enabled = new Set(env.data.chunks.map((c) => c.index));
      const sys = env.data.systems[0];
      state.picked = new Set(sys ? sys.recommended.map((e) => e.unique_key) : []);
      state.entries = sys ? Object.fromEntries([...sys.recommended, ...sys.alternatives].map((e) => [e.unique_key, e])) : {};
      state.mapDirty = true;
      return true;
    } catch (e) {
      setStatus(`Error: ${e.message}`, ...statusIds);
      return false;
    } finally {
      $("imAnalyzeBtn").disabled = false;
      $("imRematchBtn").disabled = false;
    }
  }

  async function analyze() {
    const text = textArea.value.trim();
    if (!text) {
      setStatus("Add a description first, or look a company up.", "imStatus");
      return;
    }
    const newStart = startSelect.value;
    // keep the user's target choice on a re-run, unless the starting system changed
    const keep = newStart === state.start ? state.targets.filter((t) => t !== newStart) : [];
    state.start = newStart;
    if (await callMatch({ text }, ["imStatus"])) {
      state.targets = keep.length ? keep : SYSTEMS.filter((s) => s !== state.start);
      renderSegments();
      renderPicks();
      renderChips();
      await go("2");
    }
  }
  $("imAnalyzeBtn").addEventListener("click", analyze);

  // ----- 2 Codes -----------------------------------------------------------------------
  function row(e, { checked, maxSim, detail, trail, attrs }) {
    const rel = maxSim > 0 ? Math.max(6, Math.round((e.similarity / maxSim) * 100)) : 0;
    const crumb = e.hierarchy.map((l) => esc(l.description)).join(" &rsaquo; ");
    return `<div class="im-row${checked ? " picked" : ""}">
      <div class="im-row-main">
        <label><input type="checkbox" class="im-pick" ${attrs} ${checked ? "checked" : ""}><span class="im-code">${esc(e.code)}</span><span class="im-title" title="${esc(e.title)}">${esc(e.title)}</span></label>
        ${trail || ""}
        <span class="im-bar-sim" title="Similarity ${e.similarity.toFixed(2)} (relative to the best in this list)"><i style="width:${rel}%"></i></span>
        <button type="button" class="im-toggle" aria-label="Details">&#9656;</button>
      </div>
      <div class="im-detail" hidden><div>${crumb}</div>${detail}</div>
    </div>`;
  }

  function wireRows(root, onChange) {
    root.querySelectorAll(".im-row").forEach((r) => {
      const t = r.querySelector(".im-toggle");
      const d = r.querySelector(".im-detail");
      t.addEventListener("click", () => {
        d.hidden = !d.hidden;
        t.innerHTML = d.hidden ? "&#9656;" : "&#9662;";
      });
      const cb = r.querySelector(".im-pick");
      cb.addEventListener("change", () => {
        r.classList.toggle("picked", cb.checked);
        onChange(cb);
      });
    });
  }

  function why(e) {
    const n = `${e.votes} source${e.votes === 1 ? "" : "s"} point here`;
    if (e.evidence_phrase) return `<p>Matched most closely by the phrase &ldquo;${esc(e.evidence_phrase)}&rdquo; (${n}).</p>`;
    const c = state.data.chunks[e.evidence_chunk];
    const t = c ? esc(c.text.length > 200 ? c.text.slice(0, 200) + "..." : c.text) : "";
    return `<p>Segment ${e.evidence_chunk + 1}: ${t} (${n})</p>`;
  }

  function renderPicks() {
    const d = state.data;
    const sys = d.systems[0];
    $("imPhase1Title").innerHTML = `Codes in <span class="ic-sys-chip on ${CLS[state.start] || ""}">${esc(NAME[state.start])}</span><span class="im-count" id="imCount"></span>`;
    const notes = d.limitations.filter((l) => l.code === "weak_match" || l.code === "short_input");
    $("imLimitNotes").hidden = !notes.length;
    $("imLimitNotes").innerHTML = notes.map((l) => esc(l.message)).join(" ");
    if (!sys) {
      $("imPicks").innerHTML = `<p class="im-note">No codes found for ${esc(state.start)}.</p>`;
      return;
    }
    const all = [...sys.recommended, ...sys.alternatives];
    const maxSim = Math.max(...all.map((e) => e.similarity), 0.0001);
    const mk = (e) => row(e, { checked: state.picked.has(e.unique_key), maxSim, detail: why(e), attrs: `data-key="${esc(e.unique_key)}"` });
    $("imPicks").innerHTML =
      sys.recommended.map(mk).join("") +
      (sys.alternatives.length ? `<details class="im-more"><summary>More candidates (${sys.alternatives.length})</summary>${sys.alternatives.map(mk).join("")}</details>` : "");
    wireRows($("imPicks"), (cb) => {
      cb.checked ? state.picked.add(cb.dataset.key) : state.picked.delete(cb.dataset.key);
      state.mapDirty = true;
      updateCount();
    });
    updateCount();
  }

  function updateCount() {
    const n = state.picked.size;
    const el = $("imCount");
    if (el) {
      el.textContent = ` ${n} selected` + (codesOk() ? "" : n < MIN_SET ? " (pick at least one)" : ` (at most ${MAX_SET})`);
      el.classList.toggle("im-count-bad", !codesOk());
    }
    $("imToTargets").disabled = !codesOk();
    $("imToTargets").textContent = state.targets.length ? "Next →" : "Report →";
    $("imNextHint").textContent = codesOk() ? "" : n < MIN_SET ? "Pick at least one code" : `${n} picked: keep at most ${MAX_SET}`;
    renderRail();
  }

  function renderSegments() {
    const d = state.data;
    const unread = d.chunks.filter((c) => c.model_window === "unread").length;
    const note = $("imWindowNote");
    note.hidden = !d.input.truncated_without_chunking;
    if (!note.hidden) {
      note.innerHTML = `${d.input.tokens} word pieces: a plain search would read only the start and ignore ${unread ? `${unread} segment${unread === 1 ? "" : "s"}` : "the rest"} (marked <span class="im-dot"></span>). Every segment is matched here.`;
    }
    $("imChunks").innerHTML = d.chunks
      .map((c) => {
        const top = (c.top && c.top[state.start] && c.top[state.start][0]) || null;
        const flag = c.model_window === "unread" ? `<span class="im-dot" title="A plain search never reads this part"></span>` : c.model_window === "partial" ? `<span class="im-dot" title="A plain search reads only the start of this segment"></span>` : "";
        return `<div class="im-seg${state.enabled.has(c.index) ? "" : " off"}" data-i="${c.index}">
          <label class="im-seg-head"><input type="checkbox" class="im-seg-check" data-i="${c.index}" ${state.enabled.has(c.index) ? "checked" : ""}>
            <strong>${c.index + 1}</strong> <span class="im-meta">${c.tokens}</span> ${flag}
            ${top ? `<span class="im-meta" title="On its own this segment points at ${esc(top.title)}">&rarr; ${esc(top.code)} ${esc(top.title.slice(0, 28))}</span>` : ""}</label>
          <p class="im-seg-text" title="Click to expand">${esc(c.text)}</p>
        </div>`;
      })
      .join("");
    $("imChunks").querySelectorAll(".im-seg-check").forEach((cb) =>
      cb.addEventListener("change", () => {
        const i = Number(cb.dataset.i);
        cb.checked ? state.enabled.add(i) : state.enabled.delete(i);
        cb.closest(".im-seg").classList.toggle("off", !cb.checked);
        $("imRematchBtn").disabled = state.enabled.size === 0;
      })
    );
    $("imChunks").querySelectorAll(".im-seg-text").forEach((p) => p.addEventListener("click", () => p.classList.toggle("open")));
    $("imRematchBtn").disabled = false;
  }

  $("imRematchBtn").addEventListener("click", async () => {
    const kept = state.data.chunks.filter((c) => state.enabled.has(c.index)).map((c) => c.text);
    if (!kept.length) return;
    if (await callMatch({ chunks: kept }, ["imStatus2"])) {
      renderSegments();
      renderPicks();
    }
  });

  function renderChips() {
    $("imTargetChips").innerHTML = SYSTEMS.filter((s) => s !== state.start)
      .map((s) => `<button type="button" class="ic-sys-chip ${CLS[s] || ""}${state.targets.includes(s) ? " on" : ""}" data-system="${esc(s)}">${esc(NAME[s])}</button>`)
      .join("");
    $("imTargetChips").querySelectorAll(".ic-sys-chip").forEach((b) =>
      b.addEventListener("click", () => {
        const s = b.dataset.system;
        state.targets = SYSTEMS.filter((x) => x !== state.start && (x === s ? !state.targets.includes(s) : state.targets.includes(x)));
        b.classList.toggle("on", state.targets.includes(s));
        state.mapDirty = true;
        updateCount();
      })
    );
  }

  $("imToTargets").addEventListener("click", () => go(state.targets.length ? `t:${state.targets[0]}` : "r"));

  // ----- 3.. the target systems ---------------------------------------------------------
  function pickedCodes() {
    return [...state.picked].map((k) => state.entries[k]).filter(Boolean).map((e) => e.code);
  }

  async function ensureMap() {
    if (!state.mapDirty && state.mapped) return true;
    const codes = pickedCodes();
    if (!codes.length) return false;
    try {
      const env = await post("/V4.0/global/sic/map", { from: state.start, codes, to: state.targets, description: state.data.input.text });
      if (env.code !== 200 || !env.data) {
        setStatus(env.message || "Could not map these codes.", "imStatus2");
        return false;
      }
      state.mapped = env.data;
      state.tPicked = {};
      state.tEntries = {};
      env.data.targets.forEach((t) => {
        state.tPicked[t.system] = new Set(t.recommended.map((e) => e.unique_key));
        state.tEntries[t.system] = Object.fromEntries([...t.recommended, ...t.alternatives].map((e) => [e.unique_key, e]));
      });
      state.mapDirty = false;
      return true;
    } catch (e) {
      setStatus(`Error: ${e.message}`, "imStatus2");
      return false;
    }
  }

  function renderTarget(system) {
    const t = state.mapped && state.mapped.targets.find((x) => x.system === system);
    $("imTargetTitle").innerHTML = `Keep the codes that fit<span class="im-count" id="imTCount"></span>`;
    const n = $("imTargetNote");
    n.hidden = !t;
    if (t) n.textContent = `Found by similarity to your ${NAME[state.start]} codes and the description, not from an official correspondence: check them.`;
    if (!t) {
      $("imTargetList").innerHTML = `<p class="im-note">No candidates found in ${esc(NAME[system])}.</p>`;
    } else {
      const all = [...t.recommended, ...t.alternatives];
      const maxSim = Math.max(...all.map((e) => e.similarity), 0.0001);
      const mk = (e) =>
        row(e, {
          checked: state.tPicked[system].has(e.unique_key),
          maxSim,
          detail: e.basis === "description" ? "<p>Matched straight from the description.</p>" : `<p>Similar to ${esc(NAME[state.start])} ${e.from_codes.map(esc).join(", ")}.</p>`,
          trail: `<span class="im-from">${e.basis === "description" ? "from description" : "from " + e.from_codes.map(esc).join(", ")}</span>`,
          attrs: `data-key="${esc(e.unique_key)}"`,
        });
      $("imTargetList").innerHTML =
        t.recommended.map(mk).join("") +
        (t.alternatives.length ? `<details class="im-more"><summary>More candidates (${t.alternatives.length})</summary>${t.alternatives.map(mk).join("")}</details>` : "");
      wireRows($("imTargetList"), (cb) => {
        const set = state.tPicked[system];
        cb.checked ? set.add(cb.dataset.key) : set.delete(cb.dataset.key);
        updateTCount(system);
      });
    }
    updateTCount(system);
    const i = state.targets.indexOf(system);
    $("imTargetNext").textContent = i < state.targets.length - 1 ? `${NAME[state.targets[i + 1]]} →` : "Report →";
    $("imTargetNext").onclick = () => go(i < state.targets.length - 1 ? `t:${state.targets[i + 1]}` : "r");
    $("imTargetBack").onclick = () => go(i > 0 ? `t:${state.targets[i - 1]}` : "2");
    // Skipping drops this system from the run: it leaves the rail and the report, and the next
    // system (or the report) opens. It can be added back with its chip on the Codes step.
    $("imTargetSkip").onclick = () => {
      state.targets = state.targets.filter((t) => t !== system);
      delete state.tPicked[system];
      renderChips();
      go(i < state.targets.length ? `t:${state.targets[i]}` : "r");
    };
  }

  function updateTCount(system) {
    const el = $("imTCount");
    if (el) el.textContent = ` ${(state.tPicked[system] || new Set()).size} selected`;
  }

  // ----- Report ---------------------------------------------------------------------------
  function chosen() {
    const h = (e) => e.hierarchy.map((l) => ({ level: l.level, id: l.id, description: l.description }));
    const start = {
      system: state.start,
      codes: [...state.picked].map((k) => state.entries[k]).filter(Boolean).map((e) => ({ code: e.code, title: e.title, hierarchy: h(e) })),
    };
    const others = state.targets.map((s) => ({
      system: s,
      codes: [...(state.tPicked[s] || [])].map((k) => state.tEntries[s][k]).filter(Boolean).map((e) => ({
        code: e.code,
        title: e.title,
        from: e.basis === "description" ? [] : e.from_codes,
        hierarchy: h(e),
      })),
    }));
    return [start, ...others];
  }

  const REPORT_CODES_SHOWN = 3; // each system's list shows this many codes; the rest sit behind an expand control

  function renderReport() {
    const row = (c) => `<div class="im-rep-row"><span class="im-code">${esc(c.code)}</span> <strong>${esc(c.title)}</strong>
            <div class="im-crumb">${c.hierarchy.map((l) => esc(l.description)).join(" &rsaquo; ")}</div></div>`;
    const block = (s, i) => {
      const shown = s.codes.slice(0, REPORT_CODES_SHOWN);
      const rest = s.codes.slice(REPORT_CODES_SHOWN);
      return `<div class="im-rep" data-i="${i}"><div class="im-rep-head"><span class="ic-sys-chip on ${CLS[s.system] || ""}">${esc(NAME[s.system])}</span><span class="im-count">${s.codes.length} code${s.codes.length === 1 ? "" : "s"}</span></div>
        ${shown.map(row).join("") || `<p class="im-meta">None chosen.</p>`}
        ${rest.length ? `<div class="im-rep-more" hidden>${rest.map(row).join("")}</div><button type="button" class="im-expand" data-n="${rest.length}">Show ${rest.length} more</button>` : ""}</div>`;
    };
    $("imReport").innerHTML = chosen().map(block).join("");
    $("imReport").querySelectorAll(".im-expand").forEach((btn) =>
      btn.addEventListener("click", () => {
        const more = btn.previousElementSibling;
        more.hidden = !more.hidden;
        btn.textContent = more.hidden ? `Show ${btn.dataset.n} more` : "Show fewer";
      })
    );
    $("imReportBack").onclick = () => go(state.targets.length ? `t:${state.targets[state.targets.length - 1]}` : "2");
  }

  // ----- PDF report ---------------------------------------------------------------------------
  function companyName() {
    return (state.company || nameInput.value || "").trim() || "Company (name not given)";
  }

  function buildPdf() {
    const date = new Date().toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
    const name = companyName();
    const pdf = new SimplePdf({
      measure: SimplePdf.canvasMeasure(),
      footer: `${name}  -  industry classification report  -  ${date}`,
      title: `${name}: industry classification report`,
    });
    pdf.text(name, { size: 22, bold: true, after: 2 });
    pdf.text(`Industry classification report  -  ${date}`, { size: 10, gray: 0.4, after: 8 });
    pdf.rule();
    pdf.space(6);
    pdf.text("Description", { size: 12, bold: true, after: 3, keepTogether: true });
    pdf.text(textArea.value.trim(), { size: 10, after: 4 });
    const d = state.data;
    if (d) {
      const kept = d.chunks.length;
      pdf.text(
        `Starting system: ${NAME[state.start]}. Matched in ${kept} segment${kept === 1 ? "" : "s"}${d.input.phrases && d.input.phrases.length ? ` and ${d.input.phrases.length} key phrases` : ""}.`,
        { size: 8.5, gray: 0.4, after: 12 }
      );
    }
    for (const s of chosen()) {
      pdf.text(`${NAME[s.system] || s.system}  (${s.codes.length} code${s.codes.length === 1 ? "" : "s"})`, { size: 13, bold: true, after: 3, keepTogether: true });
      if (!s.codes.length) pdf.text("None chosen.", { size: 10, gray: 0.4, after: 8 });
      for (const c of s.codes) {
        pdf.text(`${c.code}   ${c.title}`, { size: 10.5, bold: true, keepTogether: true });
        pdf.text(c.hierarchy.map((l) => l.description).join(" \u203a "), { size: 8.5, gray: 0.4, indent: 12 });
        if (s.system !== state.start) {
          pdf.text(c.from && c.from.length ? `From ${NAME[state.start]} ${c.from.join(", ")}` : "Matched from the description", { size: 8.5, gray: 0.4, indent: 12 });
        }
        pdf.space(5);
      }
      pdf.space(6);
    }
    pdf.rule();
    pdf.space(4);
    pdf.text(
      "These codes are suggestions found by comparing the description with each code's wording, and, for systems other than the starting one, by similarity to the codes chosen there. They are not an official classification or correspondence: check them before relying on them.",
      { size: 8.5, gray: 0.4 }
    );
    return pdf.build();
  }

  $("imPdfBtn").addEventListener("click", () => {
    const bytes = buildPdf();
    const slug = companyName().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "company";
    const stamp = new Date().toISOString().slice(0, 10);
    const url = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `industry-codes-${slug}-${stamp}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  });

  function asText() {
    return chosen()
      .map(
        (s) =>
          `${NAME[s.system] || s.system}\n` +
          s.codes.map((c) => `  ${c.code}  ${c.title}${c.from && c.from.length ? `  (from ${c.from.join(", ")})` : ""}\n     ${c.hierarchy.map((l) => l.description).join(" > ")}`).join("\n")
      )
      .join("\n\n");
  }

  $("imCopyBtn").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(asText());
      $("imCopyBtn").textContent = "Copied";
      setTimeout(() => ($("imCopyBtn").textContent = "Copy as text"), 1500);
    } catch {
      /* clipboard unavailable */
    }
  });
  $("imViewJsonBtn").addEventListener("click", () => {
    if (window.showJsonModal) showJsonModal({ source: state.source, start: state.start, result: chosen(), match: state.data, map: state.mapped });
  });
  $("imRestartBtn").addEventListener("click", () => {
    state.data = null;
    state.mapped = null;
    state.targets = [];
    nameInput.value = "";
    textArea.value = "";
    updateTextMeta();
    setStatus("");
    go("1");
  });

  // ----- entry points ------------------------------------------------------------------------
  // `query` comes from Home or another Company tab: a company name (its description is
  // fetched) or, when it is clearly a description (many words or full sentences), the
  // description itself. Either way the user lands on step 1 with the text in place, free to
  // edit it or look up another company, and starts the match when ready.
  async function open(query) {
    const q = (query || "").trim();
    await go("1");
    if (!q) return;
    const words = (q.match(/\S+/g) || []).length;
    const looksLikeDescription = words > 12 || /[.!?]\s+\S/.test(q);
    if (looksLikeDescription) {
      nameInput.value = "";
      textArea.value = q;
      state.source = "typed";
      updateTextMeta();
      setStatus("");
    } else {
      await lookup(q);
    }
    textArea.focus({ preventScroll: true });
    textArea.setSelectionRange(0, 0);
    textArea.scrollTop = 0;
  }

  window.industryMatch = { open, hasResult: () => !!state.data, buildPdf };
  renderRail();
}

document.addEventListener("DOMContentLoaded", initIndustryMatch);
