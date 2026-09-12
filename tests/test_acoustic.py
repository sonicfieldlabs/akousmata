import json
import threading
from types import SimpleNamespace
import numpy as np
import pytest
import soundfile as sf
from akousma.model_ecology import embedding
from akousmata_app.acoustic.index import Index
from akousmata_app.acoustic.service import Service
from akousmata_app.acoustic.catalog import allowed
from akousmata_app.acoustic.runtime import digest

SPACE=dict(model='test',revision='a'*40,preprocessing_sha256='b'*64,dimensions=3,pooling='projected',metric='cosine')

def segment(source,start=0,end=1,space=None,vector=None):
    return dict(embedding=dict(space=space or SPACE,vector=vector or [1.,0.,0.]),receipt=dict(source_sha256=source,start_seconds=start,end_seconds=end),deployment_id='test')

def asset(name='one',source='c'*64,generated=False):
    return dict(id=name,sha256=source,title=name,kind='library',library_key=name,generated=generated,parents=[])

def test_index_reuse_space_isolation_and_deleted_restricted_assets(tmp_path):
    index=Index(tmp_path);space=embedding(segment('c'*64)['embedding'])[0];a=asset();b=asset('copy')
    index.save_asset('one',space,a['sha256'],[segment(a['sha256'])])
    index.save_asset('copy',space,a['sha256'],[segment(a['sha256'])])
    assert index.cached(space,a['sha256'],0,1)
    result=index.search(segment(a['sha256'])['embedding'],{'one':a,'copy':b})
    assert len(result)==1
    other={**SPACE,'revision':'d'*40}
    assert index.search(dict(space=other,vector=[1.,0.,0.]),{'one':a})==[]
    assert index.search(segment(a['sha256'])['embedding'],{})==[]
    assert index.cached(space,a['sha256'],0,1) is None


def test_stale_audio_generated_and_nonfinite_do_not_leak(tmp_path):
    index=Index(tmp_path);a=asset(generated=True);s=segment(a['sha256']);space=embedding(s['embedding'])[0]
    index.save_asset('one',space,a['sha256'],[s])
    assert index.search(s['embedding'],{'one':a})==[]
    assert len(index.search(s['embedding'],{'one':a},include_generated=True))==1
    assert index.search(s['embedding'],{'one':{**a,'sha256':'e'*64}},include_generated=True)==[]
    with pytest.raises(ValueError):index.save_asset('bad',space,a['sha256'],[segment(a['sha256'],vector=[float('nan'),1,0])])
    assert not allowed({'listening':{'oida.listen':{'payload':{'privacy_mode':'incognito'}}}})
    assert not allowed({'extensions':{'akousmata.acoustic':{'excluded':True}}})
    assert not allowed({'provenance':{'consent_status':'revoked'}})
    assert not allowed({'annotations':{'acoustic_excluded':True}})
    assert allowed({'privacy_mode':'private'})


def harness(tmp_path):
    path=tmp_path/'audio.wav';sf.write(path,np.zeros(48000),48000)
    a={**asset(source=digest(path)),'path':str(path)};rows={'one':a};calls=[]
    def encode(items,cancel=lambda:None):
        cancel();calls.append(items)
        return [segment(a['sha256'],x.get('start_seconds',0),x.get('seconds',1)) for x in items]
    runtime=SimpleNamespace(error=None,space=SPACE,space_id=embedding(segment(a['sha256'])['embedding'])[0],encode=encode,status=lambda:dict(available=True))
    service=Service(tmp_path,runtime=runtime,catalog=SimpleNamespace(inventory=lambda:rows))
    return service,a,rows,calls


def test_backfill_is_additive_idempotent_and_rechecks_permission(tmp_path):
    service,a,rows,calls=harness(tmp_path);before=(tmp_path/'audio.wav').read_bytes()
    job=dict(new_segments=0,reused_segments=0)
    service.index_asset(a,lambda:None,job);service.index_asset(a,lambda:None,job)
    assert len(calls)==1 and job==dict(new_segments=1,reused_segments=1)
    assert (tmp_path/'audio.wav').read_bytes()==before
    service.index.prune({});calls.clear()
    old=service.runtime.encode
    def revoke(items,cancel):
        value=old(items,cancel);rows.clear();return value
    service.runtime.encode=revoke
    with pytest.raises(ValueError,match='restricted'):service.index_asset(a,lambda:None,job)
    assert not service.index.segments('one',service.runtime.space_id,a['sha256'])


def test_query_cache_and_missing_query_audio(tmp_path):
    service,a,rows,calls=harness(tmp_path);job=dict(new_segments=0,reused_segments=0)
    with pytest.raises(ValueError,match='Index this sound'):service.query(asset_id='one')
    service.index_asset(a,lambda:None,job)
    service.query(text='percussive');service.query(text='percussive')
    assert len(calls)==2
    assert service.query(asset_id='one')['results']==[]  # Never return self-content.
    with pytest.raises(ValueError):service.query(text='x',asset_id='one')


