# Public projections and counts

Akousmata's owner application is a trusted local API. `/api/health`, library
search, audio, settings, export responses and other owner routes contain private
data. They are not suitable for a public status ribbon or relay.

Consumers can reuse `akousmata_app.server.public_router` in a separate FastAPI
application. It exposes only the three read-only `/api/public` routes. Configure
`AKOUSMATA_PATH` on that host. Mounting the full `app` also exposes owner routes;
the navigator does not provide authentication or a multi-user permission system.

```python
from fastapi import FastAPI
from akousmata_app.server import public_router

app = FastAPI()
app.include_router(public_router)
```

## Owner grants

`POST /api/records/{id}/publication` accepts `{"fields": ["summary", "tags"]}`.
Allowed groups are `summary`, `subject`, `tags`, `provenance`, `audio_metadata`
and `listener_types`. An empty list approves only the mandatory record ID,
creation timestamp and source schema version. Unknown or repeated fields are
rejected. `GET` returns `unpublished`, `granted`, `stale` or `revoked`; `DELETE`
revokes the grant. These operations belong to the local owner interface.

The existing consent gate still requires `owned`, `licensed` or `public_domain`.
Consent alone does not publish a record. A grant lives in a host-owned SQLite
table and binds selected fields to the SHA-256 of canonical JSON for the entire
source record. Imported extensions cannot create grants. Reads recheck consent
and current source equality. Changed sources become unavailable until approved
again; this is content equality, not a history of every external mutation.
The consent setter explicitly revokes the grant, including when consent is
later restored. Forgetting removes availability, while reindex and reopen retain
grants for unchanged records. Canonical records are never rewritten to publish.

The owner must approve the actual selected content under applicable rights and
covenants. This API does not interpret covenant prose, license terms or external
policy changes. It does not grant access to raw accounts or audio. Automated
covenant-policy integration remains a consumer responsibility.

## Projection contract

`akousmata/public-record/v1` is a metadata projection, not a canonical akousma or
a round-trip backup. It carries `projection_contract`, `akousma_id`, `created_at`
and `source_schema_version`, plus approved fields that exist in the source.
Provenance permits only app, origin, source type and consent status. Audio
metadata permits only duration, sample rate and channel count. Listener types
use the existing classification helper and require separate approval.

Raw listenings, auditums, covenant blocks, annotations, location, identities,
lineage, extensions, asset IDs/hashes and source audio URIs are omitted. Summary
does not fall back to a raw listening report. The existing path sanitizer remains
an additional defense; it is not semantic redaction of approved prose.

## Public reads

- `GET /api/public/records?limit=50&cursor=…&tag=…&text=…` returns records and a
  continuation cursor. Limits are 1–200. Tag and text filters search only approved
  projected tags, summary and subject. Pagination happens after permissions and
  filters; private records create no gaps. A changed visible view returns 409:
  restart without a cursor. Malformed cursors return 400.
- `GET /api/public/records/{id}` returns the projection. Private, revoked, stale,
  forgotten and nonexistent records all return the same 404 response.
- `GET /api/public/status?tag=…&text=…` returns `total`, `with_audio_metadata`,
  `by_app` and `latest_created_at` for the same permitted, filtered set. An app is
  counted only when its provenance is approved; audio metadata is not playback
  availability. An empty view has zero totals, an empty app map and null timestamp.

Pages and counts use `akousmata/public-view/v1`, `audience: public` and
`Cache-Control: no-store`. They contain no whole-library totals, private IDs,
exclusion counts, receipts or store paths. Cursor fingerprints cover only public
filtered data and query settings. Private additions do not alter the cursor.
Counts and pages scan the granted candidate set using the existing record index;
memory is bounded by page size, but latency grows with the granted set. Separate
requests can observe different views if the library changes between them.

## Selection and public packs

`POST /api/export` reuses the same projection helper. `audience: selection`
(default) is an explicit local owner selection with the existing consent gate.
`fields` defaults to summary, subject, tags, provenance and audio metadata.
`audience: public` restricts each record to its current grant, ignores attempts
to widen its fields and always omits audio bytes. No public export or download
route is mounted by `public_router`.

JSONL, wiki pages and previews use the same projected data. Wiki generation does
not look up unselected children or raw records. File numbering counts included
records only. Archive manifests contain no excluded identities or reasons;
those remain in the owner response. A separate `.owner.json` file beside the
archive retains only the blocked count for the local pack list. Share the pack
directory or ZIP, not the surrounding private exports directory.

Revocation affects future views and exports. It cannot recall previously copied
archives, audio or client-held data. Existing packs are not regenerated by this
change. Oída, GERM and the unified application can consume these APIs/helpers;
their integration and deployment are separate work.
