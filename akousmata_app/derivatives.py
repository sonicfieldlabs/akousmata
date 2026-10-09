"""Bounded numeric derivative objects; publication remains a host operation.

Objects are content addressed and never loaded with pickle. Callers must bind
returned metadata to an admitted record before exposing a download.
"""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import re
import tempfile
import json
import time
from functools import wraps
from copy import deepcopy
import uuid

import numpy as np

MAX_OBJECT_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
DTYPES = {"float32", "float64", "complex64", "complex128", "uint8"}
OBJECT_NAME = re.compile(r"[0-9a-f]{64}\.npy")


def _locked(function):
    @wraps(function)
    def run(owner, *args, **kwargs):
        try:
            import fcntl
        except ImportError as exc:
            raise RuntimeError('Derivative publication requires POSIX file locking on this host') from exc
        root = Path(owner if isinstance(owner, (str, Path)) else owner.root)
        root.mkdir(parents=True, exist_ok=True)
        with (root / '.derivatives.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                return function(owner, *args, **kwargs)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    return run


def inspect_numeric(data: bytes) -> dict:
    """Check the NPY header before allocating or loading its array."""
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_OBJECT_BYTES:
        raise ValueError("Derivative exceeds object byte budget")
    stream = io.BytesIO(data)
    try:
        version = np.lib.format.read_magic(stream)
        if version == (1, 0):
            shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
        elif version == (2, 0):
            shape, fortran, dtype = np.lib.format.read_array_header_2_0(stream)
        else:
            raise ValueError("Unsupported numeric object version")
    except (EOFError, TypeError) as exc:
        raise ValueError("Invalid numeric object header") from exc
    if dtype.hasobject or dtype.name not in DTYPES or dtype.fields:
        raise ValueError("Unsupported numeric object dtype")
    if not 1 <= len(shape) <= 4 or any(type(n) is not int or n <= 0 for n in shape):
        raise ValueError("Invalid numeric object shape")
    import math
    expanded = math.prod(shape) * dtype.itemsize
    if expanded > MAX_EXPANDED_BYTES or stream.tell() + expanded != len(data):
        raise ValueError("Numeric shape/bytes mismatch or expansion budget exceeded")
    values = np.load(io.BytesIO(data), allow_pickle=False)
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite numeric object")
    return {"sha256": hashlib.sha256(data).hexdigest(), "dtype": dtype.name,
            "shape": list(shape), "byte_count": len(data),
            "expanded_bytes": expanded, "content_type": "application/x-npy"}


@_locked
def retain_numeric(root: Path, data: bytes) -> dict:
    """Durably publish one verified immutable object using atomic replacement."""
    metadata = inspect_numeric(data)
    objects = Path(root) / "objects"
    objects.mkdir(parents=True, exist_ok=True)
    name = metadata["sha256"] + ".npy"
    destination = objects / name
    if destination.is_symlink():
        raise ValueError("Symlinked derivative object")
    if destination.exists():
        if destination.read_bytes() != data:
            raise ValueError("Existing content-addressed object is corrupt")
    else:
        fd, temporary = tempfile.mkstemp(prefix=".spectral-", dir=objects)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
            directory = os.open(objects, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return {**metadata, "object_ref": "akousmata://objects/" + name}


def resolve_numeric(root: Path, object_ref: str) -> tuple[bytes, dict]:
    prefix = "akousmata://objects/"
    if not isinstance(object_ref, str) or not object_ref.startswith(prefix):
        raise ValueError("Invalid derivative locator")
    name = object_ref[len(prefix):]
    if not OBJECT_NAME.fullmatch(name):
        raise ValueError("Invalid derivative identity")
    path = Path(root) / "objects" / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_OBJECT_BYTES:
        raise ValueError("Derivative unavailable or oversized")
    data = path.read_bytes()
    metadata = inspect_numeric(data)
    if metadata["sha256"] != name[:-4]:
        raise ValueError("Derivative digest mismatch")
    return data, metadata


def _tables(store):
    store.conn.execute('''CREATE TABLE IF NOT EXISTS akousmata_derivative_grants (
        record_id TEXT PRIMARY KEY, bundle_digest TEXT NOT NULL,
        expires_at REAL NOT NULL, state TEXT NOT NULL)''')


def _bundle_digest(bundle):
    return hashlib.sha256(json.dumps(bundle, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def _policy_digest(record, bundle):
    return _bundle_digest({'bundle': bundle, 'consent': record.get('provenance', {}).get('consent_status'),
                           'covenant': record.get('auditum', {}).get('covenant'),
                           'native_policy': record.get('extensions', {}).get('oida.native-policy')})


@_locked
def grant_derivatives(store, record_id, *, memory, derivatives_permitted, expires_at, commit=True):
    """Owner-only grant following independently resolved retention/covenant policy.

    Consent labels in records never create this grant. Expiry must be supplied
    from the audio retention deadline, not invented from the derivative.
    """
    if memory != 'record_audio' or derivatives_permitted is not True:
        raise ValueError('Audio retention and derivative permission required')
    if not isinstance(expires_at, (int, float)) or not np.isfinite(expires_at) or expires_at <= time.time():
        raise ValueError('A current audio-retention deadline is required')
    record = store.get(record_id)
    if record is None or store.forgotten(record_id):
        raise ValueError('Record unavailable')
    bundle = record.get('extensions', {}).get('oida.spectral')
    from akousma.spectral import spectral_bundle_errors
    errors = spectral_bundle_errors(bundle, resolve_object=lambda ref: resolve_numeric(store.root, ref)[1])
    if errors or bundle['record_ref'] != record_id:
        raise ValueError('Invalid or mismatched spectral bundle')
    _tables(store)
    store.conn.execute('''CREATE TABLE IF NOT EXISTS akousmata_derivative_objects (
        record_id TEXT NOT NULL, object_ref TEXT NOT NULL,
        PRIMARY KEY(record_id, object_ref))''')
    for view in bundle['views']:
        if view['state'] == 'retained':
            store.conn.execute('INSERT OR IGNORE INTO akousmata_derivative_objects VALUES (?, ?)',
                               (record_id, view['object_ref']))
    source_ref = record.get('audio', {}).get('uri', '')
    if re.fullmatch(r'akousmata://objects/[0-9a-f]{64}\.wav', source_ref):
        store.conn.execute('INSERT OR IGNORE INTO akousmata_derivative_objects VALUES (?, ?)', (record_id, source_ref))
    store.conn.execute('''INSERT INTO akousmata_derivative_grants VALUES (?, ?, ?, 'granted')
        ON CONFLICT(record_id) DO UPDATE SET bundle_digest=excluded.bundle_digest,
        expires_at=excluded.expires_at, state='granted' ''',
        (record_id, _policy_digest(record, bundle), expires_at))
    if commit:
        store.conn.commit()


def authorized_bundle(store, record_id):
    """Recheck live record, forgetting and host grant on every lookup."""
    _tables(store)
    grant = store.conn.execute('SELECT * FROM akousmata_derivative_grants WHERE record_id=?',
                               (record_id,)).fetchone()
    record = store.get(record_id)
    if not record or store.forgotten(record_id) or grant is None:
        raise ValueError('Derivative access unavailable')
    if record.get('provenance', {}).get('consent_status') in {'denied', 'revoked', 'restricted'}:
        raise ValueError('Derivative consent revoked')
    bundle = record.get('extensions', {}).get('oida.spectral')
    if grant['state'] != 'granted' or grant['expires_at'] <= time.time() or _policy_digest(record, bundle) != grant['bundle_digest']:
        raise ValueError('Derivative grant expired, revoked or stale')
    return bundle


@_locked
def list_derivatives(store, record_id):
    bundle = authorized_bundle(store, record_id)
    return {'record_ref': record_id, 'views': [
        {key: view[key] for key in ('view_id', 'kind', 'state', 'for')}
        for view in bundle['views']]}


@_locked
def read_derivative(store, record_id, view_id):
    bundle = authorized_bundle(store, record_id)
    view = next((v for v in bundle['views'] if v['view_id'] == view_id), None)
    if view is None or view['state'] != 'retained':
        raise ValueError('Derivative is not retained')
    data, actual = resolve_numeric(store.root, view['object_ref'])
    if any(actual[k] != view[k] for k in ('sha256', 'shape', 'dtype', 'byte_count', 'expanded_bytes')):
        raise ValueError('Derivative metadata mismatch')
    authorized_bundle(store, record_id)
    return data


@_locked
def reconcile_derivatives(store):
    """Remove expired/forgotten grant objects unless another live grant uses them.

    Unindexed objects are left for publication recovery; this function never
    assumes that an unrecognized object is disposable.
    """
    _tables(store)
    store.conn.execute('''CREATE TABLE IF NOT EXISTS akousmata_derivative_objects (
        record_id TEXT NOT NULL, object_ref TEXT NOT NULL,
        PRIMARY KEY(record_id, object_ref))''')
    rows = store.conn.execute('SELECT record_id, object_ref FROM akousmata_derivative_objects').fetchall()
    live, obsolete = set(), set()
    for row in rows:
        try:
            bundle = authorized_bundle(store, row['record_id'])
            current = {v.get('object_ref') for v in bundle['views'] if v['state'] == 'retained'}
            current.add((store.get(row['record_id']) or {}).get('audio', {}).get('uri'))
            (live if row['object_ref'] in current else obsolete).add(row['object_ref'])
        except ValueError:
            obsolete.add(row['object_ref'])
    removed = 0
    # Existing non-native audio records retain their independent ownership.
    for row in store.conn.execute('SELECT akousma_id FROM akousmata').fetchall():
        record = store.get(row['akousma_id'])
        if 'oida.spectral' not in record.get('extensions', {}):
            live.add(record.get('audio', {}).get('uri'))
    for ref in obsolete - live:
        name = ref.removeprefix('akousmata://objects/')
        if OBJECT_NAME.fullmatch(name):
            path = Path(store.root) / 'objects' / name
            if not path.is_symlink():
                path.unlink(missing_ok=True)
                removed += 1
        elif re.fullmatch(r'[0-9a-f]{64}\.wav', name):
            path = Path(store.root) / 'objects' / name[:2] / name
            if not path.is_symlink():
                path.unlink(missing_ok=True)
        store.conn.execute('DELETE FROM akousmata_derivative_objects WHERE object_ref=?', (ref,))
    store.conn.commit()
    return {'removed_objects': removed}


def _durable_json(path, value):
    with path.open('x') as output:
        json.dump(value, output, allow_nan=False)
        output.flush()
        os.fsync(output.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _recover(store):
    directory = Path(store.root) / '.spectral-transactions'
    directory.mkdir(exist_ok=True)
    for journal in directory.glob('*.json'):
        if journal.is_symlink() or journal.stat().st_size > 32768:
            raise ValueError('Invalid spectral recovery journal')
        entry = json.loads(journal.read_text())
        for name in entry['created']:
            if not re.fullmatch(r'[0-9a-f]{64}\.(npy|wav)', name):
                raise ValueError('Invalid staged object name')
            ref = 'akousmata://objects/' + name
            # A committed record wins over an interrupted publication journal.
            referenced = False
            for row in store.conn.execute('SELECT record FROM akousmata'):
                record = json.loads(row['record'])
                views = record.get('extensions', {}).get('oida.spectral', {}).get('views', [])
                if record.get('audio', {}).get('uri') == ref or any(v.get('object_ref') == ref for v in views):
                    referenced = True
                    break
            if not referenced:
                target = Path(store.root) / 'objects'
                if name.endswith('.wav'):
                    target /= name[:2]
                (target / name).unlink(missing_ok=True)
        journal.unlink()
    objects = Path(store.root) / 'objects'
    for staged in [*objects.glob('.spectral-*'), *objects.glob('??/.spectral-*')]:
        if staged.is_file() and not staged.is_symlink():
            staged.unlink()


@_locked
def recover_derivatives(store):
    _recover(store)
    return reconcile_derivatives.__wrapped__(store)


@_locked
def revoke_derivatives(store, record_id):
    _tables(store)
    store.conn.execute("UPDATE akousmata_derivative_grants SET state='revoked' WHERE record_id=?", (record_id,))
    store.conn.commit()
    return reconcile_derivatives.__wrapped__(store)


@_locked
def publish_bundle(store, record, payloads, *, memory, derivatives_permitted,
                   expires_at, validate_native=None, resolve_representation=None,
                   cancelled=lambda: False, source_bytes=None):
    """Publish a fresh record and its derivative grant in one SQLite commit.

    Files precede the transaction and are journaled for crash recovery. No
    canonical record points to staged bytes. Callbacks belong to the host.
    """
    if memory != 'record_audio' or derivatives_permitted is not True:
        raise ValueError('Signal-bearing derivatives require audio retention')
    if store.get(record['akousma_id']) is not None:
        raise ValueError('Spectral publication requires a fresh record identity')
    if sum(len(data) for data in payloads.values()) > MAX_OBJECT_BYTES:
        raise ValueError('Bundle exceeds 64 MiB')
    _recover(store)
    prepared = deepcopy(record)
    bundle = prepared['extensions']['oida.spectral']
    retained = [v for v in bundle['views'] if v['state'] == 'retained']
    if set(payloads) != {v['view_id'] for v in retained}:
        raise ValueError('Payload membership must match retained views')
    created = []
    for view in retained:
        meta = inspect_numeric(payloads[view['view_id']])
        name = meta['sha256'] + '.npy'
        if not (Path(store.root) / 'objects' / name).exists():
            created.append(name)
        view.update({k: v for k, v in meta.items() if k != 'content_type'})
        view['object_ref'] = 'akousmata://objects/' + name
    if source_bytes is not None:
        import soundfile as sf
        if len(source_bytes) > 96*1024**2 or hashlib.sha256(source_bytes).hexdigest() != bundle['subject_ref']:
            raise ValueError('Source audio identity or size mismatch')
        info = sf.info(io.BytesIO(source_bytes))
        if info.format != 'WAV':
            raise ValueError('Retained native source must be WAV')
        source_name = bundle['subject_ref'] + '.wav'
        if not (Path(store.root) / 'objects' / source_name[:2] / source_name).exists():
            created.append(source_name)
        prepared['audio'] = dict(asset_id=bundle['subject_ref'], content_hash=bundle['subject_ref'],
                                 uri='akousmata://objects/' + source_name, sample_rate=info.samplerate,
                                 channels=info.channels, duration_seconds=info.duration)
        prepared['auditum']['honest_absences'] = [a for a in prepared['auditum'].get('honest_absences', [])
                                                 if a.get('subject') != 'raw audio']
    journal = Path(store.root) / '.spectral-transactions' / (uuid.uuid4().hex + '.json')
    _durable_json(journal, {'created': created})
    try:
        if source_bytes is not None:
            objects = Path(store.root) / 'objects' / source_name[:2]
            objects.mkdir(parents=True, exist_ok=True)
            destination = objects / source_name
            if destination.is_symlink():
                raise ValueError('Symlinked source object')
            if destination.exists():
                if destination.read_bytes() != source_bytes:
                    raise ValueError('Corrupt source object')
            else:
                fd, temporary = tempfile.mkstemp(prefix='.spectral-', dir=objects)
                try:
                    with os.fdopen(fd, 'wb') as output:
                        output.write(source_bytes)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(temporary, destination)
                    fd = os.open(objects, os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                finally:
                    Path(temporary).unlink(missing_ok=True)
        for view in retained:
            if cancelled():
                raise InterruptedError('Spectral publication cancelled')
            retain_numeric.__wrapped__(store.root, payloads[view['view_id']])
        store.put(prepared, supported_versions=['1.8.0'], validate_native=validate_native,
                  resolve_representation=resolve_representation,
                  resolve_object=lambda ref: resolve_numeric(store.root, ref)[1], commit=False)
        grant_derivatives.__wrapped__(store, prepared['akousma_id'], memory=memory,
                                      derivatives_permitted=True, expires_at=expires_at, commit=False)
        if cancelled():
            raise InterruptedError('Spectral publication cancelled')
        store.conn.commit()
        journal.unlink()
        return prepared
    except BaseException:
        store.conn.rollback()
        _recover(store)
        raise
