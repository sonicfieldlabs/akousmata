/* akousmata — listening navigator. Vanilla JS over the local API. */

const state = {
  tab: "library",
  records: [],
  selected: null,
  tags: [],
  activeTag: "",
  activeCovenant: "",
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

async function apiForm(path, form) {
  const response = await fetch(appPath(path), { method: "POST", body: form });
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return response.json();
}

/* ── tabs ─────────────────────────────────────────────────────────────── */

const TABS = ["library", "constellations", "timeline", "graph", "map", "wiki", "diary", "research", "audit", "settings"];

$("tabs").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-tab]");
  if (!button) return;
  state.tab = button.dataset.tab;
  for (const item of $("tabs").querySelectorAll("button")) item.classList.toggle("active", item === button);
  for (const name of TABS) $(`tab-${name}`).hidden = name !== state.tab;
  if (state.tab === "constellations") loadConstellations();
  if (state.tab === "timeline") loadTimeline();
  if (state.tab === "graph") loadGraph(state.selected || null);
  if (state.tab === "map") loadMap();
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
  if ($("f-class").value) params.set("record_class", $("f-class").value);
  if ($("f-listener").value) params.set("listener_type", $("f-listener").value);
  if (state.activeTag) params.set("tag", state.activeTag);
  if (state.activeCovenant) params.set("covenant", state.activeCovenant);
  return params;
}

