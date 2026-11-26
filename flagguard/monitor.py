"""Opt-in single-process monitor; never executes provider writes."""
import os
import json
import logging
from contextlib import closing
from .agent import Investigation, investigate_once

log = logging.getLogger(__name__)

def scan(db, analysis):
    services = [s.strip() for s in os.getenv("FLAGGUARD_ALLOWED_SERVICES","").split(",") if s.strip()]
    flags = [s.strip() for s in os.getenv("FLAGGUARD_ALLOWED_FEATURE_NAMES","").split(",") if s.strip()]
    environment = os.getenv("FLAGGUARD_TELEMETRY_ENVIRONMENT","development")
    for service in services:
        for flag in flags:
            evidence = analysis(service, environment, flag)
            if evidence["recommendation"] not in ("propose_rollback","investigate_shared_failure","investigate_latency_regression"):
                continue
            key = json.dumps([service,environment,flag,evidence["recommendation"]])
            with closing(db()) as conn, conn:
                conn.execute("CREATE TABLE IF NOT EXISTS monitor_incidents (id INTEGER PRIMARY KEY, scope TEXT, created INTEGER DEFAULT (unixepoch()), result TEXT)")
                conn.execute("BEGIN IMMEDIATE")
                recent = conn.execute("SELECT id FROM monitor_incidents WHERE scope=? AND created>=unixepoch()-600",(key,)).fetchone()
                if recent:
                    continue
                rowid=conn.execute("INSERT INTO monitor_incidents(scope,result) VALUES(?,?)",(key,json.dumps({"status":"investigating"}))).lastrowid
            try:
                result=investigate_once(db,analysis,Investigation(service=service,environment=environment,flag=flag))
            except Exception:
                log.exception("Monitor investigation failed")
                result={"status":"failed"}
            with closing(db()) as conn, conn:
                conn.execute("UPDATE monitor_incidents SET result=? WHERE id=?",(json.dumps(result),rowid))

def build_monitor_router(authorize,db):
    from fastapi import APIRouter, Depends
    router=APIRouter(prefix="/api/v1",dependencies=[Depends(authorize)])
    @router.get("/monitor/incidents")
    def incidents():
        with closing(db()) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS monitor_incidents (id INTEGER PRIMARY KEY, scope TEXT, created INTEGER DEFAULT (unixepoch()), result TEXT)")
            rows=conn.execute("SELECT id,created,result FROM monitor_incidents ORDER BY id DESC LIMIT 100").fetchall()
        return [{"id":r[0],"created":r[1],"result":json.loads(r[2])} for r in rows]
    return router
