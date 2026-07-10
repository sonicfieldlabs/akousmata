/* akousmata — listening navigator. Vanilla JS over the local API. */

const state = {
  tab: "library",
  records: [],
  selected: null,
  tags: [],
  activeTag: "",
  wikiPages: null,
  graph: null,
  research: null,
  settings: null,
};

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 2600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return response.json();
}

/* ── tabs ─────────────────────────────────────────────────────────────── */

$("tabs").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-tab]");
  if (!button) return;
  state.tab = button.dataset.tab;
  for (const item of $("tabs").querySelectorAll("button")) item.classList.toggle("active", item === button);
  for (const name of ["library", "graph", "wiki", "research", "settings"]) $(`tab-${name}`).hidden = name !== state.tab;
  if (state.tab === "graph") loadGraph(state.selected || null);
  if (state.tab === "wiki") loadWiki();
  if (state.tab === "settings") loadSettings();
});

/* ── library ──────────────────────────────────────────────────────────── */

function filterParams() {
  const params = new URLSearchParams();
  const text = $("f-text").value.trim();
  if (text) params.set("text", text);
  if ($("f-app").value) params.set("app_filter", $("f-app").value);
  if ($("f-origin").value) params.set("origin", $("f-origin").value);
  if (state.activeTag) params.set("tag", state.activeTag);
  return params;
}

async function loadRecords() {
  const data = await api(`/api/records?${filterParams()}`);
  state.records = data.records;
  const list = $("rec-list");
  list.replaceChildren();
  if (!state.records.length) {
    list.append(el("div", "empty", "no memories match — the library holds silence here"));
    return;
  }
  for (const record of state.records) {
    const item = el("div", "rec" + (record.akousma_id === state.selected ? " active" : ""));
    const line1 = el("div", "line1");
    line1.append(el("span", "summ", record.summary));
    line1.append(el("span", "when", (record.created_at || "").slice(0, 16).replace("T", " ")));
    const line2 = el("div", "line2");
    line2.append(el("span", `badge app-${record.originating_app || "unknown"}`, record.originating_app || "?"));
    if (record.origin) line2.append(el("span", "badge", record.origin));
    if (record.has_audio) line2.append(el("span", "badge", "audio"));
    if (record.parent_count) line2.append(el("span", "minitag", `⭡${record.parent_count}`));
    if (record.relation_count) line2.append(el("span", "minitag", `≈${record.relation_count}`));
    for (const tag of record.tags.slice(0, 4)) line2.append(el("span", "minitag", `#${tag}`));
    item.append(line1, line2);
    item.addEventListener("click", () => selectRecord(record.akousma_id));
    list.append(item);
  }
}

async function loadTags() {
  const data = await api("/api/tags");
  state.tags = data.tags;
  const wrap = $("tag-chips");
  wrap.replaceChildren();
  for (const item of state.tags.slice(0, 14)) {
    const chip = el("span", "tagchip" + (state.activeTag === item.tag ? " active" : ""), `#${item.tag} ${item.count}`);
    chip.addEventListener("click", () => {
      state.activeTag = state.activeTag === item.tag ? "" : item.tag;
      loadTags();
      loadRecords();
    });
    wrap.append(chip);
  }
}

async function selectRecord(id) {
  state.selected = id;
  await loadRecords();
  const data = await api(`/api/records/${id}`);
  renderDetail(data);
}

function kvRow(grid, key, value) {
  grid.append(el("span", "k", key), el("span", "", value ?? "—"));
}

function linkTo(id, label, missing) {
  const anchor = el("span", "link" + (missing ? " missing" : ""), label || id);
  anchor.addEventListener("click", () => selectRecord(id));
  return anchor;
}

