"""Export packs — a selection of memories as a shareable research bundle.

A pack contains sanitized records (JSONL), their wiki pages, optionally
their audio objects, and a manifest that names what was EXCLUDED and why.
Consent is the gate: records whose ``consent_status`` is not
``owned``/``licensed``/``public_domain`` are blocked from export and reported,
never silently dropped or silently included. Sanitization strips personal
annotations and local paths; the earworm spec's consent rule made operational.
"""
from __future__ import annotations

import json
import re
import secrets
import shutil
import time
from typing import Any

from akousmata_app import __version__
from akousmata_app.paths import store_root
from akousmata_app.records import AUDIO_EXTENSIONS, resolve_audio_path, summary_line

EXPORTABLE_CONSENT = {"owned", "licensed", "public_domain"}
_LOCAL_PATH_RE = re.compile(
    r"(?:file://)?/(?:Users|home|private|tmp|var/folders|Volumes)/[^\s\"'`]+"
)
_WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\(?:Users|Documents and Settings)\\[^\s\"'`]+")
_SECRET_KEYS = {"api_key", "apikey", "password", "secret", "token", "access_token"}


def exportable(record: dict[str, Any]) -> tuple[bool, str]:
    consent = str((record.get("provenance") or {}).get("consent_status") or "unknown")
    if consent in EXPORTABLE_CONSENT:
        return True, consent
    return False, f"consent_status is '{consent}' (needs owned/licensed/public_domain)"


def sanitize(record: dict[str, Any], *, include_audio: bool) -> dict[str, Any]:
    """A copy safe to share: no personal annotations, no local paths, and no
    geolocation — where someone listens is as sensitive as what they heard
    (spec v1.2 consent rule)."""
    clean = json.loads(json.dumps(record, ensure_ascii=False))
    clean.pop("annotations", None)
    clean.pop("location", None)
    extensions = clean.get("extensions") or {}
    extensions.pop("akousmata.app", None)
    audio = clean.get("audio") or {}
    uri = str(audio.get("uri") or "")
    if include_audio and (uri.startswith("file://") or uri.startswith("/") or uri.startswith("akousmata://")):
        audio["uri"] = f"pack://audio/{clean['akousma_id']}"
    elif uri:
        audio.pop("uri", None)
    return _sanitize_value(clean)


def _sanitize_value(value: Any, *, key: str = "") -> Any:
    if key.lower() in _SECRET_KEYS:
        return None
    if isinstance(value, dict):
        return {
            child_key: cleaned
            for child_key, child_value in value.items()
            if (cleaned := _sanitize_value(child_value, key=str(child_key))) is not None
        }
    if isinstance(value, list):
        return [
            cleaned
            for item in value
            if (cleaned := _sanitize_value(item, key=key)) is not None
        ]
    if isinstance(value, str):
        if value.startswith("file://") or value.startswith("/") or _WINDOWS_PATH_RE.fullmatch(value):
            return None
        value = _LOCAL_PATH_RE.sub("[local path removed]", value)
        return _WINDOWS_PATH_RE.sub("[local path removed]", value)
    return value


def build_pack(
    store,
    *,
    name: str,
    akousma_ids: list[str],
    include_audio: bool = True,
    include_wiki: bool = True,
) -> dict[str, Any]:
    name = name.strip() or "export"
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    # The display name belongs in the manifest, not in a filesystem path. A
    # random suffix also prevents two exports in the same second from colliding.
    root = store_root() / "exports" / f"pack-{stamp}-{secrets.token_hex(4)}"
    (root / "records").mkdir(parents=True, exist_ok=True)

    included: list[str] = []
    excluded: list[dict[str, str]] = []
    lines: list[str] = []
    files: list[dict[str, Any]] = []

    for position, akousma_id in enumerate(dict.fromkeys(akousma_ids), start=1):
        record = store.get(akousma_id)
        if record is None:
            excluded.append({"akousma_id": akousma_id, "reason": "record not found (forgotten or never existed)"})
            continue
        ok, reason = exportable(record)
        if not ok:
            excluded.append({"akousma_id": akousma_id, "reason": reason})
            continue
        audio_path = resolve_audio_path(store, record) if include_audio else None
        clean = sanitize(record, include_audio=audio_path is not None)
        if include_audio:
            if audio_path is not None:
                audio_dir = root / "audio"
                audio_dir.mkdir(exist_ok=True)
                suffix = audio_path.suffix.lower().lstrip(".")
                suffix = suffix if suffix in AUDIO_EXTENSIONS else "wav"
                audio_name = f"record-{position:04d}.{suffix}"
                target = audio_dir / audio_name
                shutil.copyfile(audio_path, target)
                clean["audio"]["uri"] = f"pack://audio/{audio_name}"
                files.append({"kind": "audio", "akousma_id": akousma_id, "path": f"audio/{audio_name}", "bytes": target.stat().st_size})

        lines.append(json.dumps(clean, ensure_ascii=False))
        included.append(akousma_id)

        if include_wiki:
            from akousmata_app import wiki

            wiki_dir = root / "wiki"
            wiki_dir.mkdir(exist_ok=True)
            wiki_name = f"record-{position:04d}.md"
            target = wiki_dir / wiki_name
            target.write_text(wiki.record_page(store, clean), encoding="utf-8")
            files.append({"kind": "wiki", "akousma_id": akousma_id, "path": f"wiki/{wiki_name}", "bytes": target.stat().st_size})

    (root / "records" / "records.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    manifest = {
        "name": name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "navigator_version": __version__,
        "included": len(included),
        "included_ids": included,
        "excluded": excluded,
        "include_audio": include_audio,
        "include_wiki": include_wiki,
        "files": files,
        "consent_rule": "records outside owned/licensed/public_domain are blocked and listed here, never silently shipped",
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    archive = shutil.make_archive(str(root), "zip", root_dir=root)
    summaries = []
    for akousma_id in included[:5]:
        record = store.get(akousma_id)
        if record:
            summaries.append(summary_line(record)[:60])
    return {
        "path": str(root),
        "archive": archive,
        "included": len(included),
        "excluded": excluded,
        "preview": summaries,
    }


def list_packs() -> list[dict[str, Any]]:
    exports_dir = store_root() / "exports"
    if not exports_dir.exists():
        return []
    packs = []
    for manifest_path in sorted(exports_dir.glob("*/manifest.json"), reverse=True):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            packs.append({
                "path": str(manifest_path.parent),
                "name": manifest.get("name"),
                "created_at": manifest.get("created_at"),
                "included": manifest.get("included"),
                "excluded": len(manifest.get("excluded") or []),
            })
        except (OSError, json.JSONDecodeError):
            continue
    return packs
