"""Owner-only navigation and explicit exports of retained representations."""

import base64
from copy import deepcopy
from hashlib import sha256

from akousma.material_terms import MaterialTerms
from akousma.representation_store import RepresentationStore


class RepresentationNavigator:
    def __init__(self, store, *, actor_ref="owner:akousmata"):
        self.store = store
        self.terms = MaterialTerms(store, actor_ref=actor_ref)
        self.memory = RepresentationStore(store, authorize=self.terms.permit)

    def detail(self, record_id):
        record = self.memory.get(record_id)
        if record is None:
            return None
        block = record["extensions"]["earworm_representation"]
        items = []
        for rep in block["representations"]:
            try:
                data = self.memory.read_bytes(rep["representation_id"])
                text = data.decode("utf-8") if rep.get("encoding") == "utf-8" else None
                available = True
            except PermissionError:
                text, available = None, False
            items.append(
                dict(representation=deepcopy(rep), text=text, available=available)
            )
        return dict(
            contract="akousmata/representations/v1",
            record=record,
            artifacts=items,
            outputs=deepcopy(block["outputs"]),
            relations=deepcopy(block["relations"]),
            return_basis=deepcopy(block.get("return")),
            memory_parents=list(record["lineage"]["parent_akousma_ids"]),
        )

    def compare(self, left, right):
        a = self.memory.read_bytes(left)
        b = self.memory.read_bytes(right)
        return dict(
            contract="akousmata/representation-comparison/v1",
            left=left,
            right=right,
            method_ref="akousmata:exact-byte-comparison:v1",
            equal=a == b,
            left_sha256=sha256(a).hexdigest(),
            right_sha256=sha256(b).hexdigest(),
            left_byte_count=len(a),
            right_byte_count=len(b),
        )

    def revisit(
        self,
        record_id,
        representation_ref,
        *,
        context_basis="independent",
        account_refs=(),
    ):
        """Prepare an explicit owner request. No provider is called or selected."""
        record = self.memory.get(record_id)
        if record is None:
            raise KeyError(record_id)
        block = record["extensions"]["earworm_representation"]
        operation = self.memory.operation(block["operation_ref"])
        if representation_ref == operation["primary_representation_ref"]:
            kind = "original"
        elif representation_ref in operation["output_representation_refs"]:
            kind = "descendant"
        else:
            raise ValueError("Revisit needs this operation's original or output")
        if context_basis not in {
            "independent",
            "informed",
            "shared_analysis",
            "unknown",
        } or len(set(account_refs)) != len(account_refs):
            raise ValueError("Declare the exact revisit context")
        if context_basis == "independent" and (
            account_refs
            or representation_ref in operation["account_representation_refs"]
        ):
            raise ValueError("A previous account cannot be an independent return")
        if context_basis in {"informed", "shared_analysis"} and not account_refs:
            raise ValueError("Informed/shared return needs explicit prior context")
        accounts = {
            r["representation_ref"] for r in block["accesses"] if r["role"] == "account"
        } | set(operation["account_representation_refs"])
        if not set(account_refs) <= accounts:
            raise ValueError("Prior account is outside this operation")
        for identity in (representation_ref, *account_refs):
            self.memory.read_bytes(identity)
            self.memory.representation(identity, action="execute")
        return dict(
            contract="akousmata/representation-revisit/v1",
            status="prepared_not_executed",
            request=dict(
                source_ref=representation_ref,
                intent="relisten",
                remember=False,
                context_inputs=[
                    dict(representation_ref=ref, role="account") for ref in account_refs
                ],
                return_to=dict(
                    previous_operation_ref=block["operation_ref"],
                    kind=kind,
                    context_basis=context_basis,
                ),
            ),
            required_selection=[
                "provider_id",
                "model_id",
                "authenticated_scope",
                "current_authority_if_adopted",
            ],
        )

    def export(self, record_id, representation_refs, *, public=False):
        record = self.memory.get(record_id)
        if record is None:
            raise KeyError(record_id)
        if (
            not isinstance(representation_refs, list)
            or not representation_refs
            or len(set(representation_refs)) != len(representation_refs)
        ):
            raise ValueError("Export requires explicit unique selected artifacts")
        block = record["extensions"]["earworm_representation"]
        selected = set(representation_refs)
        reps = {r["representation_id"]: r for r in block["representations"]}
        if not selected <= set(reps):
            raise ValueError("Export artifact is outside this record")
        artifacts = []
        for identity in representation_refs:
            data = self.memory.read_bytes(
                identity, action="export_public" if public else "export"
            )
            artifacts.append(
                dict(
                    representation=deepcopy(reps[identity]),
                    bytes_base64=base64.b64encode(data).decode("ascii"),
                )
            )
        return dict(
            contract="akousmata/representation-export/v1",
            record_ref=record_id,
            destination="public" if public else "owner",
            canonical_record_rewritten=False,
            artifacts=artifacts,
            outputs=[
                deepcopy(o)
                for o in block["outputs"]
                if o["representation_ref"] in selected
            ],
            relations=[
                deepcopy(r)
                for r in block["relations"]
                if r["from_ref"] in selected and r["to_ref"] in selected
            ],
            omitted_representation_count=len(reps) - len(selected),
        )


def build_router(open_store):
    from fastapi import APIRouter, HTTPException, Query, Response
    from pydantic import BaseModel, ConfigDict, Field

    class ExportBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        representation_refs: list[str] = Field(min_length=1, max_length=32)
        public: bool = False

    class RevisitBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        representation_ref: str
        context_basis: str = "independent"
        account_refs: list[str] = Field(default_factory=list, max_length=32)

    router = APIRouter(prefix="/api/representations", tags=["Representations"])

    def call(function):
        store = open_store()
        try:
            return function(RepresentationNavigator(store))
        except PermissionError:
            raise HTTPException(
                403, "Current material terms withhold this representation"
            ) from None
        except KeyError:
            raise HTTPException(404, "Retained representation is unavailable") from None
        except ValueError:
            raise HTTPException(
                422, "Invalid representation request or retained identity"
            ) from None
        finally:
            store.close()

    @router.get("")
    def records(
        limit: int = Query(50, ge=1, le=200),
        form: str | None = None,
        output_kind: str | None = None,
        query: str | None = Query(None, max_length=200),
        cursor: str | None = Query(None, max_length=43),
    ):
        return call(
            lambda nav: dict(
                contract="akousmata/representations/v1",
                **nav.memory.page(limit=limit, form=form, output_kind=output_kind,
                                  query=query, cursor=cursor),
            )
        )

    @router.get("/records/{record_id}")
    def detail(record_id: str):
        result = call(lambda nav: nav.detail(record_id))
        if result is None:
            raise HTTPException(404, "Retained representation record is unavailable")
        return result

    @router.get("/artifacts/{representation_ref}")
    def artifact(representation_ref: str):
        data = call(lambda nav: nav.memory.read_bytes(representation_ref))
        return Response(
            data,
            media_type="application/octet-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": "attachment",
            },
        )

    @router.get("/compare")
    def compare(left: str, right: str):
        return call(lambda nav: nav.compare(left, right))

    @router.post("/records/{record_id}/export")
    def export(record_id: str, body: ExportBody):
        return call(
            lambda nav: nav.export(
                record_id, body.representation_refs, public=body.public
            )
        )

    @router.post("/records/{record_id}/revisit")
    def revisit(record_id: str, body: RevisitBody):
        return call(lambda nav: nav.revisit(record_id, **body.model_dump()))

    return router
