"""Owner projections over synthetic records produced by the real D3 owner APIs."""

import json
from copy import deepcopy
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from akousma import AkousmataStore
from akousmata_app import listening_relations as relations, publication, exports, wiki
from akousmata_app.server import app


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setenv("AKOUSMATA_PATH", str(tmp_path))
    monkeypatch.setenv("AKOUSMATA_WATCHER", "0")
    bundle = json.loads(
        (Path(__file__).parent / "fixtures/listening-relations.json").read_text()
    )
    store = AkousmataStore(tmp_path)
    for key, record in bundle.items():
        if isinstance(record, dict):
            store.put(record)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        yield store, client, bundle
    store.close()


def test_independent_second_and_influenced_views_preserve_canonical_sources(library):
    store, client, b = library
    for key in ["independent", "second_report", "influenced"]:
        source = deepcopy(b[key])
        identifier = source["akousma_id"]
        response = client.get(f"/api/records/{identifier}")
        assert response.status_code == 200, response.text
        projection = response.json()["listening_relations"]
        assert projection == relations.project(source, store.get)
        assert response.json()["record"] == source == store.get(identifier)
        assert {
            n["listening_id"] for n in projection["nodes"] if n["kind"] == "listening"
        } == {p["listening_id"] for p in source["auditum"]["listenings"]}
        if key == "independent":
            assert (
                projection["independent"] and not projection["counts"]["second_report"]
            )
        if key == "second_report":
            assert (
                projection["counts"]["second_report"] == 1
                and not projection["counts"]["recorded_redirection"]
            )
        if key == "influenced":
            assert projection["counts"]["recorded_redirection"] == 1
            edge = next(
                e for e in projection["edges"] if e["kind"] == "recorded_redirection"
            )
            assert edge["evidence"][0]["before_decision_ref"] == "before"
            assert "abstain to proceed" in edge["effect"]
        assert "Who listened to whom" in wiki.record_page(store, source)


def test_pages_match_full_projection_and_reject_changed_references(library):
    store, client, b = library
    record = b["influenced"]
    url = f"/api/records/{record['akousma_id']}/listening-relations"
    first = client.get(url, params={"limit": 1}).json()
    rows = list(first["edges"])
    cursor = first["next_cursor"]
    assert cursor
    while cursor:
        page = client.get(url, params={"limit": 1, "cursor": cursor}).json()
        rows += page["edges"]
        cursor = page["next_cursor"]
    assert rows == relations.project(record, store.get)["edges"]
    modified = deepcopy(b["source"])
    modified["summary"] = "Owner metadata changed"
    store.put(modified)
    assert (
        client.get(url, params={"limit": 1, "cursor": first["next_cursor"]}).status_code
        == 409
    )
    assert client.get(url, params={"cursor": "invalid"}).status_code == 400
    assert client.get(url, params={"limit": 0}).status_code == 400
    assert client.get("/api/records/missing/listening-relations").status_code == 404


def test_missing_sources_and_unresolved_influence_stay_explicit(library):
    store, client, b = library
    value = deepcopy(b["second_report"])
    snapshot = relations.project(value)
    assert any(n.get("status") == "snapshot_only" for n in snapshot["nodes"])
    value["listening"]["akouo.second-report"]["payload"]["source_snapshots"] = {}
    missing = relations.project(value)
    assert any(n.get("status") == "missing" for n in missing["nodes"])
    assert len(missing["edges"]) == len(snapshot["edges"])
    value = deepcopy(b["influenced"])
    value["auditum"]["ensemble"]["influence_edges"][0]["from_listening_id"] = "missing"
    projection = relations.project(value)
    assert (
        projection["counts"]["unresolved_influence"] == 1
        and not projection["counts"]["recorded_redirection"]
    )
    value = deepcopy(b["influenced"])
    value["listening"]["oida.influence-evidence"]["payload"]["traces"][0]["trace"][
        "trace_id"
    ] = "unbound"
    projection = relations.project(value)
    assert (
        projection["counts"]["declared_influence"] == 1
        and not projection["counts"]["recorded_redirection"]
    )


def test_publication_exports_and_revocation_do_not_disclose_owner_relations(library):
    store, client, b = library
    for key in ["independent", "influenced"]:
        record = deepcopy(b[key])
        record["provenance"]["consent_status"] = "owned"
        store.put(record)
        publication.grant(store, record["akousma_id"], ["summary"])
    first = publication.public_page(store, limit=1)
    second = publication.public_page(store, limit=1, cursor=first["next_cursor"])
    assert len(first["records"]) + len(second["records"]) == 2
    for projection in first["records"] + second["records"]:
        assert "listening_relations" not in projection and "auditum" not in projection
        assert "Who listened to whom" not in wiki.record_page(store, projection)
    identifier = b["influenced"]["akousma_id"]
    publication.revoke(store, identifier)
    assert publication.public_record(store, identifier) is None
    with pytest.raises(publication.ViewChanged):
        publication.public_page(store, limit=1, cursor=first["next_cursor"])
    with pytest.raises(ValueError):
        exports.checked_fields(["listening_relations"])
    assert (
        client.get(f"/api/records/{identifier}/listening-relations").status_code == 200
    )


def test_additive_human_review_stays_distinct_from_second_model_and_influence(library):
    store, client, b = library
    source = deepcopy(b["source"])
    result = client.post(
        "/api/human-records",
        json=dict(
            summary="A synthetic human response",
            notes="Different interpretation",
            heard=True,
            response_to=source["akousma_id"],
        ),
    )
    assert result.status_code == 200, result.text
    human = result.json()["record"]
    projection = client.get(
        "/api/records/" + human["akousma_id"] + "/listening-relations"
    ).json()
    assert projection["counts"]["record_response"] == 1
    assert (
        not projection["counts"]["second_report"]
        and not projection["counts"]["recorded_redirection"]
    )
    assert store.get(source["akousma_id"]) == source
    revision = client.post(
        "/api/human-records/" + human["akousma_id"] + "/revisions",
        json=dict(
            summary="A revised synthetic response",
            notes="Still a human account",
            heard=True,
            reason="Review clarification",
        ),
    )
    assert revision.status_code == 200, revision.text
    revised = revision.json()["record"]
    assert revised["akousma_id"] != human["akousma_id"]
    assert store.get(human["akousma_id"]) == human
    assert (
        client.get(
            "/api/records/" + revised["akousma_id"] + "/listening-relations"
        ).json()["counts"]["record_response"]
        == 1
    )
