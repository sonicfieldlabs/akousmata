# Canonical relation indexing and reviewed research

Unreleased local K6/K9/O18 integration. The owner service reuses Earworm's
`relation_edges` index, AKOUO A11 and the existing research module and watcher.

## Index and migration

Opening the navigator adds `metadata_json` to the existing triplet index and
backfills it from canonical `lineage.relations`. Each payload remains distinct even
when several criteria link the same pair with the same type. SQLite triggers keep
metadata current for new writes, updates and reindexing; original canonical JSON
is unchanged. Legacy relation consumers keep their existing columns and behavior.

`GET /api/records/{id}/relations/indexed?limit=50&cursor=...&rel_type=similar_by`
returns canonical payloads, direction and explicit missing targets. SQL bounds each
page to 1–200 edges. A persisted index revision invalidates cursors after writes with
409; callers restart pagination. The revision is conservative: unrelated writes may
also invalidate a cursor. No second graph store or all-pairs scan is introduced.

## Proposals and additive review

`POST /api/research/proposals` accepts the A11 research request documented by AKOUO.
Up to 32 selected canonical sources and 64 criterion-bearing proposals are validated
by the installed AKOUO/Earworm contracts. The owner stores a new unreviewed E15 record;
it does not modify source accounts, execute a new listening or promote source claims.
Known scores remain attributed to supplied method/evidence; this service does not
invent comparisons or run a new scoring model. Existing deterministic/LLM research
sessions continue to operate, and `GET /api/research` also lists durable proposal states.

The request ID binds exact request and source fingerprints. Identical retries return
the same proposal, changed inputs conflict, failed validation is recorded, and
`POST /api/research/requests/{request_id}/cancel` cancels before the commit seal.
Durable intent and canonical identity/content checks recover an interruption after
the record write without duplicating it. Supported topology is one active owner
process per store. Independent concurrent owner processes are not coordinated by
the in-process commit lock.

`POST /api/research/proposals/{record_id}/reviews` appends an event with `review_id`,
`actor_ref`, `reason`, `status` and `expected_event` (zero for the first review).
Statuses are accepted, contested, rejected and superseded; superseded additionally
requires a different retained `replacement_ref`. A stale expected event conflicts.
Retries reuse exact review identity/content. Source and proposal records remain
unchanged; the latest event describes review state rather than overwriting the E15
unreviewed source. Research corrections can therefore be inspected in order.

`GET /api/research/proposals/{record_id}/events?after=0&limit=100` streams a bounded
SSE page with durable event IDs and an end event containing `next_after`. Reconnect
using that cursor for later events. This uses the existing research SSE format;
ordinary traversal session events keep their original endpoint and behavior.

Acceptance counts are grouped by evidence ancestry, including inherited research
sources and original listening identities in retained ensembles. Ancestry traversal
is bounded to 64 nodes and rejects missing/cyclic evidence. `counts_as_new_evidence`
means a previously uncounted retained evidence group, not independent empirical
confirmation, truth, consensus or a new human/model listening. Rewording a criterion
or reviewing inherited research does not create another confirmation.

## Changed records and Oida

The existing shared-store writer triggers queue new/changed records. Initial migration
queues existing records once. `POST /api/research/changes/{id}` explicitly queues a
known record; `GET /api/research/reconcile?limit=32&after=...` returns a bounded keyset
page with current digests and missing-source gaps. Reading does not consume work.
After processing a change, `POST /api/research/changes/{id}/acknowledge` with its exact
`sha256` clears it; stale evidence cannot clear a newer change.

The existing scheduled watcher calls reconciliation and exposes pending work in
its status. Oida already starts this watcher with its embedded navigator, and now
also delegates proposals, cancellation, change notification, reconciliation and
acknowledgment through `/owner/research/...`. There is no second research scheduler.
Disabling the existing watcher disables automatic ticks; the explicit owner endpoints
remain usable. Pending changes require a selected comparison policy/proposal or an
explicit acknowledgment; a maintenance tick does not invent a research conclusion
or automatically call an LLM/provider.

## Disclosure and forgetting

All new routes and review/index metadata stay inside the existing local owner
boundary. The public field allowlist is unchanged. Publication/revocation does not
expose criteria, source links or review reasons. Forgetting a proposal removes its
review events and retained recovery payload and marks its request forgotten, so
replay cannot reconstruct it. Referenced sources that disappear remain gaps, and
reviews refuse stale or forgotten evidence. Permission references remain declared
owner evidence; no new independent rights verification is claimed.
