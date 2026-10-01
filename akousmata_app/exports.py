"""Export packs — a selection of memories as a shareable research bundle.

A pack contains allowlisted metadata projections (JSONL), matching wiki pages,
optional owner-selected audio, and a manifest. Exclusion identities and reasons
stay in the owner response; only a count is retained beside the archive. Public
packs additionally require current host-owned grants and never include audio.
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
PROJECTION_CONTRACT = "akousmata/public-record/v1"
PROJECTION_FIELDS = {"summary", "subject", "tags", "provenance", "audio_metadata", "listener_types"}
DEFAULT_EXPORT_FIELDS = ("summary", "subject", "tags", "provenance", "audio_metadata")


def claim_clock() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def exportable(record: dict[str, Any]) -> tuple[bool, str]:
    claims = record.get("extensions", {}).get("earworm_listening_context", {}).get("claims", [])
    if claims:
        from akousma.listening_context import claim_validity_at
        now = claim_clock()
        try:
            if any(claim_validity_at(claim, now) != "current" for claim in claims):
                return False, "receiving claim currency is not current; owner review required"
        except (ValueError, TypeError, KeyError):
            return False, "invalid receiving claim validity"
    consent = str((record.get("provenance") or {}).get("consent_status") or "unknown")
    if consent in EXPORTABLE_CONSENT:
        return True, consent
    return False, f"consent_status is '{consent}' (needs owned/licensed/public_domain)"


def checked_fields(fields) -> list[str]:
    if (not isinstance(fields, (list, tuple)) or any(not isinstance(f, str) for f in fields)
            or len(set(fields)) != len(fields) or not set(fields) <= PROJECTION_FIELDS):
        raise ValueError("projection fields must be unique members of " + ", ".join(sorted(PROJECTION_FIELDS)))
    return sorted(fields)


def sanitize(record: dict[str, Any], *, include_audio: bool,
             fields=DEFAULT_EXPORT_FIELDS) -> dict[str, Any]:
    """Explicit metadata projection, never a rewritten canonical akousma.

    Callers establish authority first. Public callers use host-local grants;
    owner-selected packs use the existing consent gate. Raw reports, claims,
    extensions, identities, locations and lineage are not implicitly exported.
    """
    fields = checked_fields(fields)
    clean = {"projection_contract": PROJECTION_CONTRACT, "akousma_id": record["akousma_id"],
             "created_at": record["created_at"], "source_schema_version": record["schema_version"]}
    for key in ("summary", "subject"):
        if key in fields and isinstance(record.get(key), str):
            clean[key] = record[key]
    if "tags" in fields:
        clean["tags"] = [tag for tag in record.get("tags", []) if isinstance(tag, str)]
    if "provenance" in fields:
        source = record.get("provenance") or {}
        clean["provenance"] = {key: source[key] for key in ("originating_app", "origin", "source_type", "consent_status")
                               if isinstance(source.get(key), str)}
    if "audio_metadata" in fields:
        source = record.get("audio") or {}
        audio = {key: source[key] for key in ("duration_seconds", "sample_rate", "channels")
                 if type(source.get(key)) in (int, float)}
        # A pack URI is added only after the selected file is copied successfully.
        if audio or include_audio:
            clean["audio"] = audio
    if "listener_types" in fields:
        from akousmata_app.records import listener_types
        clean["listener_types"] = listener_types(record)
    clean = _sanitize_value(clean)
    json.dumps(clean, allow_nan=False)
    if "akousma_id" not in clean:
        raise ValueError("record identity is not suitable for a public projection")
    return clean


class _PackView:
    """Wiki rendering may consult only records already projected into the pack."""
    def children(self, _record_id):
        return []  # Lineage is outside the metadata projection contract.


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
    audience: str = "selection",
    fields=DEFAULT_EXPORT_FIELDS,
) -> dict[str, Any]:
    if audience not in {"selection", "public"}:
        raise ValueError("audience must be selection or public")
    fields = checked_fields(fields)
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

    for akousma_id in dict.fromkeys(akousma_ids):
        record = store.get(akousma_id)
        if record is None:
            excluded.append({"akousma_id": akousma_id, "reason": "record not found (forgotten or never existed)"})
            continue
        ok, reason = exportable(record)
        if not ok:
            excluded.append({"akousma_id": akousma_id, "reason": reason})
            continue
        audio_path = resolve_audio_path(store, record) if include_audio and audience == "selection" else None
        if audio_path is not None and (not audio_path.is_file() or audio_path.suffix.lower().lstrip(".") not in AUDIO_EXTENSIONS):
            audio_path = None
        if audience == "public":
            from akousmata_app.publication import public_record
            clean = public_record(store, akousma_id)
            if clean is None:
                excluded.append({"akousma_id": akousma_id, "reason": "no current public projection grant"})
                continue
            # Metadata approval never grants export of the underlying audio bytes.
            audio_path = None
        else:
            clean = sanitize(record, include_audio=audio_path is not None, fields=fields)
            if "audio_metadata" not in fields:
                audio_path = None
        # Names reveal only included positions, never gaps from private records.
        position = len(included) + 1
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
            target.write_text(wiki.record_page(_PackView(), clean), encoding="utf-8")
            files.append({"kind": "wiki", "akousma_id": akousma_id, "path": f"wiki/{wiki_name}", "bytes": target.stat().st_size})

    (root / "records" / "records.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    manifest = {
        "name": _sanitize_value(name) or "export",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "navigator_version": __version__,
        "included": len(included),
        "included_ids": included,
        "excluded": [],
        "exclusion_details": "owner response only",
        "projection_contract": PROJECTION_CONTRACT,
        "audience": audience,
        "include_audio": include_audio and audience == "selection" and "audio_metadata" in fields,
        "include_wiki": include_wiki,
        "files": files,
        "consent_rule": "records outside owned/licensed/public_domain are blocked; exclusion details remain in the owner response",
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    archive = shutil.make_archive(str(root), "zip", root_dir=root)
    root.with_suffix(".owner.json").write_text(json.dumps({"excluded": len(excluded)}) + "\n", encoding="utf-8")
    summaries = [summary_line(json.loads(line))[:60] for line in lines[:5]]
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
            owner_path = manifest_path.parent.with_suffix(".owner.json")
            excluded = (json.loads(owner_path.read_text(encoding="utf-8"))["excluded"]
                        if owner_path.exists() else len(manifest.get("excluded") or []))
            packs.append({
                "path": str(manifest_path.parent),
                "name": manifest.get("name"),
                "created_at": manifest.get("created_at"),
                "included": manifest.get("included"),
                "excluded": excluded,
            })
        except (OSError, json.JSONDecodeError):
            continue
    return packs
