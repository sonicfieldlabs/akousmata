"""Private versioned navigator over a synthetic complete text work."""

import base64
from copy import deepcopy
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from akousma import AkousmataStore
from akousma.material_terms import MATERIAL_ACTIONS, MaterialTerms
from akousma.representation_store import RepresentationStore
from akousma.representations import REPRESENTATION_CONTRACTS
from akousmata_app.exports import exportable, sanitize
from akousmata_app.representations import RepresentationNavigator
from akousmata_app.request_boundary import RequestBoundary


@pytest.fixture
def retained(tmp_path, monkeypatch):
    root = tmp_path / "memory"
    monkeypatch.setenv("AKOUSMATA_PATH", str(root))
    monkeypatch.setenv("AKOUSMATA_WATCHER", "0")
    base = AkousmataStore(root)
    terms = MaterialTerms(base, actor_ref="fixture:owner")
    terms.set(
        "fixture:terms:repository-license",
        actions=sorted(MATERIAL_ACTIONS - {"export_public"}),
        basis="Synthetic owner fixture",
    )
    memory = RepresentationStore(base, authorize=terms.permit)
    record = json.loads(
        (Path(__file__).parent / "fixtures/text-work-19.json").read_text()
    )
    memory.put(record, supported_contracts=REPRESENTATION_CONTRACTS)
    from akousmata_app import server

    monkeypatch.setattr(server, "_REQUEST_BOUNDARY", RequestBoundary())
    monkeypatch.setattr(server, "_WORKSPACE_ID", None)
    yield base, terms, record, server
    base.close()


def test_navigator_separates_artifacts_outputs_sources_and_authorship(retained):
    base, _, record, _ = retained
    nav = RepresentationNavigator(base)
    detail = nav.detail(record["akousma_id"])
    assert len(detail["artifacts"]) == 3 and detail["outputs"][0]["kind"] == "work"
    assert detail["outputs"][0]["authored_by"] == ["fixture-author"]
    compare = nav.compare("fixture:source", "fixture:work")
    assert (
        compare["equal"] is False
        and compare["method_ref"] == "akousmata:exact-byte-comparison:v1"
    )
    exported = nav.export(record["akousma_id"], ["fixture:work"])
    assert exported["omitted_representation_count"] == 2 and exported["relations"] == []
    assert (
        base64.b64decode(exported["artifacts"][0]["bytes_base64"])
        == b"hum\n    hum\n\nlet the next line stay open\n"
    )
    assert base.get(record["akousma_id"])["provenance"]["consent_status"] == "unknown"
    with pytest.raises(PermissionError):
        nav.export(record["akousma_id"], ["fixture:work"], public=True)


def test_revisit_prepares_exact_original_or_descendant_without_execution(retained):
    base, _, record, _ = retained
    nav = RepresentationNavigator(base)
    original = nav.revisit(record["akousma_id"], "fixture:source")
    descendant = nav.revisit(record["akousma_id"], "fixture:work")
    assert original["request"]["return_to"]["kind"] == "original"
    assert descendant["request"]["return_to"]["kind"] == "descendant"
    assert (
        descendant["status"] == "prepared_not_executed"
        and descendant["request"]["remember"] is False
    )
    assert "provider_id" not in descendant["request"]
    with pytest.raises(ValueError):
        nav.revisit(record["akousma_id"], "outside")
    with pytest.raises(ValueError):
        nav.revisit(record["akousma_id"], "fixture:work", context_basis="informed")
    informed = nav.revisit(
        record["akousma_id"],
        "fixture:work",
        context_basis="informed",
        account_refs=["fixture:account"],
    )
    assert informed["request"]["context_inputs"] == [
        dict(representation_ref="fixture:account", role="account")
    ]


def test_legacy_projection_cannot_export_or_relabel_new_record(retained):
    _, _, record, _ = retained
    value = deepcopy(record)
    value["provenance"]["consent_status"] = "owned"
    assert exportable(value)[0] is False
    with pytest.raises(ValueError, match="versioned"):
        sanitize(value, include_audio=True)


def test_legacy_research_graph_relations_and_counts_cannot_collect_new_material(retained):
    from akousmata_app import graph, listening_relations, records
    from akousmata_app.research import ResearchSession
    base, _, record, _ = retained
    assert ResearchSession("written listening", seed_ids=[record["akousma_id"]]).gather(base) == []
    assert graph.full_graph(base)["nodes"] == []
    assert records.stats(base)["total"] == 0 and records.stats(base)["latest_created_at"] is None
    assert records.timeline(base)["total"] == 0
    with pytest.raises(ValueError, match="versioned"):
        listening_relations.project(record, base.get)


def test_every_private_representation_route_keeps_real_owner_boundary(retained):
    _, _, record, server = retained
    local = TestClient(
        server.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)
    )
    remote = TestClient(
        server.app, base_url="http://127.0.0.1", client=("100.64.0.9", 50000)
    )
    routes = [
        "/api/representations",
        "/api/representations/records/" + record["akousma_id"],
        "/api/representations/artifacts/fixture:work",
        "/api/representations/compare?left=fixture:source&right=fixture:work",
    ]
    for route in routes:
        assert local.get(route).status_code == 200
        assert remote.get(route).status_code == 403
    path = "/api/representations/records/" + record["akousma_id"] + "/export"
    assert (
        local.post(path, json=dict(representation_refs=["fixture:work"])).status_code
        == 200
    )
    assert (
        local.post(
            path, json=dict(representation_refs=["fixture:work"], public=True)
        ).status_code
        == 403
    )
    assert (
        local.post(
            path,
            headers={"Origin": "https://foreign.invalid"},
            json=dict(representation_refs=["fixture:work"]),
        ).status_code
        == 403
    )
    artifact = local.get("/api/representations/artifacts/fixture:work")
    assert (
        artifact.headers["x-content-type-options"] == "nosniff"
        and artifact.headers["content-disposition"] == "attachment"
    )
    assert local.get("/api/records/" + record["akousma_id"]).status_code == 404
    assert local.get("/inscriptions").status_code == 200
    assert "representations.js" in local.get("/inscriptions").text
    assert remote.get("/inscriptions").status_code == 403
    assert (
        local.post(
            path.replace("/export", "/revisit"),
            json=dict(representation_ref="fixture:work"),
        ).json()["status"]
        == "prepared_not_executed"
    )


def test_current_restrictions_hide_material_and_metadata_and_stop_exports(retained):
    base, terms, record, _ = retained
    old = terms.get("fixture:terms:repository-license")
    terms.set(
        old["terms_ref"],
        actions=["read_metadata"],
        basis="Only metadata remains allowed",
        expected_revision=old["revision"],
    )
    nav = RepresentationNavigator(base)
    detail = nav.detail(record["akousma_id"])
    assert all(
        a["text"] is None and a["available"] is False for a in detail["artifacts"]
    )
    with pytest.raises(PermissionError):
        nav.export(record["akousma_id"], ["fixture:work"])
    current = terms.get(old["terms_ref"])
    terms.revoke(old["terms_ref"], expected_revision=current["revision"])
    assert nav.memory.list() == []
    with pytest.raises(PermissionError):
        nav.detail(record["akousma_id"])


@pytest.mark.parametrize(
    "selected", [[], ["fixture:work", "fixture:work"], ["outside"]]
)
def test_export_is_an_explicit_selection_from_the_record(retained, selected):
    base, _, record, _ = retained
    with pytest.raises(ValueError):
        RepresentationNavigator(base).export(record["akousma_id"], selected)
