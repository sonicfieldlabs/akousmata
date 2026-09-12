# Listening relationships in the owner navigator

Unreleased local implementation. The record detail view adds “who listened to whom”
and the owner wiki uses the same read-only projection. Existing producer records,
pass identities, claim categories and additive human revisions remain unchanged.

- Independent retained passes have no inferred influence edge. An aggregate's input
  references describe retained inputs, not fresh second-model execution.
- Second reports require the matching A2 route/pass/report identity and explicit
  report-of inputs. They do not imply direct audio access or causal influence.
- Record responses remain additive kinship declarations, distinct from second
  reports and redirection. A human revision creates a new record, preserving earlier
  human and machine accounts.
- Recorded redirection connects explicit canonical ensemble/listening references,
  matching target attribution and preservation fields. A linked retained decision
  trace is inspectable separately. The view checks reference/trace availability;
  it does not repeat a model run or independently establish causality.
- Declared influence with unavailable trace evidence remains labelled as declared.
  Incomplete references remain unresolved, rather than becoming convincing arrows.

The arrangement follows a declared signal flow: named earlier records enter distinct
passes, comparisons retain differences, second reports address their inputs, and
redirection requires a trace. Scheduling and co-presence create no new edge.

`GET /api/records/{id}/listening-relations?limit=50&cursor=...` returns the owner-only
`akousmata/listening-relations/v1` JSON view. This is a derived export, not a replacement
canonical record. The ID lookup uses the existing indexed store. Each page includes
nodes and up to 200 edges; concatenating edge pages matches the full detail view.
The cursor fingerprints the record and resolved source state. Changes to either
invalidate continuation with HTTP 409. Missing source records remain visible as
`missing`; a retained source snapshot without the canonical record is `snapshot_only`.
A changed canonical source is distinguished from the exact retained input snapshot.

The public metadata allowlist is unchanged. These participant/pass identities, links,
source gaps and decision traces do not enter public projections or public packs.
A summary publication grant does not grant relationship disclosure. Revocation and
source changes continue to invalidate public views/cursors. Owner detail, wiki and
relationship JSON remain accessible under the existing local owner boundary.

Fixtures were produced through the implemented D3 owner APIs using synthetic source
accounts and an explicitly deterministic second report. They establish integration
and reference behavior, not human hearing, model competence or empirical causality.
