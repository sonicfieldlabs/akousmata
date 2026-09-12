# Walkable lineage and graph captures

The owner Graph view reuses canonical parent and typed relation indexes. Open record
returns to the retained account; walk links loads a bounded neighborhood. Generation
means the record declares a generated source; listening means it retains listening
accounts. Parent links connect stages without proving that an output was heard.
Relation criteria remain attached to their individual indexed edges.

Capture graph saves an explicit timestamped view in the local SQLite store. Replay
selects that saved event, not a reconstructed history of every record mutation.
Whole-library captures contain at most 800 nodes; focused captures permit depths
1–4. Edges cap at four times the node limit, at most 1600. Relation expansion per
node caps at 200. No hidden nodes are merged: truncation and endpoint gaps explicitly
represent omissions. The UI defaults to 300 nodes and depth 3 for focused captures.

Snapshot events paginate using increasing event IDs (`after`, `next_after`). This
cursor is a capture timeline, not a producer-event cursor. Capture rejects a
concurrent canonical revision rather than storing a mixed view. Replay applies
current restricted-consent and missing-record filtering. Authorized forgetting
invalidates the complete payload of every affected snapshot, leaving only an event
ID and timestamp. Snapshots are owner-local and do not enter public export fields.
These checks do not interpret free-text rights as machine-readable permission.

Existing source records are never rewritten by capture or replay. Snapshots retain
bounded metadata until invalidated; no automatic archive, model call, audio playback,
public publication, or calibration evidence is produced by this feature.
