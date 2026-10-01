from copy import deepcopy
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from akousma import AkousmataStore, AUDITUM_LISTENER_TYPES
from akousmata_app.server import app
from akousmata_app import publication


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setenv("AKOUSMATA_PATH", str(tmp_path))
    monkeypatch.setenv("AKOUSMATA_WATCHER", "0")
    store = AkousmataStore(tmp_path)
    source = json.loads(
        (Path(__file__).parent / "fixtures/research-workflow.json").read_text()
    )["sources"][0]
    for kind in AUDITUM_LISTENER_TYPES:
        r = deepcopy(source)
        r["akousma_id"] = "facet_" + kind
        r["summary"] = "Synthetic " + kind + " account"
        r["auditum"]["listenings"][0]["listener_type"] = kind
        store.put(r)
    observation = json.loads(
        (Path(__file__).parent / "fixtures/access-observation.json").read_text()
    )
    store.put(observation)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        yield store, client, observation
    store.close()


def test_qualified_facets_all_types_and_combination_before_limit(library):
    store, client, obs = library
    opts = client.get("/api/facets").json()["facets"]
    assert {o["value"] for o in opts["listener_type"]} == set(AUDITUM_LISTENER_TYPES)
    for kind in AUDITUM_LISTENER_TYPES:
        r = client.get(
            "/api/records",
            params={"listener_type": kind, "recipient": "reviewer:fixture", "limit": 1},
        )
        assert r.status_code == 200, r.text
        assert r.json()["records"][0]["akousma_id"] == "facet_" + kind
    matter = obs["extensions"]["earworm_matter_context"]
    for key in ("register", "scale"):
        r = client.get("/api/records", params={key: matter[key + "s"][0]})
        assert r.status_code == 200, r.text
        assert any(x["akousma_id"] == obs["akousma_id"] for x in r.json()["records"])
    assert client.get("/api/records?subject=nonexistent").json()["records"] == []
    assert (
        client.get(
            "/api/records?human_access=unknown&listener_type=invalid"
        ).status_code
        == 400
    )


def test_original_payloads_unknown_undeclared_and_revocation(library):
    store, client, obs = library
    before = deepcopy(obs)
    view = client.get("/api/records/" + obs["akousma_id"]).json()["access_view"]
    assert view["declaration"] == obs["extensions"]["earworm_listening_access"]
    assert view["matter_context"] == obs["extensions"]["earworm_matter_context"]
    assert store.get(obs["akousma_id"]) == before
    r = store.get("facet_human")
    r["akousma_id"] = "no_declarations"
    r["extensions"].pop("earworm_listening_access")
    r["extensions"].pop("earworm_listening_context")
    store.put(r)
    assert (
        client.get("/api/records/no_declarations").json()["access_view"]["status"]
        == "undeclared"
    )
    assert (
        client.get("/api/records?human_access=undeclared").json()["records"][0][
            "akousma_id"
        ]
        == "no_declarations"
    )
    r = store.get("no_declarations")
    r["provenance"]["consent_status"] = "owned"
    store.put(r)
    publication.grant(store, r["akousma_id"], ["summary"])
    assert "access_view" not in publication.public_record(store, r["akousma_id"])
    publication.revoke(store, r["akousma_id"])
    assert publication.public_record(store, r["akousma_id"]) is None


def test_known_visual_access_does_not_promote_capture_or_audio_access(library):
    store, client, _ = library
    record = store.get("facet_human")
    record["akousma_id"] = "known_visual"
    access = record["extensions"]["earworm_listening_access"]
    access["human_access"] = [
        dict(
            status="known",
            listener_ref="human:fixture",
            chain_refs=["display:fixture"],
            conditions="Synthetic visual rendering only",
            rendering_refs=["rendering:fixture"],
            access_modes=["visual"],
            evidence_refs=["evidence:fixture"],
        )
    ]
    store.put(record)
    result = client.get("/api/records?human_access=known").json()["records"]
    assert [r["akousma_id"] for r in result] == ["known_visual"]
    view = client.get("/api/records/known_visual").json()["access_view"]
    assert view["declaration"]["human_access"][0]["access_modes"] == ["visual"]
    assert view["declaration"]["capture"]["status"] == "unknown"
    assert view["declaration"]["model_input"]["status"] == "unknown"
