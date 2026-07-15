# Wiki and producer conventions

Akousmata maintains a local wiki over an Earworm-compatible akousma store.
These conventions keep that wiki reproducible without allowing the navigator
to overwrite records owned by another producer.

## Data boundary

The store is personal runtime data, not repository content. Its
`index.sqlite`, `objects/`, `wiki/`, `settings.json`, and `exports/` paths must
remain untracked. The navigator creates and maintains those paths at runtime.

Akousmata may update tags, annotations, the top-level summary and location,
the `human.*` and `akousmata.*` listening namespaces, and
`extensions["akousmata.app"]`. It does not rewrite another producer's
listening block, the capture description, or a listening covenant. Withheld
material stays an attributed absence and is never reconstructed.

Location is consent-scoped: exports always remove it, and the optional map
layer is disabled by default. Provider credentials remain in the local store
settings and are never written to exported records or logs.

## Wiki layout

The wiki lives below `<store>/wiki/`:

```text
records/<akousma_id>.md  deterministic record pages
tags/<slug>.md           deterministic tag pages
topics/<slug>.md         persistent research syntheses
research/                bounded research-session logs
index.md                 generated catalog
log.md                   append-only operations journal
```

Wikilinks use `[[record:<akousma_id>]]`, `[[tag:<slug>]]`, and
`[[topic:<slug>]]`; an optional label uses `[[kind:name|label]]`.

Record and tag pages are derived from the store and may be regenerated. Topic
pages are synthesis and survive rebuilds. Journal entries use:

```text
## [ISO-time] operation | subject — note
```

## Operations

- `ingest` refreshes a record page, its tag pages, the index, and the journal.
- `query` gathers a bounded corpus and files the answer as a topic page.
- `lint` checks store integrity, orphan pages, missing pages, and dangling
  wikilinks. Missing records and audio are reported rather than erased.

The store implementation comes from Earworm's `py-akousma` package. Store
format changes belong upstream; this repository owns the navigation layer.
