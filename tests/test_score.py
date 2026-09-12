from test_bundles import case  # noqa: F401
from akousmata_app.graph_history import capture
from akousmata_app.score import project
import pytest


def test_clocks_resolution_and_current_forgetting(case):  # noqa: F811
    source, _, record = case
    snapshot = capture(source, focus=record["akousma_id"])
    score = project(source, event_id=snapshot["event_id"], scales=["records"])
    assert score["events"][0]["source_clock"] == record["created_at"]
    assert score["events"][0]["bucket_ms"] % 1000 == 0
    assert score["event_clock"] == snapshot["captured_at"]
    source.forget(record["akousma_id"])
    with pytest.raises(RuntimeError):
        project(source, event_id=snapshot["event_id"], scales=["records"])


def test_observation_source_clock_is_not_account_creation(case):  # noqa: F811
    import json
    from pathlib import Path
    source, _, _ = case
    record=json.loads((Path(__file__).parent/'fixtures/access-observation.json').read_text())
    source.put(record)
    snapshot=capture(source,focus=record['akousma_id'])
    score=project(source,event_id=snapshot['event_id'],scales=['observations'])
    assert score['events'][0]['source_clock']=='2026-07-26T11:00:00Z'
    assert score['events'][0]['source_clock']!=record['created_at']
