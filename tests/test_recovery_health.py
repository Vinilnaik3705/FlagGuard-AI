import json
import sqlite3
from contextlib import closing
import pytest
from flagguard.main import db
from flagguard.recovery_health import verify_recoveries

@pytest.mark.parametrize("count,errors,enabled,expected",[
    (100,0,False,"healthy"),
    (100,20,False,"unhealthy"),
    (10,0,False,"inconclusive"),
    (100,0,True,"inconclusive"),
])
def test_recovery_health(monkeypatch,count,errors,enabled,expected):
    monkeypatch.setenv("FLAGGUARD_ANALYSIS_WINDOW_SECONDS","300")
    monkeypatch.setenv("FLAGGUARD_MIN_COHORT_REQUESTS","100")
    monkeypatch.setenv("FLAGGUARD_ERROR_THRESHOLD_PERCENT","5")
    with closing(db()) as conn,conn:
        now=conn.execute("SELECT unixepoch()").fetchone()[0]
        completed=now-301
        conn.execute("CREATE TABLE monitor_incidents(id INTEGER PRIMARY KEY,result TEXT)")
        conn.execute("CREATE TABLE cli_changes(id TEXT,status TEXT,feature TEXT,target INTEGER)")
        conn.execute("CREATE TABLE audit_log(entity TEXT,entity_id TEXT,action TEXT,status TEXT,created INTEGER)")
        incident={"service":"payment","environment":"development","flag":"checkout","recommendation":"propose_rollback","recovery_plan":{"id":"plan1"}}
        conn.execute("INSERT INTO monitor_incidents VALUES(1,?)",(json.dumps(incident),))
        conn.execute("INSERT INTO cli_changes VALUES('plan1','verified','checkout',0)")
        conn.execute("INSERT INTO audit_log VALUES('cli_change','plan1','result','verified',?)",(completed,))
        for i in range(count):
            payload={"flags":{"checkout":enabled},"status_code":500 if i<errors else 200,"latency_ms":10}
            conn.execute("INSERT INTO events(service,environment,payload,received) VALUES('payment','development',?,?)",(json.dumps(payload),completed+1))
        # Older failures must not contaminate post-recovery health.
        conn.execute("INSERT INTO events(service,environment,payload,received) VALUES('payment','development',?,?)",(json.dumps({"flags":{"checkout":False},"status_code":500}),completed-1))
    verify_recoveries(db)
    with closing(db()) as conn:
        result=json.loads(conn.execute("SELECT result FROM monitor_incidents").fetchone()[0])
    assert result["recovery_health"]["status"]==expected
    assert sum(g["requests"] for g in result["recovery_health"]["groups"].values())==count
