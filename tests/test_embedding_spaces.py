import sqlite3
import json
from types import SimpleNamespace
from akousmata_app.similar import _embedding, _embedding_cosine, _corpus


def record(revision="a" * 40, preprocessing="b" * 64):
    return {
        "extensions": {
            "akousmata.app": {
                "embedding": {
                    "vector": [1, 0, 0],
                    "space": {
                        "model": "test",
                        "revision": revision,
                        "preprocessing_sha256": preprocessing,
                        "dimensions": 3,
                        "pooling": "mean",
                        "metric": "cosine",
                    },
                }
            }
        }
    }


def test_no_cross_space_comparison_or_legacy_promotion():
    a = _embedding(record())
    assert _embedding_cosine(a, _embedding(record())) == 1
    assert _embedding_cosine(a, _embedding(record(revision="c" * 40))) is None
    assert _embedding_cosine(a, _embedding(record(preprocessing="c" * 64))) is None
    assert (
        _embedding({"extensions": {"akousmata.app": {"embedding": [1, 0, 0]}}}) is None
    )


def test_cache_distinguishes_stores_and_in_place_updates():
    def store(label):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE akousmata(record TEXT)")
        conn.execute(
            "INSERT INTO akousmata VALUES (?)", (json.dumps({"akousma_id": label}),)
        )
        return SimpleNamespace(conn=conn)

    a, b = store("a"), store("b")
    try:
        assert _corpus(a)[0]["record"]["akousma_id"] == "a"
        assert _corpus(b)[0]["record"]["akousma_id"] == "b"
        b.conn.execute(
            "UPDATE akousmata SET record=?", (json.dumps({"akousma_id": "updated"}),)
        )
        assert _corpus(b)[0]["record"]["akousma_id"] == "updated"
    finally:
        a.conn.close()
        b.conn.close()
