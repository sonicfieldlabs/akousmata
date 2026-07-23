# Changelog

## 0.5.0 — The Accountable Library

- Added first-class akousma v1.4 auditum rendering: attributable listening
  routes, preserved disagreement, honest absence, scoped action authority and
  receipts, and revision lineage.
- Added `GET /api/audit/accountability`, card summaries, accountable and
  disagreement filters, health counts, wiki sections, and graph metadata.
- Manual human memories now declare an attributable auditum and explicitly
  record when raw audio was not retained.
- Changed “listen again” from mutation-in-place to a new `same_source_as`
  revision record. The earlier hearing remains intact.
- Kept legacy v1.x records valid and visibly named as legacy rather than
  treating missing newer fields as an error.
- Contract `akousmata/v0.5`; store floor raised to `akousma >= 0.5.0`.

## 0.4.0 — Under Which Ethics

- **Covenant rendering (spec v1.3)**: records made under a listening covenant
  (AKOÚŌ v0.7's sovereignty layer) show it in a new detail section — the
  covenant's name, contract, lineage (`extends`), the rules that acted, what
  was withheld (counted and attributed to its rule, never described), and how
  many commitments the covenant carries. The block is producer-owned: the
  navigator renders and filters by it, never edits it.
- **Covenant filtering**: `GET /api/records?covenant=<id>` and a library
  filter chip — "everything listened under this covenant" is one click from
  any record; cards carry `covenant_id` and a ☖ marker.
- Withholding is displayed as honest absence, kept visually distinct from
  `undetermined`; unknown top-level fields continue to render in "more
  details" (the covenant block itself is now a known field).
- Exports: the covenant block travels — it contains identity, counts, and
  rule names by construction, never withheld content or the covenant's text.
- Contract `akousmata/v0.4`; store floor raised to `py-akousma >= 0.4.0`;
  29 hermetic tests.

## 0.3.0 — The Listening Map

- **Map view**: a hand-rolled Web-Mercator canvas (no map library) plotting
  where listenings happened — embedded Natural Earth 110m coastlines by
  default, pan/zoom/cluster/click-through to the library, and an **opt-in**
  OSM street-tile layer (off by default; the only remote call the UI can
  make, and it says so).
- **Geolocation (spec v1.2)**: records carry an optional consent-scoped
  `location {lat, lon, accuracy_m, altitude_m, label, source, captured_at}`.
  Manual memories and diary entries can attach it ("use my location" or
  typed coordinates); any record can be geotagged, corrected, or cleared
  from its new "place" section — location is listener-annotatable.
- **Capture rendering (spec v1.2)**: the `capture` block (direction
  past/future/live · window seconds · trigger) shows in the detail pane;
  the capturing app's account is displayed, never edited here.
- **Open records (spec v1.2)**: unknown top-level fields are preserved and
  rendered in a "more details" section instead of being invisible.
- **Privacy**: export packs strip `location` unconditionally — where someone
  listens is as sensitive as what they heard.
- **Performance**: kin-by-resemblance now scores against a cached corpus
  (invalidated on any store write) instead of re-parsing every record per
  detail open; the SSE change feed holds one store connection per subscriber
  instead of reconnecting every poll; `store.tags()` and `created_at`
  ordering ride the new py-akousma 0.3 fast paths.
- New endpoint `GET /api/map`; record cards gain `has_location`; store floor
  raised to `py-akousma >= 0.3.0`; 28 hermetic tests.

## 0.2.0 — Living with the Library

- **Constellations**: saved, ordered selections of memories playable as
  soundwalks; a forgotten member stays visible as honest absence.
- **Timeline of listening**: day/month/season/year buckets plus weekday and
  hour recurrence (season labels are meteorological conventions, not
  ecological claims).
- **Kin-search**: accountable resemblance per record from shared tags,
  description tokens, duration, stored DSP features, and already-computed
  local embeddings — every score carries its basis; no remote embedder is
  ever called.
- **Listening diary**: daily digests written into the wiki's diary layer.
- **Consent audit + export packs**: a consent overview, per-record consent
  updates, and sanitized exports (owned/licensed/public-domain only; local
  paths and secret keys stripped).
- **Listen-again**: send any record back through the Oída gateway
  (`oida/gateway/v0.2`) and file the fresh hearing as a new navigator-owned
  listening entry beside the old one.
- **Durable watcher**: persisted tie-safe cursor (via py-akousma
  `changed_since(after_id=…)`), offline-created records reconciled, diary
  digests refreshed, scheduled lint, live-editable intervals.
- Store floor raised to `py-akousma >= 0.2.2`; test suite grown to 25
  hermetic tests.

## 0.1.0 — The Listening Navigator (initial release)

- Local-first FastAPI app + vanilla static UI (oída's aesthetic) over the
  shared akousmata store: library with filters (app/origin/tag/text/time),
  audio playback, tag/note/summary editing, typed kinship editing, manual
  human listening events (heard-live or file, content-addressed), and forget
  with honest absence.
- Graph view: lineage (solid) + kinship (dashed) over the whole library or a
  memory's neighborhood.
- Wiki layer (llm-wiki pattern forked into sonic memories): deterministic
  record/tag pages, persistent topic pages, index.md catalog, log.md
  journal, ingest/rebuild/lint operations with store integrity via
  py-akousma verify().
- Auto-research sessions: deterministic traversal reports without any LLM;
  bounded BYOK research loops (OpenAI-compatible, Anthropic, or a local CLI
  agent via stdin) that file topic pages back into the wiki. SSE progress.
- Germ handoff links (sound / prompt / lineage) and a realtime store watch
  (SSE) so memories written by oída or germ appear as they happen.
- Requires earworm/packages/py-akousma >= 0.2.1 (tags, changed_since,
  forget).
