# akousmata API

Local endpoints (default http://127.0.0.1:5180, env `AKOUSMATA_PORT`/`AKOUSMATA_HOST`):

- `GET /api/health` — store path, totals by app/origin, latest timestamp.
- `GET /api/records` — filters: `app_filter`, `origin`, `source_type`, `tag`, `text`, `since`, `until`, `covenant`, `accountable`, `disagreement`, `route_decision`, `stop_decision`, `limit`. Cards include covenant identity plus listening, ensemble, disagreement, absence, action, decision, stop, decision-only, and revision summaries.
- `POST /api/records` — manual memory without audio: `{summary, notes?, tags?, place?, heard_at?, kind, parent_akousma_ids?, relations?, location?}`. `location` is spec-v1.2 `{lat, lon, accuracy_m?, altitude_m?, label?, source?, captured_at?}`; `place` doubles as its label when none is given.
- `POST /api/records/import` — the same manual-memory object as JSON in multipart field `metadata`, plus an `audio` file (100 MB maximum). The server copies bytes into the content-addressed store; it never accepts a server-side filesystem path.
- `GET /api/records/{id}` — full record + parents/children/kinship + audio availability. Unknown top-level fields (spec v1.2 open records) come through verbatim and render in the UI's "more details" section.
- `PATCH /api/records/{id}` — guarded edit: `tags`, `annotations`, `summary`, `location` only (`location: {}` clears; location is listener-annotatable per spec v1.2).
- `POST /api/records/{id}/relations` / `DELETE …/relations?type=&target_akousma_id=` — typed kinship.
- `POST /api/records/{id}/forget` — `{delete_audio?, actor?, reason?}`; returns an `earworm/forgetting-receipt/v1`. Inbound edges remain as absence and the receipt carries no forgotten content.
- `GET /api/forgetting-receipts?akousma_id=` — content-free durable receipts, newest first. A receipt prevents silent resurrection under the same id.
- `GET /api/audio/{id}` — stream resolvable audio.
- `GET /api/tags` — distinct tags with counts.
- `GET /api/graph` — whole library (`limit`) or `focus=<id>&depth=` neighborhood; edges carry `kind` (lineage|relation) and `type`.
- `GET /api/map` — the listening map's feed: `{points: [{akousma_id, lat, lon, label, accuracy_m, summary, created_at, originating_app, tags, direction, has_audio}], located, unlocated, total}`. Points are where listenings happened, not where sounds live.
- `GET/POST/PATCH/DELETE /api/constellations…` — ordered saved selections and playable resolution with missing-member absences.
- `GET /api/timeline?bucket=day|month|season|year` — temporal buckets plus recurrence rhythms.
- `GET /api/records/{id}/similar` — tagged/textual, DSP-feature, and optional stored-local-embedding kinship with explicit score bases.
- `POST /api/diary` / `GET /api/diary/{day}` — quick capture (`{text, tags?, place?, location?}`) and maintained daily digest.
- `GET /api/audit/accountability` — accountable/legacy coverage, route and stop decisions, decision-only records, plural-listening and explicitly declared ear-swarm counts, forgetting receipts, disagreement/revision coverage, and attributable structural issues. It audits record shape; it does not adjudicate claims.
- `GET /api/audit/consent` / `POST /api/records/{id}/consent` — consent, rights notes, capture conditions, and exportability.
- `POST /api/export` / `GET /api/exports` — sanitized selection packs with wiki/audio files, exclusions, consent gate, and manifest.
- `POST /api/records/{id}/listen-again` — fresh Oída gateway pass filed as a new akousma v1.5 revision with pass/provenance/decision references, `same_source_as` kinship, and `auditum.revision.revises_akousma_id`. The source record is not mutated; a pre-listening refusal is returned as a route outcome and never converted into a hearing.
- `GET /api/germ-link/{id}?mode=sound|prompt|lineage` — optional GERM deep link; returns 409 until a URL is explicitly configured.
- `GET /api/wiki` · `GET /api/wiki/page/{kind}/{name}` · `POST /api/wiki/rebuild` · `POST /api/wiki/ingest/{id}` · `GET /api/wiki/lint`.
- `POST /api/research` — `{question, seed_ids?, tags?, max_steps?}` → `{session_id}`; `GET /api/research` lists sessions; `GET /api/research/{id}/events` streams SSE progress.
- `GET /api/events` — SSE store watch (new records).
- `GET /api/watcher` / `POST /api/watcher/run` — scheduled-maintenance status and immediate reconciliation/lint.
- `GET/PUT /api/settings` — germ/oída URLs, watcher intervals, and BYOK LLM config (key masked in reads; stored only in local settings.json).
