import pytest
from fastapi.testclient import TestClient
from flagguard.main import app, db
from flagguard.workspace import read_workspace
from flagguard import providers, monitor

@pytest.fixture
def setup(monkeypatch):
    for k,v in {"FLAGGUARD_API_KEY":"admin","FLAGGUARD_TELEMETRY_KEY":"ingest","FLAGGUARD_VIEWER_KEY":"viewer","FLAGGUARD_ALLOWED_SERVICES":"payment","FLAGGUARD_ALLOWED_FEATURE_NAMES":"checkout,search","FLAGGUARD_TELEMETRY_ENVIRONMENT":"development","FLAGGUARD_ENFORCE_TELEMETRY_SCOPE":"true"}.items():
        monkeypatch.setenv(k,v)
    client=TestClient(app,headers={"Authorization":"Bearer admin"})
    config={"service":"payment","environment":"development","flags":["checkout"],"window_seconds":120,"minimum":50,"threshold":6,"error_gap":2,"latency_ratio":2,"latency_delta_ms":100}
    return client,config

def test_workspace_authorization(setup):
    c,body=setup
    for key in ("viewer","ingest"):
        assert c.get("/api/v1/workspace",headers={"Authorization":"Bearer "+key}).status_code==401
    assert c.put("/api/v1/workspace",json={**body,"service":"other"}).status_code==403
    assert c.put("/api/v1/workspace",json={**body,"flags":["other"]}).status_code==403

def test_workspace_activation(setup):
    c,body=setup
    assert c.put("/api/v1/workspace",json=body).status_code==200
    assert c.post("/api/v1/workspace/activation",json={"active":True}).status_code==409
    assert c.post("/api/v1/telemetry",headers={"Authorization":"Bearer ingest"},json={"service":"payment","environment":"development","flags":{"checkout":False},"status_code":200,"latency_ms":10}).status_code==200
    assert c.get("/api/v1/workspace/telemetry").json()["ready"]
    assert c.post("/api/v1/workspace/activation",json={"active":True}).status_code==200
    assert read_workspace(db)["active"]
    assert c.post("/api/v1/workspace/activation",json={"active":False}).status_code==200
    assert not read_workspace(db)["active"]

def test_workspace_policy(setup):
    c,body=setup
    assert c.put("/api/v1/workspace",json=body).status_code==200
    result=c.get("/api/v1/analysis",params={"service":"payment","environment":"development","flag":"checkout"}).json()
    assert result["window_seconds"]==120
    assert result["policy"]["minimum"]==50
    assert result["policy"]["threshold"]==6

def test_discovery(setup,monkeypatch):
    c,body=setup
    monkeypatch.setattr(providers,"sdk_flags",lambda:[{"feature":{"name":"checkout"},"enabled":False},{"feature":{"name":"unapproved"},"enabled":True}])
    assert c.get("/api/v1/workspace/flags").json()=={"flags":[{"name":"checkout","enabled":False}]}

def test_pause_blocks_scan(setup):
    c,body=setup
    c.put("/api/v1/workspace",json=body)
    def unexpected(*args):
        pytest.fail("Paused workspace must not scan")
    monitor.scan(db,unexpected)