async function loadRecords() {
  const data = await api(`/api/records?${filterParams()}`);
  state.records = data.records;
  const covenantChip = $("covenant-chip");
  covenantChip.replaceChildren();
  if (state.activeCovenant) {
    const chip = el("span", "tagchip active", `☖ ${state.activeCovenant} ×`);
    chip.title = "showing memories listened under this covenant — click to clear";
    chip.addEventListener("click", () => { state.activeCovenant = ""; loadRecords(); });
    covenantChip.append(chip);
  }
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
    line2.append(el("span", `badge record-${record.record_class || "legacy"}`, (record.record_class || "legacy").replaceAll("_", " ")));
    for (const listenerType of record.listener_types || []) {
      const typeBadge = el("span", "minitag", listenerType.replaceAll("_", " "));
      typeBadge.title = "declared by auditum.listenings[].listener_type";
      line2.append(typeBadge);
    }
    if (record.owned_human_record) line2.append(el("span", "minitag", record.human_editable ? "my editable head" : "my earlier revision"));
    if (record.has_audio) line2.append(el("span", "badge", "audio"));
    if (record.has_location) line2.append(el("span", "minitag", "⌖"));
    if (record.covenant_id) {
      const mark = el("span", "minitag", "☖");
      mark.title = `listened under ${record.covenant_id}`;
      line2.append(mark);
    }
    if (record.auditum_contract) {
      const mark = el("span", "minitag", record.decision_only ? `◇${record.route_decision_count || 0}` : `◎${record.listening_count || 0}`);
      mark.title = record.decision_only
        ? `${record.route_decision_count || 0} attributable pre-listening decision(s); no acoustic listening`
        : `${record.listening_count || 0} attributable listening(s)`;
      line2.append(mark);
    }
    if (record.stop_decision_count) {
      const mark = el("span", "minitag", `⊣${record.stop_decision_count}`);
      mark.title = "route stopped, withheld, deferred, or refused — open for the attributed reason";
      line2.append(mark);
    }
    if (record.ensemble_kind) {
      const mark = el("span", "minitag", record.ensemble_kind === "ear_swarm" ? "swarm" : "plural");
      mark.title = `explicit ${record.ensemble_kind.replaceAll("_", " ")} declaration`;
      line2.append(mark);
    }
    if (record.disagreement_count) {
      const mark = el("span", "minitag", `≠${record.disagreement_count}`);
      mark.title = "preserved disagreement — open the record to inspect each position";
      line2.append(mark);
    }
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
  const identityRow = el("div", "row");
  identityRow.append(el("span", `badge record-${data.card?.record_class || "legacy"}`, (data.card?.record_class || "legacy").replaceAll("_", " ")));
  for (const listenerType of data.card?.listener_types || []) identityRow.append(el("span", "minitag", listenerType.replaceAll("_", " ")));
  if (data.human_record?.owned_locally) identityRow.append(el("span", "minitag", data.human_record.editable ? "my current human head" : "my preserved earlier revision"));
  pane.append(identityRow);

  const provenance = record.provenance || {};
  const grid = el("div", "kv");
  kvRow(grid, "created", record.created_at);
  kvRow(grid, "app · origin", `${provenance.originating_app || "?"} · ${provenance.origin || "?"}`);
  kvRow(grid, "source type", provenance.source_type);
  if (provenance.device) kvRow(grid, "device", provenance.device);
  if (provenance.consent_status) kvRow(grid, "consent", provenance.consent_status);
  if ((provenance.pipeline_effects || []).length) kvRow(grid, "pipeline", provenance.pipeline_effects.join(" → "));
  if ((record.audio || {}).duration_seconds) kvRow(grid, "duration", `${record.audio.duration_seconds}s`);
  const capture = record.capture || {};
  if (capture.direction || capture.seconds || capture.trigger) {
    const parts = [
      capture.direction,
      capture.seconds ? `${capture.seconds}s window` : null,
      capture.trigger ? `via ${capture.trigger}` : null,
    ].filter(Boolean);
    kvRow(grid, "capture", parts.join(" · "));
  }
  pane.append(grid);

  if (data.audio_available) {
    const audio = el("audio");
    audio.controls = true;
    audio.src = appPath(`/api/audio/${record.akousma_id}`);
    pane.append(audio);
  }

  // Human account lifecycle. Editing never rewrites the selected record: it
  // creates the next attributable revision and leaves this one intact.
  const revisionHistory = data.revision?.history || [];
  if (revisionHistory.length > 1 || data.revision?.root_id !== record.akousma_id) {
    const historySection = el("div", "section linklist");
    historySection.append(el("h2", "", "revision history"));
    for (const item of revisionHistory) {
      const row = el("div", "row");
      const marker = (data.revision.head_ids || []).includes(item.akousma_id) ? "head" : "preserved";
      row.append(linkTo(item.akousma_id, item.summary, false));
      row.append(el("span", "note", `${marker} · ${item.record_class.replaceAll("_", " ")} · ${(item.created_at || "").slice(0, 16)}`));
      historySection.append(row);
    }
    pane.append(historySection);
  }

  if (data.human_record?.editable) {
    const editSection = el("div", "section");
    editSection.append(el("h2", "", "edit my current human listening"));
    editSection.append(el("p", "note", "Saving creates a new revision. This record and its machine links remain preserved."));
    const humanEntry = Object.values(record.listening || {}).find((entry) => entry && typeof entry === "object") || {};
    const humanPayload = humanEntry.payload && typeof humanEntry.payload === "object" ? humanEntry.payload : humanEntry;
    const editor = el("div", "form-grid");
    const summaryInput = el("input"); summaryInput.type = "text"; summaryInput.value = data.summary || "";
    const notesInput = el("textarea"); notesInput.value = humanPayload.notes || "";
    const tagsInput = el("input"); tagsInput.type = "text"; tagsInput.value = (record.tags || []).join(", ");
    const heardInput = el("input"); heardInput.type = "checkbox"; heardInput.checked = data.card?.record_class === "human";
    const heardLabel = el("label", "note", " I personally heard this event"); heardLabel.prepend(heardInput);
    const reasonInput = el("input"); reasonInput.type = "text"; reasonInput.placeholder = "why this revision is needed";
    const saveRevision = el("button", "btn primary", "save as new revision");
    saveRevision.addEventListener("click", async () => {
      try {
        const result = await api(`/api/human-records/${record.akousma_id}/revisions`, {
          method: "POST",
          body: JSON.stringify({
            summary: summaryInput.value.trim(),
            notes: notesInput.value,
            tags: tagsInput.value.split(",").map((tag) => tag.trim()).filter(Boolean),
            heard_at: humanPayload.heard_at || null,
            place: humanPayload.place || null,
            kind: humanPayload.kind || "heard_live",
            location: record.location || null,
            heard: heardInput.checked,
            reason: reasonInput.value.trim(),
          }),
        });
        toast(`new human revision ${result.record.akousma_id}`);
        await loadRecords();
        selectRecord(result.record.akousma_id);
      } catch (error) { toast(error.message); }
    });
    editor.append(
      el("label", "", "summary"), summaryInput,
      el("label", "", "notes"), notesInput,
      el("label", "", "tags"), tagsInput,
      el("label", "", "hearing claim"), heardLabel,
      el("label", "", "revision reason"), reasonInput,
      el("label", "", ""), saveRevision,
    );
    editSection.append(editor);
    pane.append(editSection);
  }

  if ((data.card?.listener_types || []).includes("agent")) {
    const humanResponse = el("div", "section row");
    humanResponse.append(el("span", "note", "Keep the machine account immutable and add your own record beside it."));
    const respondButton = el("button", "btn primary", "Add my listening in response");
    respondButton.addEventListener("click", () => openHumanForm(record.akousma_id));
    humanResponse.append(respondButton);
    pane.append(humanResponse);
  }

  // Library curation is metadata over any record; it is not an edit to the
  // producer's listening/event account.
  const tagSection = el("div", "section");
  tagSection.append(el("h2", "", "library curation · tags"));
  tagSection.append(el("p", "note", "Curation metadata only — machine and human listening cores remain immutable."));
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

  // place (spec v1.2 location — listener-annotatable: add or correct it here)
  const placeSection = el("div", "section");
  placeSection.append(el("h2", "", "library curation · place"));
  const loc = record.location && typeof record.location.lat === "number" ? record.location : null;
  const placeRow = el("div", "row");
  if (loc) {
    const bits = [loc.label, `${loc.lat.toFixed(4)}, ${loc.lon.toFixed(4)}`];
    if (loc.accuracy_m) bits.push(`±${Math.round(loc.accuracy_m)} m`);
    if (loc.source) bits.push(loc.source);
    placeRow.append(el("span", "", `⌖ ${bits.filter(Boolean).join(" · ")}`));
    const showButton = el("button", "btn", "show on the map");
    showButton.addEventListener("click", () => {
      MAP.focus = { lat: loc.lat, lon: loc.lon };
      document.querySelector('[data-tab="map"]').click();
    });
    placeRow.append(showButton);
  } else {
    placeRow.append(el("span", "note", "no location — geotag this memory to see it on the listening map"));
  }
  const placeEdit = el("button", "btn", loc ? "edit" : "add location");
  placeRow.append(placeEdit);
  if (loc) {
    const placeClear = el("button", "btn danger", "remove");
    placeClear.addEventListener("click", async () => {
      await api(`/api/records/${record.akousma_id}`, { method: "PATCH", body: JSON.stringify({ location: {} }) });
      toast("location removed");
      selectRecord(record.akousma_id);
    });
    placeRow.append(placeClear);
  }
  placeSection.append(placeRow);
  const placeEditor = el("div", "row");
  placeEditor.hidden = true;
  placeEditor.style.marginTop = "8px";
  const latInput = el("input");
  latInput.type = "text"; latInput.placeholder = "lat"; latInput.style.width = "110px";
  const lonInput = el("input");
  lonInput.type = "text"; lonInput.placeholder = "lon"; lonInput.style.width = "110px";
  const labelInput = el("input");
  labelInput.type = "text"; labelInput.placeholder = "place name (optional)"; labelInput.style.flex = "1";
  if (loc) { latInput.value = loc.lat; lonInput.value = loc.lon; labelInput.value = loc.label || ""; }
  let geoSource = "manual";
  let geoAccuracy = null;
  for (const input of [latInput, lonInput]) input.addEventListener("input", () => { geoSource = "manual"; geoAccuracy = null; });
  const hereButton = el("button", "btn", "use my location");
  hereButton.addEventListener("click", () => {
    if (!navigator.geolocation) { toast("no geolocation in this browser"); return; }
    navigator.geolocation.getCurrentPosition((position) => {
      latInput.value = position.coords.latitude.toFixed(5);
      lonInput.value = position.coords.longitude.toFixed(5);
      geoSource = "gps";
      geoAccuracy = position.coords.accuracy || null;
    }, () => toast("location permission denied"));
  });
  const placeSave = el("button", "btn primary", "save place");
  placeSave.addEventListener("click", async () => {
    const lat = parseFloat(latInput.value);
    const lon = parseFloat(lonInput.value);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) { toast("lat and lon are needed"); return; }
    const body = { location: { lat, lon, label: labelInput.value.trim() || null, source: geoSource } };
    if (geoAccuracy) body.location.accuracy_m = geoAccuracy;
    try {
      await api(`/api/records/${record.akousma_id}`, { method: "PATCH", body: JSON.stringify(body) });
      toast("place saved");
      selectRecord(record.akousma_id);
    } catch (error) { toast(error.message); }
  });
  placeEditor.append(latInput, lonInput, labelInput, hereButton, placeSave);
  placeEdit.addEventListener("click", () => { placeEditor.hidden = !placeEditor.hidden; });
  placeSection.append(placeEditor);
  pane.append(placeSection);

  // covenant (spec v1.3 — under which ethics this was listened). Producer-owned:
  // the navigator renders and filters by it, never edits it.
  const cov = record.covenant && record.covenant.id ? record.covenant : null;
  if (cov) {
    const covSection = el("div", "section");
    covSection.append(el("h2", "", "covenant"));
    const head = el("div", "row");
    head.append(el("span", "", `☖ ${cov.name || cov.id}`));
    if (cov.version && cov.name) head.append(el("span", "note", `v${cov.version}`));
    if (cov.contract) head.append(el("span", "badge", cov.contract));
    const filterButton = el("button", "btn", "all under this covenant");
    filterButton.addEventListener("click", () => {
      state.activeCovenant = cov.id;
      loadRecords();
    });
    head.append(filterButton);
    covSection.append(head);
    if ((cov.extends || []).length) {
      covSection.append(el("div", "note", `stands on ${cov.extends.join(", ")}`));
    }
    for (const item of cov.withheld || []) {
      covSection.append(el("div", "note",
        `withheld: ${item.subject || "?"}${item.count != null ? ` ×${item.count}` : ""} — under ${String(item.rule || "its rules").replaceAll("_", " ")}`));
    }
    if ((cov.rules_applied || []).length) {
      covSection.append(el("div", "note", `rules applied: ${cov.rules_applied.join(" · ")}`));
    }
    if (cov.commitments) {
      covSection.append(el("div", "note", `${cov.commitments} commitment${cov.commitments === 1 ? "" : "s"} carried with the covenant`));
    }
    pane.append(covSection);
  }

  // Accountable auditum (spec v1.6). This is an index over producer-owned
  // reports: attribution and disagreement are rendered, never synthesized.
  const auditum = record.auditum && record.auditum.contract ? record.auditum : null;
  if (auditum) {
    const auditSection = el("div", "section");
    auditSection.append(el("h2", "", "accountable auditum"));
    const head = el("div", "row");
    head.append(el("span", "badge", auditum.contract));
    head.append(el("span", "note", `${(auditum.listenings || []).length} listening(s) · ${(auditum.route_decisions || []).length} route decision(s) · ${(auditum.disagreements || []).length} disagreement(s) · ${(auditum.honest_absences || []).length} attributed absence(s)`));
    auditSection.append(head);
    for (const listening of auditum.listenings || []) {
      const box = el("div", "listening-entry");
      const label = `${listening.listener_id || "?"} · ${listening.listener_type || "?"}`;
      box.append(el("div", "ns", `${label} · ${listening.listening_id || "?"}`));
      box.append(el("div", "", listening.report_namespace || "missing report namespace"));
      if (listening.contract) box.append(el("div", "note", listening.contract));
      if ((listening.route || []).length) box.append(el("div", "note", `route: ${listening.route.join(" → ")}`));
      auditSection.append(box);
    }
    for (const disagreement of auditum.disagreements || []) {
      const box = el("div", "listening-entry");
      box.append(el("div", "ns", `≠ ${disagreement.subject || disagreement.id || "disagreement"} · ${disagreement.status || "?"}`));
      for (const position of disagreement.positions || []) {
        box.append(el("div", "", `${position.listening_id || "?"}: ${position.statement || "?"}${position.claim_category ? ` [${position.claim_category}]` : ""}`));
      }
      if (disagreement.resolution_note) box.append(el("div", "note", disagreement.resolution_note));
      auditSection.append(box);
    }
    for (const absence of auditum.honest_absences || []) {
      auditSection.append(el("div", "note", `absence · ${(absence.kind || "?").replaceAll("_", " ")} · ${absence.subject || "?"} — ${absence.attributed_to || "unattributed"}${absence.count != null ? ` ×${absence.count}` : ""}`));
    }
    for (const decision of auditum.route_decisions || []) {
      const box = el("div", "listening-entry");
      box.append(el("div", "ns", `decision · ${decision.gate || "?"} → ${(decision.outcome || "?").replaceAll("_", " ")}`));
      box.append(el("div", "", decision.subject || "unnamed subject"));
      box.append(el("div", "note", `${decision.reason || "reason not recorded"} — ${(decision.authority || {}).actor || "unattributed actor"}`));
      if (decision.receipt) {
        box.append(el("div", "note", `receipt · ${decision.receipt.result || "recorded"}${decision.receipt.recovery ? ` · ${decision.receipt.recovery}` : ""}`));
      }
      auditSection.append(box);
    }
    for (const action of auditum.actions || []) {
      const authority = action.authority || {};
      auditSection.append(el("div", "note", `action · ${action.status || "?"} · ${action.proposal || "?"} — authority ${authority.mode || "missing"}${(authority.scopes || []).length ? ` (${authority.scopes.join(", ")})` : ""}`));
    }
    if (auditum.ensemble) {
      const ensemble = auditum.ensemble;
      const box = el("div", "listening-entry");
      box.append(el("div", "ns", `ensemble · ${(ensemble.kind || "?").replaceAll("_", " ")}`));
      box.append(el("div", "note", `${(ensemble.listening_ids || []).length} attributable listenings · ${(ensemble.influence_edges || []).length} influence edge(s)`));
      box.append(el("div", "note", `permissions ${ensemble.permissions_preserved ? "preserved" : "not preserved"} · disagreements ${ensemble.disagreements_preserved ? "preserved" : "not preserved"}`));
      if (ensemble.dissolution_rule) box.append(el("div", "note", `dissolution: ${ensemble.dissolution_rule}`));
      auditSection.append(box);
    }
    if (auditum.revision && auditum.revision.revises_akousma_id) {
      const revision = el("div", "", "revision of ");
      revision.append(linkTo(auditum.revision.revises_akousma_id, auditum.revision.revises_akousma_id, false));
      if (auditum.revision.reason) revision.append(el("span", "note", ` — ${auditum.revision.reason}`));
      auditSection.append(revision);
    }
    if ((data.accountability?.issues || []).length) {
      for (const issue of data.accountability.issues) auditSection.append(el("div", "badge blocked", issue));
    }
    pane.append(auditSection);
  }

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

  // open record: top-level fields this navigator doesn't know yet (spec v1.2
  // preserves them; showing them keeps the record honest about what it holds)
  const KNOWN_TOP = new Set([
    "akousma_id", "schema_version", "created_at", "session_id", "audio", "provenance",
    "listening", "lineage", "tags", "annotations", "extensions", "summary", "location", "capture", "covenant", "auditum",
  ]);
  const extraKeys = Object.keys(record).filter((key) => !KNOWN_TOP.has(key)).sort();
  if (extraKeys.length) {
    const openSection = el("div", "section");
    openSection.append(el("h2", "", "more details (open record)"));
    for (const key of extraKeys) {
      const box = el("div", "listening-entry");
      box.append(el("div", "ns", key));
      const value = record[key];
      if (typeof value === "string") box.append(el("div", "", value));
      else box.append(el("pre", "mono", JSON.stringify(value, null, 2).slice(0, 900)));
      openSection.append(box);
    }
    pane.append(openSection);
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
    const sameSourceVerified = relType.value === "same_source_as"
      ? confirm("Have you verified that both records concern the same source? This is stronger than a response link.")
      : false;
    if (relType.value === "same_source_as" && !sameSourceVerified) return;
    try {
      await api(`/api/records/${record.akousma_id}/relations`, {
        method: "POST",
        body: JSON.stringify({
          type: relType.value,
          target_akousma_id: relTarget.value.trim(),
          same_source_verified: sameSourceVerified,
        }),
      });
      toast("kinship added");
      selectRecord(record.akousma_id);
    } catch (error) { toast(error.message); }
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
  noteSection.append(el("h2", "", "library curation · note"));
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
  if (state.settings?.germ_url) {
    for (const mode of ["sound", "prompt", "lineage"]) {
      const button = el("button", "btn", `germ: ${mode}`);
      button.addEventListener("click", async () => {
        const data = await api(`/api/germ-link/${record.akousma_id}?mode=${mode}`);
        window.open(data.germ_url, "_blank");
      });
      actions.append(button);
    }
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
    const reason = prompt("Reason for forgetting (kept in the content-free receipt):", "explicit forget request");
    if (reason === null || !reason.trim()) return;
    const result = await api(`/api/records/${record.akousma_id}/forget`, {
      method: "POST",
      body: JSON.stringify({ delete_audio: false, actor: "human-operator", reason: reason.trim() }),
    });
    state.selected = null;
    $("rec-detail").replaceChildren(el("div", "empty", "forgotten"));
    toast(`forgotten · receipt ${result.receipt.receipt_id}`);
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
        toast(`fresh listening filed as revision ${result.record.akousma_id}`);
        selectRecord(result.record.akousma_id);
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

for (const id of ["f-text", "f-app", "f-origin", "f-class", "f-listener"]) {
  $(id).addEventListener(id === "f-text" ? "input" : "change", () => loadRecords());
}
function openHumanForm(responseTo = "") {
  $("add-form").hidden = false;
  $("m-response-to").value = responseTo;
  $("m-same-source").checked = false;
  $("m-summary").focus();
  $("add-form").scrollIntoView({ behavior: "smooth", block: "start" });
}

$("btn-add").addEventListener("click", () => {
  if ($("add-form").hidden) openHumanForm();
  else $("add-form").hidden = true;
});
$("m-cancel").addEventListener("click", () => { $("add-form").hidden = true; });

const manualGeo = { source: "manual", accuracy_m: null };
for (const id of ["m-lat", "m-lon"]) {
  $(id).addEventListener("input", () => { manualGeo.source = "manual"; manualGeo.accuracy_m = null; $("m-loc-status").textContent = ""; });
}
$("m-locate").addEventListener("click", () => {
  if (!navigator.geolocation) { $("m-loc-status").textContent = "no geolocation in this browser"; return; }
  $("m-loc-status").textContent = "asking…";
  navigator.geolocation.getCurrentPosition((position) => {
    $("m-lat").value = position.coords.latitude.toFixed(5);
    $("m-lon").value = position.coords.longitude.toFixed(5);
    manualGeo.source = "gps";
    manualGeo.accuracy_m = position.coords.accuracy || null;
    $("m-loc-status").textContent = manualGeo.accuracy_m ? `±${Math.round(manualGeo.accuracy_m)} m` : "located";
  }, () => { $("m-loc-status").textContent = "permission denied"; });
});

$("m-save").addEventListener("click", async () => {
  const audioFile = $("m-audio").files[0] || null;
  const body = {
    summary: $("m-summary").value.trim(),
    notes: $("m-notes").value.trim(),
    tags: $("m-tags").value.split(",").map((t) => t.trim()).filter(Boolean),
    place: $("m-place").value.trim() || null,
    heard_at: $("m-heard").value.trim() || null,
    kind: $("m-kind").value,
    heard: $("m-heard-confirm").checked,
  };
  const responseTo = $("m-response-to").value.trim();
  if (responseTo) body.response_to = responseTo;
  if (responseTo && $("m-same-source").checked) {
    body.same_source_as = responseTo;
    body.same_source_verified = true;
  }
  const lat = parseFloat($("m-lat").value);
  const lon = parseFloat($("m-lon").value);
  if (Number.isFinite(lat) && Number.isFinite(lon)) {
    body.location = { lat, lon, source: manualGeo.source };
    if (manualGeo.accuracy_m) body.location.accuracy_m = manualGeo.accuracy_m;
  }
  try {
    let data;
    if (audioFile) {
      const form = new FormData();
      form.append("metadata", JSON.stringify(body));
      form.append("audio", audioFile, audioFile.name);
      data = await apiForm("/api/human-records/import", form);
    } else {
      data = await api("/api/human-records", { method: "POST", body: JSON.stringify(body) });
    }
    $("m-status").textContent = "";
    $("add-form").hidden = true;
    for (const id of ["m-summary", "m-notes", "m-tags", "m-place", "m-heard", "m-response-to", "m-audio", "m-lat", "m-lon"]) $(id).value = "";
    $("m-heard-confirm").checked = true;
    $("m-same-source").checked = false;
    $("m-loc-status").textContent = "";
    manualGeo.source = "manual";
    manualGeo.accuracy_m = null;
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
    const data = await api(`/api/diary/${encodeURIComponent(day)}`);
    $("d-digest").innerHTML = renderMarkdown(data.markdown);
  } catch (error) {
    $("d-digest").replaceChildren(el("p", "note", error.message));
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
        heard: $("d-heard").checked,
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
  const [data, accountability] = await Promise.all([
    api("/api/audit/consent"),
    api("/api/audit/accountability"),
  ]);
  $("accountability-totals").textContent = `${accountability.accountable} accountable · ${accountability.legacy} legacy · ${accountability.with_issues} with issues · ${accountability.with_route_decisions} with decisions · ${accountability.decision_only} decision only · ${accountability.plural_listenings} plural · ${accountability.ear_swarms} declared ear swarms · ${accountability.with_disagreement} with disagreement · ${accountability.revisions} revisions`;
  const accountabilityWrap = $("accountability-list");
  accountabilityWrap.replaceChildren();
  for (const item of accountability.items) {
    const row = el("div", "audit-row");
    const anchor = el("span", "link", item.summary);
    anchor.addEventListener("click", () => {
      document.querySelector('[data-tab="library"]').click();
      selectRecord(item.akousma_id);
    });
    row.append(el("span", `badge ${item.status === "issues" ? "blocked" : item.status === "accountable" ? "ok" : ""}`, item.status), anchor);
    if (item.listening_count) row.append(el("span", "note", `${item.listening_count} listening(s) · ${item.distinct_listener_count} listener(s)`));
    if (item.disagreement_count) row.append(el("span", "note", `≠ ${item.disagreement_count}`));
    if (item.route_decision_count) row.append(el("span", "note", `${item.route_decision_count} decision(s) · ${item.stop_decision_count} stop(s)`));
    if (item.decision_only) row.append(el("span", "badge", "decision only"));
    if (item.ensemble_kind) row.append(el("span", "badge", item.ensemble_kind.replaceAll("_", " ")));
    if (item.revision_of) row.append(el("span", "note", "revision"));
    for (const issue of item.issues || []) row.append(el("span", "badge blocked", issue));
    accountabilityWrap.append(row);
  }
  const receipts = $("forgetting-list");
  receipts.replaceChildren();
  $("forgetting-totals").textContent = `${accountability.forgetting_receipt_count} content-free receipt(s)`;
  for (const receipt of accountability.forgetting_receipts || []) {
    const row = el("div", "audit-row");
    row.append(
      el("span", "badge", "forgotten"),
      el("span", "link", receipt.akousma_id),
      el("span", "note", `${receipt.created_at} · ${receipt.actor} · ${receipt.reason}`),
      el("span", "note", receipt.audio_deleted ? "audio deleted" : receipt.shared_audio_preserved ? "shared audio preserved" : "record deleted"),
    );
    receipts.append(row);
  }
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

/* ── map (the listening map — where listenings happened) ─────────────────
   Hand-rolled Web-Mercator canvas, no map library: embedded Natural Earth
   coastlines by default, optional OSM raster tiles behind an explicit
   opt-in (the only remote call this app can make, and it is off by default). */

const MAP = {
  land: null, points: [], unlocated: 0,
  center: { x: 0.5, y: 0.42 },   // web-mercator unit coords
  zoom: 1.6,                      // world = 256 * 2^zoom px
  tiles: false, tileCache: new Map(), drawn: [],
  focus: null, raf: 0, booted: false, wired: false,
};

const mercX = (lon) => (lon + 180) / 360;
function mercY(lat) {
  const s = Math.min(0.9999, Math.max(-0.9999, Math.sin((lat * Math.PI) / 180)));
  return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
}
const worldSize = () => 256 * 2 ** MAP.zoom;

function scheduleMapDraw() {
  if (MAP.raf) return;
  MAP.raf = requestAnimationFrame(() => { MAP.raf = 0; drawMap(); });
}

async function loadMap() {
  if (!MAP.land) {
    try {
      const data = await (await fetch(appPath("/static/land-110m.json"))).json();
      MAP.land = data.rings || [];
    } catch { MAP.land = []; }
  }
  const data = await api("/api/map");
  MAP.points = data.points
    .filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon))
    .map((p) => ({ ...p, mx: mercX(p.lon), my: mercY(p.lat) }));
  MAP.unlocated = data.unlocated;
  $("map-status").textContent = `${data.located} located · ${data.unlocated} without location`;
  if (!MAP.wired) wireMap();
  if (MAP.focus) {
    MAP.center = { x: mercX(MAP.focus.lon), y: mercY(MAP.focus.lat) };
    MAP.zoom = Math.max(MAP.zoom, 12);
    MAP.focus = null;
  } else if (!MAP.booted) {
    fitMap();
  }
  MAP.booted = true;
  scheduleMapDraw();
}

function fitMap() {
  const w = $("map").parentElement.clientWidth || 800;
  const h = 560;
  if (!MAP.points.length) {
    MAP.center = { x: 0.5, y: 0.42 };
    MAP.zoom = Math.max(1.2, Math.log2(Math.max(1, w / 300)));
    return;
  }
  const xs = MAP.points.map((p) => p.mx);
  const ys = MAP.points.map((p) => p.my);
  MAP.center = { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: (Math.min(...ys) + Math.max(...ys)) / 2 };
  const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 1e-4);
  MAP.zoom = Math.min(13, Math.max(1.2, Math.log2((Math.min(w, h) * 0.55) / (256 * span))));
}

function wireMap() {
  MAP.wired = true;
  const canvas = $("map");
  let drag = null;
  canvas.addEventListener("pointerdown", (event) => {
    drag = { x: event.clientX, y: event.clientY, moved: false };
    try { canvas.setPointerCapture(event.pointerId); } catch {}
  });
  canvas.addEventListener("pointermove", (event) => {
    if (drag) {
      const dx = event.clientX - drag.x;
      const dy = event.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      MAP.center.x = (((MAP.center.x - dx / worldSize()) % 1) + 1) % 1;
      MAP.center.y = Math.min(1, Math.max(0, MAP.center.y - dy / worldSize()));
      drag.x = event.clientX;
      drag.y = event.clientY;
      $("map-tooltip").hidden = true;
      scheduleMapDraw();
    } else {
      hoverMap(event);
    }
  });
  canvas.addEventListener("pointerup", (event) => {
    const wasDrag = drag && drag.moved;
    drag = null;
    if (!wasDrag) clickMap(event);
  });
  canvas.addEventListener("pointercancel", () => { drag = null; });
  canvas.addEventListener("pointerleave", () => { $("map-tooltip").hidden = true; });
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoomMapAt(event, -event.deltaY * 0.0035);
  }, { passive: false });
  canvas.addEventListener("dblclick", (event) => zoomMapAt(event, 1));
  $("map-fit").addEventListener("click", () => { fitMap(); scheduleMapDraw(); });
  const tilesBox = $("map-tiles");
  MAP.tiles = localStorage.getItem("akousmata.map.tiles") === "1";
  tilesBox.checked = MAP.tiles;
  $("map-attrib").hidden = !MAP.tiles;
  tilesBox.addEventListener("change", () => {
    MAP.tiles = tilesBox.checked;
    localStorage.setItem("akousmata.map.tiles", MAP.tiles ? "1" : "0");
    $("map-attrib").hidden = !MAP.tiles;
    scheduleMapDraw();
  });
  window.addEventListener("resize", () => { if (state.tab === "map") scheduleMapDraw(); });
}

