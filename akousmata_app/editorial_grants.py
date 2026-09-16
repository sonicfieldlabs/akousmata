"""Owner-held private editorial grants, never members of the public view.

A grant covers exact record metadata for a named private reviewer group. Audio
bytes still need a separate exact-content authorization. Append-only revisions
preserve earlier decisions; expiry, withdrawal and record changes fail closed.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from akousmata_app import exports
from akousmata_app.publication import _digest

CONTRACT = "akousmata/editorial-grant/v1"
TABLE = "akousmata_editorial_grants"


def _time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Editorial grant times require a timezone")
    return parsed


def _exists(store):
    return store.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone() is not None


def _latest(store, record_id, reviewer_group):
    if not _exists(store):
        return None
    row = store.conn.execute(
        "SELECT payload FROM akousmata_editorial_grants WHERE record_id=? AND reviewer_group=? ORDER BY revision DESC LIMIT 1",
        (record_id, reviewer_group),
    ).fetchone()
    return json.loads(row[0]) if row else None


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Editorial grant identity, author and basis must be explicit")
    return value


def grant(store, record_id, *, reviewer_group, expected_record_sha256, authorized_by, basis, expires_at):
    """Explicit local owner action; does not alter the record or public grants."""
    for value in (record_id, reviewer_group, authorized_by, basis):
        _text(value)
    record = store.get(record_id)
    if record is None:
        raise KeyError("record not found")
    if not exports.exportable(record)[0]:
        raise ValueError("Owner record consent does not permit export")
    digest = _digest(record)
    if expected_record_sha256 != digest:
        raise ValueError("Record changed before editorial authorization")
    now = datetime.now(UTC)
    if _time(expires_at) <= now:
        raise ValueError("Editorial grant expiry must be in the future")
    return _append(store, record_id, reviewer_group, {
        "contract": CONTRACT, "audience": "editorial", "reviewer_group": reviewer_group,
        "record_id": record_id, "record_sha256": digest, "state": "granted",
        "authorized_by": authorized_by, "basis": basis,
        "authorized_at": now.isoformat(), "expires_at": expires_at,
        "scope": "record_metadata", "audio_authorized": False, "public_authorized": False,
    })


def _append(store, record_id, reviewer_group, value):
    # Serialize revision allocation and insertion; never silently overwrite a
    # prior decision. A caller's unrelated transaction must not be committed.
    if store.conn.in_transaction:
        raise ValueError("Editorial grant needs its own owner transaction")
    try:
        store.conn.execute("BEGIN IMMEDIATE")
        store.conn.execute("""CREATE TABLE IF NOT EXISTS akousmata_editorial_grants (
            record_id TEXT NOT NULL, reviewer_group TEXT NOT NULL, revision INTEGER NOT NULL,
            payload TEXT NOT NULL, PRIMARY KEY(record_id,reviewer_group,revision))""")
        previous = _latest(store, record_id, reviewer_group)
        value = {**value, "revision": (previous["revision"] + 1) if previous else 1}
        # Check again inside the writer transaction to close authorization races.
        if value["state"] == "granted":
            record = store.get(record_id)
            if record is None or _digest(record) != value["record_sha256"] or not exports.exportable(record)[0]:
                raise ValueError("Record changed during editorial authorization")
        store.conn.execute("INSERT INTO akousmata_editorial_grants VALUES (?,?,?,?)",
                           (record_id, reviewer_group, value["revision"], json.dumps(value, sort_keys=True)))
        store.conn.commit()
        return value
    except BaseException:
        store.conn.rollback()
        raise


def revoke(store, record_id, *, reviewer_group, authorized_by, basis):
    for value in (record_id, reviewer_group, authorized_by, basis):
        _text(value)
    previous = _latest(store, record_id, reviewer_group)
    if previous is None:
        raise ValueError("No editorial grant to revoke")
    return _append(store, record_id, reviewer_group, {
        **previous, "state": "revoked", "authorized_by": authorized_by,
        "basis": basis, "authorized_at": datetime.now(UTC).isoformat(),
    })


def grant_status(store, record_id, *, reviewer_group):
    """Read-only, including when the grant table does not exist."""
    _text(reviewer_group)
    value = _latest(store, record_id, reviewer_group)
    if value is None:
        return {"state": "unpublished", "audience": "editorial", "reviewer_group": reviewer_group}
    if (value.get("contract") != CONTRACT or value.get("audience") != "editorial"
            or value.get("record_id") != record_id or value.get("reviewer_group") != reviewer_group
            or value.get("state") not in ("granted", "revoked")
            or value.get("scope") != "record_metadata" or value.get("audio_authorized") is not False
            or value.get("public_authorized") is not False):
        raise ValueError("Malformed owner editorial grant")
    state = value["state"]
    if state != "revoked":
        record = store.get(record_id)
        if record is None or not exports.exportable(record)[0] or _digest(record) != value["record_sha256"]:
            state = "stale"
        elif not _time(value["authorized_at"]) <= datetime.now(UTC) < _time(value["expires_at"]):
            state = "expired_or_not_current"
    return {**value, "state": state}
