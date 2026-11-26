from uuid import uuid4
from unittest.mock import MagicMock
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from flagguard.main import app
from flagguard.identity import identity
from flagguard import tenant_telemetry as t

def test_key_generation():
    key, hashed=t.new_key()
    assert key.startswith("fg_v2_")
    assert hashed==t.digest(key)
    assert key not in hashed
    assert t.new_key()[0]!=key

def test_membership_denial():
    conn=MagicMock()
    conn.execute.return_value.fetchone.return_value=None
    with pytest.raises(HTTPException) as exc:
        t.membership(conn,uuid4(),{"id":str(uuid4())})
    assert exc.value.status_code==404

def test_viewer_cannot_write():
    conn=MagicMock()
    conn.execute.return_value.fetchone.return_value=("viewer",)
    with pytest.raises(HTTPException) as exc:
        t.membership(conn,uuid4(),{"id":str(uuid4())},True)
    assert exc.value.status_code==403

def test_analysis_scopes_query():
    conn=MagicMock()
    conn.execute.return_value.fetchall.return_value=[]
    wid,aid=uuid4(),uuid4()
    result=t.analyze(conn,wid,aid,"checkout",t.Policy().model_dump())
    assert result["recommendation"]=="insufficient_evidence"
    sql,params=conn.execute.call_args.args
    assert "workspace_id=%s AND application_id=%s" in sql
    assert params[:2]==(wid,aid)

def test_ingestion_rejects_wrong_scope(monkeypatch):
    conn=MagicMock()
    conn.__enter__.return_value=conn
    conn.execute.return_value.fetchone.return_value=(uuid4(),uuid4(),"payment","development",["checkout"])
    monkeypatch.setattr(t,"connect",lambda:conn)
    c=TestClient(app)
    response=c.post("/api/v2/telemetry",headers={"Authorization":"Bearer fg_v2_example"},json={"service":"other","environment":"development","flags":{"checkout":True},"status_code":200,"latency_ms":10})
    assert response.status_code==403
    assert conn.execute.call_count==1

def test_invalid_key_rejected_without_database(monkeypatch):
    monkeypatch.setattr(t,"connect",lambda:pytest.fail("Unexpected database access"))
    c=TestClient(app)
    assert c.post("/api/v2/telemetry",headers={"Authorization":"Bearer admin"},json={"service":"payment","environment":"development","flags":{"checkout":True},"status_code":200,"latency_ms":10}).status_code==401

def test_cross_workspace_application_list_denied(monkeypatch):
    conn=MagicMock()
    conn.__enter__.return_value=conn
    conn.execute.return_value.fetchone.return_value=None
    monkeypatch.setattr(t,"connect",lambda:conn)
    app.dependency_overrides[identity]=lambda:{"id":str(uuid4())}
    try:
        assert TestClient(app).get("/api/v2/workspaces/"+str(uuid4())+"/applications").status_code==404
        assert conn.execute.call_count==1
    finally:
        app.dependency_overrides.pop(identity,None)