function eventMerc(event) {
  const rect = $("map").getBoundingClientRect();
  const px = event.clientX - rect.left;
  const py = event.clientY - rect.top;
  return {
    px, py,
    x: MAP.center.x + (px - rect.width / 2) / worldSize(),
    y: MAP.center.y + (py - rect.height / 2) / worldSize(),
  };
}

function zoomMapAt(event, delta) {
  const before = eventMerc(event);
  MAP.zoom = Math.min(17, Math.max(1.2, MAP.zoom + delta));
  const after = eventMerc(event);
  MAP.center.x = (((MAP.center.x + before.x - after.x) % 1) + 1) % 1;
  MAP.center.y = Math.min(1, Math.max(0, MAP.center.y + before.y - after.y));
  scheduleMapDraw();
}

function drawMap() {
  const canvas = $("map");
  const wrap = canvas.parentElement;
  const w = wrap.clientWidth;
  const h = 560;
  canvas.width = w * devicePixelRatio;
  canvas.height = h * devicePixelRatio;
  canvas.style.height = `${h}px`;
  const ctx = canvas.getContext("2d");
  ctx.scale(devicePixelRatio, devicePixelRatio);
  const size = worldSize();
  ctx.fillStyle = "#fdfdfc";
  ctx.fillRect(0, 0, w, h);
  if (MAP.tiles) drawTiles(ctx, w, h, size);
  else {
    drawGraticule(ctx, w, h, size);
    drawLand(ctx, w, h, size);
  }
  drawPoints(ctx, w, h, size);
}