def test_cancel_and_restart_do_not_autorun(tmp_path):
    service,a,rows,calls=harness(tmp_path)
    service.index.save_job(dict(id='old',status='running'))
    again=Service(tmp_path,runtime=service.runtime,catalog=service.catalog)
    assert again.index.jobs()[0]['status']=='interrupted'
    entered=threading.Event()
    def waiting(asset,cancel,job):
        import time
        entered.set()
        while True:cancel();time.sleep(.01)
    service.index_asset=waiting
    job=service.start(['one']);assert entered.wait(2)
    service.cancel(job['id'])
    assert service.job_lock.acquire(timeout=2);service.job_lock.release()
    saved=next(j for j in service.index.jobs() if j['id']==job['id'])
    assert saved['status']=='cancelled'


def test_owner_api_bounds_and_origin(monkeypatch,tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from akousmata_app.acoustic import api
    service,a,rows,calls=harness(tmp_path)
    monkeypatch.setattr(api,'service',lambda:service)
    app=FastAPI();app.include_router(api.router);client=TestClient(app)
    assert client.post('/api/acoustic/query',json={'text':'x'},headers={'Origin':'https://foreign.test'}).status_code==403
    assert client.post('/api/acoustic/backfill',json={'limit':100}).status_code==422
    assert client.post('/api/acoustic/query',json={'asset_id':'../../private'}).status_code==422
    assert client.post('/api/acoustic/query',json={'text':'x','path':'/private'}).status_code==422
    assert client.post('/api/acoustic/query',json={'text':'x','asset_id':'record:one'}).status_code==400
    assert calls==[]


def test_real_subprocess_is_stopped_before_admission_released(tmp_path,monkeypatch):
    monkeypatch.setenv("LISTENINGSTACK_RESOURCE_DIR",str(tmp_path/"resources"))
    import time
    from akousmata_app.acoustic.runtime import Runtime
    import sys
    script=tmp_path/'worker.py';marker=tmp_path/'started'
    script.write_text('import pathlib,time\npathlib.Path('+repr(str(marker))+').touch()\ntime.sleep(30)\n')
    runtime=Runtime();runtime.error=None;runtime.entry=dict(manifest=dict(id='fake'),model=str(tmp_path),worker=str(script),python=sys.executable)
    runtime.registry=SimpleNamespace(require=lambda *a:None);runtime.verify=lambda m:[]
    event=threading.Event();errors=[]
    def cancel():
        if event.is_set():raise InterruptedError('cancelled')
    def execute():
        try:runtime.encode([dict(text='test')],cancel)
        except InterruptedError:errors.append('cancelled')
    thread=threading.Thread(target=execute);thread.start()
    deadline=time.monotonic()+3
    while not marker.exists() and time.monotonic()<deadline:time.sleep(.01)
    assert marker.exists();event.set();thread.join(timeout=3)
    assert not thread.is_alive() and errors==['cancelled'] and not runtime.lock.locked()


def test_catalog_exact_aliases_and_restriction_apply_to_duplicate_audio(tmp_path,monkeypatch):
    from akousmata_app.acoustic import catalog as module
    import sqlite3
    audio=tmp_path/'audio.wav';sf.write(audio,np.zeros(48000),48000)
    sha=digest(audio)
    record=dict(akousma_id='memory',audio=dict(content_hash='sha256:'+sha),summary='original',created_at='2026-09-10T00:00:00Z')
    db=sqlite3.connect(':memory:');db.execute('CREATE TABLE akousmata(record TEXT)');db.execute('INSERT INTO akousmata VALUES(?)',(json.dumps(record),))
    store=SimpleNamespace(conn=db,close=lambda:None)
    monkeypatch.setattr(module,'open_store',lambda:store);monkeypatch.setattr(module,'store_root',lambda:tmp_path)
    catalog=module.Catalog();key='a'*64
    catalog.germ=lambda path:dict(items=[dict(key=key,title='copy',kind='recording',sound_id='sound')]) if path=='/workspace/library' else dict(path=str(audio))
    try:
        inventory=catalog.inventory();assert set(inventory)=={'record:memory','library:'+key}
        record['annotations']=dict(acoustic_excluded=True)
        db.execute('UPDATE akousmata SET record=?',(json.dumps(record),))
        assert catalog.inventory()=={}
    finally:db.close()


def test_generated_ancestry_survives_recording_and_exact_memory_alias(tmp_path,monkeypatch):
    from akousmata_app.acoustic import catalog as module
    import sqlite3
    files=[]
    for index in range(3):
        path=tmp_path/f'{index}.wav';sf.write(path,np.full(4800,.1*index),48000);files.append(path)
    record=dict(akousma_id='review',audio=dict(content_hash='sha256:'+digest(files[2])),summary='review',created_at='2026-09-10T00:00:00Z')
    db=sqlite3.connect(':memory:');db.execute('CREATE TABLE akousmata(record TEXT)');db.execute('INSERT INTO akousmata VALUES(?)',(json.dumps(record),))
    monkeypatch.setattr(module,'open_store',lambda:SimpleNamespace(conn=db,close=lambda:None));monkeypatch.setattr(module,'store_root',lambda:tmp_path)
    rows=[dict(key=str(i+1)*64,title='sound',sound_id=f'sound{i}',kind='generated' if i==0 else 'recording',parents=[] if i==0 else [f'sound{i-1}']) for i in range(3)]
    catalog=module.Catalog()
    catalog.germ=lambda path:dict(items=rows) if path=='/workspace/library' else dict(path=str(files[int(path.split('/')[3][0])-1]))
    try:
        inventory=catalog.inventory()
        assert all(row['generated'] for row in inventory.values())
        assert inventory['record:review']['generated']
    finally:db.close()
