/* YT-SQL conformance dashboard. Server mode fetches live data; static mode
   (window.__STATIC_DATA__) renders the embedded snapshot and disables execution. */

"use strict";

const state = { view: "overview", overview: null, functions: null, legacy: null, caseIndex: null, static: Boolean(window.__STATIC_DATA__) };

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}

function get(url) {
  if (state.static) return Promise.reject(new Error("static snapshot"));
  return fetch(url).then((response) => {
    if (!response.ok) throw new Error(`${response.status} ${url}`);
    return response.json();
  });
}

function card(n, label, cls = "") {
  return el("div", { class: `card ${cls}` }, el("div", { class: "n", text: n }), el("div", { class: "l", text: label }));
}

function table(headers, rows, onRowClick) {
  const tableNode = el("table");
  tableNode.append(el("thead", {}, el("tr", {}, ...headers.map((h) => el("th", { text: h })))));
  const tbody = el("tbody");
  for (const row of rows) {
    const cells = row.cells.map((c) => (c instanceof Node ? c : el("td", {}, document.createTextNode(String(c ?? "")))));
    const tr = el("tr", row.attrs || {}, ...cells);
    if (onRowClick) tr.addEventListener("click", (event) => { if (!event.target.closest("a,button")) onRowClick(row.key); });
    tbody.append(tr);
  }
  tableNode.append(tbody);
  return tableNode;
}

function show(view) {
  state.view = view;
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== `view-${view}`));
  render(view);
}

function render(view) {
  const target = document.getElementById(`view-${view}`);
  if (view === "overview") void renderOverview(target);
  if (view === "functions") void renderFunctions(target);
  if (view === "legacy") void renderLegacy(target);
  if (view === "cases") void renderCases(target);
}

// --- Overview ---

async function renderOverview(target) {
  target.replaceChildren(el("p", { class: "note", text: "Loading…" }));
  if (!state.overview) {
    try { state.overview = await get("/api/overview"); }
    catch { return renderStaticOverview(target); }
  }
  const o = state.overview;
  target.replaceChildren(
    el("h2", { text: "Normative corpus" }),
    el("div", { class: "cards" },
      card(o.normative_cases, "approved normative cases"),
      card(o.torture_mirrors, "torture mirrors (lexical stress variants)"),
      card(o.provisional_cases, "provisional (awaiting admission)"),
      card(o.reviewed_retirements, "reviewed retirements recorded")),
    el("h2", { text: "Corpus composition" }),
    compositionTable(o),
    el("h2", { text: "Legacy surface (migration scope)" }),
    el("div", { class: "cards" },
      card(o.legacy_files ?? "–", "legacy test files"),
      card(o.legacy_test_functions ?? "–", "test functions"),
      card(o.legacy_assertion_sites ?? "–", "assertion sites")),
    el("p", { class: "note", text: o.generated_note })
  );
}

function renderStaticOverview(target) {
  const o = state.overview || window.__STATIC_DATA__?.overview || {};
  document.getElementById("mode-badge").textContent = "static snapshot";
  target.replaceChildren(
    el("p", { class: "note", text: "Static snapshot: data embedded at generation time; server mode recomputes from the live tree." }),
    el("div", { class: "cards" },
      card(o.normative_cases ?? "?", "approved normative cases"),
      card(o.torture_mirrors ?? "?", "torture mirrors (lexical stress variants)"),
      card(o.reviewed_retirements ?? "?", "reviewed retirements recorded")),
    el("h2", { text: "Corpus composition" }),
    compositionTable(o)
  );
}

function compositionTable(o) {
  const descriptions = o.category_descriptions || {};
  const outcomeDescriptions = o.outcome_descriptions || {};
  const rows = [];
  const maxCategory = Math.max(1, ...Object.values(o.categories || {}));
  for (const [name, count] of Object.entries(o.categories || {})) {
    rows.push({ key: name, cells: [
      el("td", { title: descriptions[name] || "No definition recorded." }, name),
      el("td", { text: String(count) }),
      el("td", {}, bar(count, maxCategory)),
    ] });
  }
  const outcomeRows = Object.entries(o.outcomes || {}).map(([name, count]) => ({
    key: name,
    cells: [el("td", { title: outcomeDescriptions[name] || "No definition recorded." }, name), el("td", { text: String(count) })],
  }));
  return el("div", {},
    table(["Category", "Cases", ""], rows),
    el("div", { style: "height: 12px" }),
    table(["Outcome", "Cases"], outcomeRows),
    el("p", { class: "note", text: "Hover a category or outcome name for its definition. Torture mirrors are excluded from these tables and reported separately above." }));
}

