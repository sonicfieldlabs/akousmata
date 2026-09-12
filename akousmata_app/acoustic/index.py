"""Content/segment/encoder-addressed side index with live eligibility filtering."""
from contextlib import contextmanager
import hashlib
import json
import sqlite3
from pathlib import Path
from akousma.model_ecology import embedding
from akousmata_app.similar import _embedding_cosine


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class Index:
    def __init__(self, root):
        self.path = Path(root) / 'acoustic.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS vectors(key TEXT PRIMARY KEY, space TEXT NOT NULL, source TEXT NOT NULL, start REAL NOT NULL, end REAL NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS vector_space ON vectors(space);
            CREATE TABLE IF NOT EXISTS bindings(asset TEXT NOT NULL, vector TEXT NOT NULL, PRIMARY KEY(asset,vector));
            CREATE TABLE IF NOT EXISTS queries(key TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            ''')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def cached(self, space, source, start, end):
        key = identity([space, source, start, end])
        with self.connect() as db:
            row = db.execute('SELECT payload FROM vectors WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_asset(self, asset, space, source, segments):
        # Commit a complete asset atomically; never overwrite another encoder's bindings.
        validated = []
        for segment in segments:
            parsed = embedding(segment['embedding'])
            if parsed is None or parsed[0] != space:
                raise ValueError('Embedding space mismatch')
            r = segment['receipt']
            if r['source_sha256'] != source or not 0 <= r['start_seconds'] < r['end_seconds']:
                raise ValueError('Invalid segment provenance')
            key = identity([space, source, r['start_seconds'], r['end_seconds']])
            validated.append((key, segment))
        with self.connect() as db:
            db.execute('DELETE FROM bindings WHERE asset=? AND vector IN (SELECT key FROM vectors WHERE space=?)', (asset, space))
            for key, segment in validated:
                r = segment['receipt']
                db.execute('INSERT OR IGNORE INTO vectors VALUES(?,?,?,?,?,?)',
                           (key, space, source, r['start_seconds'], r['end_seconds'], json.dumps(segment, allow_nan=False)))
                db.execute('INSERT OR IGNORE INTO bindings VALUES(?,?)', (asset, key))

    def prune(self, eligible):
        with self.connect() as db:
            for row in db.execute('SELECT DISTINCT asset FROM bindings').fetchall():
                if row[0] not in eligible:
                    db.execute('DELETE FROM bindings WHERE asset=?', (row[0],))
            db.execute('DELETE FROM vectors WHERE key NOT IN (SELECT vector FROM bindings)')

    def segments(self, asset, space, source):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT v.payload FROM vectors v JOIN bindings b ON b.vector=v.key WHERE b.asset=? AND v.space=? AND v.source=? ORDER BY v.start', (asset,space,source))]

    def query_cache(self, key, value=None):
        with self.connect() as db:
            if value is not None:
                db.execute('INSERT OR REPLACE INTO queries VALUES(?,?)',(key,json.dumps(value)))
                db.execute('DELETE FROM queries WHERE rowid NOT IN (SELECT rowid FROM queries ORDER BY rowid DESC LIMIT 128)')
                return value
            row=db.execute('SELECT payload FROM queries WHERE key=?',(key,)).fetchone()
            return json.loads(row[0]) if row else None

    def search(self, query, eligible, *, scope='all', limit=10, exclude_source=None, include_generated=False):
        parsed = embedding(query)
        if parsed is None:
            raise ValueError('Invalid query embedding')
        self.prune(eligible)
        def candidates():
            with self.connect() as db:
                yield from db.execute('SELECT v.*, b.asset FROM vectors v JOIN bindings b ON b.vector=v.key WHERE space=?', (parsed[0],))
        groups={}
        for row in candidates():
            asset=eligible.get(row['asset'])
            if not asset or row['source'] != asset['sha256'] or row['source']==exclude_source:
                continue
            if scope != 'all' and asset['kind'] != scope:
                continue
            if asset.get('generated') and not include_generated:
                continue
            payload=json.loads(row['payload']);score=_embedding_cosine(parsed,embedding(payload['embedding']))
            if score is None:continue
            entry={k:v for k,v in asset.items() if k not in {'path','sha256'}}
            entry.update(score=round(score,6),basis='CLAP cosine; uncalibrated resemblance, not source identity',
                         segment=payload['receipt'],space=payload['embedding']['space'],
                         deployment_id=payload['deployment_id'],source_sha256=row['source'])
            # One best segment per source, regardless of duplicate records/uploads.
            previous=groups.get(row['source'])
            if previous is None or score>previous['score']:groups[row['source']]=entry
        return sorted(groups.values(),key=lambda x:(-x['score'],x['id']))[:limit]

    def save_job(self, value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?)',(value['id'],json.dumps(value)))

    def jobs(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload FROM jobs ORDER BY rowid DESC LIMIT 20')]

    def stats(self, space):
        with self.connect() as db:
            assets=db.execute('SELECT COUNT(DISTINCT b.asset) FROM bindings b JOIN vectors v ON b.vector=v.key WHERE v.space=?',(space,)).fetchone()[0]
            vectors=db.execute('SELECT COUNT(*) FROM vectors WHERE space=?',(space,)).fetchone()[0]
        return dict(assets=assets,segments=vectors)
