# akousmata — the listening navigator

Centaur workspace launches set an immutable workspace ID and process generation.
`GET /owner/identity` reads that binding without opening or migrating the store;
writes require matching workspace, generation and store fingerprint headers. The
listen-again bridge verifies Oída's identity before forwarding work. Standalone
launches without these variables report explicit legacy mode.

**akousma** (ἄκουσμα, "a thing heard"; plural **akousmata**) — one sound's
memory. **Earworm is the protocol, the akousma is the shared record, the
akousmata is the whole library**: a network of listened things and their
relations. This app is how you walk it — navigating sonic memories, not audio
files.

The akousmata stores what agents listen (oída's ears, algophony's
evaluations, germ's cultivations) **and what you listen**. Human and machine
accounts remain separate records in the same library, with each listener
declared and typed links between accounts when warranted.
Every memory carries provenance and causal lineage ("made from") plus typed
kinship ("belongs with"): variants, recurrences, series, responses. A heard
memory carries attributable listenings; a gate that closed before hearing can
instead carry a decision-only auditum without pretending that sound occurred.

Source version: `0.8.3`, an unpublished local package candidate.

## What it is

A local-first library app over the shared akousmata store. It loads **no
models and runs no agents** — it is the quiet room of the Listening Stack:

- **Library** — filter by app, origin, tag, text, time, exact listener type,
  and derived record class; play resolvable audio; curate tags, notes, and
  location separately from listening accounts; add human listenings (heard
  live or from a file, which is content-addressed into the store); forget with a
  content-free durable receipt that leaves absence visible without retaining
  the forgotten description.
- **Human listening lifecycle** — one stable identifier in ignored local
  settings owns human records. Only the unique current head of an owned human
  account can be edited, and saving creates a new attributable revision rather
  than rewriting history. Notes do not imply hearing: hearing is an explicit
  self-attestation. A human record may `response_to` a machine listening;
  `same_source_as` additionally requires explicit source verification.
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
- **Public projections** — explicit local grants select shareable metadata;
  public pages and counts include only current approved projections. Export
  packs reuse the same allowlist. [Integration and limits](docs/public-projections.md).
- **Covenants (spec v1.3)** — records made under a listening covenant say so:
  the detail pane shows under which ethics a sound was listened (the
  covenant's identity and lineage, the rules that acted, what was withheld —
  counted and attributed, never described — and the commitments it carries),
  and one click filters the library to everything heard under that covenant.
  The navigator displays sovereignty; it never edits it.
- **Accountable auditums (spec v1.6)** — cards, detail pages, the wiki, graph,
  and Audit view expose each attributable listener and route, temporal-pass
  and provenance references, preserved disagreement, honest absences, action
  authority, route decisions, receipts, and revisions. A refusal before
  hearing is rendered as a decision-only memory with no audio or acoustic
  claim. Legacy v1.x records remain valid and are named as legacy, not
  defective.
- **Plural listening and declared ear swarms** — several listeners stay
  distinct by default. The navigator uses “ear swarm” only for an explicit
  ensemble that records influence, preserved permissions and disagreements,
  and a dissolution rule; listener count alone never manufactures consensus.
- **Listen again** — a record with resolvable audio can make a fresh pass
  through the Oída gateway; the new claims, routes, apparatus, and summary are
  filed as a new revision record that points to the earlier hearing. Re-listening
  never silently overwrites or mutates the account it revises.
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
- **Optional GERM handoff** — configure a local GERM URL to send a memory as
  sound, prompt, or lineage. With no URL configured, the library has no GERM
  dependency and shows no handoff controls.
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
| [Earworm](https://github.com/sonicfieldlabs/earworm) | `akousma >=0.8.4` / spec v1.8 | Canonical store with checked object resolution, no-audio listening accounts, listener-type/class indexes, and additive revision chains. |
| [AKOÚŌ](https://github.com/sonicfieldlabs/akouo) | `akouo/v0.9` | Owns claim taxonomy, provenance, temporal passes, route decisions, corpus disclosure, and situated context rendered by the navigator. |
| [OÍDA](https://github.com/sonicfieldlabs/oida) | 0.11.0 / `oida/gateway/v0.6` | Writes typed machine and human listening records, links related accounts, and embeds the navigator at `/library/`. |
| [GERM](https://github.com/sonicfieldlabs/germ) | 0.3.3 (optional) | Receives explicit sound, prompt, and lineage handoffs when separately configured. |
| [Algophony](https://github.com/sonicfieldlabs/algophony) | 0.5.2 | Adds batch evaluation stamps and comparison relations. |
| [ORAM](https://github.com/sonicfieldlabs/oram) | 0.4.1 | ORAM exports can enter the store through OÍDA or another akousma producer; ORAM is not a direct store writer. |

## Run

```sh
pip install --find-links vendor -e .  # reviewed local candidate dependencies
akousmata          # http://127.0.0.1:5180
```

Installing Oída installs and mounts this navigator at `/library/`; standalone
mode remains useful for library-only work. In the Sonic Field monorepo the
canonical sibling packages are editable. Tests: `uv run pytest -q`.

## Owner access and settings

The owner app defaults to loopback access. It accepts `localhost`, `127.0.0.1`
and `::1` hosts, rejects foreign origins on mutations, and preserves the
workspace binding checks. Local command-line clients may omit Origin.
Forwarded headers are rejected; proxy header interpretation is disabled.
Mounting the full app retains these owner controls. The separate read-only
`public_router` serves only approved projections.

Non-loopback startup requires both `AKOUSMATA_ACCESS_TOKEN` (at least 32
characters) and `AKOUSMATA_ALLOWED_HOSTS` (comma-separated exact hostnames
without ports). In this mode every owner request requires
`Authorization: Bearer <token>`, including reads and static assets. This is an
integration mode for authenticated clients or a TLS gateway that supplies the
authorization header and strips forwarded headers; the standalone UI does not
manage tokens. An unauthenticated non-loopback bind is refused.

Settings patches are typed and validated before saving. Watcher intervals must
be finite: ingestion accepts 0.1 to 86,400 seconds and lint accepts 0.01 to
1,440 minutes. Saves preserve omitted fields, serialize concurrent writers,
and atomically replace `settings.json` with owner-only POSIX permissions.
Malformed existing fields fall back to defaults without discarding other valid
fields. Masked provider keys returned by the UI preserve the stored key when
round-tripped; a local OpenAI-compatible provider can operate without an API key.

## The stack around it

- **oída** listens and remembers (and embeds this library view as its
  history); optional **GERM** can cultivate remembered sounds into new ones; **algophony**
  evaluates batches and stamps results back onto records; **AKOÚŌ** defines
  how everything listens. The akousmata is where all of it — and you —
  keep one shared memory.

## What does not exist yet

- **A coordinated new package release.** The 0.8.3 package candidate and its
  repaired owner dependencies are prepared locally. A public release is separate.
- **Multiple owners or account management.** The navigator serves one owner.
  Optional bearer admission authenticates access to that owner's full app.
  Only `public_router` is meant for publishing selected projections on another
  host, and it has three read-only `/api/public` routes
  ([public projections](docs/public-projections.md)).
- **A listening model or an agent.** It runs neither. The one model it can use, CLAP for acoustic
  retrieval, is optional and runs in a separate offline process. Without it, memory and every other
  workflow still work ([acoustic retrieval](docs/acoustic-retrieval.md)).
- **Audio in a transfer.** A bundle carries records and their original audio locators. It does not
  copy external audio or claim that the audio becomes available
  ([bundles and score](docs/bundles-and-score.md)).

## License

MIT. The store data is yours and never part of the repository.

Receiving claims with an Earworm listening-context validity declaration are checked
again for every new export and public read. Unknown, future or expired currency
is withheld from current projections. Retention-review dates do not delete the
canonical historical record or extend claim validity. Existing local export
archives remain historical copies, not continuously refreshed views.

[Listening relationships](docs/listening-relations.md) documents the owner view of
independent passes, second reports, additive responses and retained influence traces.

[Producer evidence and additive correction](docs/producer-evidence.md) defines the
boundary between human responses, library curation, research review and authorized
forgetting.

[Canonical research proposals and relation metadata](docs/research-proposals.md)
reuse the existing index, research sessions and scheduled watcher with additive
reviews, durable retry/cancellation and explicit evidence-ancestry accounting.

[Qualified facets and access views](docs/access-facets.md) expose subject/recipient,
matter register/scale and declared human access, with the full listener taxonomy.

The Graph tab provides walkable retained lineage and explicit local captures with
cursor pagination and replay. See [graph history](docs/graph-history.md) for privacy,
bounds and the distinction between saved captures and continuous event history.

D5 adds [verified owner bundles and score projections](docs/bundles-and-score.md)
through the existing export, canonical record and graph-history services.
