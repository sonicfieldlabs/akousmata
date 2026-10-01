"""Live, local owner inventory. Model requests cannot supply arbitrary file paths."""
import json
import os
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit
from urllib.request import urlopen
from urllib.error import HTTPError
from akousmata_app.paths import open_store, store_root
from akousmata_app.records import resolve_audio_path, summary_line, card
from .runtime import digest


def content_hash(record):
    value=str((record.get('audio') or {}).get('content_hash') or '').removeprefix('sha256:').lower()
    return value if re.fullmatch('[a-f0-9]{64}',value) else None


def allowed(record):
    if (record.get('annotations') or {}).get('acoustic_excluded'):
        return False
    if (record.get('extensions') or {}).get('akousmata.acoustic',{}).get('excluded'):
        return False
    def restricted(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key=='privacy_mode' and item=='incognito':return True
                if key=='raw_audio_policy' and item in {'not_stored','withheld','deleted'}:return True
                if key in {'consent','consent_status','permission'} and isinstance(item,str) and item in {'denied','revoked','withheld'}:return True
                if restricted(item):return True
        elif isinstance(value,list):
            return any(restricted(v) for v in value)
        return False
    return not restricted(record)


class Catalog:
    def __init__(self):
        self.hashes={};self.lock=threading.Lock()

    def hash(self,path):
        stat=path.stat();key=(str(path),stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
        with self.lock:
            if key not in self.hashes:
                if len(self.hashes)>1024:self.hashes.clear()
                self.hashes[key]=digest(path)
            return self.hashes[key]

    def germ(self,path):
        base=os.getenv('AKOUSMATA_ACOUSTIC_GERM_URL')
        if not base:return None
        parts=urlsplit(base)
        if parts.scheme!='http' or parts.hostname not in {'127.0.0.1','localhost','::1'} or parts.username or parts.password or parts.path not in {'','/'}:
            raise ValueError('Acoustic library owner must be a configured loopback origin')
        try:
            with urlopen(base.rstrip('/')+path,timeout=20) as response:
                raw=response.read(8*1024*1024+1)
        except HTTPError as exc:
            if exc.code==404 and path.startswith('/library/audio/'):return None
            raise
        if len(raw)>8*1024*1024:raise ValueError('Library exceeds inventory bound')
        return json.loads(raw)

    def inventory(self):
        roots=[store_root().resolve(),*[Path(p).expanduser().resolve() for p in os.getenv('AKOUSMATA_ACOUSTIC_AUDIO_ROOTS','').split(os.pathsep) if p]]
        def checked(path):
            if not path:return None
            path=Path(path).resolve()
            if not path.is_file() or path.stat().st_size>512*1024*1024 or not any(path.is_relative_to(root) for root in roots):return None
            return path
        store=open_store()
        try:
            rows=store.conn.execute('SELECT record FROM akousmata LIMIT 5001').fetchall()
            if len(rows)>5000:raise ValueError('Inventory exceeds 5000 records; narrow the archive before indexing')
            records={r['akousma_id']:r for row in rows for r in [json.loads(row[0])]}
            eligible={k:v for k,v in records.items() if allowed(v)}
            records_by_hash={}
            for rid,record in eligible.items():
                sha=content_hash(record)
                if sha:records_by_hash.setdefault(sha,[]).append(rid)
            blocked_hashes=set()
            for rid,record in records.items():
                if rid in eligible:continue
                sha=content_hash(record)
                if sha:blocked_hashes.add(sha)
                path=checked(resolve_audio_path(store,record))
                if path:blocked_hashes.add(self.hash(path))
            items={}
            for rid,record in eligible.items():
                path=checked(resolve_audio_path(store,record))
                if not path:continue
                sha=self.hash(path)
                if sha in blocked_hashes:continue
                items['record:'+rid]=dict(id='record:'+rid,kind='memory',record_id=rid,library_key=None,
                    card=card(record),title=summary_line(record) or rid,tags=record.get('tags') or [],path=str(path),sha256=sha,
                    generated=(record.get('provenance') or {}).get('source_type')=='generated',parents=(record.get('lineage') or {}).get('parents') or [])
            catalog=self.germ('/workspace/library')
            if catalog:
                library=catalog['items']
                if len(library)>5000:raise ValueError('Library exceeds bounded inventory')
                generated_ids = {i['sound_id'] for i in library if i['kind'] == 'generated'}
                for _ in range(len(library)):
                    descendants = {i['sound_id'] for i in library if any(p in generated_ids for p in i.get('parents', []) if isinstance(p, str))}
                    if descendants <= generated_ids:break
                    generated_ids.update(descendants)
                for row in library:
                    key=row['key']
                    if not re.fullmatch('[a-f0-9]{64}',key):continue
                    refs=row.get('memory_ids') or []
                    refs=list(set(refs+[x['record_id'] for x in row.get('memory_influences',[]) if x.get('record_id')]))
                    if any(rid not in eligible for rid in refs) or not allowed(row):continue
                    location=self.germ('/library/audio/'+key+'/resolve')
                    if not location:continue
                    path=checked(location['path'])
                    if not path:continue
                    sha=self.hash(path)
                    if sha in blocked_hashes:continue
                    item=dict(id='library:'+key,kind='library',library_key=key,record_id=None,title=row['title'],tags=row.get('tags') or [],
                        path=str(path),sha256=sha,generated=row['sound_id'] in generated_ids,parents=row.get('parents') or [],memory_ids=refs,sound_id=row['sound_id'])
                    items[item['id']]=item
                    # A memory influence is not the source recording. Link only exact content.
                    for rid in records_by_hash.get(sha,[]):
                        items['record:'+rid]={**item,'id':'record:'+rid,'kind':'memory','record_id':rid,'title':summary_line(eligible[rid]) or rid,'card':card(eligible[rid])}
            return items
        finally:
            store.close()
