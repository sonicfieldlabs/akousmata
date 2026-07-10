"""The akousmata navigator server — a library of listened memories.

Local-first FastAPI app over the shared store. Loads no models and runs no
agents: filtering, tagging, editing, manual memories, graph navigation, the
wiki layer, research sessions (optionally LLM-deepened via BYOK), germ
handoff links, and a realtime change feed.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from akousmata_app import AKOUSMATA_CONTRACT, __version__, graph, records, research, wiki
from akousmata_app.paths import open_store, store_root
from akousmata_app.settings import load as load_settings
from akousmata_app.settings import public_view, save as save_settings

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
GERM_MODES = ("sound", "prompt", "lineage")

app = FastAPI(title="akousmata", version=__version__)


class ManualMemory(BaseModel):
    summary: str
    notes: str = ""
    tags: list[str] = []
    heard_at: str | None = None
    place: str | None = None
    kind: str = "heard_live"
    audio_path: str | None = None
    parent_akousma_ids: list[str] = []
    relations: list[dict[str, Any]] = []


class RecordPatch(BaseModel):
    tags: list[str] | None = None
    annotations: dict[str, Any] | None = None
    summary: str | None = None


class RelationBody(BaseModel):
    type: str
    target_akousma_id: str
    note: str | None = None


class ForgetBody(BaseModel):
    delete_audio: bool = False


class ResearchBody(BaseModel):
    question: str
    seed_ids: list[str] = []
    tags: list[str] = []
    max_steps: int = 4


class SettingsPatch(BaseModel):
    germ_url: str | None = None
    oida_url: str | None = None
    llm: dict[str, Any] | None = None


def _store():
    try:
        return open_store()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> dict[str, Any]:
    store = _store()
    try:
        info = records.stats(store)
        return {
            "app": "akousmata",
            "version": __version__,
            "contract": AKOUSMATA_CONTRACT,
            "store_path": str(store_root()),
            **info,
        }
    finally:
        store.close()


@app.get("/api/records")
def list_records(
    app_filter: str | None = None,
    origin: str | None = None,
    source_type: str | None = None,
    tag: str | None = None,
    text: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    store = _store()
    try:
        found = records.list_records(
            store,
            app=app_filter,
            origin=origin,
            source_type=source_type,
            tag=tag,
            text=text,
            since=since,
            until=until,
            limit=max(1, min(limit, 1000)),
        )
        return {"records": [records.card(r) for r in found]}
    finally:
        store.close()


@app.post("/api/records")
def create_record(body: ManualMemory) -> dict[str, Any]:
    if not body.summary.strip():
        raise HTTPException(status_code=400, detail="summary is required")
    store = _store()
    try:
        try:
            record = records.create_manual_memory(
                store,
                summary=body.summary,
                notes=body.notes,
                tags=body.tags,
                heard_at=body.heard_at,
                place=body.place,
                kind=body.kind,
                audio_path=body.audio_path,
                parent_akousma_ids=body.parent_akousma_ids,
                relations=body.relations,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        wiki.ingest(store, record["akousma_id"])
        return {"record": record}
    finally:
        store.close()


@app.get("/api/records/{akousma_id}")
def record_detail(akousma_id: str) -> dict[str, Any]:
    store = _store()
    try:
        found = records.detail(store, akousma_id)
        if found is None:
            raise HTTPException(status_code=404, detail=f"akousma not found: {akousma_id}")
        return found
    finally:
        store.close()


@app.patch("/api/records/{akousma_id}")
def patch_record(akousma_id: str, body: RecordPatch) -> dict[str, Any]:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    store = _store()
    try:
        try:
            record = records.update_record(store, akousma_id, patch)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        wiki.ingest(store, akousma_id)
        return {"record": record}
    finally:
        store.close()


@app.post("/api/records/{akousma_id}/relations")
def add_relation(akousma_id: str, body: RelationBody) -> dict[str, Any]:
    store = _store()
    try:
        try:
            record = records.add_relation(store, akousma_id, body.type, body.target_akousma_id, body.note)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        wiki.ingest(store, akousma_id)
        return {"record": record}
    finally:
        store.close()


@app.delete("/api/records/{akousma_id}/relations")
def delete_relation(akousma_id: str, type: str, target_akousma_id: str) -> dict[str, Any]:
    store = _store()
    try:
        try:
            record = records.remove_relation(store, akousma_id, type, target_akousma_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        wiki.ingest(store, akousma_id)
        return {"record": record}
    finally:
        store.close()


@app.post("/api/records/{akousma_id}/forget")
def forget(akousma_id: str, body: ForgetBody) -> dict[str, Any]:
    store = _store()
    try:
        if not hasattr(store, "forget"):
            raise HTTPException(status_code=501, detail="py-akousma >= 0.2.1 required for forget()")
        removed = store.forget(akousma_id, delete_audio=body.delete_audio)
        if not removed:
            raise HTTPException(status_code=404, detail=f"akousma not found: {akousma_id}")
        wiki.log_append("forget", akousma_id, "record removed; inbound edges remain as absence")
        return {"forgotten": akousma_id}
    finally:
        store.close()


@app.get("/api/audio/{akousma_id}")
def audio(akousma_id: str):
    store = _store()
    try:
        record = store.get(akousma_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"akousma not found: {akousma_id}")
        path = records.resolve_audio_path(store, record)
        if path is None:
            raise HTTPException(status_code=404, detail="no resolvable audio for this memory")
        return FileResponse(path)
    finally:
        store.close()


@app.get("/api/tags")
def tags() -> dict[str, Any]:
    store = _store()
    try:
        return {"tags": store.tags() if hasattr(store, "tags") else []}
    finally:
        store.close()


@app.get("/api/graph")
def get_graph(focus: str | None = None, depth: int = 2, limit: int = 400) -> dict[str, Any]:
    store = _store()
    try:
        if focus:
            return graph.neighborhood(store, focus, depth=max(1, min(depth, 4)), limit=max(10, min(limit, 500)))
        return graph.full_graph(store, limit=max(10, min(limit, 800)))
    finally:
        store.close()


@app.get("/api/germ-link/{akousma_id}")
def germ_link(akousma_id: str, mode: str = "sound") -> dict[str, Any]:
    if mode not in GERM_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {GERM_MODES}")
    store = _store()
    try:
        if store.get(akousma_id) is None:
            raise HTTPException(status_code=404, detail=f"akousma not found: {akousma_id}")
    finally:
        store.close()
    base = str(load_settings().get("germ_url") or "http://127.0.0.1:5178").rstrip("/")
    return {
        "akousma_id": akousma_id,
        "mode": mode,
        "germ_url": f"{base}/import?{urlencode({'akousma': akousma_id, 'mode': mode})}",
    }


# ── wiki ─────────────────────────────────────────────────────────────────────

@app.get("/api/wiki")
def wiki_index() -> dict[str, Any]:
    pages = wiki.list_pages()  # also ensures the wiki directories exist
    root = store_root() / "wiki" / "index.md"
    return {"pages": pages, "index": root.read_text(encoding="utf-8") if root.exists() else None}


@app.get("/api/wiki/page/{kind}/{name}")
def wiki_page(kind: str, name: str) -> dict[str, Any]:
    text = wiki.read_page(kind, name)
    if text is None:
        raise HTTPException(status_code=404, detail=f"no {kind} page named {name}")
    return {"kind": kind, "name": name, "markdown": text}


@app.post("/api/wiki/rebuild")
def wiki_rebuild() -> dict[str, Any]:
    store = _store()
    try:
        return wiki.rebuild(store)
    finally:
        store.close()


@app.post("/api/wiki/ingest/{akousma_id}")
def wiki_ingest(akousma_id: str) -> dict[str, Any]:
    store = _store()
    try:
        try:
            return wiki.ingest(store, akousma_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        store.close()


@app.get("/api/wiki/lint")
def wiki_lint() -> dict[str, Any]:
    store = _store()
    try:
        return wiki.lint(store)
    finally:
        store.close()


# ── research ─────────────────────────────────────────────────────────────────

@app.post("/api/research")
def start_research(body: ResearchBody) -> dict[str, Any]:
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="question is required")
    session = research.start(
        body.question,
        seed_ids=body.seed_ids,
        tags=body.tags,
        max_steps=body.max_steps,
    )
    return {"session_id": session.id}


@app.get("/api/research")
def research_sessions() -> dict[str, Any]:
    return {"sessions": research.list_sessions()}


@app.get("/api/research/{session_id}/events")
async def research_events(session_id: str) -> StreamingResponse:
    session = research.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"unknown research session: {session_id}")

    async def stream():
        cursor = 0
        while True:
            while cursor < len(session.events):
                yield f"data: {json.dumps(session.events[cursor], ensure_ascii=False)}\n\n"
                cursor += 1
            if session.done and cursor >= len(session.events):
                yield f"data: {json.dumps({'kind': 'end', 'result_slug': session.result_slug, 'mode': session.mode})}\n\n"
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── realtime change feed ─────────────────────────────────────────────────────

@app.get("/api/events")
async def change_events() -> StreamingResponse:
    async def stream():
        cursor = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        while True:
            await asyncio.sleep(2.0)
            store = open_store()
            try:
                fresh = store.changed_since(cursor, limit=50) if hasattr(store, "changed_since") else []
            finally:
                store.close()
            for record in fresh:
                cursor = max(cursor, str(record.get("created_at") or cursor))
                yield f"data: {json.dumps(records.card(record), ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── settings ─────────────────────────────────────────────────────────────────

@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return public_view()


@app.put("/api/settings")
def put_settings(body: SettingsPatch) -> dict[str, Any]:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    llm = patch.get("llm")
    if isinstance(llm, dict) and str(llm.get("api_key") or "").startswith("•"):
        llm.pop("api_key")  # masked value round-tripped from the UI: keep the stored key
    return public_view(save_settings(patch))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main() -> None:
    import os

    import uvicorn

    uvicorn.run(app, host=os.getenv("AKOUSMATA_HOST", "127.0.0.1"), port=int(os.getenv("AKOUSMATA_PORT", "5180")))


if __name__ == "__main__":
    main()