const mapOffsets = (size, w) => (size > w * 2 ? [0] : [-size, 0, size]);

function drawLand(ctx, w, h, size) {
  if (!MAP.land || !MAP.land.length) return;
  for (const offset of mapOffsets(size, w)) {
    const path = new Path2D();
    for (const ring of MAP.land) {
      for (let i = 0; i < ring.length; i += 1) {
        const x = (mercX(ring[i][0]) - MAP.center.x) * size + w / 2 + offset;
        const y = (mercY(ring[i][1]) - MAP.center.y) * size + h / 2;
        if (i === 0) path.moveTo(x, y);
        else path.lineTo(x, y);
      }
      path.closePath();
    }
    ctx.fillStyle = "#efefeb";
    ctx.fill(path, "evenodd");
    ctx.strokeStyle = "#dcdcd6";
    ctx.lineWidth = 1;
    ctx.stroke(path);
  }
}

function drawGraticule(ctx, w, h, size) {
  ctx.strokeStyle = "#eeeeea";
  ctx.lineWidth = 1;
  for (const offset of mapOffsets(size, w)) {
    for (let lon = -180; lon < 180; lon += 30) {
      const x = (mercX(lon) - MAP.center.x) * size + w / 2 + offset;
      if (x < -2 || x > w + 2) continue;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    }
  }
  for (let lat = -60; lat <= 80; lat += 20) {
    const y = (mercY(lat) - MAP.center.y) * size + h / 2;
    if (y < -2 || y > h + 2) continue;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }
}

