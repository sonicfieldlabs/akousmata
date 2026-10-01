"""Durable proposal/review operations owned by the existing research service.

One active owner process per store. Canonical writes keep their existing commit
boundary; persisted intent and exact content permit recovery across that boundary.
"""

from copy import deepcopy
import json
import threading
from datetime import datetime, timezone
from akousmata_app.listening_relations import digest

_LOCK = threading.RLock()


def ensure(store):
    initial = (
        store.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_changes'"
        ).fetchone()
        is None
    )
    store.conn.executescript("""
    CREATE TABLE IF NOT EXISTS research_requests (
      request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, state TEXT NOT NULL,
      record_id TEXT NOT NULL, record_json TEXT);
    CREATE TABLE IF NOT EXISTS research_review_events (
      event_id INTEGER PRIMARY KEY AUTOINCREMENT, proposal_ref TEXT NOT NULL,
      event_json TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS research_reviews_proposal ON research_review_events(proposal_ref,event_id);
    CREATE TABLE IF NOT EXISTS research_changes (record_id TEXT PRIMARY KEY);
    CREATE TRIGGER IF NOT EXISTS research_changed_insert AFTER INSERT ON akousmata
      BEGIN INSERT OR IGNORE INTO research_changes VALUES(NEW.akousma_id); END;
    CREATE TRIGGER IF NOT EXISTS research_forgotten AFTER DELETE ON akousmata
      BEGIN UPDATE research_requests SET state='forgotten',record_json=NULL WHERE record_id=OLD.akousma_id;
      DELETE FROM research_review_events WHERE proposal_ref=OLD.akousma_id;
      INSERT OR IGNORE INTO research_changes VALUES(OLD.akousma_id); END;
    CREATE TRIGGER IF NOT EXISTS research_changed_update AFTER UPDATE OF record ON akousmata
      WHEN OLD.record != NEW.record
      BEGIN INSERT OR IGNORE INTO research_changes VALUES(NEW.akousma_id); END;
    """)
    if initial:
        store.conn.execute(
            "INSERT OR IGNORE INTO research_changes SELECT akousma_id FROM akousmata"
        )
        store.conn.commit()


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError("Nonempty bounded text required")
    return value


def _sources(store, request):
    refs = request.get("source_refs")
    if (
        not isinstance(refs, list)
        or not 1 <= len(refs) <= 32
        or any(not isinstance(r, str) for r in refs)
    ):
        raise ValueError("Supply 1-32 source references")
    records = [store.get(r) for r in refs]
    if any(r is None for r in records):
        raise ValueError("Unresolved proposal input")
    return records


def submit(store, request):
    from akouo_contract.record_workflows import research_proposal
    from akousma import validation_errors
    from akousma.record_evolution import next_record_reference_errors

    _text(request.get("request_id"))
    _text(request.get("record_id"))
    ensure(store)
    sources = _sources(store, request)
    fingerprint = digest([request, sources])
    with _LOCK:
        row = store.conn.execute(
            "SELECT * FROM research_requests WHERE request_id=?",
            (request["request_id"],),
        ).fetchone()
        if row:
            if row["fingerprint"] != fingerprint:
                raise RuntimeError("Request identity already binds different content")
            if row["state"] in ("cancelled", "forgotten"):
                raise RuntimeError("Request was cancelled")
            if row["state"] == "complete":
                if store.get(row["record_id"]) is None:
                    raise RuntimeError(
                        "Completed proposal was forgotten; no automatic reconstruction"
                    )
                return dict(
                    request_id=request["request_id"],
                    record_id=row["record_id"],
                    state="complete",
                    replayed=True,
                )
        else:
            if store.get(request["record_id"]) is not None:
                raise RuntimeError("Proposal identity already exists")
            store.conn.execute(
                "INSERT INTO research_requests VALUES(?,?,?,?,NULL)",
                (request["request_id"], fingerprint, "pending", request["record_id"]),
            )
            store.conn.commit()
    # Expensive contract validation outside the lock leaves cancellation available.
    try:
        record = research_proposal(
            request,
            sources,
            validate_record=validation_errors,
            validate_references=next_record_reference_errors,
        )
    except Exception:
        with _LOCK:
            store.conn.execute(
                "UPDATE research_requests SET state='failed' WHERE request_id=? AND state='pending'",
                (request["request_id"],),
            )
            store.conn.commit()
        raise
    with _LOCK:
        row = store.conn.execute(
            "SELECT * FROM research_requests WHERE request_id=?",
            (request["request_id"],),
        ).fetchone()
        if row["state"] == "cancelled":
            raise RuntimeError("Request was cancelled")
        if digest([request, _sources(store, request)]) != fingerprint:
            raise RuntimeError("Proposal source changed during validation")
        existing = store.get(record["akousma_id"])
        if existing is not None and existing != record:
            raise RuntimeError("Canonical proposal identity collision")
        store.conn.execute(
            "UPDATE research_requests SET state=?,record_json=? WHERE request_id=?",
            ("committing", json.dumps(record), request["request_id"]),
        )
        store.conn.commit()
        if existing is None:
            store.put(record)
        store.conn.execute(
            "UPDATE research_requests SET state=? WHERE request_id=?",
            ("complete", request["request_id"]),
        )
        store.conn.commit()
    return dict(
        request_id=request["request_id"],
        record_id=record["akousma_id"],
        state="complete",
        replayed=False,
    )


