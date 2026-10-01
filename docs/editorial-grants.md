# Private editorial grants

`akousmata_app.editorial_grants` is an owner-side Python API for exact-record,
named-reviewer-group metadata grants. It does not make a record public. The
existing `publication` module and public router continue to consult only public
grants.

`grant()` requires the expected canonical record SHA-256, reviewer group, author,
basis and timezone-bearing future expiry. The existing owner export-consent gate
still applies. `revoke()` appends a withdrawal. Every decision has a monotonically
increasing revision within its record/group pair; earlier decisions remain in
`akousmata_editorial_grants`. Writers use a dedicated SQLite transaction and
refuse to commit a caller's unrelated pending transaction.

`grant_status()` is read-only, including when the table is absent. Its states
distinguish unpublished, granted, revoked, stale and expired/not-current. A
changed record requires a new exact authorization. An imported record extension
is never a grant, nor is permission for one reviewer group permission for another.

Scope is `record_metadata`. No audio bytes, public publication, third-party rights
clearance or sending authority are implied. Central's exact projected-content
approval and audio's separate record/asset/content/revision authorization must
still be checked. No live grants have been created during implementation.

## Integration status

The module and owner tests are implemented. Central's exporter now accepts an
explicit `--reviewer-group` for editorial export, uses this owner's grant status,
binds the group into the exact projected-content decision and rechecks the owner
grant before publishing staged files. Editorial audio without a group refuses;
an existing public grant does not substitute for a private group grant. The
candidate-local authorization workflow, contract/version release binding and
end-to-end real-audio packaging are pending. Do not label an audio
package qualified based on these owner tests alone. The initial qualification
must use an isolated candidate owner store; existing live public grants and
services must remain untouched.
