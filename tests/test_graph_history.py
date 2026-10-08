import json
from copy import deepcopy
from pathlib import Path
import pytest
from akousma import AkousmataStore
from akousmata_app import graph, graph_history as history


@pytest.fixture
def library(tmp_path):
    store = AkousmataStore(tmp_path)
    records = json.loads(
        (Path(__file__).parent / "fixtures/research-workflow.json").read_text()
    )["sources"]
    for index, record in enumerate(records):
        if index:
            record["lineage"]["parent_akousma_ids"] = [records[index - 1]["akousma_id"]]
        store.put(record)
    yield store, records
    store.close()


def test_capture_cursor_replay_restriction_and_forgetting(library):
    store, records = library
    first = history.capture(store)
    record = deepcopy(records[0])
    record["tags"] = ["changed"]
    store.put(record)
    second = history.capture(store)
    assert first["event_id"] < second["event_id"]
    page = history.events(store, limit=1)
    assert page["next_after"] == first["event_id"]
    assert (
        history.events(store, after=page["next_after"])["events"][0]["event_id"]
        == second["event_id"]
    )
    assert history.replay(store, first["event_id"])["nodes"] == first["nodes"]
    record["provenance"]["consent_status"] = "restricted"
    store.put(record)
    replay = history.replay(store, first["event_id"])
    assert next(n for n in replay["nodes"] if n["id"] == record["akousma_id"])[
        "missing"
    ]
    assert all(
        record["akousma_id"] not in (e["from"], e["to"]) for e in replay["edges"]
    )
    store.forget(record["akousma_id"])
    with pytest.raises(RuntimeError, match="forgetting"):
        history.replay(store, first["event_id"])
    assert (
        store.conn.execute(
            "SELECT payload FROM graph_snapshots WHERE event_id=?", (first["event_id"],)
        ).fetchone()[0]
        is None
    )


def test_bounds_stages_and_source_preservation(library):
    store, records = library
    view = graph.full_graph(store, limit=1)
    assert len(view["nodes"]) <= 1 and len(view["edges"]) <= 4 and view["truncated"]
    for bad in (0, 801, "10", True):
        with pytest.raises(ValueError):
            history.capture(store, limit=bad)
    with pytest.raises(ValueError):
        history.capture(store, focus=[])
    view = history.capture(store)
    assert "generation" in {n["stage"] for n in view["nodes"]}
    for record in records:
        assert store.get(record["akousma_id"]) == record


def test_capture_rejects_concurrent_revision(library, monkeypatch):
    store, records = library
    original = graph.full_graph

    def changed(*args, **kwargs):
        view = original(*args, **kwargs)
        record = deepcopy(records[0])
        record["tags"] = ["concurrent"]
        store.put(record)
        return view

    monkeypatch.setattr(graph, "full_graph", changed)
    with pytest.raises(RuntimeError, match="changed during capture"):
        history.capture(store)
    assert history.events(store)["events"] == []


def test_walk_three_stages_and_api_errors(library, monkeypatch):
    from fastapi.testclient import TestClient
    from akousmata_app.server import app

    store, records = library
    view = graph.neighborhood(store, records[0]["akousma_id"], depth=3)
    assert len(view["nodes"]) == 3
    assert {e["role"] for e in view["edges"]} == {
        "generated from",
        "later listening lineage",
    }
    monkeypatch.setenv("AKOUSMATA_PATH", str(store.root))
    monkeypatch.setenv("AKOUSMATA_WATCHER", "0")
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        assert (
            client.post("/api/graph/snapshots", json={"limit": "wrong"}).status_code
            == 400
        )
        result = client.post("/api/graph/snapshots", json={})
        assert result.status_code == 200
        assert (
            client.get(f"/api/graph/snapshots/{result.json()['event_id']}").status_code
            == 200
        )
