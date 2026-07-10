# Changelog

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
