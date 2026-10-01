# Local bundles and score data (D5, unreleased)

Akousmata remains the owner of shared record export and import. E17 manifests
(`earworm/listening-memories/v1`) add record IDs, schema versions, exact serialized
payload and source hashes, evidence class, covenants, transforms and recipient
requirements. New APIs are `POST /api/bundles/export` and `/api/bundles/import`.

Export accepts `record_ids` (1–128 distinct IDs) and `disclosure` (`private` or
`public-projection`). Private bundles preserve complete canonical JSON, including
unknown private extensions. Public bundles reuse the existing `build_pack` grant
and sanitizer pipeline; they contain metadata projections only. Source contents
and public grants are checked again before publication. No export creates a grant.

Import accepts bounded `archive_base64` plus `supported_contracts`. Explicitly
negotiate the bundle contract and each required reader contract, for example
`earworm/akousma/v1.6`, `earworm/akousma/v1.7` and `earworm/akousma/v1.8`. The ZIP boundary is 32 MiB,
129 members including its manifest, and no unlisted or duplicate members. Paths
are validated and members are read without filesystem extraction. All payload
hashes, canonical identities, references and current forgetting checks
precede writes. Revision dependencies are ordered. Same-ID identical records
reuse; changed identities refuse. Imports never install publication grants.

Private import is restoration, not publication admission. Unknown consent and
expired, future or unknown receiving claims remain part of the original canonical
record; restoration does not rewrite them or establish current validity. A receiving
store's forgetting ledger still refuses restoration. Publication requires a current
local grant and the existing consent/current-claim checks. Import receipts identify
`admission: private-restoration` and `grants_imported: false`.

Private canonical bundles support round trips for negotiated 1.6/1.7/1.8 records,
subject to the same owner validation and reference closure as record intake.
Spectral records still need their locally admissible objects; the archive does not
install external objects or validators. Public-projection bundles are for reading,
not canonical restoration: their sanitized payloads cannot replace the source records
and are refused by canonical import. Negotiating a reader contract alone does not
make a projection, generated asset pack or incomplete dependency set importable.

Graph records additionally require the owner-selected installed
`AKOUSMATA_MASA_VALIDATOR_MODULE` and `AKOUSMATA_MASA_CORE_MODULE`. The shared
Earworm offline adapter validates actual MASA evidence and obtains lineage
directions from the canonical registry; archive content cannot supply a validator.

The existing store rechecks its current forgetting ledger at every write. Import
is an additive batch, not a cross-file/SQLite transaction: an unexpected I/O error
or concurrent restriction after preflight can leave earlier accepted records.
Retry safely reuses those records. `bundle-receipts/` under the receiving store
retains successful import receipts. Runtime rollback never restores an old
revocation ledger. Bundle JSON preserves original audio locators; this record
transfer does not copy external audio or claim that it becomes locally available.
Agent-addressed generated asset ZIPs are supplied by GERM under the separate E17
`agent-sounds/v1` contract and cannot be imported as canonical memory records.

`POST /api/score` accepts a K10 `event_id`, selected `scales` (`records`,
`listenings`, `observations`) and `resolution_ms` (1–86400000). K10 supplies graph
snapshot membership and event clock. The projection resolves current canonical
record content and consent; it is not historical record replay. Original source
clocks remain distinct from quantized display buckets and the snapshot clock.
Each row includes a current source hash; coverage/gaps and a 2,000-event cap are
explicit. Missing clocks remain unknown. Authorized forgetting invalidates K10
captures instead of allowing their old content to return.

Local tests cover private/unknown-extension preservation, public grant scope,
1.6/1.7/1.8 negotiation, identity and hash conflicts, malformed archives, graph import
with actual MASA validation, current forgetting, score clocks and source gaps.
No physical sensing or improved perceptual access is inferred.
