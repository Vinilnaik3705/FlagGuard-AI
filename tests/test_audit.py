import sqlite3
from contextlib import closing
from fastapi.testclient import TestClient
from flagguard.main import app,db
from flagguard.audit import record,prune
from flagguard import cli_provider

def setup(tmp_path,monkeypatch):
    for k,v in {"FLAGGUARD_DB":str(tmp_path/"audit.db"),"FLAGGUARD_API_KEY":"admin","FLAGGUARD_TELEMETRY_KEY":"ingest","FLAGGUARD_ENABLE_WRITES":"true","FLAGSMITH_EXECUTION_PROVIDER":"cli","FLAGGUARD_ALLOWED_FEATURE_NAMES":"checkout","FLAGSMITH_ENVIRONMENT_ID":"demo","FLAGSMITH_PROJECT_ID":"1","FLAGGUARD_RATE_LIMIT_ENABLED":"false"}.items():
        monkeypatch.setenv(k,v)
    return TestClient(app,headers={"Authorization":"Bearer admin"})

def test_audit_transitions(tmp_path,monkeypatch):
    c=setup(tmp_path,monkeypatch)
    state={"feature":"checkout","enabled":True}
    monkeypatch.setattr(cli_provider,"snapshot",lambda f:dict(state))
    monkeypatch.setattr(cli_provider,"update",lambda f,v:state.update(enabled=v))
    p=c.post("/api/v1/cli-changes",json={"feature":"checkout","enabled":False}).json()
    path="/api/v1/cli-changes/"+p["id"]
    assert c.post(path+"/approval",json={"approve":True}).status_code==200
    assert c.post(path+"/execute").json()["status"]=="verified"
    entries=c.get("/api/v1/audit").json()
    assert [e["status"] for e in entries]==["verified","executing","approved","pending"]
    assert all(e["entity_id"]==p["id"] for e in entries)

def test_audit_permissions(tmp_path,monkeypatch):
    c=setup(tmp_path,monkeypatch)
    assert c.get("/api/v1/audit",headers={"Authorization":"Bearer ingest"}).status_code==401
    assert c.get("/api/v1/audit").json()==[]

def test_retention_preserves_audit(tmp_path,monkeypatch):
    setup(tmp_path,monkeypatch)
    monkeypatch.setenv("FLAGGUARD_TELEMETRY_RETENTION_DAYS","7")
    with closing(db()) as conn,conn:
        conn.execute("INSERT INTO events(service,environment,payload,received) VALUES('a','dev','{}',unixepoch()-864000)")
        conn.execute("INSERT INTO events(service,environment,payload) VALUES('a','dev','{}')")
        record(conn,"cli_change","example","result","verified")
    assert prune(db)==1
    with closing(db()) as conn:
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0]==1
        assert conn.execute("SELECT count(*) FROM audit_log").fetchone()[0]==1
