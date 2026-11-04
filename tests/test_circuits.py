"""Runs and circuits through the navigator's API: recall for the decider, keeping for Khipu."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

akousma = pytest.importorskip("akousma")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from akousma.listening_circuit import empty_run_memory, fold_run_memory  # noqa: E402

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "circuit.json").read_text())


def _record(circuit):
    listenings = [
        {"listening_id": lid, "listener_id": "oida", "listener_type": "agent", "created_at": "2026-10-30T03:00:00Z",
         "report_namespace": f"oida.{lid}", "contract": "akouo/v0.9"}
        for lid in ("lst_1", "lst_2", "lst_3")
    ]
    auditum = akousma.auditum(
        listenings=listenings,
        honest_absences=[{"id": "absence-raw", "kind": "not_retained", "subject": "raw audio",
                          "attributed_to": "local retention boundary", "listening_id": "lst_1"}],
        route_decisions=[akousma.route_decision(
            "decision-lst_1", gate="inference", outcome="proceed", subject="listening pass",
            reason="The run admitted this window.", actor="test", listening_id="lst_1", producer_contract="akouo/v0.9")],
    )
    return akousma.new_akousma(originating_app="oida", subject="a radio window", auditum=auditum,
                               session_id=circuit["run"]["session_id"], extensions={"earworm_listening_circuit": circuit})


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("AKOUSMATA_PATH", str(tmp_path / "store"))
    monkeypatch.setenv("AKOUSMATA_WATCHER", "0")
    store = akousma.AkousmataStore(tmp_path / "store")
    circuit = deepcopy(FIXTURE["circuit"])
    rid = store.put(_record(circuit))
    store.close()
    from akousmata_app.server import app
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
    return {"client": client, "rid": rid, "circuit": circuit}


def test_a_run_is_recalled_with_its_moves_and_its_memory(world):
    client, circuit = world["client"], world["circuit"]
    session = circuit["run"]["session_id"]
    detail = client.get(f"/api/runs/{session}")
    assert detail.status_code == 200
    assert detail.json()["memory"] is None
    assert [s["move"] for s in detail.json()["steps"]] == ["switch_source", "relisten_same", "relisten_same", "sound"]
    assert client.get("/api/runs/ses_unknown").status_code == 404

    memory = empty_run_memory(session, "2026-10-30T03:00:00Z")
    put = client.put(f"/api/runs/{session}/memory", json={"memory": memory, "expected_revision": None})
    assert put.status_code == 200 and put.json()["revision"] == 0
    later = fold_run_memory(memory, at="2026-10-30T03:05:00Z", source_key="locustream_1010",
                            akousma_id=world["rid"], circuit=circuit, heard_as=["music"])
    assert client.put(f"/api/runs/{session}/memory", json={"memory": later, "expected_revision": 0}).status_code == 200
    stale = client.put(f"/api/runs/{session}/memory", json={"memory": later, "expected_revision": 0})
    assert stale.status_code == 409
    other = client.put("/api/runs/ses_other/memory", json={"memory": later, "expected_revision": None})
    assert other.status_code == 400
    bad = deepcopy(later)
    bad["sources"]["locustream_1010"]["transcript"] = "words"
    assert client.put(f"/api/runs/{session}/memory", json={"memory": bad, "expected_revision": 1}).status_code == 422

    runs = client.get("/api/runs").json()["runs"]
    assert runs[0]["session_id"] == session and runs[0]["windows"] == 1
    assert client.get(f"/api/runs/{session}").json()["memory"]["sources"]["locustream_1010"]["soundings"] == 1


def test_a_source_and_a_record_answer_for_their_moves(world):
    client = world["client"]
    steps = client.get("/api/circuits", params={"source_key": "locustream_1010", "move": "sound"}).json()["steps"]
    assert [s["akousma_id"] for s in steps] == [world["rid"]]
    found = client.get(f"/api/records/{world['rid']}/circuit").json()
    assert found["errors"] == [] and found["circuit"]["run"]["source_key"] == "locustream_1010"
    assert found["targets"] == {"akm_window_0003": "unavailable", "akm_sounded_0001": "unavailable"}
    assert client.get("/api/records/akm_missing/circuit").status_code == 404
