import pytest
from fastapi.testclient import TestClient
from flagguard.main import app

@pytest.fixture
def client(tmp_path,monkeypatch):
    for k,v in {"FLAGGUARD_DB":str(tmp_path/"limits.db"),"FLAGGUARD_API_KEY":"admin-test","FLAGGUARD_TELEMETRY_KEY":"ingest-test","FLAGGUARD_REQUIRE_SEPARATE_KEYS":"true","FLAGGUARD_RATE_LIMIT_ENABLED":"false"}.items():
        monkeypatch.setenv(k,v)
    return TestClient(app,headers={"Authorization":"Bearer ingest-test"})

event={"service":"payment","environment":"development","flags":{"checkout":False},"status_code":200,"latency_ms":10}

@pytest.mark.parametrize("change",[
    {"flags":{"checkout":"false"}},
    {"status_code":"200"},
    {"latency_ms":-1},
    {"flags":{}},
    {"unexpected":"field"},
])
def test_invalid_events(client,change):
    assert client.post("/api/v1/telemetry",json={**event,**change}).status_code==422

def test_payload_limit(client):
    assert client.post("/api/v1/telemetry",content=b"x"*32769,headers={"Content-Type":"application/json"}).status_code==413

def test_rate_limit(client,monkeypatch):
    monkeypatch.setenv("FLAGGUARD_RATE_LIMIT_ENABLED","true")
    monkeypatch.setenv("FLAGGUARD_TELEMETRY_RPM","2")
    assert client.post("/api/v1/telemetry",json=event).status_code==200
    assert client.post("/api/v1/telemetry",json=event).status_code==200
    response=client.post("/api/v1/telemetry",json=event)
    assert response.status_code==429
    assert response.headers["Retry-After"]=="60"
