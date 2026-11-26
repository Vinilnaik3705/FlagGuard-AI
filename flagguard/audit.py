"""Persistent transition audit and bounded telemetry retention."""
import os
from contextlib import closing
from fastapi import APIRouter, Depends, Query

def audit_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY, created INTEGER DEFAULT (unixepoch()), entity TEXT NOT NULL, entity_id TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL)")

def record(conn, entity, entity_id, action, status):
    audit_table(conn)
    conn.execute("INSERT INTO audit_log(entity,entity_id,action,status) VALUES(?,?,?,?)",(entity,entity_id,action,status))

def prune(db):
    days=int(os.getenv("FLAGGUARD_TELEMETRY_RETENTION_DAYS","7"))
    if not 1<=days<=365:
        raise ValueError("Telemetry retention must be between 1 and 365 days")
    with closing(db()) as conn, conn:
        conn.execute("CREATE INDEX IF NOT EXISTS events_received_idx ON events(received)")
        return conn.execute("DELETE FROM events WHERE id IN (SELECT id FROM events WHERE received < unixepoch()-? ORDER BY received LIMIT 10000)",(days*86400,)).rowcount

def build_audit_router(authorize,db):
    router=APIRouter(prefix="/api/v1",dependencies=[Depends(authorize)])
    @router.get("/audit")
    def audit(limit:int=Query(100,ge=1,le=500), before_id:int|None=Query(None,gt=0)):
        with closing(db()) as conn, conn:
            audit_table(conn)
            rows=conn.execute("SELECT id,created,entity,entity_id,action,status FROM audit_log WHERE (? IS NULL OR id < ?) ORDER BY id DESC LIMIT ?",(before_id,before_id,limit)).fetchall()
        return [dict(zip(("id","created","entity","entity_id","action","status"),r)) for r in rows]
    return router
