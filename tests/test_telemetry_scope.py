import time
import pytest
from fastapi.testclient import TestClient
from flagguard.main import app

@pytest.fixture
def client(tmp_path,monkeypatch):
    for k,v in {"FLAGGUARD_DB":str(tmp_path/"scope.db"),"FLAGGUARD_API_KEY":"admin","FLAGGUARD_TELEMETRY_KEY":"ingest","FLAGGUARD_ENFORCE_TELEMETRY_SCOPE":"true","FLAGGUARD_ALLOWED_SERVICES":"payment","FLAGGUARD_ALLOWED_FEATURE_NAMES":"checkout","FLAGGUARD_TELEMETRY_ENVIRONMENT":"development","FLAGGUARD_RATE_LIMIT_ENABLED":"false"}.items():
        monkeypatch.setenv(k,v)
    return TestClient(app,headers={"Authorization":"Bearer ingest"})

event={"service":"payment","environment":"development","flags":{"checkout":False},"status_code":200,"latency_ms":10}

def test_allowed_scope(client):
    assert client.post("/api/v1/telemetry",json=event).status_code==200

@pytest.mark.parametrize("change",[{"service":"other"},{"environment":"production"},{"flags":{"checkout":False,"unknown":True}}])
def test_disallowed_scope(client,change):
    assert client.post("/api/v1/telemetry",json={**event,**change}).status_code==403

def test_empty_allowlist(client,monkeypatch):
    monkeypatch.delenv("FLAGGUARD_ALLOWED_SERVICES")
    assert client.post("/api/v1/telemetry",json=event).status_code==403

def test_otlp_scope(client):
    def attr(k,v):
        return {"key":k,"value":{"boolValue" if type(v) is bool else "intValue" if type(v) is int else "stringValue":v}}
    now=time.time_ns()
    span={"traceId":"a"*32,"spanId":"b"*16,"startTimeUnixNano":str(now-10000000),"endTimeUnixNano":str(now),"attributes":[attr("flagguard.request",True),attr("flagguard.flag.checkout",True),attr("http.response.status_code",500)]}
    payload={"resourceSpans":[{"resource":{"attributes":[attr("service.name","other"),attr("deployment.environment.name","development")]},"scopeSpans":[{"spans":[span]}]}]}
    response=client.post("/v1/traces",json=payload)
    assert response.status_code==200
    assert response.json()["partialSuccess"]["rejectedSpans"]=="1"
    result=client.get("/api/v1/analysis",params={"service":"other","environment":"development","flag":"checkout"},headers={"Authorization":"Bearer admin"}).json()
    assert result["groups"]=={}