function bar(value, max) {
  const wrap = el("div", { class: "bar" });
  const span = el("span", { class: "retained" });
  span.style.width = `${(100 * value) / max}%`;
  wrap.append(span);
  return wrap;
}

// --- Functions ---

async function renderFunctions(target) {
  target.replaceChildren(el("p", { class: "note", text: "Loading…" }));
  if (!state.functions) {
    try { state.functions = await get("/api/functions"); }
    catch { state.functions = window.__STATIC_DATA__?.functions || []; }
  }
  const dimensions = ["valid_syntax", "invalid_syntax", "semantics"];
  const dimensionLabels = { valid_syntax: "Valid syntax", invalid_syntax: "Invalid syntax", semantics: "Semantics" };
  const grid = el("div", { class: "grid" });
  grid.append(el("div", { class: "head", text: "Function" }), ...dimensions.map((d) => el("div", { class: "head", text: dimensionLabels[d] })));
  for (const fn of state.functions) {
    grid.append(el("div", { class: "fn" }, el("span", { text: fn.name }), el("span", { class: "kbd", text: fn.kind || "" })));
    for (const dim of dimensions) {
      const entry = fn.dimensions?.[dim] || { status: "missing", reviewed_case_ids: [] };
      const cell = el("div", { class: `cell ${entry.status}`, title: entry.status, text: `${(entry.reviewed_case_ids || []).length}` });
      cell.addEventListener("click", () => showCaseList(entry.reviewed_case_ids || [], `${fn.name} — ${dimensionLabels[dim]}`));
      grid.append(cell);
    }
  }
  target.replaceChildren(
    el("h2", { text: "19 Registered Functions × Coverage Dimensions" }),
    el("div", { class: "legend" },
      el("span", {}, el("i", { class: "covered" }), "Covered"),
      el("span", {}, el("i", { class: "partial" }), "Partially reviewed"),
      el("span", {}, el("i", { class: "unverified" }), "Unverified")),
    el("p", { class: "note", text: "Numbers are reviewed replacement case IDs per dimension (from COVERAGE-GAP-MATRIX.json). Click a cell to open its cases." }),
    grid);
}

function showCaseList(ids, title) {
  openDetail(el("div", {},
    el("h3", { text: title }),
    el("p", { class: "meta", text: `${ids.length} case(s)` }),
    el("div", { class: "chips" }, ...ids.map((id) => el("a", { class: "chip", onclick: () => openCase(id), text: id })))));
}

// --- Legacy ---

async function renderLegacy(target) {
  target.replaceChildren(el("p", { class: "note", text: "Loading…" }));
  if (!state.legacy) {
    try { state.legacy = await get("/api/legacy"); }
    catch { state.legacy = window.__STATIC_DATA__?.legacy || { counts: {}, files: [] }; }
  }
  const files = state.legacy.files || [];
  const classified = new Map();
  for (const file of files) {
    const decision = file.retirement_decision || "unknown";
    classified.set(decision, (classified.get(decision) || 0) + 1);
  }
  const rows = files
    .filter((file) => (file.tests || []).length > 0)
    .sort((a, b) => (b.tests || []).length - (a.tests || []).length)
    .slice(0, 120)
    .map((file) => ({
      key: file.path,
      cells: [file.path, (file.tests || []).length, decisionBadge(file.retirement_decision), bar(1, 1)],
      attrs: {},
    }));
  target.replaceChildren(
    el("h2", { text: "Legacy test surface" }),
    el("div", { class: "cards" },
      card(state.legacy.counts?.legacy_test_files ?? "-", "test files"),
      card(state.legacy.counts?.test_functions ?? "-", "test functions"),
      card(state.legacy.counts?.assertion_sites ?? "-", "assertion sites")),
    el("h2", { text: "Dispositions" }),
    el("div", { class: "chips" }, ...[...classified.entries()].map(([name, count]) => el("span", { class: "chip", title: decisionDescription(name), text: `${decisionLabel(name)}: ${count}` }))),
    el("h2", { text: "Files with tests (top by test count)" }),
    el("p", { class: "note", text: "Click a file to inspect its tests. Retirements pair with replacement case IDs in REVIEWED-RETIREMENTS.json." }),
    table(["File", "Tests", "Decision", ""], rows, (path) => openLegacyFile(path)));
}

