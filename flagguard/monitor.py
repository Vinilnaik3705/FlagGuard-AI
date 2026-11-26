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
            recommendation = evidence["recommendation"]
            anomalous = recommendation in ("propose_rollback","investigate_shared_failure","investigate_latency_regression")
            key = json.dumps([service,environment,flag,recommendation])
            with closing(db()) as conn, conn:
                conn.execute("CREATE TABLE IF NOT EXISTS monitor_incidents (id INTEGER PRIMARY KEY, scope TEXT, created INTEGER DEFAULT (unixepoch()), result TEXT)")
                conn.execute("BEGIN IMMEDIATE")
                now=conn.execute("SELECT unixepoch()").fetchone()[0]
                rows=conn.execute("SELECT id,created,result FROM monitor_incidents WHERE scope=? ORDER BY id DESC",(key,)).fetchall() if anomalous else conn.execute("SELECT id,created,result FROM monitor_incidents WHERE substr(scope,1,?)=? ORDER BY id DESC",(len(json.dumps([service,environment,flag])[:-1]+", "),json.dumps([service,environment,flag])[:-1]+", ")).fetchall()
                blocked=False
                for rid,created,raw in rows:
                    old=json.loads(raw)
                    lifecycle=old.get("lifecycle",{})
                    if lifecycle.get("status")=="resolved":
                        continue
                    if old.get("recovery_health",{}).get("status")=="healthy":
                        lifecycle.update(status="resolved",resolved_at=now,resolution="post_rollback_health")
                    elif old.get("status") in ("failed","investigating"):
                        if now-created<600:
                            blocked=True
                        else:
                            lifecycle.update(status="investigation_failed",closed_at=now)
                    elif lifecycle.get("status")=="investigation_failed":
                        continue
                    else:
                        lifecycle.update(status="open",last_checked_at=now)
                        if recommendation=="monitor":
                            since=lifecycle.setdefault("healthy_since",now)
                            if now-since>=evidence.get("window_seconds",300):
                                lifecycle.update(status="resolved",resolved_at=now,resolution="sustained_normal_comparison")
                        else:
                            lifecycle.pop("healthy_since",None)
                        if lifecycle["status"]=="open":
                            blocked=True
                    old["lifecycle"]=lifecycle
                    conn.execute("UPDATE monitor_incidents SET result=? WHERE id=?",(json.dumps(old),rid))
                if blocked or not anomalous:
                    continue
                rowid=conn.execute("INSERT INTO monitor_incidents(scope,result) VALUES(?,?)",(key,json.dumps({"status":"investigating","lifecycle":{"status":"open","opened_at":now}}))).lastrowid
            try:
                result=investigate_once(db,analysis,Investigation(service=service,environment=environment,flag=flag))
            except Exception:
                log.exception("Monitor investigation failed")
                result={"status":"failed"}
            with closing(db()) as conn, conn:
                result["lifecycle"]={"status":"open","opened_at":now,"last_checked_at":now}
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
