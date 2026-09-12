# Local acoustic retrieval (P2)

Akousmata owns a derived `acoustic.sqlite3` index beside the canonical store. It never
inserts embeddings into existing Auditum JSON or changes original audio. CLAP runs in an
isolated offline subprocess through the existing Earworm deployment registry and heavy-job
lease. Missing CLAP does not disable current memory, MOSS, or generation workflows.

## Owner API

All routes are private owner operations, separate from `/api/public`:

- `GET /api/acoustic/status`: model availability, embedding space, stored index counts and recent jobs.
- `POST /api/acoustic/backfill`: `{asset_ids?: string[], offset?: number, limit?: number}`.
  Select up to 32 explicit asset IDs or a bounded inventory slice (default 16).
- `POST /api/acoustic/jobs/{id}/cancel`: request cancellation; child termination precedes lease release.
- `POST /api/acoustic/query`: exactly one of `{text}` or `{asset_id}`, with optional `scope`
  (`all`, `memory`, `library`), `limit` (1–30), and `include_generated` (default false).

Asset identifiers are `record:<record-id>` or `library:<GERM-key>`. Clients cannot submit
arbitrary audio paths. Audio must resolve from a current owner record or GERM's existing
library resolver, within configured local roots. GERM remains the sound library authority.

Set `AKOUSMATA_CLAP_CONFIG` to the provisioned manifest, `AKOUSMATA_ACOUSTIC_GERM_URL` to the
local GERM origin, and `AKOUSMATA_ACOUSTIC_AUDIO_ROOTS` to permitted local audio roots, separated
by the platform path separator. No request downloads weights or calls an external model.

## Index and ranking contract

Index keys include source SHA-256, exact segment start/end, and the Earworm embedding-space
identity. The space includes the pinned encoder revision, processor/worker/environment
identity, 512 dimensions, projection/normalization and cosine metric. Changing the encoder
or preprocessing creates a separate space. Legacy record embeddings remain untouched.

Original audio retains its format. CLAP receives a 48 kHz mono analysis view; each segment
receipt records native format, boundaries, resampling/downmixing, repeat-padding, waveform
hash and log-mel processor hash. Short tails use the pinned processor's repeat-pad policy.
Text queries are capped at 500 characters and 77 tokens; the worker records truncation.

Sources up to 120 seconds are split into non-overlapping ten-second segments. Longer files
are explicitly skipped rather than silently truncated. Each job is limited to 15 minutes;
a worker handles at most 12 segments, waits at most 120 seconds for the heavy lease, and
has a 180-second execution deadline. Only one CLAP request runs per owner process. Restarted
backfills become interrupted; a user must resume explicitly, reusing completed vectors.

Every query rechecks the live inventory, file identity and current eligibility. Removed or
restricted bindings are pruned, along with orphaned vectors. Changed audio cannot match its
old vectors. Incognito/not-stored, denied/revoked consent, `annotations.acoustic_excluded`,
and `extensions["akousmata.acoustic"].excluded` are excluded. Local private access is not a
public export grant. Sources that reference a missing/restricted memory are withheld
conservatively. Memory-to-library aliasing requires an exact audio content hash; a generation
influence is not evidence that the generated waveform was the original recording.

Ranking uses the best segment cosine per source; duplicate uploads/records do not multiply
its weight. Sound queries compare each indexed query segment and keep the best candidate
score. Identical source bytes are excluded from sound-query results. Generated descendants
are omitted by default and remain labelled when explicitly included. Similarity is neither
a calibrated probability nor proof of source identity, causation, or independent corroboration.

The text/tag workflow remains available. The CLAP index and query cache are private derived
data, not canonical memory. A text-vector cache stores at most 128 hashed queries; sound
queries reuse indexed vectors. Backfill jobs and Discovery retrieval events retain operational
provenance separately from existing Auditums.
