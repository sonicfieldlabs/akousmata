"""Pinned CLAP deployment and bounded cancellable subprocess admission."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from akousma.deployments import DeploymentRegistry
from akousma.model_ecology import embedding
from akousma.resource_admission import heavy_lease
from .index import identity


def digest(path):
    with open(path,'rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


class Runtime:
    def __init__(self, config=None):
        self.config_path = config or os.getenv('AKOUSMATA_CLAP_CONFIG')
        self.entry = None
        self.error = 'CLAP has not been provisioned'
        self.lock = threading.Lock()
        self.registry = DeploymentRegistry('akousmata')
        self.registry.register_adapter('clap-local', ['embed_audio','embed_text'], verify=self.verify)
        try:
            if self.config_path:
                self.entry=json.loads(Path(self.config_path).read_text())
                self.registry.admit(self.entry['manifest'])
                self.space=self.entry['space']
                parsed=embedding(dict(space=self.space,vector=[1.0]*512))
                if parsed is None:raise ValueError('Invalid 512-dimensional space')
                self.space_id=parsed[0]
                self.error=None
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.error='CLAP deployment unavailable: '+str(exc)[:250]

    def verify(self, manifest):
        try:
            e=self.entry
            if not e or manifest!=e['manifest']:return ['Deployment mismatch']
            for path,sha in e['artifacts'].items():
                if digest(path)!=sha:return ['Artifact changed: '+Path(path).name]
            for path in [e['worker'],str(Path(e['python']).resolve()),e['receipt'],e['lock']]:
                if path not in e['artifacts']:return ['Unverified runtime component']
            versions=json.loads(subprocess.check_output([e['python'],'-c',
                'import importlib.metadata,json;print(json.dumps({d.metadata["Name"].lower().replace("_","-"):d.version for d in importlib.metadata.distributions()}))'],timeout=10,text=True))
            for line in Path(e['lock']).read_text().splitlines():
                if '==' in line:
                    name,version=line.split('==',1)
                    if versions.get(name.lower().replace('_','-'))!=version:return ['Runtime package changed: '+name]
            model=Path(e['model'])
            for path in model.iterdir():
                if path.is_file() and str(path) not in e['artifacts']:return ['Unverified model file']
            receipt=json.loads(Path(e['receipt']).read_text())
            if receipt['status']!='passed' or receipt['worker_sha256']!=digest(e['worker']):return ['Validation receipt mismatch']
            if receipt['model_sha256']!=digest(model/'pytorch_model.bin'):return ['Weights receipt mismatch']
            if manifest['validation_receipt']!=digest(e['receipt']):return ['Receipt not pinned']
            if manifest['runtime_revision']!=digest(e['worker']):return ['Worker not pinned']
            if manifest['components'][0]['sha256']!=digest(model/'pytorch_model.bin'):return ['Manifest weights mismatch']
            if manifest['license_review']!=digest(model/'README.md'):return ['License review mismatch']
            if manifest['measured_peak_memory_mib']<receipt['peak_memory_mib']:return ['Insufficient measured reservation']
            if e['space']['revision']!=manifest['components'][0]['revision']:return ['Encoder revision mismatch']
            if e['space']['preprocessing_sha256']!=identity({Path(k).name:v for k,v in e['artifacts'].items() if k.endswith('.json') and Path(k).parent==model} | {'worker':digest(e['worker']), 'environment':digest(e['lock'])}):return ['Preprocessing identity mismatch']
        except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError):return ['Incomplete deployment']
        return []

    def status(self):
        return dict(available=self.error is None, reason=self.error, model='laion/larger_clap_general',
                    space=getattr(self,'space',None), experimental=True)

    def encode(self, items, cancel=lambda:None):
        if self.error:raise ValueError(self.error)
        if not 1<=len(items)<=12:raise ValueError('Choose 1–12 segments per worker request')
        for item in items:
            capability='embed_text' if 'text' in item else 'embed_audio'
            self.registry.require(self.entry['manifest']['id'],capability,item.get('seconds',1))
            if 'text' in item and not 1<=len(item['text'])<=500:raise ValueError('Text query must contain 1–500 characters')
        if not self.lock.acquire(blocking=False):raise RuntimeError('CLAP worker is busy; retry after the current job')
        try:
            cancel()
            problems=self.verify(self.entry['manifest'])
            if problems:raise ValueError('; '.join(problems))
            with heavy_lease('akousmata','embed_audio',timeout=120,checkpoint=cancel):
                with tempfile.TemporaryDirectory(prefix='clap-') as folder:
                    root=Path(folder);request=root/'request.json';output=root/'output.json'
                    request.write_text(json.dumps(dict(model=self.entry['model'],items=items)))
                    env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','TMPDIR'}}
                    env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='2',TOKENIZERS_PARALLELISM='false')
                    started=time.monotonic()
                    with (root/'stderr').open('w') as log:
                        process=subprocess.Popen([self.entry['python'],self.entry['worker'],str(request),str(output)],env=env,stdout=log,stderr=log)
                        try:
                            while process.poll() is None:
                                cancel()
                                if time.monotonic()-started>180:raise TimeoutError('CLAP worker deadline exceeded')
                                time.sleep(.1)
                            if process.returncode or not output.exists():raise RuntimeError('CLAP worker failed; no vectors committed')
                            if output.stat().st_size>2*1024*1024:raise ValueError('Worker output exceeds bounds')
                            value=json.loads(output.read_text())
                        finally:
                            if process.poll() is None:
                                process.terminate()
                                try:process.wait(timeout=2)
                                except subprocess.TimeoutExpired:process.kill();process.wait()
            cancel()
            if len(value['items'])!=len(items):raise ValueError('Worker result count mismatch')
            results=[]
            for requested,item in zip(items,value['items']):
                v=dict(space=self.space,vector=item['vector'])
                if embedding(v) is None:raise ValueError('Invalid worker vector')
                if 'path' in requested and item['receipt']['source_sha256']!=digest(requested['path']):raise ValueError('Source changed during embedding')
                results.append(dict(embedding=v,receipt=item['receipt'],deployment_id=self.entry['manifest']['id']))
            return results
        finally:
            self.lock.release()