function drawTiles(ctx, w, h, size) {
  const z = Math.max(1, Math.min(19, Math.round(MAP.zoom)));
  const n = 2 ** z;
  const tilePx = size / n;
  const x0 = Math.floor((MAP.center.x - w / 2 / size) * n);
  const x1 = Math.floor((MAP.center.x + w / 2 / size) * n);
  const y0 = Math.max(0, Math.floor((MAP.center.y - h / 2 / size) * n));
  const y1 = Math.min(n - 1, Math.floor((MAP.center.y + h / 2 / size) * n));
  for (let tx = x0; tx <= x1; tx += 1) {
    for (let ty = y0; ty <= y1; ty += 1) {
      const img = mapTile(z, ((tx % n) + n) % n, ty);
      if (!img) continue;
      const sx = (tx / n - MAP.center.x) * size + w / 2;
      const sy = (ty / n - MAP.center.y) * size + h / 2;
      ctx.drawImage(img, sx, sy, tilePx + 0.5, tilePx + 0.5);
    }
  }
}

function mapTile(z, x, y) {
  const key = `${z}/${x}/${y}`;
  const cached = MAP.tileCache.get(key);
  if (cached) return cached.complete && cached.naturalWidth ? cached : null;
  if (MAP.tileCache.size > 300) MAP.tileCache.delete(MAP.tileCache.keys().next().value);
  const img = new Image();
  img.crossOrigin = "anonymous";
  img.onload = () => { if (state.tab === "map") scheduleMapDraw(); };
  img.src = `https://tile.openstreetmap.org/${z}/${x}/${y}.png`;
  MAP.tileCache.set(key, img);
  return null;
}

