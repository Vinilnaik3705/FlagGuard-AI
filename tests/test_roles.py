import pytest
from fastapi.testclient import TestClient
from flagguard.main import app

@pytest.fixture
def viewer(tmp_path,monkeypatch):
    for k,v in {"FLAGGUARD_DB":str(tmp_path/"roles.db"),"FLAGGUARD_API_KEY":"admin","FLAGGUARD_VIEWER_KEY":"viewer","FLAGGUARD_TELEMETRY_KEY":"ingest","FLAGGUARD_REQUIRE_SEPARATE_KEYS":"true","FLAGGUARD_RATE_LIMIT_ENABLED":"false"}.items():
        monkeypatch.setenv(k,v)
    return TestClient(app,headers={"Authorization":"Bearer viewer"})

def test_viewer_reads_metrics(viewer):
    assert viewer.get("/api/v1/analysis",params={"service":"payment","environment":"development","flag":"checkout"}).status_code==200

def test_viewer_reads_incidents(viewer):
    assert viewer.get("/api/v1/monitor/incidents").status_code==200

def test_viewer_cannot_mutate(viewer):
    for path,body in [
        ("/api/v1/command",{"message":"Execute rollback"}),
        ("/api/v1/investigate",{"service":"payment","environment":"development","flag":"checkout"}),
        ("/api/v1/cli-changes",{"feature":"checkout","enabled":False}),
        ("/api/v1/cli-changes/example/approval",{"approve":True}),
        ("/api/v1/cli-changes/example/execute",None),
        ("/api/v1/changes/example/execute",None),
        ("/api/v1/approvals/example",{"approve":True}),
        ("/api/v1/telemetry",{"service":"payment","environment":"development","flags":{"checkout":True},"status_code":200,"latency_ms":10}),
        ("/v1/traces",{"resourceSpans":[]}),
    ]:
        assert viewer.post(path,json=body).status_code==401

def test_viewer_cannot_read_audit(viewer):
    assert viewer.get("/api/v1/audit").status_code==401

def test_telemetry_key_cannot_be_viewer(viewer,monkeypatch):
    monkeypatch.setenv("FLAGGUARD_VIEWER_KEY","ingest")
    assert viewer.get("/api/v1/monitor/incidents",headers={"Authorization":"Bearer ingest"}).status_code==401

def test_revoked_viewer(viewer,monkeypatch):
    monkeypatch.delenv("FLAGGUARD_VIEWER_KEY")
    assert viewer.get("/api/v1/monitor/incidents").status_code==401
