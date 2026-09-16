import copy
import json
from datetime import UTC, datetime, timedelta

import akousma
import pytest
from akousmata_app import editorial_grants, publication


@pytest.fixture
def owned(tmp_path):
    store = akousma.AkousmataStore(tmp_path)
    record = akousma.new_akousma(audio={"asset_id": "fixture-asset"}, originating_app="editorial-grant-test", summary="private example")
    record["provenance"]["consent_status"] = "owned"
    store.put(record)
    yield store, record
    store.close()


def authorize(store, record, **changes):
    values = {"reviewer_group": "Antikythera editorial board", "expected_record_sha256": publication._digest(record),
              "authorized_by": "fixture owner", "basis": "private review only",
              "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()}
    values.update(changes)
    return editorial_grants.grant(store, record["akousma_id"], **values)


def test_private_grant_never_creates_public_visibility_or_mutates_record(owned):
    store, record = owned
    before = copy.deepcopy(store.get(record["akousma_id"]))
    grant = authorize(store, record)
    assert grant["revision"] == 1 and grant["audio_authorized"] is False
    assert publication.public_page(store)["records"] == []
    assert publication.grant_status(store, record["akousma_id"])["state"] == "unpublished"
    assert editorial_grants.grant_status(store, record["akousma_id"], reviewer_group="Antikythera editorial board")["state"] == "granted"
    assert editorial_grants.grant_status(store, record["akousma_id"], reviewer_group="other group")["state"] == "unpublished"
    assert store.get(record["akousma_id"]) == before


def test_absent_status_is_read_only(owned):
    store, record = owned
    assert not editorial_grants._exists(store)
    editorial_grants.grant_status(store, record["akousma_id"], reviewer_group="board")
    assert not editorial_grants._exists(store)


def test_revision_history_revocation_and_reauthorization(owned):
    store, record = owned
    first = authorize(store, record)
    second = editorial_grants.revoke(store, record["akousma_id"], reviewer_group=first["reviewer_group"], authorized_by="owner", basis="withdrawn")
    assert second["revision"] == 2
    assert editorial_grants.grant_status(store, record["akousma_id"], reviewer_group=first["reviewer_group"])["state"] == "revoked"
    third = authorize(store, record)
    assert third["revision"] == 3
    rows = store.conn.execute("SELECT payload FROM akousmata_editorial_grants ORDER BY revision").fetchall()
    assert json.loads(rows[0][0]) == first
    assert len(rows) == 3


def test_changed_record_and_consent_invalidate_grant(owned):
    store, record = owned
    authorize(store, record)
    record["summary"] = "changed"
    store.put(record)
    assert editorial_grants.grant_status(store, record["akousma_id"], reviewer_group="Antikythera editorial board")["state"] == "stale"
    record["provenance"]["consent_status"] = "unknown"
    store.put(record)
    with pytest.raises(ValueError, match="consent"):
        authorize(store, record)


@pytest.mark.parametrize("change", [
    {"expected_record_sha256": "0" * 64}, {"reviewer_group": ""}, {"authorized_by": ""},
    {"expires_at": "2020-01-01T00:00:00Z"}, {"expires_at": "2099-01-01T00:00:00"},
])
def test_invalid_authorization_refuses_without_grant(owned, change):
    store, record = owned
    with pytest.raises(ValueError):
        authorize(store, record, **change)
    assert not editorial_grants._exists(store)


def test_caller_transaction_is_not_committed(owned):
    store, record = owned
    store.conn.execute("BEGIN")
    with pytest.raises(ValueError, match="own owner transaction"):
        authorize(store, record)
    assert store.conn.in_transaction
    store.conn.rollback()


def test_expiry_does_not_fall_back_to_an_older_grant(owned, monkeypatch):
    store, record = owned
    grant = authorize(store, record)
    future = datetime.now(UTC) + timedelta(days=2)

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return future

    monkeypatch.setattr(editorial_grants, "datetime", Later)
    assert editorial_grants.grant_status(store, record["akousma_id"], reviewer_group=grant["reviewer_group"])["state"] == "expired_or_not_current"


def test_private_grant_revocation_does_not_revoke_public_grant(owned):
    store, record = owned
    publication.grant(store, record["akousma_id"], ["summary"])
    authorize(store, record)
    editorial_grants.revoke(store, record["akousma_id"], reviewer_group="Antikythera editorial board", authorized_by="owner", basis="private withdrawal")
    assert publication.grant_status(store, record["akousma_id"])["state"] == "granted"
    publication.revoke(store, record["akousma_id"])
    assert editorial_grants.grant_status(store, record["akousma_id"], reviewer_group="Antikythera editorial board")["state"] == "revoked"
