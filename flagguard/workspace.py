"""Single-workspace onboarding. Server environment remains the security ceiling."""
import json
import os
from contextlib import closing
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from .core import policy
from . import providers
from .audit import record

def ceiling(name):
    return sorted({v.strip() for v in os.getenv(name,"").split(",") if v.strip()})

class Workspace(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False)
    service: str=Field(min_length=1,max_length=100)
    environment: str=Field(min_length=1,max_length=100)
    flags: list[str]=Field(min_length=1,max_length=100)
    window_seconds: int=Field(ge=30,le=3600,strict=True)
    minimum: int=Field(ge=20,le=5000,strict=True)
    threshold: float=Field(ge=0,le=100)
    error_gap: float=Field(ge=0,le=100)
    latency_ratio: float=Field(ge=1.1,le=100)
    latency_delta_ms: float=Field(ge=1,le=86400000)

class Activation(BaseModel):
    model_config=ConfigDict(extra="forbid")
    active: StrictBool

def read_workspace(db):
    with closing(db()) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace_config'").fetchone():
            return None
        row=conn.execute("SELECT config,active FROM workspace_config WHERE id=1").fetchone()
        return {**json.loads(row[0]),"active":bool(row[1])} if row else None

def authorized(config):
    return (config["service"] in ceiling("FLAGGUARD_ALLOWED_SERVICES")
            and config["environment"]==os.getenv("FLAGGUARD_TELEMETRY_ENVIRONMENT","development")
            and bool(config["flags"]) and set(config["flags"])<=set(ceiling("FLAGGUARD_ALLOWED_FEATURE_NAMES")))

def scoped_policy(db,service,environment,flag):
    config=read_workspace(db)
    if config and authorized(config) and service==config["service"] and environment==config["environment"] and flag in config["flags"]:
        return {k:config[k] for k in policy()}
    return policy()

def telemetry_counts(db,config):
    counts={f:0 for f in config["flags"]}
    with closing(db()) as conn:
        rows=conn.execute("SELECT payload FROM events WHERE service=? AND environment=? AND received>=unixepoch()-? ORDER BY id DESC LIMIT 10000",(config["service"],config["environment"],config["window_seconds"])).fetchall()
    for (raw,) in rows:
        flags=json.loads(raw).get("flags",{})
        for f in counts:
            counts[f]+=int(f in flags)
    return counts

def build_workspace_router(authorize,db):
    router=APIRouter(prefix="/api/v1/workspace",dependencies=[Depends(authorize)])
    @router.get("")
    def get():
        config=read_workspace(db)
        return {"configuration":config,"defaults":policy(),"allowed_services":ceiling("FLAGGUARD_ALLOWED_SERVICES"),"allowed_flags":ceiling("FLAGGUARD_ALLOWED_FEATURE_NAMES"),"environment":os.getenv("FLAGGUARD_TELEMETRY_ENVIRONMENT","development"),"provider_configured":bool(os.getenv("FLAGSMITH_ENVIRONMENT_KEY")),"management_configured":all(bool(os.getenv(k)) for k in ("FLAGSMITH_ADMIN_API_KEY","FLAGSMITH_ENVIRONMENT_ID","FLAGSMITH_PROJECT_ID")),"telemetry_key_configured":bool(os.getenv("FLAGGUARD_TELEMETRY_KEY")),"writes_enabled":os.getenv("FLAGGUARD_ENABLE_WRITES")=="true","legacy_monitor_enabled":os.getenv("FLAGGUARD_MONITOR_ENABLED")=="true","effective_active":bool(config["active"] and authorized(config)) if config else os.getenv("FLAGGUARD_MONITOR_ENABLED")=="true"}
    @router.get("/flags")
    def flags():
        try:
            data=providers.sdk_flags()
            if not isinstance(data,list):
                raise providers.ProviderError("Unexpected flag response")
            return {"flags":[{"name":v["feature"]["name"],"enabled":v["enabled"]} for v in data if isinstance(v,dict) and isinstance(v.get("feature"),dict) and v["feature"].get("name") in ceiling("FLAGGUARD_ALLOWED_FEATURE_NAMES") and type(v.get("enabled")) is bool]}
        except providers.ProviderError as exc:
            raise HTTPException(502,str(exc)) from None
    @router.put("")
    def save(body:Workspace):
        config=body.model_dump()
        if not authorized(config) or len(set(body.flags))!=len(body.flags):
            raise HTTPException(403,"Configuration must stay within server allowlists")
        with closing(db()) as conn,conn:
            conn.execute("CREATE TABLE IF NOT EXISTS workspace_config(id INTEGER PRIMARY KEY CHECK(id=1),config TEXT NOT NULL,active INTEGER NOT NULL)")
            conn.execute("INSERT INTO workspace_config VALUES(1,?,0) ON CONFLICT(id) DO UPDATE SET config=excluded.config,active=0",(json.dumps(config),))
            record(conn,"workspace","1","configure","inactive")
        return {"configuration":{**config,"active":False}}
    @router.get("/telemetry")
    def check():
        config=read_workspace(db)
        if not config or not authorized(config):
            raise HTTPException(409,"Save an authorized configuration first")
        counts=telemetry_counts(db,config)
        return {"counts":counts,"ready":all(counts.values())}
    @router.post("/activation")
    def activate(body:Activation):
        config=read_workspace(db)
        if not config:
            raise HTTPException(409,"Save configuration first")
        if body.active and (not authorized(config) or not all(telemetry_counts(db,config).values())):
            raise HTTPException(409,"Authorized configuration and recent telemetry for every selected flag are required")
        with closing(db()) as conn,conn:
            expected={k:v for k,v in config.items() if k!="active"}
            updated=conn.execute("UPDATE workspace_config SET active=? WHERE id=1 AND config=?",(int(body.active),json.dumps(expected)))
            if updated.rowcount!=1:
                raise HTTPException(409,"Configuration changed; reload and retry")
            record(conn,"workspace","1","activation","active" if body.active else "inactive")
        return {"active":body.active}
    return router
