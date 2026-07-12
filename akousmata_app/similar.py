"""Kin by resemblance over stored features and optional local embeddings.

No models: similarity is computed from what the memories already carry —
shared tags, overlapping description tokens, duration proximity, and (when
producers stored them) overlapping numeric features. A producer may also
store a local embedding vector; Akousmata compares it but never calls a remote
embedding service. Every score comes with its basis, so resemblance stays an
argument, not an oracle.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

from akousmata_app.records import card, summary_line

_TOKEN_RE = re.compile(r"[a-zà-öø-ÿ]{3,}")
_STOP = {
    "the", "and", "with", "from", "that", "this", "for", "over", "under", "into",
    "una", "los", "las", "del", "con", "por", "para", "que", "sound", "audio",
}


def _tokens(record: dict[str, Any]) -> set[str]:
    parts = [summary_line(record)]
    for entry in (record.get("listening") or {}).values():
        if isinstance(entry, dict):
            payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else entry
            for key in ("caption", "summary", "notes", "main_reading", "brief"):
                value = payload.get(key) if isinstance(payload, dict) else None
                if isinstance(value, str):
                    parts.append(value)
            if isinstance(entry.get("summary"), str):
                parts.append(entry["summary"])
    text = " ".join(parts).lower()
    return {t for t in _TOKEN_RE.findall(text) if t not in _STOP}


def _features(record: dict[str, Any]) -> dict[str, float]:
    found: dict[str, float] = {}
    for entry in (record.get("listening") or {}).values():
        if not isinstance(entry, dict):
            continue
        payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else entry
        features = payload.get("features") if isinstance(payload, dict) else None
        if isinstance(features, dict):
            for key, value in features.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    found[str(key)] = float(value)
    return found


def _embedding(record: dict[str, Any]) -> list[float] | None:
    """Find an already-computed local embedding without generating one."""
    candidates: list[Any] = []
    app_extension = (record.get("extensions") or {}).get("akousmata.app") or {}
    if isinstance(app_extension, dict):
        candidates.extend([app_extension.get("embedding"), app_extension.get("embedding_vector")])
    for entry in (record.get("listening") or {}).values():
        if not isinstance(entry, dict):
            continue
        payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else entry
        if isinstance(payload, dict):
            candidates.extend([payload.get("embedding"), payload.get("embedding_vector")])
    for candidate in candidates:
        if (
            isinstance(candidate, list)
            and len(candidate) >= 2
            and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in candidate)
        ):
            return [float(value) for value in candidate]
    return None


def _embedding_cosine(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right):
        return None
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm <= 1e-12 or right_norm <= 1e-12:
        return None
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


_CORPUS_CACHE: dict[str, Any] = {"key": None, "items": []}


def _corpus(store) -> list[dict[str, Any]]:
    """Parsed records with precomputed tokens/features/embeddings, cached per
    process. The key changes on any write: INSERT OR REPLACE assigns a fresh
    rowid and forget() changes the count, so edits invalidate it too."""
    row = store.conn.execute("SELECT COUNT(*) AS n, MAX(rowid) AS r FROM akousmata").fetchone()
    key = (row["n"], row["r"])
    if _CORPUS_CACHE["key"] != key:
        items = []
        for db_row in store.conn.execute("SELECT record FROM akousmata").fetchall():
            record = json.loads(db_row["record"])
            items.append({
                "record": record,
                "tokens": _tokens(record),
                "features": _features(record),
                "embedding": _embedding(record),
            })
        _CORPUS_CACHE["key"] = key
        _CORPUS_CACHE["items"] = items
    return _CORPUS_CACHE["items"]


def similar(store, akousma_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
    origin = store.get(akousma_id)
    if origin is None:
        raise KeyError(f"akousma not found: {akousma_id}")
    origin_tags = set(origin.get("tags") or [])
    origin_tokens = _tokens(origin)
    origin_features = _features(origin)
    origin_embedding = _embedding(origin)
    origin_duration = (origin.get("audio") or {}).get("duration_seconds")
    origin_hash = (origin.get("audio") or {}).get("content_hash")

    scored: list[dict[str, Any]] = []
    for item in _corpus(store):
        record = item["record"]
        if record["akousma_id"] == akousma_id:
            continue
        score = 0.0
        basis: list[str] = []

        if origin_hash and (record.get("audio") or {}).get("content_hash") == origin_hash:
            score += 1.0
            basis.append("identical audio content")

        tags = set(record.get("tags") or [])
        shared_tags = origin_tags & tags
        if shared_tags:
            score += 0.45 * len(shared_tags) / max(1, len(origin_tags | tags))
            basis.append("shared tags: " + ", ".join(sorted(shared_tags)[:4]))

        tokens = item["tokens"]
        shared_tokens = origin_tokens & tokens
        if shared_tokens and origin_tokens and tokens:
            cosine = len(shared_tokens) / math.sqrt(len(origin_tokens) * len(tokens))
            if cosine > 0.08:
                score += 0.4 * cosine
                basis.append("description overlap: " + ", ".join(sorted(shared_tokens)[:5]))

        duration = (record.get("audio") or {}).get("duration_seconds")
        if isinstance(origin_duration, (int, float)) and isinstance(duration, (int, float)) and max(origin_duration, duration) > 0:
            proximity = 1.0 - min(1.0, abs(origin_duration - duration) / max(origin_duration, duration))
            if proximity > 0.8:
                score += 0.08 * proximity
                basis.append("similar duration")

        features = item["features"]
        shared_keys = [k for k in origin_features if k in features]
        if len(shared_keys) >= 3:
            distances = []
            for key in shared_keys:
                a, b = origin_features[key], features[key]
                denominator = max(abs(a), abs(b), 1e-6)
                distances.append(min(1.0, abs(a - b) / denominator))
            closeness = 1.0 - sum(distances) / len(distances)
            if closeness > 0.5:
                score += 0.35 * closeness
                basis.append(f"feature closeness over {len(shared_keys)} shared measurements")

        embedding = item["embedding"]
        if origin_embedding is not None and embedding is not None:
            cosine = _embedding_cosine(origin_embedding, embedding)
            if cosine is not None and cosine > 0.2:
                score += 0.6 * max(0.0, cosine)
                basis.append(f"local embedding cosine {cosine:.3f} ({len(embedding)} dimensions)")

        if score > 0.05 and basis:
            scored.append({"card": card(record), "score": round(min(score, 1.0), 3), "basis": basis})

    scored.sort(key=lambda item: -item["score"])
    return scored[: max(1, min(limit, 50))]
