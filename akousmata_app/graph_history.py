"""Explicit bounded graph captures, replayed under current owner restrictions."""

import json
from datetime import datetime, timezone
from akousmata_app import graph


def ensure(store):
    store.conn.executescript("""
    CREATE TABLE IF NOT EXISTS graph_snapshots(event_id INTEGER PRIMARY KEY AUTOINCREMENT,captured_at TEXT NOT NULL,payload TEXT);
    CREATE TABLE IF NOT EXISTS graph_snapshot_members(event_id INTEGER NOT NULL,record_id TEXT NOT NULL,PRIMARY KEY(event_id,record_id));
    CREATE INDEX IF NOT EXISTS graph_snapshot_records ON graph_snapshot_members(record_id);
    CREATE TRIGGER IF NOT EXISTS graph_forget_snapshot AFTER DELETE ON akousmata BEGIN
      UPDATE graph_snapshots SET payload=NULL WHERE event_id IN (SELECT event_id FROM graph_snapshot_members WHERE record_id=OLD.akousma_id);
      DELETE FROM graph_snapshot_members WHERE event_id IN (SELECT event_id FROM graph_snapshots WHERE payload IS NULL);
    END;
    """)


def capture(store, focus=None, depth=2, limit=120):
    ensure(store)
    from akousmata_app.relation_index import ensure as ensure_relations

    ensure_relations(store)
    if focus is not None and (
        not isinstance(focus, str) or not focus or len(focus) > 512
    ):
        raise ValueError("Invalid focus")
    if type(depth) is not int or not 1 <= depth <= 4:
        raise ValueError("Invalid depth")
    revision = store.conn.execute(
        "SELECT revision FROM relation_index_state WHERE id=1"
    ).fetchone()[0]
    view = (
        graph.neighborhood(store, focus, depth=depth, limit=limit)
        if focus
        else graph.full_graph(store, limit=limit)
    )
    store.conn.execute("BEGIN IMMEDIATE")
    if (
        store.conn.execute(
            "SELECT revision FROM relation_index_state WHERE id=1"
        ).fetchone()[0]
        != revision
    ):
        store.conn.rollback()
        raise RuntimeError("Graph changed during capture; retry")
    stamp = datetime.now(timezone.utc).isoformat()
    cur = store.conn.execute(
        "INSERT INTO graph_snapshots(captured_at,payload) VALUES(?,?)",
        (stamp, json.dumps(view)),
    )
    event_id = cur.lastrowid
    members = {n["id"] for n in view["nodes"]} | {
        e[k] for e in view["edges"] for k in ("from", "to")
    }
    store.conn.executemany(
        "INSERT INTO graph_snapshot_members VALUES(?,?)",
        [(event_id, r) for r in members],
    )
    store.conn.commit()
    return dict(event_id=event_id, captured_at=stamp, **view)


def events(store, after=0, limit=50):
    ensure(store)
    if after < 0 or not 1 <= limit <= 200:
        raise ValueError("Invalid event bounds")
    rows = store.conn.execute(
        "SELECT event_id,captured_at,payload IS NOT NULL AS available FROM graph_snapshots WHERE event_id>? ORDER BY event_id LIMIT ?",
        (after, limit),
    ).fetchall()
    return dict(
        events=[dict(r) for r in rows],
        next_after=rows[-1]["event_id"] if rows else after,
    )


def replay(store, event_id):
    ensure(store)
    row = store.conn.execute(
        "SELECT * FROM graph_snapshots WHERE event_id=?", (event_id,)
    ).fetchone()
    if row is None:
        raise ValueError("Unknown snapshot")
    if row["payload"] is None:
        raise RuntimeError("Snapshot invalidated by authorized forgetting")
    view = json.loads(row["payload"])
    withheld = set()
    for ref in store.conn.execute(
        "SELECT record_id FROM graph_snapshot_members WHERE event_id=?", (event_id,)
    ):
        record = store.get(ref[0])
        if record is None or graph._restricted(record):
            withheld.add(ref[0])
    view["nodes"] = [
        n
        if n["id"] not in withheld
        else dict(
            id=n["id"],
            label="(missing or restricted)",
            missing=True,
            app="unknown",
            stage="unavailable",
        )
        for n in view["nodes"]
    ]
    view["edges"] = [
        e
        for e in view["edges"]
        if e["from"] not in withheld and e["to"] not in withheld
    ]
    return dict(
        event_id=event_id,
        captured_at=row["captured_at"],
        replay=True,
        current_restriction_gaps=len(withheld),
        **view,
    )
