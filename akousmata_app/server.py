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

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from akousmata_app import AKOUSMATA_CONTRACT, __version__, constellations, exports, graph, records, research, similar, watcher, wiki
from akousmata_app.paths import open_store, store_root
from akousmata_app.settings import load as load_settings
from akousmata_app.settings import public_view, save as save_settings

_PACKAGED_STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR = _PACKAGED_STATIC_DIR if _PACKAGED_STATIC_DIR.exists() else Path(__file__).resolve().parents[1] / "static"
GERM_MODES = ("sound", "prompt", "lineage")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os

    settings = load_settings()
    watcher_settings = settings.get("watcher") or {}
    if os.getenv("AKOUSMATA_WATCHER", "1") != "0" and watcher_settings.get("enabled", True):
        watcher.start(
            ingest_seconds=float(watcher_settings.get("ingest_seconds", 60)),
            lint_minutes=float(watcher_settings.get("lint_minutes", 30)),
        )
    yield
    watcher.stop()


app = FastAPI(title="akousmata", version=__version__, lifespan=lifespan)


class ManualMemory(BaseModel):
    summary: str
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    heard_at: str | None = None
    place: str | None = None
    kind: str = "heard_live"
    audio_path: str | None = None
    parent_akousma_ids: list[str] = Field(default_factory=list)
    relations: list[dict[str, Any]] = Field(default_factory=list)
    location: dict[str, Any] | None = None


class RecordPatch(BaseModel):
    tags: list[str] | None = None
    annotations: dict[str, Any] | None = None
    summary: str | None = None
    location: dict[str, Any] | None = None  # {} clears; {lat, lon, …} sets


class RelationBody(BaseModel):
    type: str
    target_akousma_id: str
    note: str | None = None


class ForgetBody(BaseModel):
    delete_audio: bool = False


class ResearchBody(BaseModel):
    question: str
    seed_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    max_steps: int = 4


class SettingsPatch(BaseModel):
    germ_url: str | None = None
    oida_url: str | None = None
    llm: dict[str, Any] | None = None
    watcher: dict[str, Any] | None = None


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
                location=body.location,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
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
            raise HTTPException(status_code=501, detail="py-akousma >= 0.2.2 required for forget()")
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


@app.get("/api/map")
def map_view() -> dict[str, Any]:
    """The listening map's feed — every located memory, plus the unlocated count."""
    store = _store()
    try:
        return records.map_points(store)
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
        # One long-lived read connection per subscriber instead of a fresh
        # connect + DDL pass every poll; WAL autocommit reads always see the
        # latest snapshot. Reopened once on any error.
        store = None
        try:
            while True:
                await asyncio.sleep(2.0)
                try:
                    if store is None:
                        store = open_store()
                    fresh = store.changed_since(cursor, limit=50) if hasattr(store, "changed_since") else []
                except Exception:
                    if store is not None:
                        store.close()
                    store = None
                    continue
                for record in fresh:
                    cursor = max(cursor, str(record.get("created_at") or cursor))
                    yield f"data: {json.dumps(records.card(record), ensure_ascii=False)}\n\n"
        finally:
            if store is not None:
                store.close()

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── constellations ───────────────────────────────────────────────────────────

class ConstellationBody(BaseModel):
    name: str
    note: str = ""
    akousma_ids: list[str] = Field(default_factory=list)


class ConstellationPatch(BaseModel):
    name: str | None = None
    note: str | None = None
    akousma_ids: list[str] | None = None


class MemberBody(BaseModel):
    akousma_id: str


@app.get("/api/constellations")
def list_constellations() -> dict[str, Any]:
    return {"constellations": constellations.list_constellations()}


