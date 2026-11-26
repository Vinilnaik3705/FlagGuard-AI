import json
import sqlite3
from contextlib import closing
import pytest
from flagguard import monitor

@pytest.fixture
def scenario(tmp_path, monkeypatch):
    monkeypatch.setenv("FLAGGUARD_ALLOWED_SERVICES","payment")
    monkeypatch.setenv("FLAGGUARD_ALLOWED_FEATURE_NAMES","checkout")
    def db():
        return sqlite3.connect(tmp_path/"lifecycle.db")
    calls=[]
    def investigate(db,analysis,query):
        calls.append(query.flag)
        return {"recommendation":"propose_rollback"}
    monkeypatch.setattr(monitor,"investigate_once",investigate)
    def scan(recommendation="propose_rollback"):
        monitor.scan(db,lambda *args:{"recommendation":recommendation,"window_seconds":30})
    def read():
        with closing(db()) as conn:
            return [json.loads(r[0]) for r in conn.execute("SELECT result FROM monitor_incidents ORDER BY id")]
    def modify(fn):
        with closing(db()) as conn,conn:
            raw=conn.execute("SELECT result FROM monitor_incidents WHERE id=1").fetchone()[0]
            data=json.loads(raw)
            fn(data)
            conn.execute("UPDATE monitor_incidents SET result=? WHERE id=1",(json.dumps(data),))
    return db,calls,scan,read,modify

def test_persistent_incident(scenario):
    db,calls,scan,read,modify=scenario
    scan()
    with closing(db()) as conn,conn:
        conn.execute("UPDATE monitor_incidents SET created=unixepoch()-1200")
    scan()
    assert len(calls)==1
    assert read()[0]["lifecycle"]["status"]=="open"

def test_resolved_incident_can_reopen(scenario):
    db,calls,scan,read,modify=scenario
    scan()
    modify(lambda d:d.update(recovery_health={"status":"healthy"}))
    scan("insufficient_evidence")
    assert read()[0]["lifecycle"]["status"]=="resolved"
    scan()
    assert len(calls)==2

def test_insufficient_evidence_resets_streak(scenario):
    db,calls,scan,read,modify=scenario
    scan()
    scan("monitor")
    assert "healthy_since" in read()[0]["lifecycle"]
    scan("insufficient_evidence")
    assert "healthy_since" not in read()[0]["lifecycle"]
    assert read()[0]["lifecycle"]["status"]=="open"

def test_monitoring_gap_resets_streak(scenario):
    db,calls,scan,read,modify=scenario
    scan()
    scan("monitor")
    modify(lambda d:d["lifecycle"].update(healthy_since=1,healthy_last_seen=1))
    scan("monitor")
    assert read()[0]["lifecycle"]["status"]=="open"
    assert read()[0]["lifecycle"]["healthy_since"]>1

def test_sustained_normal_comparison_resolves(scenario):
    db,calls,scan,read,modify=scenario
    scan()
    scan("monitor")
    with closing(db()) as conn:
        now=conn.execute("SELECT unixepoch()").fetchone()[0]
    modify(lambda d:d["lifecycle"].update(healthy_since=now-31,healthy_last_seen=now-1))
    scan("monitor")
    assert read()[0]["lifecycle"]["status"]=="resolved"