// Migration decisions are recorded in the retirement audit as internal enum
// values; the dashboard renders them as readable labels with an explanation.
const DECISION_LABELS = {
  retain_pending_assertion_level_review: "Retained, pending assertion-level review",
};
const DECISION_DESCRIPTIONS = {
  retain_pending_assertion_level_review:
    "The file's assertions have not yet been individually reviewed against the portable corpus. The file is kept until that review retires, migrates or reclassifies each assertion.",
};

function decisionLabel(decision) {
  return DECISION_LABELS[decision] || decision || "";
}

function decisionDescription(decision) {
  return DECISION_DESCRIPTIONS[decision] || "No explanation recorded for this decision.";
}

function decisionBadge(decision) {
  const span = el("span", { title: decisionDescription(decision), text: decisionLabel(decision) });
  if ((decision || "").startsWith("retain")) span.className = "run-ok";
  return span;
}

function openLegacyFile(path) {
  const file = (state.legacy.files || []).find((f) => f.path === path);
  if (!file) return;
  const tests = (file.tests || []).map((t) => `${t.name} (${(t.assertion_sites || []).length || t.assertions || 1} sites)`);
  openDetail(el("div", {},
    el("h3", { text: path }),
    el("p", { class: "meta", text: `classification: ${file.previous_classification || "–"} · decision: ${decisionLabel(file.retirement_decision) || "–"}` }),
    el("ul", {}, ...tests.map((t) => el("li", { text: t })))));
}

// --- Cases ---

async function renderCases(target) {
  if (!state.caseIndex) {
    if (state.static) state.caseIndex = window.__STATIC_DATA__?.cases || [];
    else {
      try { state.caseIndex = (await get("/api/cases?limit=5000")).cases || []; }
      catch { state.caseIndex = []; }
    }
  }
  const filters = el("div", { class: "filters" },
    el("input", { id: "case-search", placeholder: "Search by case ID, feature or query text…", oninput: () => refreshCaseTable() }),
    el("select", { id: "case-category", onchange: () => refreshCaseTable() },
      el("option", { value: "", text: "all categories" }),
      ...Object.keys(state.overview ? state.overview.categories : window.__STATIC_DATA__?.overview?.categories || {}).map((c) => el("option", { value: c, text: c }))),
    el("select", { id: "case-outcome", onchange: () => refreshCaseTable() },
      el("option", { value: "", text: "all outcomes" }),
      ...["rows", "error:syntax", "error:type", "error:resolution", "error:evaluation", "error:unsupported", "error:parameter", "provisional"].map((c) => el("option", { value: c, text: c }))),
    el("span", { class: "kbd", id: "case-count" }));
  target.replaceChildren(el("h2", { text: "Test browser" }), filters, el("div", { id: "case-table" }));
  refreshCaseTable();
}

function caseFiltersActive() {
  return Boolean(
    document.getElementById("case-search").value.trim() ||
    document.getElementById("case-category").value ||
    document.getElementById("case-outcome").value
  );
}

function refreshCaseTable() {
  const container = document.getElementById("case-table");
  if (!caseFiltersActive()) {
    container.replaceChildren(renderCaseTree(state.caseIndex || []));
    document.getElementById("case-count").textContent = "Browsing the directory tree — search or filter for a flat list";
    return;
  }
  const query = document.getElementById("case-search").value.trim().toLowerCase();
  const category = document.getElementById("case-category").value;
  const outcome = document.getElementById("case-outcome").value;
  const matches = state.caseIndex.filter((c) =>
    (!category || c.category === category) &&
    (!outcome || c.outcome === outcome) &&
    (!query || `${c.id} ${(c.features || []).join(" ")} ${(c.datasets || []).join(" ")}`.toLowerCase().includes(query)));
  document.getElementById("case-count").textContent = `${matches.length} matching case${matches.length === 1 ? "" : "s"}`;
  const rows = matches.slice(0, 200).map((c) => ({
    key: c.id,
    cells: [c.id, c.outcome, (c.features || []).join(", "), c.torture ? "torture" : ""],
  }));
  container.replaceChildren(table(["Case", "Outcome", "Features", ""], rows, (id) => openCase(id)));
}

