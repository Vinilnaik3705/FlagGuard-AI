import pytest
from fastapi.testclient import TestClient
from flagguard.main import app

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FLAGGUARD_DB",str(tmp_path/"security.db"))
    monkeypatch.setenv("FLAGGUARD_API_KEY","admin-test")
    monkeypatch.setenv("FLAGGUARD_TELEMETRY_KEY","ingest-test")
    monkeypatch.setenv("FLAGGUARD_REQUIRE_SEPARATE_KEYS","true")
    return TestClient(app)

def headers(key):
    return {"Authorization":"Bearer "+key}

event={"service":"payment","environment":"development","flags":{"checkout":False},"status_code":200,"latency_ms":10}

def test_telemetry_key_ingestion(client):
    assert client.post("/api/v1/telemetry",json=event,headers=headers("ingest-test")).status_code==200
    assert client.post("/v1/traces",json={"resourceSpans":[]},headers=headers("ingest-test")).status_code==200

def test_telemetry_key_cannot_administer(client):
    for path,body in [("/api/v1/cli-changes",{"feature":"checkout","enabled":False}),("/api/v1/cli-changes/test/approval",{"approve":True}),("/api/v1/cli-changes/test/execute",None),("/api/v1/command",{"message":"Inspect flags"})]:
        assert client.post(path,json=body,headers=headers("ingest-test")).status_code==401
    assert client.get("/api/v1/monitor/incidents",headers=headers("ingest-test")).status_code==401

def test_admin_key_not_ingestion_key(client):
    assert client.post("/api/v1/telemetry",json=event,headers=headers("admin-test")).status_code==401
    assert client.get("/api/v1/monitor/incidents",headers=headers("admin-test")).status_code==200

def test_missing_key_fails_closed(client,monkeypatch):
    monkeypatch.delenv("FLAGGUARD_TELEMETRY_KEY")
    assert client.post("/api/v1/telemetry",json=event,headers=headers("admin-test")).status_code==503

def test_identical_keys_rejected(client,monkeypatch):
    monkeypatch.setenv("FLAGGUARD_TELEMETRY_KEY","admin-test")
    assert client.post("/api/v1/telemetry",json=event,headers=headers("admin-test")).status_code==503