function drawPoints(ctx, w, h, size) {
  MAP.drawn = [];
  const cell = 36;
  const grid = new Map();
  for (const p of MAP.points) {
    let sx = (p.mx - MAP.center.x) * size + w / 2;
    sx -= Math.round((sx - w / 2) / size) * size; // nearest world copy
    const sy = (p.my - MAP.center.y) * size + h / 2;
    if (sx < -24 || sx > w + 24 || sy < -24 || sy > h + 24) continue;
    const key = `${Math.floor(sx / cell)}:${Math.floor(sy / cell)}`;
    const bucket = grid.get(key) || { xs: 0, ys: 0, items: [] };
    bucket.xs += sx;
    bucket.ys += sy;
    bucket.items.push(p);
    grid.set(key, bucket);
  }
  ctx.font = "11px -apple-system, sans-serif";
  for (const bucket of grid.values()) {
    const x = bucket.xs / bucket.items.length;
    const y = bucket.ys / bucket.items.length;
    if (bucket.items.length > 1) {
      const r = Math.min(17, 9 + bucket.items.length);
      ctx.beginPath(); ctx.arc(x, y, r + 3, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(169, 118, 47, 0.15)"; ctx.fill();
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = "#a9762f"; ctx.fill();
      ctx.fillStyle = "#fff";
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(String(bucket.items.length), x, y + 0.5);
      MAP.drawn.push({ x, y, r: r + 3, kind: "cluster", items: bucket.items });
    } else {
      const p = bucket.items[0];
      ctx.beginPath(); ctx.arc(x, y, 9, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(169, 118, 47, 0.14)"; ctx.fill();
      ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2);
      ctx.fillStyle = APP_COLORS[p.originating_app] || APP_COLORS.unknown; ctx.fill();
      if (p.akousma_id === state.selected) { ctx.strokeStyle = "#1d1d1b"; ctx.lineWidth = 2; ctx.stroke(); }
      MAP.drawn.push({ x, y, r: 11, kind: "point", p });
    }
  }
  ctx.textAlign = "start";
  ctx.textBaseline = "alphabetic";
}

function mapHit(event) {
  const rect = $("map").getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  let best = null;
  for (const item of MAP.drawn) {
    const d = Math.hypot(item.x - x, item.y - y);
    if (d <= item.r + 2 && (!best || d < best.d)) best = { ...item, d };
  }
  return best;
}

function hoverMap(event) {
  const hit = mapHit(event);
  const tip = $("map-tooltip");
  $("map").style.cursor = hit ? "pointer" : "grab";
  if (!hit) { tip.hidden = true; return; }
  tip.replaceChildren();
  if (hit.kind === "cluster") {
    tip.append(el("div", "", `${hit.items.length} memories here — click to get closer`));
    for (const p of hit.items.slice(0, 4)) tip.append(el("div", "note", (p.summary || p.akousma_id).slice(0, 60)));
    if (hit.items.length > 4) tip.append(el("div", "note", `… ${hit.items.length - 4} more`));
  } else {
    tip.append(el("div", "", (hit.p.summary || hit.p.akousma_id).slice(0, 90)));
    const meta = [
      hit.p.label,
      (hit.p.created_at || "").slice(0, 10),
      hit.p.originating_app,
      hit.p.direction ? `${hit.p.direction} listen` : null,
    ].filter(Boolean).join(" · ");
    if (meta) tip.append(el("div", "note", meta));
  }
  const rect = $("map").getBoundingClientRect();
  tip.style.left = `${Math.min(event.clientX - rect.left + 14, rect.width - 220)}px`;
  tip.style.top = `${event.clientY - rect.top + 10}px`;
  tip.hidden = false;
}

function clickMap(event) {
  const hit = mapHit(event);
  if (!hit) return;
  if (hit.kind === "cluster") {
    MAP.center = {
      x: hit.items.reduce((sum, p) => sum + p.mx, 0) / hit.items.length,
      y: hit.items.reduce((sum, p) => sum + p.my, 0) / hit.items.length,
    };
    MAP.zoom = Math.min(17, MAP.zoom + 1.8);
    scheduleMapDraw();
  } else {
    document.querySelector('[data-tab="library"]').click();
    selectRecord(hit.p.akousma_id);
  }
}

/* ── wiki ─────────────────────────────────────────────────────────────── */

function renderMarkdown(markdown) {
  const escape = (s) => s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
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
    $("wiki-body").replaceChildren(el("p", "note", "no " + kind + " page for " + name + " yet — " + error.message));
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
  const profile = data.human_profile || {};
  $("s-listener-id").value = profile.listener_id || "";
  $("s-display-name").value = profile.display_name || "";
  $("s-profile-privacy").value = profile.privacy || "private";
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
    human_profile: {
      display_name: $("s-display-name").value.trim(),
      privacy: $("s-profile-privacy").value,
    },
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
    if (state.tab === "map") loadMap();
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
