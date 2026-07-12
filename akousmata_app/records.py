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

EDITABLE_FIELDS = {"tags", "annotations", "summary", "location"}

# Meteorological convention, not an ecological claim (see /api/timeline docs).
_SEASON_BY_MONTH = {
    12: "DJF", 1: "DJF", 2: "DJF",
    3: "MAM", 4: "MAM", 5: "MAM",
    6: "JJA", 7: "JJA", 8: "JJA",
    9: "SON", 10: "SON", 11: "SON",
}


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
    covenant_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    kwargs: dict[str, Any] = {}
    if covenant_id is not None:
        # py-akousma >= 0.4; older stores simply have no covenant column
        kwargs["covenant_id"] = covenant_id
    return store.query(
        originating_app=app,
        origin=origin,
        source_type=source_type,
        tag=tag,
        text=text,
        since=since,
        until=until,
        limit=limit,
        **kwargs,
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
        "has_location": isinstance((record.get("location") or {}).get("lat"), (int, float)),
        "covenant_id": (record.get("covenant") or {}).get("id"),
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


def _checked_location(value: dict[str, Any]) -> dict[str, Any]:
    """Validate a location dict through the spec builder (v1.2 ranges/enums)."""
    lib = _akousma()
    label = value.get("label")
    try:
        return lib.location(
            value.get("lat"),
            value.get("lon"),
            accuracy_m=value.get("accuracy_m"),
            altitude_m=value.get("altitude_m"),
            label=str(label).strip() or None if label is not None else None,
            source=value.get("source") or "manual",
            captured_at=value.get("captured_at"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid location: {exc}") from exc


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
    location: dict[str, Any] | None = None,
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

    checked_location = _checked_location(location) if location else None
    if checked_location is not None and not checked_location.get("label") and place:
        checked_location["label"] = place

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
        location=checked_location,
    )
    record["extensions"]["akousmata.app"] = {"listener": {"type": "human", "process": "manual_entry"}}
    store.put(record)
    return record


def update_record(store, akousma_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Edit the app-owned fields only (tags, annotations, summary, location).

    Location is listener-annotatable per spec v1.2: the navigator may add or
    correct where a sound was heard after the fact; ``{}`` clears it."""
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
    if "location" in patch:
        value = patch["location"]
        if not isinstance(value, dict):
            raise ValueError("location must be an object with lat/lon, or {} to clear it")
        if not value:
            record.pop("location", None)
        else:
            record["location"] = _checked_location(value)
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


def timeline(store, *, bucket: str = "day") -> dict[str, Any]:
    """Memories over time: counts per bucket with apps and top tags — the
    library's rhythm made visible."""
    from datetime import datetime
    import json as _json

    sizes = {"day": 10, "month": 7, "year": 4}
    if bucket not in {*sizes, "season"}:
        raise ValueError("bucket must be day, month, season, or year")
    size = sizes.get(bucket)
    rows = store.conn.execute("SELECT record FROM akousmata ORDER BY created_at ASC").fetchall()
    buckets: dict[str, dict[str, Any]] = {}
    weekdays: dict[str, int] = {}
    hours: dict[str, int] = {}
    for row in rows:
        record = _json.loads(row["record"])
        timestamp = str(record.get("created_at") or "")
        try:
            moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            moment = None
        if bucket == "season" and moment is not None:
            season = _SEASON_BY_MONTH[moment.month]
            season_year = moment.year + 1 if moment.month == 12 else moment.year
            created = f"{season_year}-{season}"
        else:
            created = timestamp[:size] if size else ""
        if not created:
            continue
        if moment is not None:
            weekday = moment.strftime("%A").lower()
            hour = f"{moment.hour:02d}"
            weekdays[weekday] = weekdays.get(weekday, 0) + 1
            hours[hour] = hours.get(hour, 0) + 1
        entry = buckets.setdefault(created, {"bucket": created, "count": 0, "by_app": {}, "tag_counts": {}})
        entry["count"] += 1
        app = (record.get("provenance") or {}).get("originating_app") or "unknown"
        entry["by_app"][app] = entry["by_app"].get(app, 0) + 1
        for tag in record.get("tags") or []:
            entry["tag_counts"][tag] = entry["tag_counts"].get(tag, 0) + 1
    out = []
    for entry in buckets.values():
        tags = sorted(entry.pop("tag_counts").items(), key=lambda item: -item[1])[:4]
        entry["top_tags"] = [tag for tag, _ in tags]
        out.append(entry)
    return {
        "bucket": bucket,
        "buckets": out,
        "total": sum(entry["count"] for entry in out),
        "recurrence_rhythms": {
            "by_weekday": weekdays,
            "by_hour_utc": hours,
            "peak_weekday": max(weekdays, key=weekdays.get) if weekdays else None,
            "peak_hour_utc": max(hours, key=hours.get) if hours else None,
            "note": "Season labels are calendar groupings (DJF/MAM/JJA/SON), not ecological-season claims.",
        },
    }


def map_points(store) -> dict[str, Any]:
    """The listening map's feed: every located memory as a light point."""
    if hasattr(store, "locations"):
        located = store.locations(limit=10000)
    else:  # py-akousma < 0.3: no hoisted lat/lon columns — scan and filter
        located = [
            record
            for record in store.query(limit=10000)
            if isinstance((record.get("location") or {}).get("lat"), (int, float))
            and isinstance((record.get("location") or {}).get("lon"), (int, float))
        ]
    total = store.conn.execute("SELECT COUNT(*) AS n FROM akousmata").fetchone()["n"]
    points = []
    for record in located:
        loc = record.get("location") or {}
        cap = record.get("capture") or {}
        points.append({
            "akousma_id": record["akousma_id"],
            "lat": loc.get("lat"),
            "lon": loc.get("lon"),
            "label": loc.get("label"),
            "accuracy_m": loc.get("accuracy_m"),
            "summary": summary_line(record),
            "created_at": record.get("created_at"),
            "originating_app": (record.get("provenance") or {}).get("originating_app"),
            "tags": list(record.get("tags") or [])[:6],
            "direction": cap.get("direction"),
            "has_audio": bool((record.get("audio") or {}).get("uri")),
        })
    return {"points": points, "located": len(points), "unlocated": total - len(points), "total": total}


def consent_audit(store) -> dict[str, Any]:
    """Every memory's consent and capture conditions at a glance; the export
    gate made visible before it bites."""
    import json as _json

    from akousmata_app.exports import EXPORTABLE_CONSENT

    rows = store.conn.execute("SELECT record FROM akousmata ORDER BY created_at DESC").fetchall()
    items = []
    totals: dict[str, int] = {}
    for row in rows:
        record = _json.loads(row["record"])
        provenance = record.get("provenance") or {}
        consent = str(provenance.get("consent_status") or "unknown")
        totals[consent] = totals.get(consent, 0) + 1
        items.append({
            "akousma_id": record["akousma_id"],
            "summary": summary_line(record)[:90],
            "originating_app": provenance.get("originating_app"),
            "consent_status": consent,
            "rights_note": provenance.get("rights_note"),
            "capture_conditions": provenance.get("capture_conditions"),
            "exportable": consent in EXPORTABLE_CONSENT,
        })
    return {
        "total": len(items),
        "totals": totals,
        "exportable": sum(1 for item in items if item["exportable"]),
        "blocked": sum(1 for item in items if not item["exportable"]),
        "items": items,
    }


CONSENT_VALUES = {"owned", "licensed", "public_domain", "unknown", "restricted"}


def set_consent(store, akousma_id: str, consent_status: str, rights_note: str | None = None) -> dict[str, Any]:
    """A human curator asserting rights over their own library — the one
    provenance field the navigator may write, and it says who set it."""
    if consent_status not in CONSENT_VALUES:
        raise ValueError(f"consent_status must be one of {sorted(CONSENT_VALUES)}")
    record = store.get(akousma_id)
    if record is None:
        raise KeyError(f"akousma not found: {akousma_id}")
    record.setdefault("provenance", {})["consent_status"] = consent_status
    if rights_note is not None:
        if rights_note.strip():
            record["provenance"]["rights_note"] = rights_note.strip()
        else:
            record["provenance"].pop("rights_note", None)
    record.setdefault("extensions", {}).setdefault("akousmata.app", {})["consent_set_by"] = "human"
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
