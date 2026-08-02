# The akousmata as an LLM-wiki — concept

This app adapts the llm-wiki / auto-research pattern (Karpathy,
gist `442a6bf5…`) from text sources to sonic memories. The pattern's insight:
instead of re-retrieving and re-synthesizing on every question (RAG), an
agent maintains a **persistent, compounding artifact** — a wiki — whose
maintenance an LLM does not tire of. Answers become pages; pages cite pages;
by the hundredth ingest the wiki answers questions no single source ever
addressed.

## The three layers, sonified

| llm-wiki layer | akousmata equivalent |
| --- | --- |
| **Raw sources** (immutable documents) | **Akousma records + audio objects.** Producers own them (oída, germ, algophony, human entries). The wiki reads, never rewrites: producer discipline is the immutability. |
| **Wiki layer** (agent-maintained markdown) | `<store>/wiki/`: one page per record, per tag, plus **topic pages** (research syntheses) — with `index.md` as the catalog and `log.md` as the append-only journal. Record/tag pages are deterministic derivations and regenerate; topic pages are synthesis and persist. |
| **Schema layer** (conventions file) | [`docs/wiki-conventions.md`](wiki-conventions.md): layout, wikilink forms, operations, and producer discipline. |

## The three operations

- **Ingest** — a memory arrives (an oída listen, a germ cultivation, a
  manual entry): its record page regenerates, its tag pages regenerate, the
  index updates, `log.md` gets a line. One ingest touches many pages —
  exactly the bookkeeping humans abandon and agents don't.
- **Query** — research sessions. The question gathers a corpus (seeds, tags,
  text search, one hop of lineage and kinship), then either produces a
  deterministic traversal report (no LLM: the graph itself answers
  recurrence/kinship/provenance questions) or runs a bounded BYOK loop —
  notes per step, following `[[record:id]]` requests the model makes — and
  files the synthesis as a **topic page**. Answers compound instead of
  evaporating into chat history.
- **Lint** — drift prevention, without which the pattern dies: store
  integrity (`verify()`: dangling parents/relations, missing audio, invalid
  records — absence reported, never erased), missing/orphan pages, dangling
  wikilinks. Run it often; the navigator exposes it as one button and one
  endpoint.

## What is different from the text version

- **The links were already there.** Sonic memories arrive with causal
  lineage and typed kinship (Earworm spec v1.1); the wiki does not have to
  invent cross-references, it renders and extends a graph the stack already
  maintains. The Memex quality — connections as valuable as documents — is
  native here.
- **Grounding is enforced by contract.** Listening entries carry their
  contract pins (`akouo/v0.9`, `akousmata/v0.6`, `oida/gateway/v0.5`); claims carry sources and
  time anchors upstream. The wiki inherits the stack's epistemic discipline
  instead of hoping for it.
- **Plurality is not a summary operation.** Akousma v1.5 auditums keep every
  listener and route attributable, and the wiki renders disagreement as
  several positions rather than smoothing it into one voice. Honest absence,
  route decisions, action authority, and re-listening revision are equally
  explicit. Several listeners are plural listening; “ear swarm” is reserved
  for an explicit ensemble with influence, permission, disagreement, and
  dissolution declarations.
- **Coded silence is not an empty record.** A refusal before capture can enter
  the library as a decision-only auditum: subject, attributed absence, route
  decision, and receipt, with no audio or invented acoustic claim. Forgetting
  similarly leaves a content-free receipt without reconstructing what was
  removed.
- **The navigator is also for humans without any LLM.** Library, graph,
  wiki, and deterministic research all work with zero keys. BYOK deepens;
  it never gates.

## Auto-research, bounded

A session = gather → (steps × think/follow) → synthesize → file. Steps are
capped, every event is logged and streamed, the result is a topic page with
inline `[[record:…]]` citations, a "what remains undetermined" section, and
suggested next listenings. Sessions are visible in `wiki/research/` and the
journal — reproducible navigation, not oracle magic.
