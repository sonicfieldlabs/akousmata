# Spectral derivatives (0.8)

`akousmata_app.derivatives.publish_bundle` admits a fresh Akousma 1.8 record and
numeric objects with explicit host native/reference validators. It journals new
objects, verifies bytes before publication, and commits the record plus host
retention grant in one database transaction. A failure rolls back and removes
unreferenced staged objects; recovery preserves objects referenced by a committed
record. POSIX locking serializes publication, grants, reads and reconciliation.
Other platforms report an unavailable locking implementation.

`GET /api/records/{id}/derivatives` lists record-scoped availability. The view
download route appends `/{view_id}`; callers never submit filesystem paths.
Every read rechecks the current record, consent/covenant binding, grant deadline,
forgetting ledger, object hash and shape/dtype/byte count. Downloads are attachments
with `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`.

Only bounded finite NPY numeric arrays are supported by this object reader.
Pickle/object dtypes, malformed headers, trailing/truncated data, symlinks and
oversized expansion are refused. Public metadata projections exclude extensions
and therefore exclude native arrays. No public derivative grant is implicit.

Record-only accounts contain no signal-bearing objects. Host grants require
audio retention plus explicit derivative permission and an audio-policy deadline.
Consent edits revoke derivative grants. Shared objects survive until no current
authorized grant references them; forgetting through the navigator and periodic
watcher reconciliation remove expired/unshared derivatives. Store opening recovers
interrupted publications. Controlled download caches are disabled.

Curating an existing 1.8 record retains its immutable native, spectral, and aperture
accounts. A new or changed account requires fresh explicit host admission.
Native source WAVs share the grant deadline with their derivatives. Controlled
audio reads recheck the grant; reconciliation removes expired source objects,
preserving any independent record that still owns the same content. Policy
digests include the native permission and covenant snapshot.
