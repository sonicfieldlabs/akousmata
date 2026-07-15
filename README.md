# akousmata — the listening navigator

**akousma** (ἄκουσμα, "a thing heard"; plural **akousmata**) — one sound's
memory. **Earworm is the protocol, the akousma is the shared record, the
akousmata is the whole library**: a network of listened things and their
relations. This app is how you walk it — navigating sonic memories, not audio
files.

The akousmata stores what agents listen (oída's ears, algophony's
evaluations, germ's cultivations) **and what you listen**: manual
human listening events live in the same library, with the listener declared.
Every memory carries provenance, structured listenings, causal lineage
("made from") and typed kinship ("belongs with"): variants, recurrences,
series, responses.

Current release: `0.4.0`.

## What it is

A local-first library app over the shared akousmata store. It loads **no
models and runs no agents** — it is the quiet room of the Listening Stack:

- **Library** — filter by app, origin, tag, text, time; play resolvable
  audio; edit tags, notes, and summaries; add manual memories (heard live or
  from a file, which is content-addressed into the store); forget (removal
  that leaves honest absence).
- **Graph** — the memory system as a navigable graph: solid edges are
  lineage, dashed edges are kinship, colors are originating apps.
- **Map** — the listening map: where listenings happened, not where sounds
  live. A hand-rolled Web-Mercator canvas (embedded Natural Earth coastlines,
  no map library) with clustering and click-through to the library; an OSM
  street-tile layer exists behind an explicit opt-in and is the only remote
  call the UI can make. Locations are consent-scoped (spec v1.2), editable
  from each record's "place" section, and always stripped from export packs.
- **Constellations** — saved, ordered graph selections that remain playable
  as soundwalks; forgotten members stay visible as meaningful absences.
- **Timeline** — day, month, calendar-season, and year views plus weekday/hour
  recurrence rhythms. Calendar seasons are organizational labels, never
  ecological claims.
- **Kin search** — accountable similarity from tags, description overlap,
  duration, stored DSP features, and optional already-computed local
  embeddings. The navigator never calls a remote embedding service.
- **Listening diary** — quick human capture with one maintained wiki digest
  per day.
- **Consent and export** — an audit of consent, rights notes, and capture
  conditions; restricted or unknown records are blocked from sanitized,
  manifest-bearing research packs.
- **Covenants (spec v1.3)** — records made under a listening covenant say so:
  the detail pane shows under which ethics a sound was listened (the
  covenant's identity and lineage, the rules that acted, what was withheld —
  counted and attributed, never described — and the commitments it carries),
  and one click filters the library to everything heard under that covenant.
  The navigator displays sovereignty; it never edits it.
- **Listen again** — a record with resolvable audio can make a fresh pass
  through the Oída gateway; the new claims, routes, apparatus, and summary are
  filed as another listening entry on the same akousma.
- **Wiki** — an LLM-wiki (after Karpathy's llm-wiki pattern) forked into
  sonic memories: a maintained markdown layer over the records with one page
  per memory, per tag, plus topic syntheses; `index.md` catalog, `log.md`
  journal, and a lint pass for drift (dangling links, orphan pages, store
  integrity). Deterministic by default; see
  [`docs/concept.md`](docs/concept.md) and
  [`docs/wiki-conventions.md`](docs/wiki-conventions.md).
- **Research** — ask the library a question. Without an LLM it produces a
  deterministic traversal report (the graph already answers recurrence and
  kinship questions); with a BYOK provider it runs a bounded research loop
  and files the answer back as a topic page, so answers compound.
- **BYOK LLM** — optional: any OpenAI-compatible endpoint (OpenAI, xAI/Grok,
  OpenRouter, Ollama, llama.cpp), Anthropic, or a **local CLI agent**
  (codex, opencode — the prompt goes to stdin, nothing leaves your machine).
  Keys live in your local `settings.json`, never in the repo. CLI commands are
  parsed as an executable and arguments; use a wrapper script if you need shell
  pipelines or redirection.
- **Germ handoff** — send any memory into germ as sound, prompt, or lineage
  (the same three buttons oída uses), turning listened things into sounding
  things.
- **Realtime** — the navigator watches the store; memories written by oída
  or germ appear as they happen.
- **Durable maintenance watcher** — immediately reconciles records created
  while the app was offline, persists a tie-safe cursor, refreshes diary
  digests, and runs scheduled lint. Intervals are live-editable in Settings.

## The store

By default the store data lives in the platform application-data directory
and is **never tracked**: `index.sqlite`, `objects/` (content-addressed
audio), `wiki/` (the maintained layer), and `settings.json`. Set
`AKOUSMATA_PATH` when the Listening Stack should share another location. The store API is
[`earworm/packages/py-akousma`](https://github.com/sonicfieldlabs/earworm)
(spec: `earworm/docs/akousma_spec_v1.md`) — this app is a navigator over
that protocol, not a fork of it.

## Listening Stack compatibility

| Component | Version / contract | Relationship |
| --- | --- | --- |
| [Earworm](https://github.com/sonicfieldlabs/earworm) | `akousma 0.4.0` / spec v1.3 | Canonical store, lineage, kinship, location/capture, and covenant record. |
| [AKOÚŌ](https://github.com/sonicfieldlabs/akouo) | `akouo/v0.7` | Claim taxonomy, apparatus, routing, memory-lineage listening, and covenants rendered by the navigator. |
| [OÍDA](https://github.com/sonicfieldlabs/oida) | 0.6.0 / `oida/gateway/v0.2` | Writes and re-listens to records; embeds the complete navigator at `/library/`. |
| [GERM](https://github.com/sonicfieldlabs/germ) | 0.2.0 | Receives sound, prompt, and lineage handoffs and writes cultivated children. |
| [Algophony](https://github.com/sonicfieldlabs/algophony) | 0.5.0 | Adds batch evaluation stamps and comparison relations. |
| [ORAM](https://github.com/sonicfieldlabs/oram) | 0.4.0 | ORAM exports can enter the store through OÍDA or another akousma producer; ORAM is not a direct store writer. |

## Run

```sh
pip install -e .   # installs the canonical akousma dependency too
akousmata          # http://127.0.0.1:5180
```

Installing Oída installs and mounts this navigator at `/library/`; standalone
mode remains useful for library-only work. In the Sonic Field monorepo the
canonical sibling packages are editable. Tests: `uv run pytest -q`.

## The stack around it

- **oída** listens and remembers (and embeds this library view as its
  history); **germ** cultivates remembered sounds into new ones; **algophony**
  evaluates batches and stamps results back onto records; **AKOÚŌ** defines
  how everything listens. The akousmata is where all of it — and you —
  keep one shared memory.

## License

MIT. The store data is yours and never part of the repository.