function renderDetail(data) {
  const record = data.record;
  const pane = $("rec-detail");
  pane.replaceChildren();

  const title = el("h3", "", data.summary);
  pane.append(title);
  pane.append(el("div", "mono note", record.akousma_id));

  const provenance = record.provenance || {};
  const grid = el("div", "kv");
  kvRow(grid, "created", record.created_at);
  kvRow(grid, "app · origin", `${provenance.originating_app || "?"} · ${provenance.origin || "?"}`);
  kvRow(grid, "source type", provenance.source_type);
  if (provenance.device) kvRow(grid, "device", provenance.device);
  if (provenance.consent_status) kvRow(grid, "consent", provenance.consent_status);
  if ((provenance.pipeline_effects || []).length) kvRow(grid, "pipeline", provenance.pipeline_effects.join(" → "));
  if ((record.audio || {}).duration_seconds) kvRow(grid, "duration", `${record.audio.duration_seconds}s`);
  pane.append(grid);

  if (data.audio_available) {
    const audio = el("audio");
    audio.controls = true;
    audio.src = `/api/audio/${record.akousma_id}`;
    pane.append(audio);
  }

  // tags editor
  const tagSection = el("div", "section");
  tagSection.append(el("h2", "", "tags"));
  const tagRow = el("div", "row");
  const tagInput = el("input");
  tagInput.type = "text";
  tagInput.value = (record.tags || []).join(", ");
  tagInput.style.flex = "1";
  const tagSave = el("button", "btn", "save tags");
  tagSave.addEventListener("click", async () => {
    const tags = tagInput.value.split(",").map((t) => t.trim()).filter(Boolean);
    await api(`/api/records/${record.akousma_id}`, { method: "PATCH", body: JSON.stringify({ tags }) });
    toast("tags updated");
    loadTags();
    selectRecord(record.akousma_id);
  });
  tagRow.append(tagInput, tagSave);
  tagSection.append(tagRow);
  pane.append(tagSection);

  // listenings
  const listening = record.listening || {};
  if (Object.keys(listening).length) {
    const section = el("div", "section");
    section.append(el("h2", "", "listenings"));
    for (const namespace of Object.keys(listening).sort()) {
      const entry = listening[namespace];
      if (typeof entry !== "object" || entry === null) continue;
      const box = el("div", "listening-entry");
      const header = el("div", "ns");
      header.append(el("span", "", namespace));
      if (entry.contract) header.append(el("span", "contract", entry.contract));
      if (entry.created_at) header.append(el("span", "", entry.created_at));
      box.append(header);
      const payload = entry.payload && typeof entry.payload === "object" ? entry.payload : entry;
      const text = entry.summary || payload.caption || payload.summary || payload.main_reading || payload.notes || payload.brief;
      if (text) box.append(el("div", "", text));
      else {
        const pre = el("pre", "mono", JSON.stringify(payload, null, 2).slice(0, 900));
        box.append(pre);
      }
      section.append(box);
    }
    pane.append(section);
  }

  // lineage + kinship
  const section = el("div", "section linklist");
  section.append(el("h2", "", "lineage & kinship"));
  if (!data.parents.length && !data.children.length && !data.related.length) {
    section.append(el("div", "note", "no connections yet — this memory stands alone"));
  }
  for (const parent of data.parents) {
    const row = el("div", "", "made from ");
    row.append(linkTo(parent.akousma_id, parent.summary, parent.missing));
    section.append(row);
  }
  for (const child of data.children) {
    const row = el("div", "", "became ");
    row.append(linkTo(child.akousma_id, child.summary, child.missing));
    section.append(row);
  }
  for (const link of data.related) {
    const verb = link.type.replaceAll("_", " ") + (link.direction === "incoming" ? " ⭠ " : " ⭢ ");
    const row = el("div", "", verb);
    row.append(linkTo(link.akousma_id, link.summary, false));
    const remove = el("button", "btn danger", "×");
    remove.style.marginLeft = "8px";
    remove.addEventListener("click", async () => {
      const [from, target] = link.direction === "incoming" ? [link.akousma_id, record.akousma_id] : [record.akousma_id, link.akousma_id];
      await api(`/api/records/${from}/relations?type=${encodeURIComponent(link.type)}&target_akousma_id=${encodeURIComponent(target)}`, { method: "DELETE" });
      selectRecord(record.akousma_id);
    });
    row.append(remove);
    section.append(row);
  }
  const addRow = el("div", "row");
  addRow.style.marginTop = "8px";
  const relType = el("select");
  for (const type of ["series_with", "variant_of", "recurrence_of", "response_to", "same_source_as", "compares_with", "replaces", "other"]) {
    relType.append(new Option(type.replaceAll("_", " "), type));
  }
  const relTarget = el("input");
  relTarget.type = "text";
  relTarget.placeholder = "akm_… target id";
  const relAdd = el("button", "btn", "relate");
  relAdd.addEventListener("click", async () => {
    if (!relTarget.value.trim()) return;
    await api(`/api/records/${record.akousma_id}/relations`, {
      method: "POST",
      body: JSON.stringify({ type: relType.value, target_akousma_id: relTarget.value.trim() }),
    });
    toast("kinship added");
    selectRecord(record.akousma_id);
  });
  addRow.append(relType, relTarget, relAdd);
  section.append(addRow);
  pane.append(section);

  // notes (annotations)
  const noteSection = el("div", "section");
  noteSection.append(el("h2", "", "notes"));
  const noteArea = el("textarea");
  noteArea.value = (record.annotations || {}).note || "";
  const noteSave = el("button", "btn", "save note");
  noteSave.addEventListener("click", async () => {
    await api(`/api/records/${record.akousma_id}`, { method: "PATCH", body: JSON.stringify({ annotations: { note: noteArea.value } }) });
    toast("note saved");
  });
  noteSection.append(noteArea, noteSave);
  pane.append(noteSection);

  // actions
  const actions = el("div", "section row");
  for (const mode of ["sound", "prompt", "lineage"]) {
    const button = el("button", "btn", `germ: ${mode}`);
    button.addEventListener("click", async () => {
      const data = await api(`/api/germ-link/${record.akousma_id}?mode=${mode}`);
      window.open(data.germ_url, "_blank");
    });
    actions.append(button);
  }
  const graphButton = el("button", "btn", "graph here");
  graphButton.addEventListener("click", () => {
    document.querySelector('[data-tab="graph"]').click();
  });
  actions.append(graphButton);
  const wikiButton = el("button", "btn", "wiki page");
  wikiButton.addEventListener("click", async () => {
    await api(`/api/wiki/ingest/${record.akousma_id}`, { method: "POST" });
    document.querySelector('[data-tab="wiki"]').click();
    openWikiPage("record", record.akousma_id);
  });
  actions.append(wikiButton);
  const forget = el("button", "btn danger", "forget…");
  forget.addEventListener("click", async () => {
    if (!confirm("Forget this memory? The record is removed; links pointing at it remain as absence.")) return;
    await api(`/api/records/${record.akousma_id}/forget`, { method: "POST", body: JSON.stringify({ delete_audio: false }) });
    state.selected = null;
    $("rec-detail").replaceChildren(el("div", "empty", "forgotten"));
    loadRecords();
    loadTags();
  });
  actions.append(forget);
  pane.append(actions);
}

