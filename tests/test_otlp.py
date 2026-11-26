import time
from fastapi.testclient import TestClient
from flagguard.main import app

def test_otlp(tmp_path,monkeypatch):
    monkeypatch.setenv("FLAGGUARD_DB",str(tmp_path/"otel.db"))
    monkeypatch.setenv("FLAGGUARD_API_KEY","test")
    client=TestClient(app,headers={"Authorization":"Bearer test"})
    def attr(k,v):
        return {"key":k,"value":{"boolValue" if isinstance(v,bool) else "intValue" if isinstance(v,int) else "stringValue":v}}
    now=time.time_ns()
    span={"traceId":"a"*32,"spanId":"b"*16,"startTimeUnixNano":str(now-10000000),"endTimeUnixNano":str(now),"attributes":[attr("flagguard.request",True),attr("flagguard.flag.checkout",True),attr("http.response.status_code",500)]}
    payload={"resourceSpans":[{"resource":{"attributes":[attr("service.name","payment"),attr("deployment.environment.name","development")]},"scopeSpans":[{"spans":[span]}]}]}
    assert client.post("/v1/traces",json=payload).status_code==200
    assert client.post("/v1/traces",json=payload).status_code==200
    result=client.get("/api/v1/analysis",params={"service":"payment","environment":"development","flag":"checkout"}).json()
    assert result["groups"]["enabled"]["requests"]==1
    assert result["groups"]["enabled"]["errors"]==1

def test_otlp_auth(monkeypatch):
    monkeypatch.setenv("FLAGGUARD_API_KEY","test")
    assert TestClient(app).post("/v1/traces",json={"resourceSpans":[]}).status_code==401

def test_otlp_invalid(monkeypatch):
    monkeypatch.setenv("FLAGGUARD_API_KEY","test")
    client=TestClient(app,headers={"Authorization":"Bearer test"})
    assert client.post("/v1/traces",json={}).status_code==400
    assert client.post("/v1/traces",content=b"abc",headers={"Content-Type":"application/x-protobuf"}).status_code==415
