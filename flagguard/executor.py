"""Explicit, single-environment default flag changes. No automatic writes."""
import os
import json
from uuid import uuid4
from contextlib import closing
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StrictBool, Field
from .audit import record
from . import providers

class Plan(BaseModel):
    state_id: int = Field(gt=0)
    enabled: StrictBool

class Approval(BaseModel):
    approve: StrictBool

def scope(state_id):
    env = providers.required("FLAGSMITH_ENVIRONMENT_ID")
    allowed = os.getenv("FLAGGUARD_ALLOWED_STATE_IDS", "").split(",")
    if os.getenv("FLAGGUARD_ENABLE_WRITES") != "true" or str(state_id) not in [s.strip() for s in allowed]:
        raise HTTPException(403, "Writes disabled or state not allowlisted")
    return env

def state_request(method, env, state_id, **kwargs):
    url = "https://api.flagsmith.com/api/v1/environments/" + quote(env, safe="") + "/featurestates/" + str(state_id) + "/"
    return providers.request(method, url, {"Authorization": "Api-Key " + providers.required("FLAGSMITH_ADMIN_API_KEY")}, **kwargs)

def snapshot(env, state_id):
    data = state_request("GET", env, state_id)
    if not isinstance(data, dict) or data.get("id") != state_id or type(data.get("enabled")) is not bool:
        raise providers.ProviderError("Unexpected state response")
    if not all(k in data and data[k] is None for k in ("identity", "feature_segment")):
        raise providers.ProviderError("Only explicitly identified environment defaults supported")
    return data

def build_executor_router(authorize, db):
    router = APIRouter(prefix="/api/v1/changes", dependencies=[Depends(authorize)])
    def connection():
        conn = db()
        conn.execute("CREATE TABLE IF NOT EXISTS changes (id TEXT PRIMARY KEY, env TEXT, state_id INTEGER, before TEXT, target INTEGER, status TEXT, created INTEGER DEFAULT (unixepoch()), detail TEXT)")
        return conn
    def read(conn, change_id):
        row = conn.execute("SELECT env,state_id,before,target,status,created FROM changes WHERE id=?", (change_id,)).fetchone()
        if row is None:
            raise HTTPException(404,"Unknown change")
        return row
    @router.post("")
    def plan(body: Plan):
        try:
            env = scope(body.state_id)
            before = snapshot(env, body.state_id)
        except providers.ProviderError as exc:
            raise HTTPException(502,str(exc)) from None
        if before["enabled"] == body.enabled:
            raise HTTPException(409,"Already in desired state")
        change_id = str(uuid4())
        with closing(connection()) as conn, conn:
            conn.execute("INSERT INTO changes(id,env,state_id,before,target,status) VALUES(?,?,?,?,?,?)",(change_id,env,body.state_id,json.dumps(before,sort_keys=True),int(body.enabled),"pending"))
            record(conn, "legacy_change", change_id, "plan", "pending")
        return {"id":change_id,"environment":env,"state_id":body.state_id,"before_enabled":before["enabled"],"target_enabled":body.enabled,"status":"pending","scope":"environment_default_only"}
    @router.post("/{change_id}/approval")
    def approve(change_id: str, body: Approval):
        status = "approved" if body.approve else "rejected"
        with closing(connection()) as conn, conn:
            result = conn.execute("UPDATE changes SET status=? WHERE id=? AND status='pending' AND created >= unixepoch()-600",(status,change_id))
            if result.rowcount != 1:
                raise HTTPException(409,"Missing, expired or decided change")
            record(conn, "legacy_change", change_id, "decision", status)
        return {"id":change_id,"status":status}
    @router.get("/{change_id}")
    def get(change_id: str):
        with closing(connection()) as conn:
            row = read(conn,change_id)
            detail = conn.execute("SELECT detail FROM changes WHERE id=?",(change_id,)).fetchone()[0]
        return {"id":change_id,"environment":row[0],"state_id":row[1],"before_enabled":json.loads(row[2])["enabled"],"target_enabled":bool(row[3]),"status":row[4],"detail":detail}
    @router.post("/{change_id}/execute")
    def execute(change_id: str):
        with closing(connection()) as conn, conn:
            row = read(conn,change_id)
            env,state_id,before,target,_,_ = row
            try:
                if scope(state_id) != env:
                    raise HTTPException(409,"Environment changed")
            except providers.ProviderError as exc:
                raise HTTPException(502,str(exc)) from None
            result = conn.execute("UPDATE changes SET status='executing' WHERE id=? AND status='approved' AND created >= unixepoch()-600",(change_id,))
            if result.rowcount != 1:
                raise HTTPException(409,"Change not approved, expired or already used")
            record(conn, "legacy_change", change_id, "execute", "executing")
        status,detail = "unknown","Execution interrupted; inspect provider before retrying"
        try:
            if snapshot(env,state_id) != json.loads(before):
                status,detail = "stale","Provider snapshot changed; create new plan"
            else:
                state_request("PATCH",env,state_id,json={"enabled":bool(target)})
                actual = snapshot(env,state_id)
                if actual["enabled"] == bool(target):
                    status,detail = "verified","Environment default verified; identity and segment overrides not verified"
                else:
                    status,detail = "unknown","Provider state differs from target"
        except providers.ProviderError as exc:
            status = "unknown"
            detail = f"Provider error: {exc}"
        finally:
            with closing(connection()) as conn, conn:
                conn.execute("UPDATE changes SET status=?,detail=? WHERE id=?",(status,detail,change_id))
                record(conn, "legacy_change", change_id, "result", status)
        return {"id":change_id,"status":status,"executed":status=="verified","detail":detail}
    return router
