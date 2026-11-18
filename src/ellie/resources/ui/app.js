"use strict";

const $ = (selector) => document.querySelector(selector);
const types = {D: "Decisions", R: "Results", F: "Findings", Q: "Questions", N: "Notes"};
const singular = {D: "Decision", R: "Result", F: "Finding", Q: "Question", N: "Note"};
const state = {data: null, project: null, memory: "", type: "", view: "overview", archived: false, query: "", hits: null};
let searchRequest = 0;
let snapshotRequest = 0;
let searchTimer;
let detailText = "";
let detailTrigger;

// Every saved string goes through textContent. Markdown stays text, never HTML.
function el(tag, className = "", text = null) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== null) node.textContent = String(text);
  return node;
}
function button(text, className, onClick) {
  const node = el("button", className, text);
  node.type = "button";
  node.addEventListener("click", onClick);
  return node;
}
function shortDate(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, {month: "short", day: "numeric"});
}
function memories() { return state.data?.project?.memories || []; }
function items() { return memories().flatMap(memory => memory.items); }
function visibleItems(ignoreType = false) {
  let result = items().filter(item => (state.archived || !item.archived) && (!state.memory || item.memory === state.memory));
  if (state.query) {
    const ranks = new Map((state.hits || []).map((hit, rank) => [hit.id, rank]));
    result = result.filter(item => ranks.has(item.id)).sort((a, b) => ranks.get(a.id) - ranks.get(b.id));
  } else {
    result.sort((a, b) => (b.fields.date || "").localeCompare(a.fields.date || "") || Number(b.id.slice(1)) - Number(a.id.slice(1)));
  }
  return ignoreType ? result : result.filter(item => !state.type || item.type === state.type);
}
async function api(path, params = {}) {
  const response = await fetch(path + "?" + new URLSearchParams(params));
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Could not read memory");
  return data;
}
function showError(error) {
  $("#error").textContent = error.message;
  $("#error").hidden = false;
}
async function refresh(project = state.project) {
  const request = ++snapshotRequest;
  $("#refresh").disabled = true;
  try {
    const data = await api("/api/snapshot", project ? {project} : {});
    if (request !== snapshotRequest) return;
    const changed = state.project !== data.project?.id;
    state.data = data;
    state.project = data.project?.id || null;
    if (changed) {
      state.memory = ""; state.query = ""; state.type = ""; state.hits = null;
      $("#search").value = "";
      searchRequest++;
    }
    $("#error").hidden = true;
    render();
    if (state.query) await search();
  } catch (error) { if (request === snapshotRequest) showError(error); }
  finally { if (request === snapshotRequest) $("#refresh").disabled = false; }
}
async function search() {
  const request = ++searchRequest;
  const query = state.query;
  if (!query || !state.project) { state.hits = null; renderContent(); return; }
  $("#result-count").textContent = "Searching…";
  try {
    const data = await api("/api/search", {project: state.project, q: query});
    if (request !== searchRequest) return;
    state.hits = data.items;
    $("#error").hidden = true;
    renderContent();
  } catch (error) { if (request === searchRequest) showError(error); }
}
function render() {
  const data = state.data;
  $("#project-count").textContent = data.projects.length;
  $("#projects").replaceChildren(...data.projects.map(project => {
    const node = button("", "project-button" + (project.id === state.project ? " active" : ""), () => refresh(project.id));
    node.setAttribute("aria-current", project.id === state.project ? "page" : "false");
    node.title = project.id;
    node.append(el("span", "project-icon", "▣"));
    const copy = el("span", "project-copy");
    copy.append(el("span", "project-name", project.name), el("span", "project-sub", project.id.split("/").slice(0, -1).join("/")));
    node.append(copy, el("span", "project-total", project.items));
    return node;
  }));
  const active = data.projects.find(project => project.id === state.project);
  $("#project-title").textContent = active?.name || "Your projects, remembered.";
  $("#project-path").textContent = active?.id || "A home for what you learned along the way.";
  document.title = active ? active.name + " · Ellie" : "Ellie · Project memory";
  $("#empty").hidden = !!active;
  $("#workspace").hidden = !active;
  if (!active) return;
  const all = items().filter(item => !item.archived);
  const cards = [["Memories kept", all.length, "Pieces of useful context", "◈"],
    ["Decisions made", all.filter(item => item.type === "D" && item.fields.status === "active").length, "The reasoning behind the work", "◇"],
    ["Lessons from attempts", all.filter(item => item.type === "R").length, "What worked. What didn’t.", "↗"],
    ["Open questions", all.filter(item => item.type === "Q" && item.fields.status === "open").length, "Things still to figure out", "?"]];
  $("#stats").replaceChildren(...cards.map(([label, count, subtitle, symbol]) => {
    const node = el("div", "stat"), top = el("div", "stat-top", label);
    top.append(el("span", "stat-symbol", symbol));
    node.append(top, el("div", "stat-number", count), el("div", "stat-sub", subtitle));
    return node;
  }));
  const available = memories().filter(memory => state.archived || !memory.archived);
  if (!available.some(memory => memory.name === state.memory)) state.memory = "";
  $("#memory-filter").replaceChildren(...[["", "All workstreams"], ...available.map(memory => [memory.name, memory.name === "project" ? "Shared project memory" : memory.name + (memory.archived ? " (archived)" : "")])].map(([value, label]) => {
    const option = el("option", "", label); option.value = value; return option;
  }));
  $("#memory-filter").value = state.memory;
  $("#saved-note").textContent = "↻ Refreshes every 15s";
  renderContent();
}
function renderContent() {
  if (!state.data?.project) return;
  const timeline = state.view === "timeline";
  document.querySelectorAll("[data-view]").forEach(node => node.setAttribute("aria-selected", String(node.dataset.view === state.view)));
  $("#filters").hidden = timeline;
  $("#items").hidden = timeline;
  $("#activity").hidden = !timeline;
  $("#search").disabled = timeline;
  $("#search").placeholder = timeline ? "Switch to a memory view to search…" : "Search what you know…";
  const available = visibleItems(true);
  $("#filters").replaceChildren(...[["", "All types"], ...Object.entries(types)].map(([type, label]) => {
    const count = available.filter(item => !type || item.type === type).length;
    const node = button("", "filter" + (state.type === type ? " active" : ""), () => {state.type = type; renderContent();});
    node.setAttribute("aria-pressed", String(state.type === type));
    node.append(el("span", "", label), el("span", "filter-count", count));
    return node;
  }));
  renderContext();
  if (timeline) { renderActivity(); return; }
  const filtered = visibleItems();
  const shown = state.view === "overview" && !state.query ? filtered.slice(0, 12) : filtered;
  $("#list-title").textContent = state.query ? "Search results" : state.view === "overview" ? "Recently remembered" : "Your memory library";
  $("#result-count").textContent = shown.length === filtered.length ? filtered.length + " items" : shown.length + " of " + filtered.length + " items";
  $("#items").replaceChildren(...shown.map(itemCard));
  $("#no-results").textContent = "No matching memories. Try another search or filter.";
  $("#no-results").hidden = filtered.length > 0;
}
function renderContext() {
  const node = $("#context");
  node.hidden = state.view !== "overview" || !!state.query;
  if (node.hidden) return;
  const active = memories().filter(memory => !memory.archived && memory.name !== "project");
  const memory = memories().find(memory => memory.name === state.memory) || active.sort((a,b) => (b.meta.updated || "").localeCompare(a.meta.updated || ""))[0] || memories()[0];
  if (!memory) { node.replaceChildren(); return; }
  const sections = memory.name === "project" ? ["Overview", "Conventions", "Next steps"] : ["Goal", "Current state", "Next steps"];
  node.replaceChildren(...sections.map(title => {
    const card = el("article", "context-card");
    card.append(el("p", "eyebrow", title.toUpperCase() + " / " + (memory.name === "project" ? "SHARED" : memory.name.toUpperCase())),
      el("p", "context-text", memory.sections[title]?.trim() || "Nothing saved here yet."),
      button("Open full memory ↗", "", () => openMemory(memory)));
    return card;
  }));
}
function itemCard(item) {
  const node = button("", "item-card", () => openItem(item));
  const top = el("div", "card-top");
  top.append(el("span", "type-badge type-" + item.type, singular[item.type].toUpperCase()), el("span", "item-id", item.id + " ↗"));
  const fields = item.fields;
  const excerpt = fields.why || fields.detail || fields.what || fields.answer || item.body.trim() || "Open to explore this memory.";
  const foot = el("div", "card-footer");
  foot.append(el("span", "memory-name", item.memory + " · " + shortDate(fields.date)));
  const status = fields.status || fields.outcome || (item.archived ? "archived" : "saved");
  const statusClass = ["failed", "open", "partial"].includes(status) ? " " + status : "";
  foot.append(el("span", "item-status" + statusClass, status));
  node.append(top, el("h3", "", item.title), el("p", "item-excerpt", excerpt), foot);
  return node;
}
function renderActivity() {
  const rows = [];
  memories().filter(memory => (state.archived || !memory.archived) && (!state.memory || state.memory === memory.name)).forEach(memory => {
    (memory.sections.Log || "").split("\n").filter(line => line.trim()).forEach(line => rows.push({date: (line.match(/\d{4}-\d{2}-\d{2}[^ ]*/) || [""])[0], title: line.replace(/^-\s*/, ""), body: memory.name, symbol: "◷"}));
  });
  const captured = new Set();
  const records = [...state.data.project.pending.map(record => ({...record, pending: true})), ...state.data.project.sessions];
  records.forEach(record => {
    const key = record.id;
    if (captured.has(key) || (state.memory && !(record.memories || []).includes(state.memory))) return;
    captured.add(key);
    rows.push({date: record.ended || record.started || "", title: (record.agent || "Agent") + " · " + (record.capture || (record.pending ? "pending" : "saved")), body: [record.id, (record.memories || []).join(", "), record.error || ""].filter(Boolean).join("\n"), symbol: record.capture === "failed" ? "!" : "↗"});
  });
  rows.sort((a,b) => b.date.localeCompare(a.date));
  const list = el("ol", "timeline-list");
  rows.forEach(row => {
    const node = el("li", "timeline-row"), body = el("div", "timeline-body");
    body.append(el("h3", "", row.title), el("p", "", row.body));
    node.append(el("span", "timeline-symbol", row.symbol), body, el("span", "timeline-meta", shortDate(row.date)));
    list.append(node);
  });
  (state.data.project.warnings || []).forEach(warning => list.append(el("li", "error", warning)));
  $("#activity").replaceChildren(list);
  $("#list-title").textContent = "The trail so far";
  $("#result-count").textContent = rows.length + " events";
  $("#no-results").hidden = rows.length > 0;
  if (!rows.length) $("#no-results").textContent = "No activity saved yet. Logs and capture records will appear here.";
}
function openDetail(title, label, raw, content) {
  detailTrigger = document.activeElement;
  detailText = raw;
  $("#detail-title").textContent = title;
  $("#detail-label").textContent = label;
  $("#detail-content").replaceChildren(...content);
  $("#copy-status").textContent = "";
  $("#detail").showModal();
}
function openItem(item) {
  const fields = el("dl", "detail-fields");
  Object.entries(item.fields).forEach(([key, value]) => {
    const row = el("div"); row.append(el("dt", "", key), el("dd", "", value)); fields.append(row);
  });
  const content = [fields];
  if (item.body.trim()) content.push(el("pre", "detail-text", item.body.trim()));
  openDetail(item.title, singular[item.type] + " / " + item.id + " / " + item.memory, item.raw, content);
}
function openMemory(memory) {
  openDetail(memory.name === "project" ? "Shared project memory" : memory.name, "FULL MEMORY / MARKDOWN", memory.raw, [el("pre", "detail-text", memory.raw)]);
}
$("#refresh").addEventListener("click", () => refresh());
$("#memory-filter").addEventListener("change", event => {state.memory = event.target.value; renderContent();});
$("#archived").addEventListener("change", event => {state.archived = event.target.checked; render();});
$("#search").addEventListener("input", event => {
  state.query = event.target.value.trim(); state.hits = null; searchRequest++;
  clearTimeout(searchTimer); searchTimer = setTimeout(search, 200);
});
document.querySelectorAll("[data-view]").forEach(node => node.addEventListener("click", () => {state.view = node.dataset.view; $("#no-results").textContent = "No matching memories. Try another search or filter."; renderContent();}));
$("#close-detail").addEventListener("click", () => $("#detail").close());
$("#detail").addEventListener("close", () => detailTrigger?.focus());
$("#detail").addEventListener("click", event => {if (event.target === $("#detail") && event.clientX < $("#detail").getBoundingClientRect().left) $("#detail").close();});
$("#copy-detail").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(detailText); $("#copy-status").textContent = "Copied"; }
  catch { $("#copy-status").textContent = "Select and copy the text above."; }
});
document.addEventListener("keydown", event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    if (state.view === "timeline") {state.view = "items"; renderContent();}
    $("#search").focus();
  }
});
refresh();
setInterval(() => {if (!document.hidden && !$("#detail").open && !$("#refresh").disabled) refresh();}, 15000);
