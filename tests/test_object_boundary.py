from hashlib import sha256

from akousma import AkousmataStore
from akousmata_app.records import resolve_audio_path


def test_owner_audio_reads_bind_record_hash_and_refuse_redirects(tmp_path):
    data = b"temporary owner read fixture"
    with AkousmataStore(tmp_path / "store") as store:
        uri = store.put_audio(data)
        record = {"audio": {"uri": uri, "content_hash": "sha256:" + sha256(data).hexdigest()}}
        path = resolve_audio_path(store, record)
        assert path.read_bytes() == data
        assert resolve_audio_path(store, {"audio": {"uri": uri, "content_hash": "sha256:" + "0" * 64}}) is None
        outside = tmp_path / "outside"
        outside.write_bytes(data)
        path.unlink()
        path.symlink_to(outside)
        assert resolve_audio_path(store, record) is None
        assert outside.read_bytes() == data


def test_explicit_external_file_reference_keeps_its_separate_host_policy(tmp_path):
    path = tmp_path / "explicit.wav"
    path.write_bytes(b"external fixture")
    assert resolve_audio_path(None, {"audio": {"uri": path.as_uri()}}) == path
