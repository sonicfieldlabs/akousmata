"""Explicit backfill jobs and private, provenance-bearing sound/text retrieval."""
import json
import threading
import time
from uuid import uuid4
from .catalog import Catalog
from .index import Index,identity
from .runtime import Runtime,digest


class Service:
    def __init__(self, root, runtime=None, catalog=None):
        self.index=Index(root);self.runtime=runtime or Runtime();self.catalog=catalog or Catalog()
        self.job_lock=threading.Lock();self.events={}
        for job in self.index.jobs():
            if job['status'] in {'queued','running','cancelling'}:
                job.update(status='interrupted',reason='Owner restarted; restart explicitly to resume cached work')
                self.index.save_job(job)

    def status(self):
        return dict(**self.runtime.status(),jobs=self.index.jobs(),stored_index=self.index.stats(getattr(self.runtime,'space_id','')),segment_seconds=10,max_asset_seconds=120,
                    max_assets_per_job=32,indexing='explicit only',default_generated=False)

    def start(self, asset_ids, offset=0, limit=16):
        if self.runtime.error:raise ValueError(self.runtime.error)
        if not 1<=limit<=32 or not 0<=offset<=10000 or len(asset_ids)>32 or len(asset_ids)!=len(set(asset_ids)):
            raise ValueError('Invalid bounded backfill selection')
        if not self.job_lock.acquire(blocking=False):raise RuntimeError('An acoustic backfill is already active')
        job=dict(id=uuid4().hex,status='queued',completed=0,reused_segments=0,new_segments=0,errors=[],
                 offset=offset,limit=limit,started_at=time.time(),time_limit_seconds=900,max_asset_seconds=120)
        event=threading.Event();self.events[job['id']]=event;self.index.save_job(job)
        def work():
            def cancel():
                if event.is_set():raise InterruptedError('Cancelled by operator')
                if time.time()-job['started_at']>900:raise TimeoutError('Backfill time window reached')
            try:
                inventory=self.catalog.inventory();cancel();self.index.prune(inventory)
                ids=asset_ids or sorted(inventory)[offset:offset+limit]
                if any(i not in inventory for i in ids):raise ValueError('One or more sources are unavailable or restricted')
                job.update(status='running',total=len(ids),inventory_count=len(inventory),next_offset=offset+len(ids))
                for aid in ids:
                    cancel();asset=inventory[aid];job['current_asset']=aid;self.index.save_job(job)
                    try:
                        self.index_asset(asset,cancel,job)
                        job['completed']+=1
                    except InterruptedError:raise
                    except Exception as exc:job['errors'].append(dict(asset_id=aid,reason=str(exc)[:200]))
                    self.index.save_job(job)
                job['status']='partial' if job['errors'] else 'complete'
            except InterruptedError as exc:job.update(status='cancelled',reason=str(exc))
            except Exception as exc:job.update(status='failed',reason=str(exc)[:200])
            finally:
                job.pop('current_asset',None);job['finished_at']=time.time();self.index.save_job(job)
                self.events.pop(job['id'],None);self.job_lock.release()
        threading.Thread(target=work,daemon=True,name='acoustic-backfill').start()
        return dict(job)

    def cancel(self, job_id):
        event=self.events.get(job_id)
        if event:event.set()
        return dict(id=job_id,cancellation_requested=event is not None)

    def index_asset(self, asset, cancel, job):
        import soundfile as sf
        path=asset['path'];info=sf.info(path)
        if not 0<info.duration<=120:raise ValueError('Select audio up to 120 seconds; longer assets are not silently truncated')
        source=digest(path)
        if source!=asset['sha256']:raise ValueError('Source changed before indexing')
        segments=[];missing=[];positions=[]
        start=0
        while start<info.frames:
            end=min(info.frames,start+info.samplerate*10);a,b=start/info.samplerate,end/info.samplerate
            cached=self.index.cached(self.runtime.space_id,source,a,b)
            segments.append(cached)
            if cached:job['reused_segments']+=1
            else:missing.append(dict(path=path,start_seconds=a,seconds=b-a));positions.append(len(segments)-1)
            start=end
        if missing:
            outputs=self.runtime.encode(missing,cancel)
            for position,output in zip(positions,outputs):segments[position]=output
            job['new_segments']+=len(outputs)
        cancel()
        current_inventory=self.catalog.inventory()
        current=current_inventory.get(asset['id'])
        if not current or current['sha256']!=source or digest(path)!=source:raise ValueError('Source removed, restricted or changed before commit')
        for related in current_inventory.values():
            if related['sha256']==source:
                self.index.save_asset(related['id'],self.runtime.space_id,source,segments)

    def query(self, *, text='', asset_id=None, scope='all', limit=10, include_generated=False):
        if self.runtime.error:raise ValueError(self.runtime.error)
        if bool(text.strip())==bool(asset_id):raise ValueError('Choose one text or sound query')
        inventory=self.catalog.inventory();self.index.prune(inventory)
        exclude=None
        if asset_id:
            asset=inventory.get(asset_id)
            if asset is None:raise ValueError('Query source is unavailable or restricted')
            vectors=self.index.segments(asset_id,self.runtime.space_id,asset['sha256'])
            if not vectors:raise ValueError('Index this sound before using it as a query')
            queries=[v['embedding'] for v in vectors];exclude=asset['sha256']
        else:
            key=identity([self.runtime.space_id,text])
            encoded=self.index.query_cache(key)
            if encoded is None or 'embedding' not in encoded:
                encoded=self.runtime.encode([dict(text=text)])[0];self.index.query_cache(key,encoded)
            queries=[encoded['embedding']]
        # Eligibility is refreshed after inference, including owner deletions/restrictions.
        inventory=self.catalog.inventory()
        if asset_id and (asset_id not in inventory or inventory[asset_id]['sha256']!=exclude):
            raise ValueError('Query source removed, restricted or changed')
        matches={}
        for query in queries:
            for row in self.index.search(query,inventory,scope=scope,limit=limit,exclude_source=exclude,include_generated=include_generated):
                previous=matches.get(row['source_sha256'])
                if previous is None or row['score']>previous['score']:matches[row['source_sha256']]=row
        return dict(results=sorted(matches.values(),key=lambda r:-r['score'])[:limit],space=self.runtime.space,
                    mode='sound' if asset_id else 'text',query_segments=len(queries),
                    query_receipt={'asset_id':asset_id,'source_sha256':exclude} if asset_id else encoded['receipt'],
                    limitations=['Cosine is not a probability or proof of source identity.',
                                 'Generated descendants are not independent evidence about their ancestors.',
                                 'Only explicitly indexed, currently eligible segments are searched.'])