for (const id of ["f-text", "f-app", "f-origin"]) {
  $(id).addEventListener(id === "f-text" ? "input" : "change", () => loadRecords());
}
$("btn-add").addEventListener("click", () => { $("add-form").hidden = !$("add-form").hidden; });
$("m-cancel").addEventListener("click", () => { $("add-form").hidden = true; });
$("m-save").addEventListener("click", async () => {
  const body = {
    summary: $("m-summary").value.trim(),
    notes: $("m-notes").value.trim(),
    tags: $("m-tags").value.split(",").map((t) => t.trim()).filter(Boolean),
    place: $("m-place").value.trim() || null,
    heard_at: $("m-heard").value.trim() || null,
    kind: $("m-kind").value,
    audio_path: $("m-audio").value.trim() || null,
  };
  try {
    const data = await api("/api/records", { method: "POST", body: JSON.stringify(body) });
    $("m-status").textContent = "";
    $("add-form").hidden = true;
    for (const id of ["m-summary", "m-notes", "m-tags", "m-place", "m-heard", "m-audio"]) $(id).value = "";
    toast("remembered");
    await loadRecords();
    await loadTags();
    selectRecord(data.record.akousma_id);
  } catch (error) {
    $("m-status").textContent = error.message;
  }
});

/* ── graph (tiny force layout on canvas) ──────────────────────────────── */

