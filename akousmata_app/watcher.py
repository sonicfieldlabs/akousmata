"""Durable scheduled auto-ingest and wiki lint for Akousmata."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from akousmata_app.paths import store_root

_EPOCH = "1970-01-01T00:00:00Z"
_STATE: dict[str, Any] = {
    "enabled": False,
    "started_at": None,
    "last_ingest_at": None,
    "ingested_count": 0,
    "last_lint_at": None,
    "last_lint_issues": None,
    "last_error": None,
    "cursor": {"created_at": _EPOCH, "akousma_id": ""},
}
_STOP = threading.Event()
_THREAD: threading.Thread | None = None
_LOCK = threading.RLock()


def status() -> dict[str, Any]:
    with _LOCK:
        return json.loads(json.dumps(_STATE))


def _state_path() -> Path:
    return store_root() / "watcher-state.json"


def _load_cursor() -> tuple[str, str]:
    path = _state_path()
    if not path.exists():
        return _EPOCH, ""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        cursor = value.get("cursor") if isinstance(value, dict) else {}
        created_at = str(cursor.get("created_at") or _EPOCH)
        akousma_id = str(cursor.get("akousma_id") or "")
        return created_at, akousma_id
    except (OSError, json.JSONDecodeError):
        return _EPOCH, ""


def _save_cursor(created_at: str, akousma_id: str) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "0.2",
        "updated_at": _now(),
        "cursor": {"created_at": created_at, "akousma_id": akousma_id},
    }
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)
    with _LOCK:
        _STATE["cursor"] = dict(payload["cursor"])


def _lint_issue_count(report: dict[str, Any]) -> int:
    count = 0
    for value in report.values():
        if isinstance(value, list):
            count += len(value)
        elif isinstance(value, dict):
            count += _lint_issue_count(value)
    return count


def run_once(*, lint: bool = False, batch_size: int = 100) -> dict[str, Any]:
    """Reconcile every record after the durable cursor, then optionally lint."""
    from akousmata_app import wiki
    from akousmata_app.paths import open_store

    cursor_at, cursor_id = _load_cursor()
    ingested = 0
    diary_days: set[str] = set()
    store = open_store()
    try:
        while True:
            if hasattr(store, "changed_since"):
                try:
                    fresh = store.changed_since(cursor_at, after_id=cursor_id, limit=batch_size)
                except TypeError:
                    fresh = store.changed_since(cursor_at, limit=batch_size)
            else:
                fresh = []
            if not fresh:
                break
            for record in fresh:
                wiki.ingest(store, record["akousma_id"])
                ingested += 1
                created_at = str(record.get("created_at") or cursor_at)
                record_id = str(record.get("akousma_id") or "")
                if (created_at, record_id) > (cursor_at, cursor_id):
                    cursor_at, cursor_id = created_at, record_id
                payload = ((record.get("listening") or {}).get("human.note") or {})
                kind = (payload.get("payload") or {}).get("kind") if isinstance(payload.get("payload"), dict) else None
                if kind == "diary":
                    diary_days.add(created_at[:10])
            _save_cursor(cursor_at, cursor_id)
            if len(fresh) < batch_size:
                break
        for day in sorted(day for day in diary_days if day):
            wiki.diary_digest(store, day)
        lint_report = wiki.lint(store) if lint else None
    finally:
        store.close()

    now = _now()
    with _LOCK:
        _STATE["ingested_count"] += ingested
        if ingested:
            _STATE["last_ingest_at"] = now
        if lint_report is not None:
            _STATE["last_lint_at"] = now
            _STATE["last_lint_issues"] = _lint_issue_count(lint_report)
        _STATE["last_error"] = None
    return {
        "ingested": ingested,
        "cursor": {"created_at": cursor_at, "akousma_id": cursor_id},
        "lint": lint_report,
    }


def _run(ingest_seconds: float, lint_minutes: float) -> None:
    next_lint = time.monotonic()
    # Reconcile immediately on startup; a watcher must also catch records
    # created while the navigator was offline.
    while not _STOP.is_set():
        try:
            lint_due = time.monotonic() >= next_lint
            run_once(lint=lint_due)
            if lint_due:
                next_lint = time.monotonic() + lint_minutes * 60
        except Exception as exc:  # noqa: BLE001 — maintenance must stay alive
            with _LOCK:
                _STATE["last_error"] = str(exc)
        if _STOP.wait(max(0.1, ingest_seconds)):
            break


def start(*, ingest_seconds: float = 60.0, lint_minutes: float = 30.0) -> None:
    global _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return
        cursor_at, cursor_id = _load_cursor()
        _STOP.clear()
        _STATE.update(
            {
                "enabled": True,
                "started_at": _now(),
                "last_error": None,
                "cursor": {"created_at": cursor_at, "akousma_id": cursor_id},
                "ingest_seconds": ingest_seconds,
                "lint_minutes": lint_minutes,
            }
        )
        _THREAD = threading.Thread(
            target=_run,
            args=(max(0.1, ingest_seconds), max(0.01, lint_minutes)),
            name="akousmata-watcher",
            daemon=True,
        )
        _THREAD.start()


def restart(*, ingest_seconds: float = 60.0, lint_minutes: float = 30.0) -> None:
    stop()
    start(ingest_seconds=ingest_seconds, lint_minutes=lint_minutes)


def stop() -> None:
    global _THREAD
    _STOP.set()
    thread = _THREAD
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=2.0)
    with _LOCK:
        _STATE["enabled"] = False
        _THREAD = None


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
