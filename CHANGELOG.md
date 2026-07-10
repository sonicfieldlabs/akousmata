# Changelog

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