const APP_COLORS = { oida: "#4a5a70", germ: "#5a6e4a", algophony: "#6e4a5e", akousmata: "#a9762f", unknown: "#90908a" };

async function loadGraph(focus) {
  const query = focus ? `?focus=${encodeURIComponent(focus)}&depth=2` : "?limit=300";
  const data = await api(`/api/graph${query}`);
  state.graph = data;
  $("graph-status").textContent = `${data.nodes.length} memories · ${data.edges.length} links${data.truncated ? " (truncated)" : ""}`;
  drawGraph();
}

$("graph-all").addEventListener("click", () => loadGraph(null));

function drawGraph() {
  const canvas = $("graph");
  const wrap = canvas.parentElement;
  canvas.width = wrap.clientWidth * devicePixelRatio;
  canvas.height = 560 * devicePixelRatio;
  canvas.style.height = "560px";
  const ctx = canvas.getContext("2d");
  ctx.scale(devicePixelRatio, devicePixelRatio);
  const width = wrap.clientWidth;
  const height = 560;
  const nodes = state.graph.nodes.map((node, index) => ({
    ...node,
    x: width / 2 + Math.cos((index / Math.max(1, state.graph.nodes.length)) * Math.PI * 2) * Math.min(width, height) * 0.32,
    y: height / 2 + Math.sin((index / Math.max(1, state.graph.nodes.length)) * Math.PI * 2) * height * 0.34,
    vx: 0, vy: 0,
  }));
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const edges = state.graph.edges.filter((e) => byId[e.from] && byId[e.to]);

  for (let step = 0; step < 220; step += 1) {
    for (const a of nodes) {
      for (const b of nodes) {
        if (a === b) continue;
        const dx = a.x - b.x, dy = a.y - b.y;
        const d2 = Math.max(80, dx * dx + dy * dy);
        const force = 1400 / d2;
        a.vx += (dx / Math.sqrt(d2)) * force;
        a.vy += (dy / Math.sqrt(d2)) * force;
      }
    }
    for (const edge of edges) {
      const a = byId[edge.from], b = byId[edge.to];
      const dx = b.x - a.x, dy = b.y - a.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const pull = (distance - 110) * 0.004;
      a.vx += dx / distance * pull * 8; a.vy += dy / distance * pull * 8;
      b.vx -= dx / distance * pull * 8; b.vy -= dy / distance * pull * 8;
    }
    for (const node of nodes) {
      node.vx += (width / 2 - node.x) * 0.0012;
      node.vy += (height / 2 - node.y) * 0.0012;
      node.x = Math.min(width - 20, Math.max(20, node.x + node.vx * 0.08));
      node.y = Math.min(height - 20, Math.max(20, node.y + node.vy * 0.08));
      node.vx *= 0.72; node.vy *= 0.72;
    }
  }

  ctx.clearRect(0, 0, width, height);
  for (const edge of edges) {
    const a = byId[edge.from], b = byId[edge.to];
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.strokeStyle = edge.kind === "lineage" ? "#1d1d1b" : "#b7b7b0";
    ctx.lineWidth = edge.kind === "lineage" ? 1.4 : 1;
    ctx.setLineDash(edge.kind === "relation" ? [4, 4] : []);
    ctx.stroke();
    ctx.setLineDash([]);
    if (edge.kind === "relation" && edge.type) {
      ctx.fillStyle = "#90908a";
      ctx.font = "10px ui-monospace, monospace";
      ctx.fillText(edge.type.replaceAll("_", " "), (a.x + b.x) / 2 + 4, (a.y + b.y) / 2 - 3);
    }
  }
  for (const node of nodes) {
    ctx.beginPath();
    ctx.arc(node.x, node.y, node.id === state.selected ? 8 : 6, 0, Math.PI * 2);
    ctx.fillStyle = APP_COLORS[node.app] || APP_COLORS.unknown;
    ctx.fill();
    if (node.id === state.selected) { ctx.strokeStyle = "#1d1d1b"; ctx.lineWidth = 2; ctx.stroke(); }
    ctx.fillStyle = "#6b6b64";
    ctx.font = "11px -apple-system, sans-serif";
    ctx.fillText(node.label.slice(0, 30), node.x + 10, node.y + 4);
  }
  canvas.onclick = (event) => {
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left, y = event.clientY - rect.top;
    const hit = nodes.find((node) => Math.hypot(node.x - x, node.y - y) < 12);
    if (hit && !hit.missing) {
      document.querySelector('[data-tab="library"]').click();
      selectRecord(hit.id);
    }
  };
}

