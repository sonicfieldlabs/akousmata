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

const APP_ROOT = new URL(".", window.location.href).pathname.replace(/\/$/, "");
const appPath = (path) => `${APP_ROOT}${path.startsWith("/") ? path : `/${path}`}`;

async function api(path, options = {}) {
  const response = await fetch(appPath(path), {
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

const TABS = ["library", "constellations", "timeline", "graph", "wiki", "diary", "research", "audit", "settings"];

$("tabs").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-tab]");
  if (!button) return;
  state.tab = button.dataset.tab;
  for (const item of $("tabs").querySelectorAll("button")) item.classList.toggle("active", item === button);
  for (const name of TABS) $(`tab-${name}`).hidden = name !== state.tab;
  if (state.tab === "constellations") loadConstellations();
  if (state.tab === "timeline") loadTimeline();
  if (state.tab === "graph") loadGraph(state.selected || null);
  if (state.tab === "wiki") loadWiki();
  if (state.tab === "diary") loadDiary();
  if (state.tab === "audit") { loadAudit(); loadPacks(); }
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
    audio.src = appPath(`/api/audio/${record.akousma_id}`);
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

  // kin by resemblance (deterministic similarity)
  const simSection = el("div", "section linklist");
  simSection.append(el("h2", "", "kin by resemblance"));
  const simBody = el("div", "note", "listening for echoes…");
  simSection.append(simBody);
  pane.append(simSection);
  api(`/api/records/${record.akousma_id}/similar?limit=6`).then((data) => {
    simBody.replaceChildren();
    if (!data.similar.length) {
      simBody.append(el("span", "note", "nothing resembles this yet"));
      return;
    }
    for (const hit of data.similar) {
      const row = el("div", "sim-row");
      const bar = el("span", "sim-bar");
      bar.style.width = `${Math.round(Math.min(1, hit.score) * 60)}px`;
      row.append(bar);
      row.append(linkTo(hit.card.akousma_id, hit.card.summary, false));
      row.append(el("span", "note", ` — ${hit.basis.join(", ")}`));
      simBody.append(row);
    }
  }).catch(() => { simBody.textContent = "similarity unavailable"; });

  // consent & rights
  const consentSection = el("div", "section");
  consentSection.append(el("h2", "", "consent & rights"));
  const consentRow = el("div", "row");
  const consentSelect = el("select");
  for (const value of ["unknown", "owned", "licensed", "public_domain", "restricted"]) {
    consentSelect.append(new Option(value.replaceAll("_", " "), value));
  }
  consentSelect.value = provenance.consent_status || "unknown";
  const rightsInput = el("input");
  rightsInput.type = "text";
  rightsInput.placeholder = "rights note (who consented, what license…)";
  rightsInput.style.flex = "1";
  rightsInput.value = provenance.rights_note || "";
  const consentSave = el("button", "btn", "set consent");
  consentSave.addEventListener("click", async () => {
    await api(`/api/records/${record.akousma_id}/consent`, {
      method: "POST",
      body: JSON.stringify({ consent_status: consentSelect.value, rights_note: rightsInput.value.trim() || null }),
    });
    toast(`consent: ${consentSelect.value}`);
    selectRecord(record.akousma_id);
  });
  consentRow.append(consentSelect, rightsInput, consentSave);
  consentSection.append(consentRow);
  consentSection.append(el("p", "note", "export packs only ship owned / licensed / public domain memories"));
  pane.append(consentSection);

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

  // listen again (oída round-trip) — only for memories with audio
  if (data.audio_available) {
    const againRow = el("div", "section row");
    againRow.append(el("span", "note", "oída, listen to this again with"));
    const presetInput = el("input");
    presetInput.type = "text";
    presetInput.value = "basic";
    presetInput.setAttribute("list", "oida-presets");
    presetInput.style.width = "110px";
    const datalist = el("datalist");
    datalist.id = "oida-presets";
    for (const preset of ["basic", "field", "voice", "music", "recall", "full"]) datalist.append(new Option(preset, preset));
    const againButton = el("button", "btn", "listen again");
    againButton.addEventListener("click", async () => {
      againButton.disabled = true;
      againButton.textContent = "oída is listening…";
      try {
        const result = await api(`/api/records/${record.akousma_id}/listen-again`, {
          method: "POST",
          body: JSON.stringify({ preset: presetInput.value.trim() || "basic" }),
        });
        toast(`fresh listening filed as ${result.namespace}`);
        selectRecord(record.akousma_id);
      } catch (error) {
        toast(error.message);
        againButton.disabled = false;
        againButton.textContent = "listen again";
      }
    });
    againRow.append(presetInput, datalist, againButton);
    pane.append(againRow);
  }

  // constellations this memory can join
  const conRow = el("div", "section row");
  conRow.append(el("span", "note", "constellation"));
  const conSelect = el("select");
  const conAdd = el("button", "btn", "add to");
  conAdd.disabled = true;
  api("/api/constellations").then((data) => {
    for (const item of data.constellations) {
      const member = (item.akousma_ids || []).includes(record.akousma_id);
      conSelect.append(new Option(`${item.name}${member ? " ✓" : ""} (${(item.akousma_ids || []).length})`, item.id));
    }
    if (!data.constellations.length) conSelect.append(new Option("none yet — create one in Constellations", ""));
    else conAdd.disabled = false;
  }).catch(() => {});
  conAdd.addEventListener("click", async () => {
    if (!conSelect.value) return;
    await api(`/api/constellations/${conSelect.value}/records`, {
      method: "POST",
      body: JSON.stringify({ akousma_id: record.akousma_id }),
    });
    toast("added to the constellation");
    selectRecord(record.akousma_id);
  });
  conRow.append(conSelect, conAdd);
  pane.append(conRow);
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

/* ── constellations ───────────────────────────────────────────────────── */

const walk = { audio: null, queue: [], index: 0, button: null };

function stopWalk() {
  if (walk.audio) { walk.audio.pause(); walk.audio = null; }
  walk.queue = [];
  if (walk.button) walk.button.textContent = "play the walk";
}

function playWalk(members, button) {
  stopWalk();
  walk.queue = members.filter((m) => m.playable);
  walk.index = 0;
  walk.button = button;
  if (!walk.queue.length) { toast("no playable memories in this constellation"); return; }
  button.textContent = "stop the walk";
  const step = () => {
    if (walk.index >= walk.queue.length) { stopWalk(); return; }
    const member = walk.queue[walk.index];
    toast(`walk ${walk.index + 1}/${walk.queue.length}: ${member.summary?.slice(0, 50) || member.akousma_id}`);
    walk.audio = new Audio(appPath(`/api/audio/${member.akousma_id}`));
    walk.audio.onended = () => { walk.index += 1; step(); };
    walk.audio.onerror = () => { walk.index += 1; step(); };
    walk.audio.play().catch(() => { walk.index += 1; step(); });
  };
  step();
}

async function loadConstellations(selectId) {
  const data = await api("/api/constellations");
  const list = $("con-list");
  list.replaceChildren();
  if (!data.constellations.length) {
    list.append(el("div", "empty", "no constellations yet — name one above, then add memories from the library"));
  }
  for (const item of data.constellations) {
    const card = el("div", "rec" + (item.id === selectId ? " active" : ""));
    const line1 = el("div", "line1");
    line1.append(el("span", "summ", item.name));
    line1.append(el("span", "when", `${(item.akousma_ids || []).length} memories`));
    card.append(line1);
    if (item.note) card.append(el("div", "line2", item.note.slice(0, 90)));
    card.addEventListener("click", () => openConstellation(item.id));
    list.append(card);
  }
  if (selectId) openConstellation(selectId);
}

async function openConstellation(id) {
  stopWalk();
  const data = await api(`/api/constellations/${id}`);
  const con = data.constellation;
  const pane = $("con-detail");
  pane.replaceChildren();
  pane.append(el("h3", "", con.name));
  if (con.note) pane.append(el("p", "note", con.note));
  pane.append(el("div", "mono note", `${con.id} · ${con.playable_count}/${con.members.length} playable`));

  const actions = el("div", "row");
  actions.style.margin = "10px 0";
  const play = el("button", "btn primary", "play the walk");
  play.addEventListener("click", () => {
    if (walk.audio) stopWalk();
    else playWalk(con.members, play);
  });
  actions.append(play);
  const exportButton = el("button", "btn", "export pack");
  exportButton.addEventListener("click", async () => {
    try {
      const result = await api("/api/export", {
        method: "POST",
        body: JSON.stringify({ name: con.name, constellation_id: con.id }),
      });
      toast(`pack built: ${result.included} shipped, ${result.excluded.length} blocked by consent`);
    } catch (error) { toast(error.message); }
  });
  actions.append(exportButton);
  const remove = el("button", "btn danger", "delete");
  remove.addEventListener("click", async () => {
    if (!confirm("Delete this constellation? The memories themselves stay in the library.")) return;
    await api(`/api/constellations/${con.id}`, { method: "DELETE" });
    $("con-detail").replaceChildren(el("div", "empty", "deleted"));
    loadConstellations();
  });
  actions.append(remove);
  pane.append(actions);

  const section = el("div", "section linklist");
  section.append(el("h2", "", "members, in order"));
  con.members.forEach((member, index) => {
    const row = el("div", "sim-row");
    row.append(el("span", "note mono", String(index + 1).padStart(2, "0")));
    if (member.missing) row.append(el("span", "link missing", `${member.akousma_id} (forgotten memory)`));
    else {
      const anchor = el("span", "link", member.summary);
      anchor.addEventListener("click", () => {
        document.querySelector('[data-tab="library"]').click();
        selectRecord(member.akousma_id);
      });
      row.append(anchor);
      if (member.playable) {
        const listen = el("button", "btn", "▸");
        listen.addEventListener("click", () => {
          stopWalk();
          walk.audio = new Audio(appPath(`/api/audio/${member.akousma_id}`));
          walk.audio.play();
        });
        row.append(listen);
      }
    }
    const drop = el("button", "btn danger", "×");
    drop.addEventListener("click", async () => {
      await api(`/api/constellations/${con.id}/records/${member.akousma_id}`, { method: "DELETE" });
      openConstellation(con.id);
      loadConstellations(con.id);
    });
    row.append(drop);
    section.append(row);
  });
  if (!con.members.length) section.append(el("div", "note", "empty — open a memory in the library and use “add to”"));
  pane.append(section);
}

$("c-create").addEventListener("click", async () => {
  const name = $("c-name").value.trim();
  if (!name) { $("c-status").textContent = "a constellation needs a name"; return; }
  try {
    const data = await api("/api/constellations", {
      method: "POST",
      body: JSON.stringify({ name, note: $("c-note").value.trim() }),
    });
    $("c-name").value = ""; $("c-note").value = ""; $("c-status").textContent = "";
    toast("constellation created");
    loadConstellations(data.constellation.id);
  } catch (error) { $("c-status").textContent = error.message; }
});

/* ── timeline ─────────────────────────────────────────────────────────── */

async function loadTimeline() {
  const data = await api(`/api/timeline?bucket=${$("tl-bucket").value}`);
  $("tl-status").textContent = `${data.total} memories across ${data.buckets.length} ${$("tl-bucket").value}s`;
  const rhythms = data.recurrence_rhythms || {};
  $("tl-rhythms").textContent = rhythms.peak_weekday
    ? `recurrence rhythm: most entries on ${rhythms.peak_weekday}s, peak UTC hour ${rhythms.peak_hour_utc}:00 · ${rhythms.note}`
    : "recurrence rhythms appear as the library grows";
  const wrap = $("timeline");
  wrap.replaceChildren();
  if (!data.buckets.length) { wrap.append(el("div", "empty", "no memories yet — the timeline starts when the library does")); return; }
  const max = Math.max(...data.buckets.map((b) => b.count));
  for (const bucket of data.buckets) {
    const row = el("div", "tl-row");
    row.append(el("span", "tl-label mono", bucket.bucket));
    const bar = el("span", "tl-bar");
    for (const [app, count] of Object.entries(bucket.by_app)) {
      const seg = el("span", "tl-seg");
      seg.style.width = `${Math.max(2, (count / max) * 420)}px`;
      seg.style.background = APP_COLORS[app] || APP_COLORS.unknown;
      seg.title = `${app}: ${count}`;
      bar.append(seg);
    }
    row.append(bar);
    row.append(el("span", "note", String(bucket.count)));
    if (bucket.top_tags.length) row.append(el("span", "note", bucket.top_tags.map((t) => `#${t}`).join(" ")));
    wrap.append(row);
  }
}

$("tl-bucket").addEventListener("change", loadTimeline);

/* ── diary ────────────────────────────────────────────────────────────── */

async function loadDiary() {
  if (!$("d-day").value) $("d-day").value = new Date().toISOString().slice(0, 10);
  openDiaryDay($("d-day").value);
  try {
    const data = await api("/api/wiki");
    const wrap = $("d-days");
    wrap.replaceChildren();
    for (const day of (data.pages.diary || []).slice(0, 10)) {
      const chip = el("span", "tagchip", day);
      chip.addEventListener("click", () => { $("d-day").value = day; openDiaryDay(day); });
      wrap.append(chip);
    }
  } catch {}
}

async function openDiaryDay(day) {
  try {
    const data = await api(`/api/diary/${day}`);
    $("d-digest").innerHTML = renderMarkdown(data.markdown);
  } catch (error) {
    $("d-digest").innerHTML = `<p class="note">${error.message}</p>`;
  }
}

$("d-load").addEventListener("click", () => openDiaryDay($("d-day").value));
$("d-save").addEventListener("click", async () => {
  const text = $("d-text").value.trim();
  if (!text) { $("d-status").textContent = "the diary needs at least a line"; return; }
  try {
    const data = await api("/api/diary", {
      method: "POST",
      body: JSON.stringify({
        text,
        tags: $("d-tags").value.split(",").map((t) => t.trim()).filter(Boolean),
        place: $("d-place").value.trim() || null,
      }),
    });
    $("d-text").value = ""; $("d-status").textContent = "";
    toast("written into the diary");
    $("d-day").value = data.day;
    openDiaryDay(data.day);
  } catch (error) { $("d-status").textContent = error.message; }
});

/* ── consent audit + export packs ─────────────────────────────────────── */

async function loadAudit() {
  const data = await api("/api/audit/consent");
  const totals = Object.entries(data.totals).map(([status, count]) => `${status.replaceAll("_", " ")} ${count}`).join(" · ");
  $("a-totals").textContent = `${data.total} memories · ${data.exportable} exportable · ${totals}`;
  const wrap = $("audit-list");
  wrap.replaceChildren();
  const items = $("a-blocked").checked ? data.items.filter((item) => !item.exportable) : data.items;
  if (!items.length) { wrap.append(el("div", "empty", "nothing here — every memory clears the current filter")); return; }
  for (const item of items) {
    const row = el("div", "audit-row");
    const anchor = el("span", "link", item.summary);
    anchor.addEventListener("click", () => {
      document.querySelector('[data-tab="library"]').click();
      selectRecord(item.akousma_id);
    });
    row.append(el("span", `badge app-${item.originating_app || "unknown"}`, item.originating_app || "?"), anchor);
    row.append(el("span", item.exportable ? "badge ok" : "badge blocked", item.exportable ? "exportable" : "blocked"));
    const select = el("select");
    for (const value of ["unknown", "owned", "licensed", "public_domain", "restricted"]) select.append(new Option(value.replaceAll("_", " "), value));
    select.value = item.consent_status || "unknown";
    select.addEventListener("change", async () => {
      await api(`/api/records/${item.akousma_id}/consent`, {
        method: "POST",
        body: JSON.stringify({ consent_status: select.value }),
      });
      toast(`consent: ${select.value}`);
      loadAudit();
    });
    row.append(select);
    if (item.rights_note) row.append(el("span", "note", item.rights_note.slice(0, 60)));
    wrap.append(row);
  }
}

$("a-refresh").addEventListener("click", loadAudit);
$("a-blocked").addEventListener("change", loadAudit);

async function loadPacks() {
  const data = await api("/api/exports");
  const wrap = $("pack-list");
  wrap.replaceChildren();
  for (const pack of data.packs) {
    const row = el("div", "sim-row");
    row.append(el("span", "", pack.name || "pack"));
    row.append(el("span", "note", `${pack.created_at || ""} · ${pack.included} shipped · ${pack.excluded} blocked`));
    row.append(el("span", "note mono", pack.path));
    wrap.append(row);
  }
}

$("x-build").addEventListener("click", async () => {
  const name = $("x-name").value.trim();
  const tag = $("x-tag").value.trim();
  if (!name || !tag) { $("x-status").textContent = "name the pack and pick a tag"; return; }
  try {
    const result = await api("/api/export", {
      method: "POST",
      body: JSON.stringify({ name, tag, include_audio: $("x-audio").checked, include_wiki: $("x-wiki").checked }),
    });
    $("x-status").textContent = `${result.included} shipped, ${result.excluded.length} blocked → ${result.path}`;
    loadPacks();
  } catch (error) { $("x-status").textContent = error.message; }
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
  const source = new EventSource(appPath(`/api/research/${data.session_id}/events`));
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
  const watcher = data.watcher || {};
  $("s-watch").value = String(watcher.enabled !== false);
  $("s-ingest").value = watcher.ingest_seconds ?? 60;
  $("s-lintm").value = watcher.lint_minutes ?? 30;
  $("r-mode-note").textContent = data.llm.configured
    ? `research runs with ${data.llm.provider}`
    : "no LLM configured — research runs as a deterministic traversal (configure one in Settings to deepen it)";
  try {
    const status = await api("/api/watcher");
    $("s-watch-status").textContent = status.enabled
      ? `running since ${status.started_at || "?"} · ${status.ingested_count} auto-ingested · last lint ${status.last_lint_at || "not yet"} (${status.last_lint_issues ?? "—"} issues)${status.last_error ? ` · last error: ${status.last_error}` : ""}`
      : "not running — interval changes apply on next launch";
  } catch {}
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
    watcher: {
      enabled: $("s-watch").value === "true",
      ingest_seconds: Number($("s-ingest").value) || 60,
      lint_minutes: Number($("s-lintm").value) || 30,
    },
  };
  const data = await api("/api/settings", { method: "PUT", body: JSON.stringify(body) });
  state.settings = data;
  $("s-status").textContent = "saved (locally)";
  loadSettings();
});

/* ── realtime ─────────────────────────────────────────────────────────── */

function watchChanges() {
  const source = new EventSource(appPath("/api/events"));
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
