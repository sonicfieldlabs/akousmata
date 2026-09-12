from functools import lru_cache
import os
from typing import Literal
from fastapi import APIRouter,HTTPException,Request,Depends
from pydantic import BaseModel,ConfigDict,Field
from akousmata_app.paths import store_root
from .service import Service

def same_origin(request:Request):
    if request.headers.get('origin') not in {None,str(request.base_url).rstrip('/')} :
        raise HTTPException(403,'Acoustic operations require the local owner origin')

router=APIRouter(prefix='/api/acoustic',dependencies=[Depends(same_origin)])

class Query(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    text:str=Field(default='',max_length=500)
    asset_id:str|None=Field(default=None,max_length=150,pattern=r'^(record:|library:)[A-Za-z0-9_:.-]+$')
    scope:Literal['all','memory','library']='all'
    limit:int=Field(default=10,ge=1,le=30)
    include_generated:bool=False

class Backfill(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    asset_ids:list[str]=Field(default_factory=list,max_length=32)
    offset:int=Field(default=0,ge=0,le=10000)
    limit:int=Field(default=16,ge=1,le=32)

@lru_cache(maxsize=4)
def instance(root,config):
    from .runtime import Runtime
    return Service(root,runtime=Runtime(config))

def service():
    return instance(str(store_root()),os.getenv('AKOUSMATA_CLAP_CONFIG'))

def call(method,*args,**kwargs):
    try:return getattr(service(),method)(*args,**kwargs)
    except (ValueError,KeyError,TypeError) as exc:raise HTTPException(400,str(exc)) from exc
    except RuntimeError as exc:raise HTTPException(409,str(exc)) from exc
    except (OSError,TimeoutError) as exc:raise HTTPException(503,'Local acoustic service unavailable') from exc

@router.get('/status')
def status():return call('status')

@router.post('/query')
def query(body:Query):return call('query',**body.model_dump())

@router.post('/backfill')
def backfill(body:Backfill):return call('start',**body.model_dump())

@router.post('/jobs/{job_id}/cancel')
def cancel(job_id:str):return call('cancel',job_id)
