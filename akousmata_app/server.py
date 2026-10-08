"""The akousmata navigator server — a library of listened memories.

Local-first FastAPI app over the shared store. Loads no models and runs no
agents: filtering, tagging, editing, manual memories, graph navigation, the
wiki layer, research sessions (optionally LLM-deepened via BYOK), optional
GERM handoff links, and a realtime change feed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from akousmata_app import AKOUSMATA_CONTRACT, __version__, constellations, exports, graph, publication, records, research, similar, watcher, wiki
from akousmata_app.llm import validate_http_url
from akousmata_app.paths import open_store, store_root
from akousmata_app.request_boundary import RequestBoundary
from akousmata_app.settings import SettingsPatch, ensure_human_profile, load as load_settings
from akousmata_app.settings import public_view, save as save_settings, update_human_profile

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
_REQUEST_BOUNDARY = RequestBoundary.from_env()
public_router = APIRouter(prefix="/api/public")
_WORKSPACE_ID = os.getenv("LISTENINGSTACK_WORKSPACE_ID")
_WORKSPACE_GENERATION = os.getenv("LISTENINGSTACK_WORKSPACE_GENERATION")
_WORKSPACE_BINDING = hashlib.sha256(
    json.dumps(
        ["akousmata", _WORKSPACE_ID, _WORKSPACE_GENERATION, str(store_root().expanduser().resolve())],
        separators=(",", ":"),
    ).encode()
).hexdigest()


@app.exception_handler(RequestValidationError)
async def invalid_request(_request: Request, exc: RequestValidationError):
    # Do not echo private input fields. Non-finite JSON input also cannot be
    # serialized by JSONResponse when included in the default error payload.
    detail = [{key: error[key] for key in ("type", "loc", "msg")} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": detail})


def _owner_open(request, *, timeout):
    import urllib.request

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect()
    ).open(request, timeout=timeout)


def _bound_owner_headers(base_url: str, owner: str) -> dict[str, str]:
    if not _WORKSPACE_ID or not _WORKSPACE_GENERATION:
        return {}
    import urllib.request

    try:
        request = urllib.request.Request(base_url.rstrip("/") + "/owner/identity")
        with _owner_open(request, timeout=2) as response:
            raw = response.read(16385)
        if len(raw) > 16384:
            raise ValueError("owner identity is too large")
        identity = json.loads(raw)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"{owner} identity is unavailable") from exc
    if (
        not isinstance(identity, dict)
        or identity.get("contract") != "centaur/owner-identity/v1"
        or identity.get("owner") != owner
        or identity.get("workspace_id") != _WORKSPACE_ID
        or identity.get("generation") != _WORKSPACE_GENERATION
        or not isinstance(identity.get("binding"), str)
    ):
        raise HTTPException(status_code=409, detail=f"{owner} workspace binding does not match Akousmata")
    return {
        "X-Centaur-Workspace": _WORKSPACE_ID,
        "X-Centaur-Generation": _WORKSPACE_GENERATION,
        "X-Centaur-Binding": identity["binding"],
    }


@app.middleware("http")
async def workspace_admission(request: Request, call_next):
    rejection = _REQUEST_BOUNDARY.reject(request)
    if rejection is not None:
        return rejection
    if _WORKSPACE_ID and _WORKSPACE_GENERATION and request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        supplied = (
            request.headers.get("x-centaur-workspace"),
            request.headers.get("x-centaur-generation"),
            request.headers.get("x-centaur-binding"),
        )
        if supplied != (_WORKSPACE_ID, _WORKSPACE_GENERATION, _WORKSPACE_BINDING):
            return JSONResponse(status_code=409, content={"detail": "akousmata refused a stale or mismatched workspace binding"})
    return await call_next(request)


@app.get("/owner/identity")
def owner_identity() -> dict[str, Any]:
    return {
        "contract": "centaur/owner-identity/v1",
        "owner": "akousmata",
        "mode": "workspace" if _WORKSPACE_ID and _WORKSPACE_GENERATION else "legacy",
        "workspace_id": _WORKSPACE_ID,
        "generation": _WORKSPACE_GENERATION,
        "binding": _WORKSPACE_BINDING,
        "pid": os.getpid(),
    }


class ManualMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    heard_at: str | None = None
    place: str | None = None
    kind: str = "heard_live"
    parent_akousma_ids: list[str] = Field(default_factory=list)
    relations: list[dict[str, Any]] = Field(default_factory=list)
    location: dict[str, Any] | None = None
    heard: bool = False
    response_to: str | None = None
    same_source_as: str | None = None
    same_source_verified: bool = False


class HumanRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    heard_at: str | None = None
    place: str | None = None
    kind: str = "heard_live"
    location: dict[str, Any] | None = None
    heard: bool
    reason: str


class HumanProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = ""
    privacy: str = "private"


class RecordPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tags: list[str] | None = None
    annotations: dict[str, Any] | None = None
    summary: str | None = None
    location: dict[str, Any] | None = None  # {} clears; {lat, lon, …} sets


class RelationBody(BaseModel):
    type: str
    target_akousma_id: str
    note: str | None = None
    same_source_verified: bool = False


class ForgetBody(BaseModel):
    delete_audio: bool = False
    actor: str = Field(default="human-operator", min_length=1, max_length=200)
    reason: str = Field(default="explicit forget request", min_length=1, max_length=1000)


class ResearchBody(BaseModel):
    question: str
    seed_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    max_steps: int = 4


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


@public_router.get("/status")
def public_status(response: Response, tag: str | None = None, text: str | None = None) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    store = _store()
    try:
        return publication.public_counts(store, tag=tag, text=text)
    finally:
        store.close()


@public_router.get("/records")
def public_records(response: Response, limit: int = Query(default=50, ge=1, le=200),
                   cursor: str | None = None, tag: str | None = None, text: str | None = None) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    store = _store()
    try:
        try:
            return publication.public_page(store, limit=limit, cursor=cursor, tag=tag, text=text)
        except publication.ViewChanged as exc:
            raise HTTPException(status_code=409, detail=str(exc), headers={"Cache-Control": "no-store"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc), headers={"Cache-Control": "no-store"}) from exc
    finally:
        store.close()


@public_router.get("/records/{akousma_id}")
def public_record(akousma_id: str, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    store = _store()
    try:
        result = publication.public_record(store, akousma_id)
        if result is None:
            raise HTTPException(status_code=404, detail="record not available", headers={"Cache-Control": "no-store"})
        return {"record": result}
    finally:
        store.close()


app.include_router(public_router)


class PublicationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: list[str]


@app.get("/api/records/{akousma_id}/publication")
def publication_status(akousma_id: str) -> dict[str, Any]:
    store = _store()
    try:
        if store.get(akousma_id) is None:
            raise HTTPException(status_code=404, detail="record not found")
        return publication.grant_status(store, akousma_id)
    finally:
        store.close()


@app.post("/api/records/{akousma_id}/publication")
def grant_publication(akousma_id: str, body: PublicationBody) -> dict[str, Any]:
    store = _store()
    try:
        try:
            return publication.grant(store, akousma_id, body.fields)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="record not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


@app.delete("/api/records/{akousma_id}/publication")
def revoke_publication(akousma_id: str) -> dict[str, Any]:
    store = _store()
    try:
        publication.revoke(store, akousma_id)
        return {"state": "revoked"}
    finally:
        store.close()


@app.get("/api/human-profile")
def human_profile() -> dict[str, Any]:
    profile = ensure_human_profile()
    return {
        **profile,
        "local_only": True,
        "note": "The listener id is a local ownership handle, not a global identity or authentication token.",
    }


@app.put("/api/human-profile")
def put_human_profile(body: HumanProfilePatch) -> dict[str, Any]:
    try:
        profile = update_human_profile(display_name=body.display_name, privacy=body.privacy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**profile, "local_only": True}


@app.get("/api/records")
def list_records(
    app_filter: str | None = None,
    origin: str | None = None,
    source_type: str | None = None,
    tag: str | None = None,
    text: str | None = None,
    since: str | None = None,
    until: str | None = None,
    covenant: str | None = None,
    accountable: bool | None = None,
    disagreement: bool | None = None,
    route_decision: bool | None = None,
    stop_decision: bool | None = None,
    listener_type: str | None = None,
    record_class: str | None = None,
    revision_of: str | None = None,
    limit: int = 200,
    subject: str | None = None, recipient: str | None = None,
    human_access: str | None = None, register: str | None = None, scale: str | None = None,
    offset: int = Query(0, ge=0), oldest_first: bool = False,
) -> dict[str, Any]:
    store = _store()
    try:
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
                covenant_id=covenant,
                has_auditum=accountable,
                has_disagreement=disagreement,
                has_route_decision=route_decision,
                has_stop_decision=stop_decision,
                listener_type=listener_type,
                record_class_filter=record_class,
                facets={k:v for k,v in dict(subject=subject,recipient=recipient,human_access=human_access,register=register,scale=scale).items() if v is not None},
                revision_of=revision_of,
                limit=max(1, min(limit, 1000)),
                offset=offset, oldest_first=oldest_first,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        profile = ensure_human_profile()
        return {"records": records.cards(store, found, local_listener_id=profile["listener_id"])}
    finally:
        store.close()


@app.post("/api/human-records")
@app.post("/api/records")
def create_record(body: ManualMemory) -> dict[str, Any]:
    return _create_manual_record(body)


def _human_relations(store, body: ManualMemory) -> list[dict[str, Any]]:
    if body.parent_akousma_ids:
        raise HTTPException(
            status_code=400,
            detail="human/machine links are kinship, not causal parents; use response_to or verified same_source_as",
        )
    requested = [dict(item) for item in body.relations]
    if body.response_to:
        requested.append({
            "type": "response_to",
            "target_akousma_id": body.response_to,
            "note": "local human response to an attributable machine listening",
        })
    if body.same_source_as:
        requested.append({
            "type": "same_source_as",
            "target_akousma_id": body.same_source_as,
            "note": "same source explicitly verified by the local human",
        })
    out: list[dict[str, Any]] = []
    for item in requested:
        rel_type = item.get("type")
        target_id = item.get("target_akousma_id")
        if not isinstance(rel_type, str) or not isinstance(target_id, str) or not target_id:
            raise HTTPException(status_code=400, detail="each relation needs type and target_akousma_id")
        target = store.get(target_id)
        if target is None:
            raise HTTPException(status_code=404, detail=f"akousma not found: {target_id}")
        if rel_type in {"response_to", "same_source_as"} and records.record_class(target) not in {"agent", "hybrid"}:
            raise HTTPException(
                status_code=400,
                detail=f"{rel_type} target must contain an attributable agent or hybrid listening",
            )
        if rel_type == "same_source_as" and not body.same_source_verified:
            raise HTTPException(status_code=400, detail="same_source_as requires explicit source verification")
        out.append(item)
    return out


def _create_manual_record(
    body: ManualMemory,
    *,
    audio_data: bytes | None = None,
    audio_extension: str = "wav",
) -> dict[str, Any]:
    if not body.summary.strip():
        raise HTTPException(status_code=400, detail="summary is required")
    store = _store()
    try:
        try:
            relation_items = _human_relations(store, body)
            record = records.create_manual_memory(
                store,
                summary=body.summary.strip(),
                notes=body.notes,
                tags=body.tags,
                heard_at=body.heard_at,
                place=body.place,
                kind=body.kind,
                audio_data=audio_data,
                audio_extension=audio_extension,
                parent_akousma_ids=[],
                relations=relation_items,
                location=body.location,
                heard=body.heard,
                human_profile=ensure_human_profile(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        wiki.ingest(store, record["akousma_id"])
        return {"record": record}
    finally:
        store.close()


@app.post("/api/human-records/import")
@app.post("/api/records/import")
async def import_record(
    metadata: Annotated[str, Form()],
    audio: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    try:
        body = ManualMemory.model_validate_json(metadata)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="invalid manual-memory metadata") from exc
    filename = audio.filename or ""
    _, separator, extension = filename.rpartition(".")
    if not separator:
        await audio.close()
        raise HTTPException(status_code=400, detail="audio filename needs a supported extension")
    try:
        extension = records.normalize_audio_extension(extension)
    except ValueError as exc:
        await audio.close()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        data = await audio.read(records.MAX_MANUAL_AUDIO_BYTES + 1)
    finally:
        await audio.close()
    if len(data) > records.MAX_MANUAL_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="uploaded audio is larger than 100 MB")
    return _create_manual_record(body, audio_data=data, audio_extension=extension)


@app.get("/api/records/{akousma_id}/listening-relations")
def listening_relations(akousma_id: str, limit: int = 50, cursor: str | None = None):
    from akousmata_app.listening_relations import page, ViewChanged
    store = _store()
    try:
        return page(store, akousma_id, limit=limit, cursor=cursor)
    except KeyError as exc:
        raise HTTPException(404, 'Unknown retained record') from exc
    except ViewChanged as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        store.close()


@app.get("/api/records/{akousma_id}")
def record_detail(akousma_id: str) -> dict[str, Any]:
    store = _store()
    try:
        found = records.detail(store, akousma_id, local_listener_id=ensure_human_profile()["listener_id"])
        if found is None:
            raise HTTPException(status_code=404, detail=f"akousma not found: {akousma_id}")
        return found
    finally:
        store.close()


@app.post("/api/human-records/{akousma_id}/revisions")
def revise_human_record(akousma_id: str, body: HumanRevision) -> dict[str, Any]:
    if not body.summary.strip():
        raise HTTPException(status_code=400, detail="summary is required")
    store = _store()
    try:
        try:
            record = records.revise_human_record(
                store,
                akousma_id,
                human_profile=ensure_human_profile(),
                summary=body.summary.strip(),
                notes=body.notes,
                tags=body.tags,
                heard_at=body.heard_at,
                place=body.place,
                kind=body.kind,
                location=body.location,
                heard=body.heard,
                reason=body.reason,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        wiki.ingest(store, record["akousma_id"])
        return {
            "record": record,
            "revises_akousma_id": akousma_id,
            "revision": records.revision_lifecycle(store, record["akousma_id"]),
        }
    finally:
        store.close()


@app.patch("/api/records/{akousma_id}/curation")
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
        return {"record": record, "operation": "library_curation"}
    finally:
        store.close()


@app.post("/api/records/{akousma_id}/relations")
def add_relation(akousma_id: str, body: RelationBody) -> dict[str, Any]:
    store = _store()
    try:
        try:
            record = records.add_relation(
                store,
                akousma_id,
                body.type,
                body.target_akousma_id,
                body.note,
                local_listener_id=ensure_human_profile()["listener_id"],
                same_source_verified=body.same_source_verified,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
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
        if not hasattr(store, "forget_with_receipt"):
            raise HTTPException(status_code=501, detail="py-akousma >= 0.6.0 required for forgetting receipts")
        receipt = store.forget_with_receipt(
            akousma_id,
            delete_audio=body.delete_audio,
            actor=body.actor,
            reason=body.reason,
        )
        if receipt is None:
            raise HTTPException(status_code=404, detail=f"akousma not found: {akousma_id}")
        from akousmata_app.derivatives import reconcile_derivatives
        reconcile_derivatives(store)
        wiki.log_append(
            "forget",
            akousma_id,
            f"record removed with receipt {receipt['receipt_id']}; inbound edges remain as absence",
        )
        return {"forgotten": akousma_id, "receipt": receipt}
    finally:
        store.close()


@app.get("/api/records/{akousma_id}/derivatives")
def derivatives_list(akousma_id: str):
    from akousmata_app.derivatives import list_derivatives
    store = _store()
    try:
        return list_derivatives(store, akousma_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        store.close()


@app.get("/api/records/{akousma_id}/derivatives/{view_id}")
def derivative_download(akousma_id: str, view_id: str):
    from fastapi.responses import Response
    from akousmata_app.derivatives import read_derivative
    store = _store()
    try:
        return Response(read_derivative(store, akousma_id, view_id),
                        media_type="application/x-npy",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "Content-Disposition": 'attachment; filename="derivative.npy"'})
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=404, detail="Derivative unavailable") from exc
    finally:
        store.close()


@app.get("/api/forgetting-receipts")
def forgetting_receipts(akousma_id: str | None = None) -> dict[str, Any]:
    """Content-free proof of forgetting, without resurrecting forgotten data."""
    store = _store()
    try:
        if not hasattr(store, "forgetting_receipts"):
            raise HTTPException(status_code=501, detail="py-akousma >= 0.6.0 required for forgetting receipts")
        items = store.forgetting_receipts(akousma_id=akousma_id)
        return {"receipts": items, "total": len(items)}
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
    base = str(load_settings().get("germ_url") or "").strip().rstrip("/")
    if not base:
        raise HTTPException(
            status_code=409,
            detail="GERM is optional and is not configured; set its URL in Settings before a handoff",
        )
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
    return {"sessions": research.list_sessions(), "proposals": _proposal_call("list_requests")}


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
    heard: bool = False


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
            heard=body.heard,
            human_profile=ensure_human_profile(),
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
            try:
                page = wiki.diary_digest(store, day)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="day must use YYYY-MM-DD") from exc
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


@app.get("/api/audit/accountability")
def audit_accountability() -> dict[str, Any]:
    store = _store()
    try:
        return records.accountability_audit(store)
    finally:
        store.close()


@app.post("/api/records/{akousma_id}/consent")
def set_consent(akousma_id: str, body: ConsentBody) -> dict[str, Any]:
    store = _store()
    try:
        try:
            record = records.set_consent(store, akousma_id, body.consent_status, body.rights_note)
            from akousmata_app.derivatives import revoke_derivatives
            revoke_derivatives(store, akousma_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        wiki.ingest(store, akousma_id)
        return {"record": record}
    finally:
        store.close()


class ExportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    akousma_ids: list[str] = Field(default_factory=list)
    constellation_id: str | None = None
    tag: str | None = None
    include_audio: bool = True
    include_wiki: bool = True
    audience: str = "selection"
    fields: list[str] = Field(default_factory=lambda: list(exports.DEFAULT_EXPORT_FIELDS))


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
        try:
            result = exports.build_pack(
                store, name=body.name, akousma_ids=ids,
                include_audio=body.include_audio, include_wiki=body.include_wiki,
                audience=body.audience, fields=body.fields,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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
        try:
            oida_url = validate_http_url(
                str(load_settings().get("oida_url") or "http://127.0.0.1:8765"),
                label="oída URL",
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        request = urllib.request.Request(
            f"{oida_url}/gateway/listen",
            data=_json.dumps({"path": str(path), "route_preset": body.preset, "remember": False}).encode("utf-8"),
            headers={"Content-Type": "application/json", **_bound_owner_headers(oida_url, "oida")},
            method="POST",
        )
        try:
            # validate_http_url() excludes urllib's local-file and custom schemes.
            with _owner_open(request, timeout=240) as response:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise ValueError("oída response exceeds its size limit")
                gateway_result = _json.loads(raw)
                if not isinstance(gateway_result, dict):
                    raise ValueError("oída response must be an object")
        except Exception as exc:  # noqa: BLE001 — any transport failure reads the same to the user
            raise HTTPException(status_code=502, detail=f"oída did not answer at {oida_url}: {exc}") from exc

        event = gateway_result.get("listening_event") if isinstance(gateway_result.get("listening_event"), dict) else {}
        if not event:
            route_outcome = (
                gateway_result.get("route_outcome")
                if isinstance(gateway_result.get("route_outcome"), dict)
                else None
            )
            raise HTTPException(
                status_code=423,
                detail={
                    "message": "oída completed the request as a pre-listening decision; no listening revision was filed",
                    "route_outcome": route_outcome,
                },
            )
        command_output = gateway_result.get("command_output") if isinstance(gateway_result.get("command_output"), dict) else {}
        aggregate = event.get("aggregate") if isinstance(event.get("aggregate"), dict) else {}
        outputs = command_output.get("outputs") if isinstance(command_output.get("outputs"), list) else []
        first_output = outputs[0] if outputs and isinstance(outputs[0], dict) else {}
        listening_context = (
            event.get("listening_context")
            if isinstance(event.get("listening_context"), dict)
            else first_output.get("listening_context")
            if isinstance(first_output.get("listening_context"), dict)
            else {}
        )
        compact = {
            "route_preset": body.preset,
            "event_id": event.get("id"),
            "title": aggregate.get("title"),
            "short_summary": aggregate.get("short_summary"),
            "detailed_summary": aggregate.get("detailed_summary"),
            "claims": command_output.get("claim_summary"),
            "routes": event.get("routes"),
            "apparatus": first_output.get("apparatus"),
            "listening_context": listening_context or None,
            "listening_provenance": event.get("listening_provenance"),
            "listening_passes": event.get("listening_passes"),
            "route_decisions": event.get("route_decisions"),
            "perception_path": gateway_result.get("perception_path"),
            "source_contract": gateway_result.get("contract"),
        }
        namespace = "akousmata.listen_again"
        created_at = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
        listening_entry = {
            "contract": AKOUSMATA_CONTRACT,
            "created_at": created_at,
            "summary": compact.get("short_summary") or compact.get("title") or "fresh oída pass",
            "payload": compact,
        }

        # A re-listening is a new record and an attributable revision. The
        # earlier hearing remains intact; both records may reference the same
        # content-addressed audio object.
        import akousma as akousma_protocol

        listening_id = str(event.get("id") or akousma_protocol.new_id("lst"))
        routes = []
        for route in event.get("routes") or []:
            route_id = route.get("route_id") if isinstance(route, dict) else route
            if isinstance(route_id, str) and route_id:
                routes.append(route_id)
        absence_items = []
        for index, absence in enumerate(listening_context.get("honest_absences") or []):
            if not isinstance(absence, dict):
                continue
            absence_items.append({
                "id": str(absence.get("id") or akousma_protocol.new_id("abs")),
                "kind": str(absence.get("kind") or "unavailable"),
                "subject": str(absence.get("subject") or "unspecified evidence"),
                "attributed_to": str(absence.get("attributed_to") or "oída listening boundary"),
                "listening_id": listening_id,
                **({"count": int(absence["count"])} if isinstance(absence.get("count"), int) else {}),
                **({"note": str(absence["note"])} if absence.get("note") else {}),
            })
        producer_decisions = event.get("route_decisions") if isinstance(event.get("route_decisions"), list) else []
        decision_items = []
        for index, producer in enumerate(producer_decisions):
            if not isinstance(producer, dict):
                continue
            authority = producer.get("authority") if isinstance(producer.get("authority"), dict) else {}
            decision_items.append(akousma_protocol.route_decision(
                str(producer.get("id") or f"decision-listen-again-{index + 1}"),
                gate=str(producer.get("gate") or "input"),
                outcome=str(producer.get("outcome") or "proceed"),
                subject=str(producer.get("subject") or "explicit re-listening input"),
                reason=str(producer.get("reason") or "Oída admitted the explicit re-listening request."),
                actor=str(authority.get("actor") or "oida-gateway"),
                decided_at=str(producer.get("decided_at") or created_at),
                authority_mode=str(authority.get("mode") or "observe_only"),
                listening_id=listening_id,
                producer_contract="akouo/v0.9",
                producer_decision_ref=str(producer.get("id") or "") or None,
                covenant_ref=str(authority.get("covenant_ref") or "") or None,
                granted_by=str(authority.get("granted_by") or "") or None,
                requires_confirmation=bool(authority.get("requires_confirmation", False)),
                reversible=bool(authority.get("reversible", True)),
                note=str(producer.get("note") or "") or None,
            ))
        if not decision_items:
            decision_items.append(akousma_protocol.route_decision(
                "decision-listen-again-input",
                gate="input",
                outcome="proceed",
                subject="explicit re-listening input",
                reason="The user requested a fresh Oída pass for a retained audio reference.",
                actor="akousmata-listen-again",
                decided_at=created_at,
                authority_mode="execute_scoped",
                listening_id=listening_id,
                producer_contract=AKOUSMATA_CONTRACT,
                granted_by="explicit Listen again action",
                requires_confirmation=False,
                reversible=True,
            ))
        pass_ref = (
            f"#/listening/{namespace}/payload/listening_passes/0"
            if compact.get("listening_passes")
            else None
        )
        provenance_ref = (
            f"#/listening/{namespace}/payload/listening_provenance"
            if compact.get("listening_provenance")
            else None
        )
        auditum = akousma_protocol.auditum(
            listenings=[{
                "listening_id": listening_id,
                "listener_id": str(event.get("listener_id") or gateway_result.get("perception_path") or "oida-gateway"),
                "listener_type": "agent",
                "created_at": created_at,
                "report_namespace": namespace,
                "contract": str(gateway_result.get("contract") or "oida/gateway/unknown"),
                "context_ref": f"#/listening/{namespace}/payload/listening_context" if listening_context else None,
                "apparatus_ref": f"#/listening/{namespace}/payload/apparatus" if compact.get("apparatus") else None,
                "claim_set_ref": f"#/listening/{namespace}/payload/claims" if compact.get("claims") else None,
                "route": routes,
                "listening_pass_ref": pass_ref,
                "listening_provenance_ref": provenance_ref,
                "route_decision_refs": [item["decision_id"] for item in decision_items],
            }],
            honest_absences=absence_items,
            route_decisions=decision_items,
            revision={
                "revision_id": akousma_protocol.new_id("rev"),
                "revises_akousma_id": akousma_id,
                "reason": "explicit listen-again pass through the OÍDA gateway",
                "changes": [
                    "fresh listening report",
                    "fresh apparatus and context declaration",
                    "fresh temporal pass, provenance, and route decisions",
                ],
                "created_at": created_at,
            },
        )
        new_record = akousma_protocol.new_akousma(
            audio=dict(record.get("audio") or {}),
            originating_app="akousmata",
            source_type="imported",
            origin=str((record.get("provenance") or {}).get("origin") or "file"),
            listening={namespace: listening_entry},
            relations=[akousma_protocol.relation("same_source_as", akousma_id, note="explicit re-listening revision")],
            tags=list(dict.fromkeys([*(record.get("tags") or []), "re-listening"])),
            extensions={"akousmata.app": {"revision_trigger": "listen_again"}},
            summary=listening_entry["summary"],
            covenant=event.get("covenant") if isinstance(event.get("covenant"), dict) else None,
            auditum=auditum,
        )
        source_provenance = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
        for key in ("consent_status", "rights_note"):
            if source_provenance.get(key) is not None:
                new_record["provenance"][key] = source_provenance[key]
        store.put(new_record)
        wiki.ingest(store, new_record["akousma_id"])
        return {
            "namespace": namespace,
            "listening": listening_entry,
            "record": new_record,
            "revision_of": akousma_id,
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
    ensure_human_profile()
    return public_view()


@app.put("/api/settings")
def put_settings(body: SettingsPatch) -> dict[str, Any]:
    import os

    patch = body.model_dump(exclude_unset=True, exclude_none=True)
    llm = patch.get("llm")
    if isinstance(llm, dict) and str(llm.get("api_key") or "").startswith("•"):
        llm.pop("api_key")  # masked value round-tripped from the UI: keep the stored key
    try:
        saved = save_settings(patch, ensure_profile=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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

    host = os.getenv("AKOUSMATA_HOST", "127.0.0.1")
    _REQUEST_BOUNDARY.validate_bind(host)
    uvicorn.run(app, host=host, port=int(os.getenv("AKOUSMATA_PORT", "5180")), proxy_headers=False)


@app.get("/api/records/{akousma_id}/relations/indexed")
def indexed_relations(akousma_id: str, limit: int = 50, cursor: str | None = None, rel_type: str | None = None):
    from akousmata_app.relation_index import page
    store = _store()
    try:
        return page(store, akousma_id, limit=limit, cursor=cursor, rel_type=rel_type)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        store.close()


@app.post("/api/research/proposals")
def submit_research_proposal(body: dict[str, Any]):
    return _proposal_call("submit", body)


def _proposal_call(operation, *args, **kwargs):
    store = _store()
    try:
        return getattr(research.proposals, operation)(store, *args, **kwargs)
    except ImportError as exc:
        raise HTTPException(503, "Install the compatible local AKOUO record workflow package") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        store.close()


@app.post("/api/research/requests/{request_id}/cancel")
def cancel_research_proposal(request_id: str):
    return _proposal_call("cancel", request_id)


@app.post("/api/research/proposals/{proposal_ref}/reviews")
def review_research_proposal(proposal_ref: str, body: dict[str, Any]):
    return _proposal_call("review", proposal_ref, body)


@app.get("/api/research/proposals/{proposal_ref}/events")
def proposal_review_events(proposal_ref: str, after: int = 0, limit: int = 100):
    items = _proposal_call("events", proposal_ref, after, limit)
    async def stream():
        for item in items:
            yield f"id: {item['event_id']}\ndata: {json.dumps(item)}\n\n"
        yield f"data: {json.dumps({'kind': 'end', 'next_after': items[-1]['event_id'] if items else after})}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/research/changes/{record_id}")
def research_record_changed(record_id: str):
    return _proposal_call("changed", record_id)


@app.get("/api/research/reconcile")
def reconcile_research(limit: int = 32, after: str = ""):
    return _proposal_call("reconcile", limit, after)


@app.post("/api/research/changes/{record_id}/acknowledge")
def acknowledge_research(record_id: str, body: dict[str, Any]):
    return _proposal_call("acknowledge", record_id, body.get("sha256"))


@app.get("/api/facets")
def library_facets():
    from akousmata_app.access_view import options
    store = _store()
    try:
        return {"facets": options(store), "value_limit": 200, "scope": "owner library"}
    finally:
        store.close()


def _graph_history_call(operation, *args, **kwargs):
    from akousmata_app import graph_history
    store = _store()
    try:
        return getattr(graph_history, operation)(store, *args, **kwargs)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        store.close()


@app.post("/api/graph/snapshots")
def capture_graph(body: dict[str, Any]):
    return _graph_history_call("capture", focus=body.get("focus"), depth=body.get("depth", 2), limit=body.get("limit", 120))


@app.get("/api/graph/snapshots")
def graph_events(after: int = 0, limit: int = 50):
    return _graph_history_call("events", after=after, limit=limit)


@app.get("/api/graph/snapshots/{event_id}")
def replay_graph(event_id: int):
    return _graph_history_call("replay", event_id)


@app.post("/api/bundles/export")
def bundle_export(body: dict[str, Any]):
    from akousmata_app.bundles import export_bundle
    try:
        with open_store() as store:
            return export_bundle(store, body["record_ids"], disclosure=body.get("disclosure", "private"))
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/bundles/import")
def bundle_import(body: dict[str, Any]):
    from akousmata_app.bundles import import_bundle, MAX_BYTES
    import base64
    try:
        if set(body) != {"archive_base64", "supported_contracts"} or len(body["archive_base64"]) > MAX_BYTES * 4 // 3 + 4:
            raise ValueError("Expected bounded archive_base64 and supported_contracts")
        data = base64.b64decode(body["archive_base64"], validate=True)
        with open_store() as store:
            return import_bundle(store, data, supported_contracts=body["supported_contracts"])
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/score")
def score_projection(body: dict[str, Any]):
    from akousmata_app.score import project
    try:
        with open_store() as store:
            return project(store, event_id=body["event_id"], scales=body["scales"], resolution_ms=body.get("resolution_ms", 1000))
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/capabilities")
def model_ecology_capabilities():
    from akousmata_app.acoustic.api import service
    return dict(contract="listening-stack/capability-catalog/v1", owner="akousmata",
        deployments=service().runtime.registry.catalog(), legacy_models=[],
        embedding_policy="Same pinned model revision, preprocessing, pooling, dimensions and metric required; legacy vectors retained but excluded from cosine")


from akousmata_app.acoustic.api import router as acoustic_router
app.include_router(acoustic_router)


if __name__ == "__main__":
    main()
