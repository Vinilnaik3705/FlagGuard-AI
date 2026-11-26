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
    assert client.post("/v1/traces",content=b"abc",headers={"Content-Type":"application/x-protobuf"}).status_code==400


def test_protobuf(tmp_path,monkeypatch):
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest, ExportTraceServiceResponse
    monkeypatch.setenv("FLAGGUARD_DB",str(tmp_path/"proto.db"))
    monkeypatch.setenv("FLAGGUARD_API_KEY","test")
    client=TestClient(app,headers={"Authorization":"Bearer test"})
    req=ExportTraceServiceRequest()
    resource=req.resource_spans.add()
    resource.resource.attributes.add(key="service.name").value.string_value="payment"
    resource.resource.attributes.add(key="deployment.environment.name").value.string_value="development"
    span=resource.scope_spans.add().spans.add()
    span.trace_id=b"a"*16
    span.span_id=b"b"*8
    span.end_time_unix_nano=time.time_ns()
    span.start_time_unix_nano=span.end_time_unix_nano-10000000
    span.attributes.add(key="flagguard.request").value.bool_value=True
    span.attributes.add(key="flagguard.flag.checkout").value.bool_value=True
    span.attributes.add(key="http.response.status_code").value.int_value=500
    for _ in range(2):
        response=client.post("/v1/traces",content=req.SerializeToString(),headers={"Content-Type":"application/x-protobuf"})
        assert response.status_code==200
        assert response.headers["content-type"]=="application/x-protobuf"
        assert ExportTraceServiceResponse.FromString(response.content).partial_success.rejected_spans==0
    result=client.get("/api/v1/analysis",params={"service":"payment","environment":"development","flag":"checkout"}).json()
    assert result["groups"]["enabled"]["requests"]==1
    assert result["groups"]["enabled"]["errors"]==1
