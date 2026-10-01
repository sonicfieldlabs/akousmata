"""Add canonical metadata to Earworm's existing relation_edges index."""

import base64
import hashlib
import json

# Preserve the established (from_id, rel_type, to_id) primary key/API. Multiple
# distinct criterion-bearing relations on that tuple remain separate payloads.
_PAYLOAD = """COALESCE((SELECT json_group_array(json(j.value))
 FROM akousmata a, json_each(a.record, '$.lineage.relations') j
 WHERE a.akousma_id=relation_edges.from_id
 AND json_extract(j.value,'$.type')=relation_edges.rel_type
 AND json_extract(j.value,'$.target_akousma_id')=relation_edges.to_id), '[]')"""


def ensure(store):
    conn = store.conn
    conn.execute("BEGIN IMMEDIATE")
    try:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(relation_edges)")}
        if "metadata_json" not in columns:
            conn.execute(
                "ALTER TABLE relation_edges ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '[]'"
            )
            conn.execute("UPDATE relation_edges SET metadata_json=" + _PAYLOAD)
        conn.execute(
            """CREATE TRIGGER IF NOT EXISTS akousmata_relation_metadata_insert
            AFTER INSERT ON relation_edges BEGIN
            UPDATE relation_edges SET metadata_json="""
            + _PAYLOAD
            + """
            WHERE from_id=NEW.from_id AND rel_type=NEW.rel_type AND to_id=NEW.to_id; END"""
        )
        conn.execute(
            """CREATE TRIGGER IF NOT EXISTS akousmata_relation_metadata_record
            AFTER UPDATE OF record ON akousmata BEGIN
            UPDATE relation_edges SET metadata_json="""
            + _PAYLOAD
            + """
            WHERE from_id=NEW.akousma_id; END"""
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS relation_index_state (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL)"
        )
        conn.execute("INSERT OR IGNORE INTO relation_index_state VALUES(1,0)")
        for table in ("akousmata", "relation_edges"):
            for action in ("INSERT", "UPDATE", "DELETE"):
                conn.execute(
                    f"CREATE TRIGGER IF NOT EXISTS relation_revision_{table}_{action} AFTER {action} ON {table} BEGIN UPDATE relation_index_state SET revision=revision+1 WHERE id=1; END"
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def page(store, identifier, *, limit=50, cursor=None, rel_type=None):
    if not 1 <= limit <= 200:
        raise ValueError("limit must be 1-200")
    ensure(store)
    revision = store.conn.execute(
        "SELECT revision FROM relation_index_state WHERE id=1"
    ).fetchone()[0]
    fingerprint = digest_key = [identifier, rel_type, revision]
    fingerprint = hashlib.sha256(json.dumps(digest_key).encode()).hexdigest()
    offset = 0
    if cursor:
        try:
            if len(cursor) > 512:
                raise ValueError()
            decoded = json.loads(base64.urlsafe_b64decode(cursor))
            offset = decoded["offset"]
            if type(offset) is not int or offset < 0:
                raise ValueError()
            if decoded["view"] != fingerprint:
                raise RuntimeError("Relation view changed; restart pagination")
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("Invalid relation cursor") from exc
    where = "(e.from_id=? OR e.to_id=?) AND (? IS NULL OR e.rel_type=?)"
    args = (identifier, identifier, rel_type, rel_type)
    total = store.conn.execute(
        "SELECT COALESCE(SUM(json_array_length(e.metadata_json)),0) FROM relation_edges e WHERE "
        + where,
        args,
    ).fetchone()[0]
    rows = store.conn.execute(
        """SELECT e.from_id,e.to_id,j.key AS ordinal,j.value AS payload,
        EXISTS(SELECT 1 FROM akousmata WHERE akousma_id=e.to_id) AS present
        FROM relation_edges e,json_each(e.metadata_json) j WHERE """
        + where
        + " ORDER BY e.from_id,e.rel_type,e.to_id,CAST(j.key AS INTEGER) LIMIT ? OFFSET ?",
        (*args, limit, offset),
    ).fetchall()
    edges = [
        dict(
            source_ref=r["from_id"],
            target_ref=r["to_id"],
            relation=json.loads(r["payload"]),
            ordinal=r["ordinal"],
            target_missing=not bool(r["present"]),
            direction="outgoing" if r["from_id"] == identifier else "incoming",
        )
        for r in rows
    ]
    if (
        revision
        != store.conn.execute(
            "SELECT revision FROM relation_index_state WHERE id=1"
        ).fetchone()[0]
    ):
        raise RuntimeError("Relation view changed; restart pagination")
    end = offset + limit
    next_cursor = (
        base64.urlsafe_b64encode(
            json.dumps(dict(view=fingerprint, offset=end)).encode()
        ).decode()
        if end < total
        else None
    )
    return dict(
        contract="akousmata/relation-index/v1",
        edges=edges,
        next_cursor=next_cursor,
        total=total,
    )
