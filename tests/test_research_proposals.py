import json
from copy import deepcopy
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from akousma import AkousmataStore
from akousmata_app import research_proposals as p, relation_index
from akousmata_app.server import app


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setenv("AKOUSMATA_PATH", str(tmp_path))
    monkeypatch.setenv("AKOUSMATA_WATCHER", "0")
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/research-workflow.json").read_text()
    )
    store = AkousmataStore(tmp_path)
    for source in fixture["sources"]:
        store.put(source)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        yield store, client, fixture
    store.close()


def test_metadata_migration_duplicates_reindex_and_gaps(library):
    store, client, b = library
    # Real existing triplet index without our additive metadata is migrated.
    record = deepcopy(b["sources"][0])
    record["lineage"]["relations"] = [
        {"type": "response_to", "target_akousma_id": "missing", "note": "first"},
        {"type": "response_to", "target_akousma_id": "missing", "note": "second"},
    ]
    store.put(record)
    first = relation_index.page(store, record["akousma_id"], limit=1)
    assert first["total"] == 2 and first["edges"][0]["target_missing"]
    second = relation_index.page(
        store, record["akousma_id"], limit=1, cursor=first["next_cursor"]
    )
    assert [first["edges"][0]["relation"], second["edges"][0]["relation"]] == record[
        "lineage"
    ]["relations"]
    store.reindex()
    assert relation_index.page(store, record["akousma_id"])["total"] == 2
    record["lineage"]["relations"][0]["note"] = "changed"
    store.put(record)
    with pytest.raises(RuntimeError):
        relation_index.page(store, record["akousma_id"], cursor=first["next_cursor"])
    assert (
        client.get(f"/api/records/{record['akousma_id']}/relations/indexed").status_code
        == 200
    )
    assert (
        client.get("/api/records/missing/relations/indexed?limit=0").status_code == 400
    )


def test_canonical_proposal_retry_review_ancestry_events_and_restart(library):
    store, client, b = library
    r = b["request"]
    before = deepcopy(b["sources"])
    response = client.post("/api/research/proposals", json=r)
    assert response.status_code == 200, response.text
    assert client.post("/api/research/proposals", json=r).json()["replayed"]
    proposal = store.get(r["record_id"])
    assert (
        proposal["extensions"]["earworm_research"]["review"]["status"] == "unreviewed"
    )
    assert [store.get(s["akousma_id"]) for s in before] == before
    body = dict(
        review_id="review1",
        actor_ref="human:reviewer",
        reason="Same retained evidence considered",
        status="accepted",
        expected_event=0,
    )
    route = f"/api/research/proposals/{r['record_id']}/reviews"
    event = client.post(route, json=body).json()
    assert event["counts_as_new_evidence"]
    assert client.post(route, json=body).json() == event
    assert client.post(route, json={**body, "review_id": "stale"}).status_code == 409
    second = {**r, "record_id": "ak_second_proposal", "request_id": "second-proposal"}
    assert client.post("/api/research/proposals", json=second).status_code == 200
    repeated = client.post(
        "/api/research/proposals/ak_second_proposal/reviews",
        json={**body, "review_id": "review2"},
    ).json()
    assert not repeated["counts_as_new_evidence"]
    for status in ["contested", "rejected", "superseded"]:
        body = dict(
            review_id=status,
            actor_ref="human:reviewer",
            reason="Additive reassessment",
            status=status,
            expected_event=event["event_id"],
            replacement_ref="ak_second_proposal",
        )
        response = client.post(route, json=body)
        assert response.status_code == 200, response.text
        event = response.json()
    stream = client.get(f"/api/research/proposals/{r['record_id']}/events?limit=2")
    assert (
        "text/event-stream" in stream.headers["content-type"]
        and "next_after" in stream.text
    )
    assert len(p.events(store, r["record_id"])) == 4
    assert store.get(r["record_id"]) == proposal
    reopened = AkousmataStore(store.root)
    try:
        assert p.submit(reopened, r)["replayed"]
    finally:
        reopened.close()


