"""Constellations — saved selections of memories, playable in order.

A constellation is a curated set of akousma ids with a name and a note: a
soundwalk through memories. Stored beside the data
(``<store>/constellations.json``, untracked), resolved against the store at
read time so forgotten members surface as honest absence instead of
disappearing.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from akousmata_app.paths import store_root
from akousmata_app.records import card

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _path():
    return store_root() / "constellations.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load() -> list[dict[str, Any]]:
    path = _path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save(items: list[dict[str, Any]]) -> None:
    _path().write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def list_constellations() -> list[dict[str, Any]]:
    return [
        {**item, "size": len(item.get("akousma_ids") or [])}
        for item in _load()
    ]


def get(constellation_id: str) -> dict[str, Any] | None:
    for item in _load():
        if item["id"] == constellation_id:
            return item
    return None


def create(name: str, note: str = "", akousma_ids: list[str] | None = None) -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise ValueError("a constellation needs a name")
    slug = _SLUG_RE.sub("-", name.lower()).strip("-") or "constellation"
    item = {
        "id": f"con_{slug[:24]}_{uuid.uuid4().hex[:6]}",
        "name": name,
        "note": note.strip(),
        "akousma_ids": list(dict.fromkeys(akousma_ids or [])),
        "created_at": _now(),
        "updated_at": _now(),
    }
    items = _load()
    items.append(item)
    _save(items)
    return item


def update(constellation_id: str, *, name: str | None = None, note: str | None = None, akousma_ids: list[str] | None = None) -> dict[str, Any]:
    items = _load()
    for item in items:
        if item["id"] == constellation_id:
            if name is not None and name.strip():
                item["name"] = name.strip()
            if note is not None:
                item["note"] = note.strip()
            if akousma_ids is not None:
                item["akousma_ids"] = list(dict.fromkeys(akousma_ids))
            item["updated_at"] = _now()
            _save(items)
            return item
    raise KeyError(f"constellation not found: {constellation_id}")


def add_member(constellation_id: str, akousma_id: str) -> dict[str, Any]:
    items = _load()
    for item in items:
        if item["id"] == constellation_id:
            if akousma_id not in item["akousma_ids"]:
                item["akousma_ids"].append(akousma_id)
                item["updated_at"] = _now()
                _save(items)
            return item
    raise KeyError(f"constellation not found: {constellation_id}")


def remove_member(constellation_id: str, akousma_id: str) -> dict[str, Any]:
    items = _load()
    for item in items:
        if item["id"] == constellation_id:
            if akousma_id in item["akousma_ids"]:
                item["akousma_ids"].remove(akousma_id)
                item["updated_at"] = _now()
                _save(items)
            return item
    raise KeyError(f"constellation not found: {constellation_id}")


def delete(constellation_id: str) -> bool:
    items = _load()
    kept = [item for item in items if item["id"] != constellation_id]
    if len(kept) == len(items):
        return False
    _save(kept)
    return True


def resolve(store, constellation: dict[str, Any]) -> dict[str, Any]:
    """Members as cards, in walk order; forgotten members stay visible as
    absences (the constellation remembers what the store forgot)."""
    members: list[dict[str, Any]] = []
    playable = 0
    from akousmata_app.records import resolve_audio_path

    for akousma_id in constellation.get("akousma_ids") or []:
        record = store.get(akousma_id)
        if record is None:
            members.append({"akousma_id": akousma_id, "missing": True, "summary": "(forgotten memory)", "has_audio": False})
            continue
        entry = card(record)
        entry["missing"] = False
        entry["playable"] = resolve_audio_path(store, record) is not None
        playable += 1 if entry["playable"] else 0
        members.append(entry)
    return {**constellation, "members": members, "playable_count": playable}