def cancel(store, request_id):
    ensure(store)
    with _LOCK:
        row = store.conn.execute(
            "SELECT state FROM research_requests WHERE request_id=?", (request_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown research request")
        if row["state"] in ("complete", "committing"):
            raise RuntimeError("Proposal commit already sealed")
        store.conn.execute(
            "UPDATE research_requests SET state=? WHERE request_id=?",
            ("cancelled", request_id),
        )
        store.conn.commit()
    return dict(request_id=request_id, state="cancelled")


def events(store, proposal_ref, after=0, limit=100):
    ensure(store)
    if after < 0 or not 1 <= limit <= 200:
        raise ValueError("Invalid event page")
    rows = store.conn.execute(
        "SELECT * FROM research_review_events WHERE proposal_ref=? AND event_id>? ORDER BY event_id LIMIT ?",
        (proposal_ref, after, limit),
    ).fetchall()
    return [dict(event_id=r["event_id"], **json.loads(r["event_json"])) for r in rows]


def _ancestry(store, record, seen=None, budget=None):
    budget = [0] if budget is None else budget
    budget[0] += 1
    if budget[0] > 64:
        raise ValueError("Evidence ancestry exceeds 64 retained nodes")
    seen = set() if seen is None else seen
    identifier = record["akousma_id"]
    if identifier in seen:
        raise ValueError("Cyclic evidence ancestry")
    if len(seen) >= 64:
        raise ValueError("Evidence ancestry exceeds supported bound")
    seen.add(identifier)
    research = record.get("extensions", {}).get("earworm_research")
    if research:
        roots = set()
        for ref in research["source_refs"]:
            source = store.get(ref)
            if source is None:
                raise ValueError("Evidence ancestry has a missing source")
            roots |= _ancestry(store, source, seen.copy(), budget)
        return roots
    retained = (
        record.get("listening", {})
        .get("akouo.retained-ensemble", {})
        .get("payload", {})
        .get("source_snapshots")
    )
    if isinstance(retained, dict) and retained:
        roots = set()
        for ref, snapshot in retained.items():
            source = store.get(ref)
            if source is None or source != snapshot:
                raise ValueError("Retained ensemble ancestry changed or is missing")
            roots |= _ancestry(store, source, seen.copy(), budget)
        return roots
    listenings = record.get("auditum", {}).get("listenings", [])
    if listenings:
        return {
            digest([p["listener_id"], p.get("listening_pass_ref") or p["listening_id"]])
            for p in listenings
        }
    return {digest(record)}


def review(store, proposal_ref, body):
    ensure(store)
    if body.get("status") not in {"accepted", "contested", "rejected", "superseded"}:
        raise ValueError("Unsupported review state")
    for k in ("actor_ref", "reason", "review_id"):
        _text(body.get(k))
    if type(body.get("expected_event")) is not int:
        raise ValueError("Expected prior event required")
    with _LOCK:
        proposal = store.get(proposal_ref)
        if not proposal or proposal.get("record_kind") != "research_proposal":
            raise ValueError("Unknown retained research proposal")
        workflow = proposal.get("extensions", {}).get("akouo_workflow", {})
        for source in workflow.get("sources", []):
            retained = store.get(source["record_ref"])
            if retained is None or digest(retained) != source["sha256"]:
                raise RuntimeError("Proposal evidence changed or was forgotten")
        history = [
            dict(event_id=r["event_id"], **json.loads(r["event_json"]))
            for r in store.conn.execute(
                "SELECT * FROM research_review_events WHERE proposal_ref=? AND json_extract(event_json,'$.review_id')=?",
                (proposal_ref, body["review_id"]),
            )
        ]
        for event in history:
            if event["review_id"] == body["review_id"]:
                if event["request"] != body:
                    raise RuntimeError("Review identity already used")
                return event
        last = store.conn.execute(
            "SELECT COALESCE(MAX(event_id),0) FROM research_review_events WHERE proposal_ref=?",
            (proposal_ref,),
        ).fetchone()[0]
        if body["expected_event"] != last:
            raise RuntimeError("Review changed; reload before appending")
        if body["status"] == "superseded":
            replacement = store.get(body.get("replacement_ref", ""))
            if (
                not replacement
                or replacement.get("record_kind") != "research_proposal"
                or replacement["akousma_id"] == proposal_ref
            ):
                raise ValueError("Supersession requires another retained proposal")
        ancestry = digest(sorted(_ancestry(store, proposal)))
        counted = body["status"] == "accepted"
        if counted:
            counted = not bool(
                store.conn.execute(
                    "SELECT 1 FROM research_review_events WHERE json_extract(event_json,'$.status')='accepted' AND json_extract(event_json,'$.ancestry')=? LIMIT 1",
                    (ancestry,),
                ).fetchone()
            )
        event = dict(
            kind="review",
            status=body["status"],
            actor_ref=body["actor_ref"],
            reason=body["reason"],
            review_id=body["review_id"],
            request=deepcopy(body),
            ancestry=ancestry,
            counts_as_new_evidence=counted,
            at=datetime.now(timezone.utc).isoformat(),
        )
        cur = store.conn.execute(
            "INSERT INTO research_review_events(proposal_ref,event_json) VALUES(?,?)",
            (proposal_ref, json.dumps(event)),
        )
        store.conn.commit()
        return dict(event_id=cur.lastrowid, **event)


def changed(store, record_id):
    ensure(store)
    if store.get(record_id) is None:
        raise ValueError("Unknown changed record")
    store.conn.execute("INSERT OR IGNORE INTO research_changes VALUES(?)", (record_id,))
    store.conn.commit()
    return dict(record_id=record_id, state="queued")


def reconcile(store, limit=32, after=""):
    ensure(store)
    if not 1 <= limit <= 100:
        raise ValueError("limit must be 1-100")
    # Keyset reconciliation, never an all-pairs comparison. Reading does not consume
    # work: only explicit acknowledgment of exact fingerprints clears the queue.
    rows = store.conn.execute(
        "SELECT record_id FROM research_changes WHERE record_id>? ORDER BY record_id LIMIT ?",
        (after, limit),
    ).fetchall()
    changes = []
    for row in rows:
        record = store.get(row["record_id"])
        changes.append(
            dict(
                record_id=row["record_id"],
                sha256=digest(record) if record else None,
                missing=record is None,
            )
        )
    return dict(
        changes=changes,
        next_after=rows[-1]["record_id"] if len(rows) == limit else None,
    )


def acknowledge(store, record_id, sha256):
    ensure(store)
    with _LOCK:
        record = store.get(record_id)
        if (digest(record) if record else None) != sha256:
            raise RuntimeError(
                "Changed source cannot be acknowledged with stale evidence"
            )
        store.conn.execute(
            "DELETE FROM research_changes WHERE record_id=?", (record_id,)
        )
        store.conn.commit()
    return dict(record_id=record_id, state="acknowledged")


def list_requests(store, after="", limit=50):
    ensure(store)
    if not 1 <= limit <= 200:
        raise ValueError("limit must be 1-200")
    return [
        dict(r)
        for r in store.conn.execute(
            "SELECT request_id,record_id,state FROM research_requests WHERE request_id>? ORDER BY request_id LIMIT ?",
            (after, limit),
        )
    ]