def test_changed_sources_collision_and_reconcile(library):
    store, client, b = library
    r = b["request"]
    assert client.post("/api/research/proposals", json=r).status_code == 200
    changed = deepcopy(b["sources"][0])
    changed["summary"] = "Changed owner metadata"
    store.put(changed)
    assert client.post("/api/research/proposals", json=r).status_code == 409
    response = client.get("/api/research/reconcile?limit=1")
    assert response.status_code == 200
    item = response.json()["changes"][0]
    assert (
        client.post(
            f"/api/research/changes/{item['record_id']}/acknowledge",
            json={"sha256": "stale"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/research/changes/{item['record_id']}/acknowledge",
            json={"sha256": item["sha256"]},
        ).status_code
        == 200
    )
    review = dict(
        review_id="r",
        actor_ref="owner",
        reason="test",
        status="accepted",
        expected_event=0,
    )
    assert (
        client.post(
            f"/api/research/proposals/{r['record_id']}/reviews", json=review
        ).status_code
        == 409
    )


def test_cancel_during_validation_and_recovery_after_store_commit(library):
    store, client, b = library
    r = b["request"]
    import akouo_contract.record_workflows as workflow

    original = workflow.research_proposal
    entered = threading.Event()
    release = threading.Event()

    def slow(*args, **kw):
        entered.set()
        assert release.wait(5)
        return original(*args, **kw)

    with (
        patch.object(workflow, "research_proposal", side_effect=slow),
        ThreadPoolExecutor() as pool,
    ):
        future = pool.submit(client.post, "/api/research/proposals", json=r)
        assert entered.wait(5)
        assert (
            client.post(f"/api/research/requests/{r['request_id']}/cancel").status_code
            == 200
        )
        release.set()
        assert future.result().status_code == 409
    assert store.get(r["record_id"]) is None
    r = {**r, "request_id": "recovery", "record_id": "ak_recovery"}
    original_put = AkousmataStore.put

    def interrupted(self, record):
        original_put(self, record)
        raise RuntimeError("simulated interruption after canonical commit")

    with patch.object(AkousmataStore, "put", interrupted):
        assert client.post("/api/research/proposals", json=r).status_code == 409
    assert store.get(r["record_id"]) is not None
    assert client.post("/api/research/proposals", json=r).status_code == 200
    assert client.post("/api/research/proposals", json=r).json()["replayed"]


def test_public_projection_and_forgetting_do_not_leak_or_reconstruct_reviews(library):
    from akousmata_app import publication, exports

    store, client, b = library
    r = b["request"]
    assert client.post("/api/research/proposals", json=r).status_code == 200
    proposal = store.get(r["record_id"])
    proposal["provenance"]["consent_status"] = "owned"
    store.put(proposal)
    publication.grant(store, r["record_id"], ["subject"])
    public = publication.public_record(store, r["record_id"])
    assert "lineage" not in public and "extensions" not in public
    with pytest.raises(ValueError):
        exports.checked_fields(["research_reviews"])
    publication.revoke(store, r["record_id"])
    assert publication.public_record(store, r["record_id"]) is None
    body = dict(
        review_id="private-review",
        actor_ref="owner",
        reason="Private assessment",
        status="accepted",
        expected_event=0,
    )
    assert (
        client.post(
            f"/api/research/proposals/{r['record_id']}/reviews", json=body
        ).status_code
        == 200
    )
    store.forget(r["record_id"])
    assert p.events(store, r["record_id"]) == []
    assert client.post("/api/research/proposals", json=r).status_code == 409
    assert store.get(r["record_id"]) is None


def test_concurrent_retry_and_canonical_index_criteria(library):
    store, client, b = library
    r = b["request"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: client.post("/api/research/proposals", json=r), range(2))
        )
    assert all(x.status_code == 200 for x in results), [x.text for x in results]
    assert (
        store.conn.execute("SELECT COUNT(*) FROM research_requests").fetchone()[0] == 1
    )
    page = relation_index.page(store, r["record_id"])
    assert page["edges"][0]["relation"] == r["relations"][0]


def test_unsupported_proposal_is_failed_and_source_change_during_validation_refused(
    library,
):
    from unittest.mock import patch
    import akouo_contract.record_workflows as workflow

    store, client, b = library
    r = deepcopy(b["request"])
    r["permissions"][0]["status"] = "unknown"
    assert client.post("/api/research/proposals", json=r).status_code == 400
    assert p.list_requests(store)[0]["state"] == "failed"
    r = {
        **b["request"],
        "request_id": "changed-during-validation",
        "record_id": "ak_changed_during_validation",
    }
    original = workflow.research_proposal

    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        source = deepcopy(b["sources"][0])
        source["summary"] = "Changed during proposal computation"
        writer = AkousmataStore(store.root)
        try:
            writer.put(source)
        finally:
            writer.close()
        return result

    with patch.object(workflow, "research_proposal", side_effect=mutate):
        assert client.post("/api/research/proposals", json=r).status_code == 409
    assert store.get(r["record_id"]) is None


def test_inherited_research_does_not_count_as_fresh_confirmation(library):
    store, client, b = library
    r = b["request"]
    assert client.post("/api/research/proposals", json=r).status_code == 200
    review = dict(
        review_id="first",
        actor_ref="reviewer",
        reason="Retained evidence",
        status="accepted",
        expected_event=0,
    )
    assert p.review(store, r["record_id"], review)["counts_as_new_evidence"]
    second = deepcopy(r)
    second.update(
        request_id="inherited",
        record_id="ak_inherited",
        source_refs=[r["record_id"], "ak_generation"],
    )
    second["permissions"] = [
        dict(record_ref=ref, status="granted", permission_ref="permission:owner")
        for ref in second["source_refs"]
    ]
    second["relations"][0]["criterion"]["input_refs"] = second["source_refs"]
    response = client.post("/api/research/proposals", json=second)
    assert response.status_code == 200, response.text
    assert not p.review(store, second["record_id"], {**review, "review_id": "second"})[
        "counts_as_new_evidence"
    ]
