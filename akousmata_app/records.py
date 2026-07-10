"""Record operations for the navigator: list, detail, manual memories, edits.

Producer discipline: this app owns `tags`, `annotations`, top-level `summary`,
and the `human.*` / `akousmata.*` listening namespaces. It never reshapes
another producer's listening block — the same additive rule every app in the
Listening Stack follows.
"""
from __future__ import annotations

import time
import wave
from hashlib import sha256
from pathlib import Path
from typing import Any

from akousmata_app import AKOUSMATA_CONTRACT
from akousmata_app.paths import ensure_pyakousma

EDITABLE_FIELDS = {"tags", "annotations", "summary"}


def _akousma():
    ensure_pyakousma()
    import akousma

    return akousma


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def list_records(
    store,
    *,
    app: str | None = None,
    origin: str | None = None,
    source_type: str | None = None,
    tag: str | None = None,
    text: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    return store.query(
        originating_app=app,
        origin=origin,
        source_type=source_type,
        tag=tag,
        text=text,
        since=since,
        until=until,
        limit=limit,
    )


def summary_line(record: dict[str, Any]) -> str:
    summary = record.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    listening = record.get("listening") or {}
    for entry in listening.values():
        if isinstance(entry, dict):
            text = entry.get("summary")
            if isinstance(text, str) and text.strip():
                return text.strip()
            payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else entry
            for key in ("caption", "summary", "brief", "main_reading", "notes"):
                value = payload.get(key) if isinstance(payload, dict) else None
                if isinstance(value, str) and value.strip():
                    return value.strip()
    prompt = (record.get("lineage") or {}).get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        return prompt.strip()
    return ", ".join(str(t) for t in record.get("tags") or []) or "(no summary)"


def card(record: dict[str, Any]) -> dict[str, Any]:
    """Compact list representation."""
    provenance = record.get("provenance") or {}
    audio = record.get("audio") or {}
    lineage = record.get("lineage") or {}
    return {
        "akousma_id": record["akousma_id"],
        "created_at": record.get("created_at"),
        "summary": summary_line(record),
        "tags": list(record.get("tags") or []),
        "originating_app": provenance.get("originating_app"),
        "origin": provenance.get("origin"),
        "source_type": provenance.get("source_type"),
        "duration_seconds": audio.get("duration_seconds"),
        "has_audio": bool(audio.get("uri")),
        "parent_count": len(lineage.get("parent_akousma_ids") or []),
        "relation_count": len(lineage.get("relations") or []),
        "listener_kinds": sorted({ns.split(".")[0] for ns in (record.get("listening") or {})}),
    }


def detail(store, akousma_id: str) -> dict[str, Any] | None:
    record = store.get(akousma_id)
    if record is None:
        return None
    parents = [pid for pid in store.parents(akousma_id)]
    children = [cid for cid in store.children(akousma_id)]
    related = store.related(akousma_id) if hasattr(store, "related") else []
    audio_path = resolve_audio_path(store, record)
    return {
        "record": record,
        "summary": summary_line(record),
        "parents": [_ref(store, pid) for pid in parents],
        "children": [_ref(store, cid) for cid in children],
        "related": [
            {**link, "summary": _ref_summary(store, link.get("akousma_id"))}
            for link in related
        ],
        "audio_available": audio_path is not None,
    }


def _ref(store, akousma_id: str) -> dict[str, Any]:
    record = store.get(akousma_id)
    if record is None:
        return {"akousma_id": akousma_id, "summary": "(missing record — absence is information)", "missing": True}
    return {"akousma_id": akousma_id, "summary": summary_line(record), "missing": False}


def _ref_summary(store, akousma_id: str | None) -> str:
    if not akousma_id:
        return ""
    record = store.get(akousma_id)
    return summary_line(record) if record else "(missing record)"


def resolve_audio_path(store, record: dict[str, Any]) -> Path | None:
    uri = str((record.get("audio") or {}).get("uri") or "")
    if uri.startswith("akousmata://"):
        path = store.resolve_uri(uri)
        return path if path is not None and path.exists() else None
    if uri.startswith("file://"):
        path = Path(uri[7:])
        return path if path.exists() else None
    if uri and Path(uri).expanduser().exists():
        return Path(uri).expanduser()
    return None


def _wav_duration(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            return round(frames / float(rate), 3) if rate else None
    except Exception:
        return None


def create_manual_memory(
    store,
    *,
    summary: str,
    notes: str = "",
    tags: list[str] | None = None,
    heard_at: str | None = None,
    place: str | None = None,
    kind: str = "heard_live",
    audio_path: str | None = None,
    parent_akousma_ids: list[str] | None = None,
    relations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A human listening event becomes an akousma: what you heard belongs in
    the same library as what the agents heard, with the listener declared."""
    lib = _akousma()
    audio: dict[str, Any] = {"asset_id": f"manual_{lib.new_id('man')[4:]}"}
    origin = "unknown"
    source_type = "recorded"
    if audio_path:
        source = Path(audio_path).expanduser()
        if not source.exists():
            raise FileNotFoundError(f"audio file not found: {audio_path}")
        data = source.read_bytes()
        ext = source.suffix.lstrip(".") or "wav"
        audio["uri"] = store.put_audio(data, ext=ext)
        audio["content_hash"] = "sha256:" + sha256(data).hexdigest()
        duration = _wav_duration(source) if ext.lower() == "wav" else None
        if duration:
            audio["duration_seconds"] = duration
        origin = "file"
        source_type = "imported"

    payload: dict[str, Any] = {"notes": notes or summary}
    if place:
        payload["place"] = place
    if heard_at:
        payload["heard_at"] = heard_at
    payload["kind"] = kind

    record = lib.new_akousma(
        audio=audio,
        originating_app="akousmata",
        source_type=source_type,
        origin=origin,
        listening={
            "human.note": {
                "contract": AKOUSMATA_CONTRACT,
                "created_at": _utc_now(),
                "summary": summary,
                "payload": payload,
            }
        },
        parent_akousma_ids=parent_akousma_ids,
        relations=relations,
        tags=tags,
        summary=summary,
    )
    record["extensions"]["akousmata.app"] = {"listener": {"type": "human", "process": "manual_entry"}}
    store.put(record)
    return record


def update_record(store, akousma_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Edit the app-owned fields only (tags, annotations, summary)."""
    unknown = set(patch) - EDITABLE_FIELDS
    if unknown:
        raise ValueError(f"not editable: {', '.join(sorted(unknown))}. Editable: {', '.join(sorted(EDITABLE_FIELDS))}")
    record = store.get(akousma_id)
    if record is None:
        raise KeyError(f"akousma not found: {akousma_id}")
    if "tags" in patch:
        record["tags"] = [str(t) for t in (patch["tags"] or []) if str(t).strip()]
    if "summary" in patch:
        summary = str(patch["summary"] or "").strip()
        if summary:
            record["summary"] = summary
        else:
            record.pop("summary", None)
    if "annotations" in patch and isinstance(patch["annotations"], dict):
        record.setdefault("annotations", {}).update(patch["annotations"])
    record.setdefault("extensions", {}).setdefault("akousmata.app", {})["edited_at"] = _utc_now()
    store.put(record)
    return record


def add_relation(store, akousma_id: str, rel_type: str, target_akousma_id: str, note: str | None = None) -> dict[str, Any]:
    lib = _akousma()
    record = store.get(akousma_id)
    if record is None:
        raise KeyError(f"akousma not found: {akousma_id}")
    relations = record.setdefault("lineage", {}).setdefault("relations", [])
    if not any(r.get("type") == rel_type and r.get("target_akousma_id") == target_akousma_id for r in relations):
        relations.append(lib.relation(rel_type, target_akousma_id, note))
        store.put(record)
    return record


def remove_relation(store, akousma_id: str, rel_type: str, target_akousma_id: str) -> dict[str, Any]:
    record = store.get(akousma_id)
    if record is None:
        raise KeyError(f"akousma not found: {akousma_id}")
    relations = record.get("lineage", {}).get("relations") or []
    kept = [r for r in relations if not (r.get("type") == rel_type and r.get("target_akousma_id") == target_akousma_id)]
    if len(kept) != len(relations):
        if kept:
            record["lineage"]["relations"] = kept
        else:
            record["lineage"].pop("relations", None)
        store.put(record)
    return record


def stats(store) -> dict[str, Any]:
    rows = store.conn.execute(
        "SELECT originating_app, origin, COUNT(*) AS n FROM akousmata GROUP BY originating_app, origin"
    ).fetchall()
    by_app: dict[str, int] = {}
    by_origin: dict[str, int] = {}
    total = 0
    for row in rows:
        total += row["n"]
        by_app[row["originating_app"] or "unknown"] = by_app.get(row["originating_app"] or "unknown", 0) + row["n"]
        by_origin[row["origin"] or "unknown"] = by_origin.get(row["origin"] or "unknown", 0) + row["n"]
    latest = store.conn.execute("SELECT MAX(created_at) AS m FROM akousmata").fetchone()
    return {"total": total, "by_app": by_app, "by_origin": by_origin, "latest_created_at": latest["m"]}