function outcomeDot(outcome) {
  const colour = outcome === "rows" ? "var(--ok)" : outcome.startsWith("error") ? "var(--bad)" : "var(--warn)";
  return el("span", { style: `display:inline-block;width:8px;height:8px;border-radius:50%;background:${colour};margin-right:6px` });
}

// Physical-directory tree: one collapsed root per top-level folder under
// yt-sql/cases, expandable down to individual cases.
function renderCaseTree(cases) {
  const roots = new Map();
  for (const entry of cases) {
    const parts = (entry.path || entry.category).split("/");
    let level = roots;
    for (let index = 0; index < parts.length - 1; index += 1) {
      if (!level.has(parts[index])) level.set(parts[index], { children: new Map(), count: 0 });
      level = level.get(parts[index]).children;
    }
    if (!level.has(parts.at(-1))) level.set(parts.at(-1), { cases: [] });
    level.get(parts.at(-1)).cases.push(entry);
  }
  const tree = el("div", { class: "tree" });
  let total = 0;
  for (const [name, node] of [...roots.entries()].sort()) {
    total += countTree(node);
    tree.append(renderTreeNode(name, node, true));
  }
  return el("details", { class: "tree-root" }, el("summary", { text: `Corpus tree (${total} cases)` }), tree);
}

function countTree(node) {
  let total = (node.cases || []).length;
  for (const child of (node.children || new Map()).values()) total += countTree(child);
  return total;
}

function renderTreeNode(name, node, root = false) {
  const details = el("details", {});
  const summary = el("summary", { text: `${name} (${countTree(node)})` });
  if (root) summary.classList.add("root-dir");
  details.append(summary);
  const children = [...(node.children || new Map()).entries()].sort();
  for (const [childName, child] of children) details.append(renderTreeNode(childName, child));
  for (const entry of (node.cases || []).sort((a, b) => a.id.localeCompare(b.id))) {
    details.append(el("div", { class: "tree-leaf" },
      outcomeDot(entry.outcome),
      el("a", { title: `${entry.id} — ${entry.outcome}`, onclick: () => openCase(entry.id), text: entry.id })));
  }
  return details;
}

// --- Case detail ---

async function openCase(id) {
  let detail = null;
  if (!state.static) {
    try { detail = await get(`/api/case/${encodeURIComponent(id)}`); }
    catch { detail = null; }
  }
  if (!detail) detail = (state.caseIndex || []).find((c) => c.id === id) || { id, error: "detail unavailable in static mode" };
  const body = el("div", {},
    el("h3", { text: detail.id }),
    el("p", { class: "meta", text: `datasets: ${(detail.datasets || []).join(", ")} · order: ${detail.order || "–"} · outcome: ${detail.outcome}` }),
    el("div", { class: "chips" }, ...(detail.features || []).map((f) => el("span", { class: "chip", text: f }))),
    detail.query ? el("pre", { text: detail.query }) : null,
    detail.expected ? el("pre", { text: JSON.stringify(detail.expected, null, 2) }) : null,
    detail.error ? el("pre", { text: JSON.stringify(detail.error, null, 2) }) : null);
  if (!state.static && !detail.provisional) {
    const runButton = el("button", { text: "Run conformance case" });
    runButton.addEventListener("click", async () => {
      runButton.disabled = true;
      runButton.textContent = "Running…";
      const result = await fetch(`/api/run/${encodeURIComponent(id)}`, { method: "POST" }).then((r) => r.json()).catch((e) => ({ status: "client_error", detail: String(e) }));
      const ok = result.status === "pass";
      body.append(el("p", { class: ok ? "run-ok" : "run-bad", text: `Result: ${result.status} (${result.duration_s}s)` }),
        result.detail ? el("pre", { text: result.detail }) : null);
      runButton.disabled = false;
      runButton.textContent = "Run again";
    });
    body.append(el("div", { class: "row-actions" }, runButton));
  }
  openDetail(body);
}

function openDetail(content) {
  const overlay = document.getElementById("detail-overlay");
  const panel = document.getElementById("detail-panel");
  panel.replaceChildren(content);
  overlay.classList.remove("hidden");
}

document.getElementById("detail-overlay").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) event.currentTarget.classList.add("hidden");
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") document.getElementById("detail-overlay").classList.add("hidden");
});

document.querySelectorAll("nav button").forEach((button) => button.addEventListener("click", () => show(button.dataset.view)));
show("overview");
