"""CLI-backed changes, separate from legacy state-ID approvals."""
import os
import json
from contextlib import closing
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StrictBool
from . import cli_provider, providers

class Plan(BaseModel):
    feature: str = Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$")
    enabled: StrictBool

class Decision(BaseModel):
    approve: StrictBool

def scope(feature):
    if os.getenv("FLAGSMITH_EXECUTION_PROVIDER") != "cli" or os.getenv("FLAGGUARD_ENABLE_WRITES") != "true":
        raise HTTPException(403,"CLI writes disabled")
    if feature not in [s.strip() for s in os.getenv("FLAGGUARD_ALLOWED_FEATURE_NAMES","").split(",")]:
        raise HTTPException(403,"Feature not allowlisted")
    return {"environment":providers.required("FLAGSMITH_ENVIRONMENT_ID"),"project":providers.required("FLAGSMITH_PROJECT_ID")}

def build_cli_router(authorize, db):
    router=APIRouter(prefix="/api/v1/cli-changes",dependencies=[Depends(authorize)])
    def connection():
        conn=db()
        conn.execute("CREATE TABLE IF NOT EXISTS cli_changes (id TEXT PRIMARY KEY, feature TEXT NOT NULL, scope TEXT NOT NULL, before TEXT NOT NULL, target INTEGER NOT NULL, status TEXT NOT NULL, created INTEGER DEFAULT (unixepoch()), detail TEXT)")
        return conn
    def read(conn,id):
        row=conn.execute("SELECT feature,scope,before,target,status,detail FROM cli_changes WHERE id=?",(id,)).fetchone()
        if row is None:
            raise HTTPException(404,"Unknown change")
        return row
    @router.post("")
    def plan(body: Plan):
        try:
            target_scope=scope(body.feature)
            before=cli_provider.snapshot(body.feature)
        except providers.ProviderError as exc:
            raise HTTPException(502,str(exc)) from None
        if before["enabled"]==body.enabled:
            raise HTTPException(409,"Already in desired state")
        id=str(uuid4())
        with closing(connection()) as conn, conn:
            conn.execute("INSERT INTO cli_changes(id,feature,scope,before,target,status) VALUES(?,?,?,?,?,?)",(id,body.feature,json.dumps(target_scope),json.dumps(before),int(body.enabled),"pending"))
        return {"id":id,"feature":body.feature,**target_scope,"before_enabled":before["enabled"],"target_enabled":body.enabled,"status":"pending"}
    @router.post("/{id}/approval")
    def approve(id: str, body: Decision):
        status="approved" if body.approve else "rejected"
        with closing(connection()) as conn, conn:
            result=conn.execute("UPDATE cli_changes SET status=? WHERE id=? AND status='pending' AND created>=unixepoch()-600",(status,id))
            if result.rowcount!=1:
                raise HTTPException(409,"Missing, expired or already decided")
        return {"id":id,"status":status}
    @router.get("/{id}")
    def get(id: str):
        with closing(connection()) as conn:
            feature,s,before,target,status,detail=read(conn,id)
        return {"id":id,"feature":feature,**json.loads(s),"before_enabled":json.loads(before)["enabled"],"target_enabled":bool(target),"status":status,"detail":detail}
    @router.post("/{id}/execute")
    def execute(id: str):
        with closing(connection()) as conn, conn:
            feature,s,before,target,_,_=read(conn,id)
            try:
                if scope(feature)!=json.loads(s):
                    raise HTTPException(409,"Target scope changed")
            except providers.ProviderError as exc:
                raise HTTPException(502,str(exc)) from None
            result=conn.execute("UPDATE cli_changes SET status='executing' WHERE id=? AND status='approved' AND created>=unixepoch()-600",(id,))
            if result.rowcount!=1:
                raise HTTPException(409,"Not approved, expired or already used")
        status,detail="unknown","Execution interrupted; inspect provider"
        try:
            if cli_provider.snapshot(feature)!=json.loads(before):
                status,detail="stale","Snapshot changed; request fresh approval"
            else:
                cli_provider.update(feature,bool(target))
                actual=cli_provider.snapshot(feature)
                expected=json.loads(before)
                expected["enabled"]=bool(target)
                if actual==expected:
                    status,detail="verified","Environment default verified"
                elif actual["enabled"]==bool(target):
                    status,detail="unknown","Target enabled state observed but other snapshot fields changed"
                else:
                    status,detail="unknown","Provider state differs from target"
        except providers.ProviderError as exc:
            detail=f"Provider error: {exc}"
        finally:
            with closing(connection()) as conn, conn:
                conn.execute("UPDATE cli_changes SET status=?,detail=? WHERE id=?",(status,detail,id))
        return {"id":id,"status":status,"executed":status=="verified","detail":detail}
    return router
