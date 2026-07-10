# akousmata API

Local endpoints (default http://127.0.0.1:5180, env `AKOUSMATA_PORT`/`AKOUSMATA_HOST`):

- `GET /api/health` — store path, totals by app/origin, latest timestamp.
- `GET /api/records` — filters: `app_filter`, `origin`, `source_type`, `tag`, `text`, `since`, `until`, `limit`. Returns compact cards.
- `POST /api/records` — manual memory: `{summary, notes?, tags?, place?, heard_at?, kind, audio_path?, parent_akousma_ids?, relations?}`.
- `GET /api/records/{id}` — full record + parents/children/kinship + audio availability.
- `PATCH /api/records/{id}` — guarded edit: `tags`, `annotations`, `summary` only.
- `POST /api/records/{id}/relations` / `DELETE …/relations?type=&target_akousma_id=` — typed kinship.
- `POST /api/records/{id}/forget` — `{delete_audio?}`; inbound edges remain as absence.
- `GET /api/audio/{id}` — stream resolvable audio.
- `GET /api/tags` — distinct tags with counts.
- `GET /api/graph` — whole library (`limit`) or `focus=<id>&depth=` neighborhood; edges carry `kind` (lineage|relation) and `type`.
- `GET/POST/PATCH/DELETE /api/constellations…` — ordered saved selections and playable resolution with missing-member absences.
- `GET /api/timeline?bucket=day|month|season|year` — temporal buckets plus recurrence rhythms.
- `GET /api/records/{id}/similar` — tagged/textual, DSP-feature, and optional stored-local-embedding kinship with explicit score bases.
- `POST /api/diary` / `GET /api/diary/{day}` — quick capture and maintained daily digest.
- `GET /api/audit/consent` / `POST /api/records/{id}/consent` — consent, rights notes, capture conditions, and exportability.
- `POST /api/export` / `GET /api/exports` — sanitized selection packs with wiki/audio files, exclusions, consent gate, and manifest.
- `POST /api/records/{id}/listen-again` — fresh Oída gateway pass filed under a new navigator-owned `akousmata.listen_again*` entry on the same record; the embedded Oída source contract remains pinned in its payload.
- `GET /api/germ-link/{id}?mode=sound|prompt|lineage` — germ deep link.
- `GET /api/wiki` · `GET /api/wiki/page/{kind}/{name}` · `POST /api/wiki/rebuild` · `POST /api/wiki/ingest/{id}` · `GET /api/wiki/lint`.
- `POST /api/research` — `{question, seed_ids?, tags?, max_steps?}` → `{session_id}`; `GET /api/research` lists sessions; `GET /api/research/{id}/events` streams SSE progress.
- `GET /api/events` — SSE store watch (new records).
- `GET /api/watcher` / `POST /api/watcher/run` — scheduled-maintenance status and immediate reconciliation/lint.
- `GET/PUT /api/settings` — germ/oída URLs, watcher intervals, and BYOK LLM config (key masked in reads; stored only in local settings.json).