@app.post("/api/constellations")
def create_constellation(body: ConstellationBody) -> dict[str, Any]:
    try:
        return {"constellation": constellations.create(body.name, body.note, body.akousma_ids)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/constellations/{constellation_id}")
def get_constellation(constellation_id: str) -> dict[str, Any]:
    item = constellations.get(constellation_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"constellation not found: {constellation_id}")
    store = _store()
    try:
        return {"constellation": constellations.resolve(store, item)}
    finally:
        store.close()


@app.patch("/api/constellations/{constellation_id}")
def patch_constellation(constellation_id: str, body: ConstellationPatch) -> dict[str, Any]:
    try:
        return {"constellation": constellations.update(constellation_id, name=body.name, note=body.note, akousma_ids=body.akousma_ids)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/constellations/{constellation_id}/records")
def add_constellation_member(constellation_id: str, body: MemberBody) -> dict[str, Any]:
    try:
        return {"constellation": constellations.add_member(constellation_id, body.akousma_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/constellations/{constellation_id}/records/{akousma_id}")
def remove_constellation_member(constellation_id: str, akousma_id: str) -> dict[str, Any]:
    try:
        return {"constellation": constellations.remove_member(constellation_id, akousma_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/constellations/{constellation_id}")
def delete_constellation(constellation_id: str) -> dict[str, Any]:
    if not constellations.delete(constellation_id):
        raise HTTPException(status_code=404, detail=f"constellation not found: {constellation_id}")
    return {"deleted": constellation_id}


# ── timeline + similarity ────────────────────────────────────────────────────

@app.get("/api/timeline")
def get_timeline(bucket: str = "day") -> dict[str, Any]:
    if bucket not in ("day", "month", "season", "year"):
        raise HTTPException(status_code=400, detail="bucket must be day, month, season, or year")
    store = _store()
    try:
        return records.timeline(store, bucket=bucket)
    finally:
        store.close()


@app.get("/api/records/{akousma_id}/similar")
def get_similar(akousma_id: str, limit: int = 10) -> dict[str, Any]:
    store = _store()
    try:
        try:
            return {"similar": similar.similar(store, akousma_id, limit=limit)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        store.close()


# ── listening diary ──────────────────────────────────────────────────────────

class DiaryBody(BaseModel):
    text: str
    tags: list[str] = Field(default_factory=list)
    place: str | None = None
    location: dict[str, Any] | None = None


@app.post("/api/diary")
def diary_entry(body: DiaryBody) -> dict[str, Any]:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="the diary needs at least a line")
    summary = text.splitlines()[0][:120]
    store = _store()
    try:
        record = records.create_manual_memory(
            store,
            summary=summary,
            notes=text,
            tags=list(dict.fromkeys([*body.tags, "diary"])),
            place=body.place,
            kind="diary",
            location=body.location,
        )
        wiki.ingest(store, record["akousma_id"])
        day = str(record.get("created_at") or "")[:10]
        digest = wiki.diary_digest(store, day)
        return {"record": record, "day": day, "digest": digest}
    finally:
        store.close()


@app.get("/api/diary/{day}")
def diary_day(day: str) -> dict[str, Any]:
    page = wiki.read_page("diary", day)
    if page is None:
        store = _store()
        try:
            page = wiki.diary_digest(store, day)
        finally:
            store.close()
    return {"day": day, "markdown": page}


# ── consent audit + export packs ─────────────────────────────────────────────

class ConsentBody(BaseModel):
    consent_status: str
    rights_note: str | None = None


@app.get("/api/audit/consent")
def audit_consent() -> dict[str, Any]:
    store = _store()
    try:
        return records.consent_audit(store)
    finally:
        store.close()


@app.post("/api/records/{akousma_id}/consent")
def set_consent(akousma_id: str, body: ConsentBody) -> dict[str, Any]:
    store = _store()
    try:
        try:
            record = records.set_consent(store, akousma_id, body.consent_status, body.rights_note)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        wiki.ingest(store, akousma_id)
        return {"record": record}
    finally:
        store.close()


class ExportBody(BaseModel):
    name: str
    akousma_ids: list[str] = Field(default_factory=list)
    constellation_id: str | None = None
    tag: str | None = None
    include_audio: bool = True
    include_wiki: bool = True


@app.post("/api/export")
def export_pack(body: ExportBody) -> dict[str, Any]:
    store = _store()
    try:
        ids = list(body.akousma_ids)
        if body.constellation_id:
            item = constellations.get(body.constellation_id)
            if item is None:
                raise HTTPException(status_code=404, detail=f"constellation not found: {body.constellation_id}")
            ids.extend(item.get("akousma_ids") or [])
        if body.tag:
            ids.extend(record["akousma_id"] for record in store.query(tag=body.tag, limit=1000))
        if not ids:
            raise HTTPException(status_code=400, detail="nothing selected: pass akousma_ids, a constellation_id, or a tag")
        result = exports.build_pack(
            store,
            name=body.name,
            akousma_ids=ids,
            include_audio=body.include_audio,
            include_wiki=body.include_wiki,
        )
        wiki.log_append("export", body.name, f"{result['included']} included, {len(result['excluded'])} blocked")
        return result
    finally:
        store.close()


@app.get("/api/exports")
def list_exports() -> dict[str, Any]:
    return {"packs": exports.list_packs()}


# ── oída round-trip: listen again ────────────────────────────────────────────

class ListenAgainBody(BaseModel):
    preset: str = "basic"


@app.post("/api/records/{akousma_id}/listen-again")
def listen_again(akousma_id: str, body: ListenAgainBody) -> dict[str, Any]:
    import json as _json
    import time as _time
    import urllib.request

    store = _store()
    try:
        record = store.get(akousma_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"akousma not found: {akousma_id}")
        path = records.resolve_audio_path(store, record)
        if path is None:
            raise HTTPException(status_code=409, detail="this memory has no resolvable audio to listen to again")
        oida_url = str(load_settings().get("oida_url") or "http://127.0.0.1:8765").rstrip("/")
        request = urllib.request.Request(
            f"{oida_url}/gateway/listen",
            data=_json.dumps({"path": str(path), "route_preset": body.preset, "remember": False}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                gateway_result = _json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — any transport failure reads the same to the user
            raise HTTPException(status_code=502, detail=f"oída did not answer at {oida_url}: {exc}") from exc

        event = gateway_result.get("listening_event") if isinstance(gateway_result.get("listening_event"), dict) else {}
        command_output = gateway_result.get("command_output") if isinstance(gateway_result.get("command_output"), dict) else {}
        aggregate = event.get("aggregate") if isinstance(event.get("aggregate"), dict) else {}
        compact = {
            "route_preset": body.preset,
            "event_id": event.get("id"),
            "title": aggregate.get("title"),
            "short_summary": aggregate.get("short_summary"),
            "detailed_summary": aggregate.get("detailed_summary"),
            "claims": command_output.get("claim_summary"),
            "routes": event.get("routes"),
            "apparatus": (command_output.get("outputs") or [{}])[0].get("apparatus") if isinstance(command_output.get("outputs"), list) else None,
            "perception_path": gateway_result.get("perception_path"),
            "source_contract": gateway_result.get("contract"),
        }
        listening = record.setdefault("listening", {})
        # The navigator owns this wrapper entry. Oída owns the embedded pass,
        # whose gateway contract is pinned inside the payload; never write or
        # rewrite another producer's namespace from Akousmata.
        namespace = "akousmata.listen_again"
        counter = 2
        while namespace in listening:
            namespace = f"akousmata.listen_again.{counter}"
            counter += 1
        listening[namespace] = {
            "contract": AKOUSMATA_CONTRACT,
            "created_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
            "summary": compact.get("short_summary") or compact.get("title") or "fresh oída pass",
            "payload": compact,
        }
        store.put(record)
        wiki.ingest(store, akousma_id)
        return {
            "namespace": namespace,
            "listening": listening[namespace],
            "record": record,
            "gateway": {"contract": gateway_result.get("contract"), "perception_path": gateway_result.get("perception_path")},
        }
    finally:
        store.close()


# ── watcher status ───────────────────────────────────────────────────────────

@app.get("/api/watcher")
def watcher_status() -> dict[str, Any]:
    return watcher.status()


@app.post("/api/watcher/run")
def watcher_run(lint: bool = True) -> dict[str, Any]:
    try:
        return watcher.run_once(lint=lint)
    except Exception as exc:  # noqa: BLE001 — surfaced as a maintenance failure
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── settings ─────────────────────────────────────────────────────────────────

@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return public_view()


@app.put("/api/settings")
def put_settings(body: SettingsPatch) -> dict[str, Any]:
    import os

    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    llm = patch.get("llm")
    if isinstance(llm, dict) and str(llm.get("api_key") or "").startswith("•"):
        llm.pop("api_key")  # masked value round-tripped from the UI: keep the stored key
    saved = save_settings(patch)
    watcher_settings = saved.get("watcher") or {}
    if os.getenv("AKOUSMATA_WATCHER", "1") != "0" and watcher_settings.get("enabled", True):
        watcher.restart(
            ingest_seconds=float(watcher_settings.get("ingest_seconds", 60)),
            lint_minutes=float(watcher_settings.get("lint_minutes", 30)),
        )
    else:
        watcher.stop()
    return public_view(saved)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main() -> None:
    import os

    import uvicorn

    uvicorn.run(app, host=os.getenv("AKOUSMATA_HOST", "127.0.0.1"), port=int(os.getenv("AKOUSMATA_PORT", "5180")))


if __name__ == "__main__":
    main()
