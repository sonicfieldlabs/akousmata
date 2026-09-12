from copy import deepcopy
import io
import json
from pathlib import Path
import zipfile
import pytest
from akousma import AkousmataStore, new_akousma
from akousmata_app.bundles import export_bundle, import_bundle, inspect_bundle
from akousmata_app import publication

CONTRACTS = ["earworm/listening-memories/v1", "earworm/akousma/v1.6", "earworm/akousma/v1.7"]


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("AKOUSMATA_PATH", str(tmp_path / "source"))
    with AkousmataStore(tmp_path / "source") as source, AkousmataStore(tmp_path / "target") as target:
        record = new_akousma(audio={"asset_id": "synthetic-unavailable", "uri": "file:///unavailable/synthetic.wav"}, originating_app="synthetic-bundle-test", extensions={"future.private": {"opaque": [1, 2]}})
        record["provenance"]["consent_status"] = "owned"
        source.put(record)
        yield source, target, record


def pack(source, record, **kw):
    result = export_bundle(source, [record["akousma_id"]], **kw)
    return Path(result["archive"]).read_bytes()


def test_private_roundtrip_unknowns_retry_and_forgetting(case):
    source, target, record = case
    data = pack(source, record)
    assert import_bundle(target, data, supported_contracts=CONTRACTS)["records"][0]["outcome"] == "retained"
    assert target.get(record["akousma_id"]) == record
    assert import_bundle(target, data, supported_contracts=CONTRACTS)["records"][0]["outcome"] == "reused"
    target.forget(record["akousma_id"])
    with pytest.raises(ValueError, match="forgetting"):
        import_bundle(target, data, supported_contracts=CONTRACTS)
    assert target.get(record["akousma_id"]) is None


def test_conflict_and_reader_negotiation(case):
    source, target, record = case
    data = pack(source, record)
    with pytest.raises(ValueError, match="support"):
        import_bundle(target, data, supported_contracts=CONTRACTS[:1])
    changed = deepcopy(record)
    changed["summary"] = "conflicting local identity"
    target.put(changed)
    with pytest.raises(ValueError, match="conflict"):
        import_bundle(target, data, supported_contracts=CONTRACTS)


def test_public_projection_reuses_grants_and_cannot_be_canonical(case):
    source, target, record = case
    with pytest.raises(ValueError, match="grant"):
        pack(source, record, disclosure="public-projection")
    publication.grant(source, record["akousma_id"], ["summary"])
    data = pack(source, record, disclosure="public-projection")
    manifest, payloads = inspect_bundle(data)
    assert b"future.private" not in b"".join(payloads.values())
    with pytest.raises(ValueError, match="Projections"):
        import_bundle(target, data, supported_contracts=CONTRACTS)


def test_tamper_and_extra_members(case):
    source, target, record = case
    data = pack(source, record)
    manifest, payloads = inspect_bundle(data)
    for extra in [False, True]:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            for name, payload in payloads.items():
                archive.writestr(name, payload if extra else b"{}")
            if extra:
                archive.writestr("../escape", b"unlisted")
        with pytest.raises(ValueError):
            import_bundle(target, out.getvalue(), supported_contracts=CONTRACTS)


def test_new_reader_negotiation_and_preflight_rollback(case):
    source, target, old = case
    modern = deepcopy(old)
    modern["akousma_id"] += "_next"
    modern["schema_version"] = "1.7.0"
    source.put(modern)
    result = export_bundle(source, [old["akousma_id"], modern["akousma_id"]])
    data = Path(result["archive"]).read_bytes()
    with pytest.raises(ValueError, match="support"):
        import_bundle(target, data, supported_contracts=CONTRACTS[:-1])
    assert target.get(old["akousma_id"]) is None
    import_bundle(target, data, supported_contracts=CONTRACTS)
    assert target.get(modern["akousma_id"]) == modern


def test_graph_import_uses_current_masa_validator(case, monkeypatch):
    import os
    from akousma.masa_runtime import masa_validator, lineage_directions
    source, target, _ = case
    module=os.environ.get("AKOUSMATA_TEST_MASA_VALIDATOR_MODULE")
    core=os.environ.get("AKOUSMATA_TEST_MASA_CORE_MODULE")
    if not module or not core:
        pytest.skip("select installed MASA modules")
    monkeypatch.setenv("AKOUSMATA_MASA_VALIDATOR_MODULE",module)
    monkeypatch.setenv("AKOUSMATA_MASA_CORE_MODULE",core)
    fixture=json.loads((Path(__file__).parent/"fixtures/bundle-graph.json").read_text())
    record=fixture["record"]
    record["provenance"]["consent_status"]="owned"
    source.put(record,validate_masa=masa_validator(module),lineage_directions=lineage_directions(core))
    data=pack(source,record)
    import_bundle(target,data,supported_contracts=CONTRACTS)
    assert target.get(record["akousma_id"])==record


def test_private_copy_preserves_unknown_consent_but_public_export_stays_gated(case):
    source, _, record = case
    record['provenance'].pop('consent_status')
    source.put(record)
    before = deepcopy(source.get(record['akousma_id']))
    data = pack(source, record)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['disclosure'] == 'private'
        assert json.loads(archive.read(manifest['entries'][0]['path'])) == before
        assert set(archive.namelist()) == {'manifest.json', manifest['entries'][0]['path']}
    assert source.get(record['akousma_id']) == before
    with pytest.raises(ValueError, match='not exportable'):
        pack(source, record, disclosure='public-projection')
