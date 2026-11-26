"""Tenant-scoped REST ingestion and analysis. No provider mutation authority."""
import hashlib
import secrets
from uuid import UUID,uuid4
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException, Response, Query
from pydantic import BaseModel, ConfigDict, Field
from psycopg.types.json import Jsonb
from psycopg.errors import UniqueViolation
from .tenant_directory import connect
from .identity import identity
from .core import summarize, assess

Name=Annotated[str,Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$")]

class Policy(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False)
    window_seconds:int=Field(default=300,ge=30,le=3600,strict=True)
    minimum:int=Field(default=100,ge=20,le=5000,strict=True)
    threshold:float=Field(default=5,ge=0,le=100)
    error_gap:float=Field(default=2,ge=0,le=100)
    latency_ratio:float=Field(default=2,ge=1.1,le=100)
    latency_delta_ms:float=Field(default=100,ge=1,le=86400000)

class Application(BaseModel):
    model_config=ConfigDict(extra="forbid")
    service:Name
    environment:Name
    flags:list[Name]=Field(min_length=1,max_length=100)
    policy:Policy=Field(default_factory=Policy)

def digest(key):
    return hashlib.sha256(key.encode()).hexdigest()

def new_key():
    key="fg_v2_"+secrets.token_urlsafe(32)
    return key,digest(key)

def membership(conn,wid,user,write=False):
    row=conn.execute("SELECT role FROM flagguard_private.members WHERE workspace_id=%s AND user_id=%s FOR SHARE",(wid,user["id"])).fetchone()
    if not row:
        raise HTTPException(404,"Workspace not found")
    if write and row[0] not in ("owner","admin"):
        raise HTTPException(403,"Administrator role required")

def application(conn,wid,aid):
    row=conn.execute("SELECT service,environment,flags,policy FROM flagguard_private.applications WHERE workspace_id=%s AND id=%s",(wid,aid)).fetchone()
    if not row:
        raise HTTPException(404,"Application not found")
    return row

def analyze(conn,wid,aid,flag,config):
    rules=dict(config)
    window=rules.pop("window_seconds")
    rows=conn.execute("SELECT payload FROM flagguard_private.telemetry_events WHERE workspace_id=%s AND application_id=%s AND received>=now()-(%s * interval '1 second') AND jsonb_exists(payload->'flags',%s) ORDER BY received DESC,id DESC LIMIT 10000",(wid,aid,window,flag)).fetchall()
    groups=summarize([r[0] for r in rows],flag)
    return {"groups":groups,"recommendation":assess(groups,**rules),"window_seconds":window,"policy":rules,"executed":False}

def build_router(Event):
    router=APIRouter(prefix="/api/v2")
    base="/workspaces/{workspace_id}/applications"

    @router.get(base)
    def list_apps(workspace_id:UUID,user=Depends(identity)):
        with connect() as conn:
            membership(conn,workspace_id,user)
            rows=conn.execute("SELECT id,service,environment,flags,policy FROM flagguard_private.applications WHERE workspace_id=%s ORDER BY service,environment",(workspace_id,)).fetchall()
        return [{"id":str(r[0]),"service":r[1],"environment":r[2],"flags":r[3],"policy":r[4]} for r in rows]

    @router.post(base,status_code=201)
    def create(workspace_id:UUID,body:Application,response:Response,user=Depends(identity)):
        if len(set(body.flags))!=len(body.flags):
            raise HTTPException(422,"Duplicate flags")
        aid=uuid4()
        key,hashed=new_key()
        try:
            with connect() as conn:
                membership(conn,workspace_id,user,True)
                conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,1))",(str(workspace_id),))
                if conn.execute("SELECT count(*) FROM flagguard_private.applications WHERE workspace_id=%s",(workspace_id,)).fetchone()[0]>=20:
                    raise HTTPException(409,"Application limit reached")
                conn.execute("INSERT INTO flagguard_private.applications(workspace_id,id,service,environment,flags,policy,key_hash) VALUES(%s,%s,%s,%s,%s,%s,%s)",(workspace_id,aid,body.service,body.environment,body.flags,Jsonb(body.policy.model_dump()),hashed))
        except UniqueViolation:
            raise HTTPException(409,"Application already exists") from None
        response.headers["Cache-Control"]="no-store"
        return {"id":str(aid),"telemetry_key":key,**body.model_dump()}

    @router.post(base+"/{application_id}/rotate-key")
    def rotate(workspace_id:UUID,application_id:UUID,response:Response,user=Depends(identity)):
        key,hashed=new_key()
        with connect() as conn:
            membership(conn,workspace_id,user,True)
            row=conn.execute("UPDATE flagguard_private.applications SET key_hash=%s WHERE workspace_id=%s AND id=%s RETURNING id",(hashed,workspace_id,application_id)).fetchone()
            if not row:
                raise HTTPException(404,"Application not found")
        response.headers["Cache-Control"]="no-store"
        return {"telemetry_key":key}

    @router.put(base+"/{application_id}/policy")
    def update_policy(workspace_id:UUID,application_id:UUID,body:Policy,user=Depends(identity)):
        with connect() as conn:
            membership(conn,workspace_id,user,True)
            row=conn.execute("UPDATE flagguard_private.applications SET policy=%s WHERE workspace_id=%s AND id=%s RETURNING id",(Jsonb(body.model_dump()),workspace_id,application_id)).fetchone()
            if not row:
                raise HTTPException(404,"Application not found")
        return body.model_dump()

    @router.get(base+"/{application_id}/analysis")
    def analysis(workspace_id:UUID,application_id:UUID,flag:str=Query(min_length=1,max_length=100),user=Depends(identity)):
        with connect() as conn:
            membership(conn,workspace_id,user)
            _,_,flags,config=application(conn,workspace_id,application_id)
            if flag not in flags:
                raise HTTPException(404,"Flag not found")
            return analyze(conn,workspace_id,application_id,flag,config)

    @router.post("/telemetry")
    def ingest(event:Event,authorization:str=Header(default="")):
        if not authorization.startswith("Bearer fg_v2_") or len(authorization)>100:
            raise HTTPException(401,"Invalid telemetry key")
        with connect() as conn:
            row=conn.execute("SELECT workspace_id,id,service,environment,flags FROM flagguard_private.applications WHERE key_hash=%s FOR SHARE",(digest(authorization[7:]),)).fetchone()
            if not row:
                raise HTTPException(401,"Invalid telemetry key")
            wid,aid,service,environment,flags=row
            if event.service!=service or event.environment!=environment or not set(event.flags)<=set(flags):
                raise HTTPException(403,"Telemetry scope not authorized")
            conn.execute("INSERT INTO flagguard_private.telemetry_events(workspace_id,application_id,payload) VALUES(%s,%s,%s)",(wid,aid,Jsonb(event.model_dump())))
        return {"accepted":True}
    return router