/* ── wiki ─────────────────────────────────────────────────────────────── */

function renderMarkdown(markdown) {
  const escape = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  let html = "";
  let inCode = false;
  let inList = false;
  for (const raw of markdown.split("\n")) {
    if (raw.startsWith("```")) {
      html += inCode ? "</pre>" : "<pre>";
      inCode = !inCode;
      continue;
    }
    if (inCode) { html += escape(raw) + "\n"; continue; }
    let line = escape(raw);
    line = line.replace(/\[\[(record|tag|topic|research):([^\]|]+)\|([^\]]+)\]\]/g, '<a class="wikilink" data-kind="$1" data-name="$2">$3</a>');
    line = line.replace(/\[\[(record|tag|topic|research):([^\]|]+)\]\]/g, '<a class="wikilink" data-kind="$1" data-name="$2">$2</a>');
    line = line.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/_([^_]+)_/g, "<em>$1</em>");
    if (/^### /.test(line)) { html += `<h3>${line.slice(4)}</h3>`; continue; }
    if (/^## /.test(line)) { html += `<h2>${line.slice(3)}</h2>`; continue; }
    if (/^# /.test(line)) { html += `<h1>${line.slice(2)}</h1>`; continue; }
    if (/^- /.test(line)) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${line.slice(2)}</li>`;
      continue;
    }
    if (inList) { html += "</ul>"; inList = false; }
    html += line.trim() ? `<p>${line}</p>` : "";
  }
  if (inList) html += "</ul>";
  if (inCode) html += "</pre>";
  return html;
}

async function loadWiki() {
  const data = await api("/api/wiki");
  state.wikiPages = data.pages;
  const nav = $("wiki-nav");
  nav.replaceChildren();
  const addGroup = (label, kind, names, pretty) => {
    if (!names.length) return;
    nav.append(el("h2", "", label));
    for (const name of names.slice(0, 60)) {
      const item = el("span", "pageitem", pretty ? pretty(name) : name);
      item.addEventListener("click", () => openWikiPage(kind, name));
      nav.append(item);
    }
  };
  addGroup("topics", "topic", data.pages.topics);
  addGroup("research", "research", data.pages.research);
  addGroup("tags", "tag", data.pages.tags, (n) => `#${n}`);
  addGroup("memories", "record", data.pages.records, (n) => n.slice(0, 22) + "…");
  if (data.index) $("wiki-body").innerHTML = renderMarkdown(data.index);
}

async function openWikiPage(kind, name) {
  try {
    const data = await api(`/api/wiki/page/${kind}/${encodeURIComponent(name)}`);
    $("wiki-body").innerHTML = renderMarkdown(data.markdown);
  } catch (error) {
    $("wiki-body").innerHTML = `<p class="note">no ${kind} page for ${name} yet — ${error.message}</p>`;
  }
}

$("wiki-body").addEventListener("click", (event) => {
  const link = event.target.closest("a.wikilink");
  if (!link) return;
  const kind = link.dataset.kind;
  const name = link.dataset.name.trim();
  if (kind === "record" && event.metaKey) {
    document.querySelector('[data-tab="library"]').click();
    selectRecord(name);
    return;
  }
  openWikiPage(kind, name);
});

$("wiki-rebuild").addEventListener("click", async () => {
  const data = await api("/api/wiki/rebuild", { method: "POST" });
  $("wiki-status").textContent = `${data.records} record pages · ${data.tags} tag pages · ${data.orphan_pages.length} orphans kept`;
  loadWiki();
});

$("wiki-lint").addEventListener("click", async () => {
  const report = await api("/api/wiki/lint");
  const issues =
    (report.dangling_wikilinks || []).length +
    (report.missing_record_pages || []).length +
    (report.orphan_record_pages || []).length +
    Object.values(report.store || {}).reduce((sum, list) => sum + (Array.isArray(list) ? list.length : 0), 0);
  $("wiki-status").textContent = issues ? `${issues} issues — see console` : "clean";
  if (issues) console.log("akousmata lint report", report);
});

/* ── research ─────────────────────────────────────────────────────────── */

$("r-start").addEventListener("click", async () => {
  const question = $("r-question").value.trim();
  if (!question) return;
  const data = await api("/api/research", {
    method: "POST",
    body: JSON.stringify({ question, max_steps: Number($("r-steps").value), seed_ids: state.selected ? [state.selected] : [] }),
  });
  const log = $("r-log");
  log.replaceChildren();
  $("r-result").replaceChildren();
  const source = new EventSource(`/api/research/${data.session_id}/events`);
  source.onmessage = async (message) => {
    const event = JSON.parse(message.data);
    if (event.kind === "end") {
      source.close();
      if (event.result_slug) {
        const page = await api(`/api/wiki/page/topic/${encodeURIComponent(event.result_slug)}`);
        $("r-result").innerHTML = renderMarkdown(page.markdown);
      }
      return;
    }
    const row = el("div", `ev kind-${event.kind}`);
    row.append(el("span", "kind", event.kind), el("span", "", event.text));
    log.append(row);
    log.scrollTop = log.scrollHeight;
  };
});

/* ── settings ─────────────────────────────────────────────────────────── */

async function loadSettings() {
  const data = await api("/api/settings");
  state.settings = data;
  $("s-germ").value = data.germ_url || "";
  $("s-oida").value = data.oida_url || "";
  $("s-provider").value = data.llm.provider || "none";
  $("s-baseurl").value = data.llm.base_url || "";
  $("s-model").value = data.llm.model || "";
  $("s-key").value = data.llm.api_key || "";
  $("s-command").value = data.llm.command || "";
  $("r-mode-note").textContent = data.llm.configured
    ? `research runs with ${data.llm.provider}`
    : "no LLM configured — research runs as a deterministic traversal (configure one in Settings to deepen it)";
}

$("s-save").addEventListener("click", async () => {
  const body = {
    germ_url: $("s-germ").value.trim(),
    oida_url: $("s-oida").value.trim(),
    llm: {
      provider: $("s-provider").value,
      base_url: $("s-baseurl").value.trim(),
      model: $("s-model").value.trim(),
      api_key: $("s-key").value.trim(),
      command: $("s-command").value.trim(),
    },
  };
  const data = await api("/api/settings", { method: "PUT", body: JSON.stringify(body) });
  state.settings = data;
  $("s-status").textContent = "saved (locally)";
  loadSettings();
});

/* ── realtime ─────────────────────────────────────────────────────────── */

function watchChanges() {
  const source = new EventSource("/api/events");
  source.onopen = () => { $("live-dot").classList.add("on"); $("live-label").textContent = "live"; };
  source.onerror = () => { $("live-dot").classList.remove("on"); $("live-label").textContent = "watching"; };
  source.onmessage = (message) => {
    const record = JSON.parse(message.data);
    toast(`new memory: ${record.summary?.slice(0, 60) || record.akousma_id} (${record.originating_app})`);
    if (state.tab === "library") { loadRecords(); loadTags(); }
  };
}

/* ── boot ─────────────────────────────────────────────────────────────── */

(async function boot() {
  try {
    const health = await api("/api/health");
    $("store-path").textContent = `${health.store_path} · ${health.total} memories`;
  } catch (error) {
    $("store-path").textContent = error.message;
  }
  await loadTags();
  await loadRecords();
  await loadSettings();
  watchChanges();
})();
