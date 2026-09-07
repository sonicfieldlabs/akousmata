"""Host-owned public grants and views over the existing canonical store.

Grants live in an application table, never in imported record extensions. They
bind exact source bytes (canonical JSON) and explicitly selected metadata fields.
Every read checks current consent and source equality before projecting anything.
"""
from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter
from typing import Any

from akousmata_app import exports

CONTRACT = "akousmata/public-view/v1"


class ViewChanged(ValueError):
    pass


def _digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _exists(store) -> bool:
    return store.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='akousmata_public_grants'").fetchone() is not None


def grant(store, record_id: str, fields: list[str]) -> dict[str, Any]:
    """Explicit owner action; consent alone never creates a public grant."""
    fields = exports.checked_fields(fields)
    record = store.get(record_id)
    if record is None:
        raise KeyError("record not found")
    allowed, reason = exports.exportable(record)
    if not allowed:
        raise ValueError(reason)
    projection = exports.sanitize(record, include_audio=False, fields=fields)
    store.conn.execute("""CREATE TABLE IF NOT EXISTS akousmata_public_grants (
        akousma_id TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL,
        fields TEXT NOT NULL, state TEXT NOT NULL CHECK (state IN ('granted','revoked'))
    )""")
    store.conn.execute("""INSERT INTO akousmata_public_grants VALUES (?, ?, ?, 'granted')
        ON CONFLICT(akousma_id) DO UPDATE SET source_sha256=excluded.source_sha256,
        fields=excluded.fields, state='granted'""", (record_id, _digest(record), json.dumps(fields)))
    store.conn.commit()
    return {"state": "granted", "fields": fields, "projection": projection}


def revoke(store, record_id: str) -> None:
    if _exists(store):
        store.conn.execute("UPDATE akousmata_public_grants SET state='revoked' WHERE akousma_id=?", (record_id,))
        store.conn.commit()


def grant_status(store, record_id: str) -> dict[str, Any]:
    if not _exists(store):
        return {"state": "unpublished", "fields": []}
    row = store.conn.execute("SELECT * FROM akousmata_public_grants WHERE akousma_id=?", (record_id,)).fetchone()
    if row is None:
        return {"state": "unpublished", "fields": []}
    record = store.get(record_id)
    current = record is not None and exports.exportable(record)[0] and _digest(record) == row["source_sha256"]
    return {"state": row["state"] if row["state"] == "revoked" or current else "stale",
            "fields": json.loads(row["fields"])}


def _visible(store, *, record_id: str | None = None):
    if not _exists(store):
        return
    # Indexed grant membership limits the candidate set. Filtering and pagination
    # happen only after projecting permitted content; raw text is never searched.
    sql = """SELECT a.record, g.source_sha256, g.fields FROM akousmata_public_grants AS g
        JOIN akousmata AS a ON a.akousma_id=g.akousma_id WHERE g.state='granted'"""
    args = []
    if record_id is not None:
        sql += " AND g.akousma_id=?"
        args.append(record_id)
    sql += " ORDER BY a.created_at DESC, a.akousma_id ASC"
    for row in store.conn.execute(sql, args):
        record = json.loads(row["record"])
        if not exports.exportable(record)[0] or _digest(record) != row["source_sha256"]:
            continue
        yield exports.sanitize(record, include_audio=False, fields=json.loads(row["fields"]))


def public_record(store, record_id: str) -> dict[str, Any] | None:
    return next(_visible(store, record_id=record_id), None)


def _matches(projection, tag, text):
    if tag is not None and tag not in projection.get("tags", []):
        return False
    if text is not None:
        searchable = " ".join([projection.get("summary", ""), projection.get("subject", ""), *projection.get("tags", [])])
        if text.casefold() not in searchable.casefold():
            return False
    return True


def public_counts(store, *, tag: str | None = None, text: str | None = None) -> dict[str, Any]:
    total = with_audio = 0
    apps = Counter()
    latest = None
    for projection in _visible(store):
        if not _matches(projection, tag, text):
            continue
        total += 1
        with_audio += int("audio" in projection)
        app = projection.get("provenance", {}).get("originating_app")
        if app is not None:
            apps[app] += 1
        latest = max(latest or "", projection["created_at"])
    return {"contract": CONTRACT, "audience": "public", "total": total,
            "with_audio_metadata": with_audio, "by_app": dict(sorted(apps.items())), "latest_created_at": latest}


def public_page(store, *, limit: int = 50, cursor: str | None = None,
                tag: str | None = None, text: str | None = None) -> dict[str, Any]:
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    offset = 0
    expected_view = None
    if cursor is not None:
        try:
            if len(cursor) > 512:
                raise ValueError()
            decoded = json.loads(base64.b64decode(cursor, altchars=b'-_', validate=True))
            if not isinstance(decoded, dict) or set(decoded) != {"offset", "view"}:
                raise ValueError()
            offset, expected_view = decoded["offset"], decoded["view"]
            if type(offset) is not int or offset < 0 or not isinstance(expected_view, str):
                raise ValueError()
        except (ValueError, TypeError, UnicodeDecodeError) as exc:
            raise ValueError("invalid public cursor") from exc
    # Memory is bounded by page size. The fingerprint covers only permitted data
    # and query settings; private totals/IDs never enter a cursor or response.
    fingerprint = hashlib.sha256(_digest({"tag": tag, "text": text}).encode())
    page = []
    position = 0
    for projection in _visible(store):
        if not _matches(projection, tag, text):
            continue
        fingerprint.update(_digest(projection).encode())
        if offset <= position < offset + limit:
            page.append(projection)
        position += 1
    view = fingerprint.hexdigest()
    if expected_view is not None and expected_view != view:
        raise ViewChanged("public view changed; restart from the first page")
    if offset > position:
        raise ValueError("invalid public cursor")
    next_cursor = None
    if offset + len(page) < position:
        payload = json.dumps({"offset": offset + len(page), "view": view}, separators=(",", ":")).encode()
        next_cursor = base64.urlsafe_b64encode(payload).decode()
    return {"contract": CONTRACT, "audience": "public", "records": page, "next_cursor": next_cursor}
