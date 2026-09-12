import io

import numpy as np
import pytest

from akousmata_app.derivatives import inspect_numeric, retain_numeric, resolve_numeric


def encoded(values):
    stream = io.BytesIO()
    np.save(stream, values, allow_pickle=False)
    return stream.getvalue()


def test_roundtrip_and_shared_content_identity(tmp_path):
    data = encoded(np.ones((8, 3), dtype=np.complex64))
    first = retain_numeric(tmp_path, data)
    assert retain_numeric(tmp_path, data) == first
    actual, metadata = resolve_numeric(tmp_path, first['object_ref'])
    assert actual == data
    assert metadata['expanded_bytes'] == 192
    assert list((tmp_path / 'objects').iterdir()) == [tmp_path / 'objects' / (first['sha256'] + '.npy')]


def test_truncation_trailing_bytes_nonfinite_and_paths(tmp_path):
    data = encoded(np.ones(8, dtype=np.float32))
    for bad in (data[:-1], data + b'extra', encoded(np.array([np.nan]))):
        with pytest.raises(ValueError):
            inspect_numeric(bad)
    for ref in ('file:///tmp/object.npy', 'akousmata://objects/../private.npy'):
        with pytest.raises(ValueError):
            resolve_numeric(tmp_path, ref)


def test_corrupt_and_symlinked_objects_are_refused(tmp_path):
    data = encoded(np.ones(8, dtype=np.float32))
    metadata = retain_numeric(tmp_path, data)
    path = tmp_path / 'objects' / (metadata['sha256'] + '.npy')
    path.write_bytes(encoded(np.zeros(8, dtype=np.float32)))
    with pytest.raises(ValueError):
        resolve_numeric(tmp_path, metadata['object_ref'])
    with pytest.raises(ValueError):
        retain_numeric(tmp_path, data)
    path.unlink()
    target = tmp_path / 'outside.npy'
    target.write_bytes(data)
    path.symlink_to(target)
    with pytest.raises(ValueError):
        resolve_numeric(tmp_path, metadata['object_ref'])


def test_hostile_header_rejected_before_array_load(monkeypatch):
    stream = io.BytesIO()
    np.lib.format.write_array_header_1_0(stream, dict(descr='<f8', fortran_order=False, shape=(2**40,)))
    monkeypatch.setattr(np, 'load', lambda *a, **k: pytest.fail('must not allocate from hostile header'))
    with pytest.raises(ValueError):
        inspect_numeric(stream.getvalue())


def test_record_grant_required_and_expiry_is_checked(tmp_path):
    import json
    import time
    from pathlib import Path
    from akousma import AkousmataStore
    from akousmata_app.derivatives import grant_derivatives, read_derivative
    root = Path(__file__).resolve().parents[2] / 'earworm/tests/contracts'
    record = json.loads((root / 'evolution/research.json').read_text())
    bundle = json.loads((root / 'spectral/bundle.json').read_text())
    record['schema_version'] = '1.8.0'
    bundle['record_ref'] = record['akousma_id']
    payload = encoded(np.ones((2, 2), dtype=np.complex64))
    metadata = retain_numeric(tmp_path, payload)
    bundle['views'][0].update({k: v for k, v in metadata.items() if k != 'content_type'})
    record['extensions']['oida.spectral'] = bundle
    with AkousmataStore(tmp_path) as store:
        store.put(record, supported_versions=['1.8.0'],
                  resolve_object=lambda ref: metadata, resolve_representation=lambda ref: bundle)
        with pytest.raises(ValueError):
            read_derivative(store, record['akousma_id'], 'view:1')
        with pytest.raises(ValueError):
            grant_derivatives(store, record['akousma_id'], memory='record',
                              derivatives_permitted=True, expires_at=time.time() + 60)
        grant_derivatives(store, record['akousma_id'], memory='record_audio',
                          derivatives_permitted=True, expires_at=time.time() + 60)
        assert read_derivative(store, record['akousma_id'], 'view:1') == payload
        from copy import deepcopy
        from akousmata_app.derivatives import reconcile_derivatives
        other = deepcopy(record)
        other['akousma_id'] = 'record-shared-spectral'
        other_bundle = other['extensions']['oida.spectral']
        other_bundle['record_ref'] = other['akousma_id']
        store.put(other, supported_versions=['1.8.0'], resolve_object=lambda ref: metadata,
                  resolve_representation=lambda ref: other_bundle)
        grant_derivatives(store, other['akousma_id'], memory='record_audio',
                          derivatives_permitted=True, expires_at=time.time() + 60)
        store.forget_with_receipt(record['akousma_id'])
        assert reconcile_derivatives(store)['removed_objects'] == 0
        assert read_derivative(store, other['akousma_id'], 'view:1') == payload
        store.conn.execute('UPDATE akousmata_derivative_grants SET expires_at=0')
        store.conn.commit()
        with pytest.raises(ValueError):
            read_derivative(store, other['akousma_id'], 'view:1')
        assert reconcile_derivatives(store)['removed_objects'] == 1
        assert not list((tmp_path / 'objects').glob('*.npy'))


def test_publication_rollback_and_crash_recovery(tmp_path):
    import json
    import time
    from pathlib import Path
    from akousma import AkousmataStore
    from akousmata_app.derivatives import publish_bundle, recover_derivatives, read_derivative
    root = Path(__file__).resolve().parents[2] / 'earworm/tests/contracts'
    record = json.loads((root / 'evolution/research.json').read_text())
    bundle = json.loads((root / 'spectral/bundle.json').read_text())
    record['schema_version'] = '1.8.0'
    bundle['record_ref'] = record['akousma_id']
    record['extensions']['oida.spectral'] = bundle
    payload = encoded(np.ones((2, 2), dtype=np.complex64))
    with AkousmataStore(tmp_path) as store:
        options = dict(memory='record_audio', derivatives_permitted=True,
                       expires_at=time.time()+60, resolve_representation=lambda ref: bundle)
        with pytest.raises(InterruptedError):
            publish_bundle(store, record, {'view:1': payload}, cancelled=lambda: True, **options)
        assert store.get(record['akousma_id']) is None
        assert not list((tmp_path / 'objects').glob('*.npy'))
        checks = iter([False, True])
        with pytest.raises(InterruptedError):
            publish_bundle(store, record, {'view:1': payload}, cancelled=lambda: next(checks), **options)
        assert store.get(record['akousma_id']) is None
        assert not list((tmp_path / 'objects').glob('*.npy'))
        # A crash before SQLite commit leaves only an owned staging journal.
        orphan = retain_numeric(tmp_path, payload)
        (tmp_path / '.spectral-transactions' / 'uncommitted.json').write_text(json.dumps({'created':[orphan['sha256']+'.npy']}))
        recover_derivatives(store)
        assert not list((tmp_path / 'objects').glob('*.npy'))
        published = publish_bundle(store, record, {'view:1': payload}, **options)
        assert read_derivative(store, record['akousma_id'], 'view:1') == payload
        name = published['extensions']['oida.spectral']['views'][0]['sha256'] + '.npy'
        (tmp_path / '.spectral-transactions' / 'crash.json').write_text(json.dumps({'created':[name]}))
        recover_derivatives(store)
        assert read_derivative(store, record['akousma_id'], 'view:1') == payload
