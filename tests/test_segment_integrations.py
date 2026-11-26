import json
import time
import pytest
from fastapi.testclient import TestClient
from flagguard.main import app
from flagguard_sdk import Client
import flagguard_sdk

def test_python_segment_payload(monkeypatch):
    class Response:
        status=200
        def __enter__(self): return self
        def __exit__(self,*args): pass
    class Opener:
        def open(self,req,timeout):
            assert json.loads(req.data)["segments"]=={"checkout":42}
            return Response()
    monkeypatch.setattr(flagguard_sdk,"build_opener",lambda *args:Opener())
    assert Client("payment","development",api_key="test").record({"checkout":True},200,10,{"checkout":42})

@pytest.mark.parametrize("segments",[{"other":42},{"checkout":True},{"checkout":-1}])
def test_invalid_sdk_segment(segments):
    with pytest.raises(ValueError):
        Client("payment","development",api_key="test").record({"checkout":True},200,10,segments)

@pytest.mark.parametrize("binary",[False,True])
def test_otlp_segment_metadata(monkeypatch,binary):
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest, ExportTraceServiceResponse
    monkeypatch.setenv("FLAGGUARD_API_KEY","admin")
    monkeypatch.setenv("FLAGGUARD_TELEMETRY_KEY","ingest")
    monkeypatch.setenv("FLAGGUARD_ENFORCE_TELEMETRY_SCOPE","true")
    monkeypatch.setenv("FLAGGUARD_ALLOWED_SERVICES","payment")
    monkeypatch.setenv("FLAGGUARD_ALLOWED_FEATURE_NAMES","checkout")
    monkeypatch.setenv("FLAGGUARD_ALLOWED_SEGMENT_IDS","42")
    monkeypatch.setenv("FLAGGUARD_TELEMETRY_ENVIRONMENT","development")
    client=TestClient(app,headers={"Authorization":"Bearer ingest"})
    now=time.time_ns()
    if binary:
        req=ExportTraceServiceRequest()
        r=req.resource_spans.add()
        r.resource.attributes.add(key="service.name").value.string_value="payment"
        r.resource.attributes.add(key="deployment.environment.name").value.string_value="development"
        s=r.scope_spans.add().spans.add()
        s.trace_id=b"a"*16
        s.span_id=b"b"*8
        s.start_time_unix_nano=now-10000000
        s.end_time_unix_nano=now
        s.attributes.add(key="flagguard.request").value.bool_value=True
        s.attributes.add(key="flagguard.flag.checkout").value.bool_value=True
        s.attributes.add(key="flagguard.segment.checkout").value.int_value=42
        s.attributes.add(key="http.response.status_code").value.int_value=500
        response=client.post("/v1/traces",content=req.SerializeToString(),headers={"Content-Type":"application/x-protobuf"})
        assert response.status_code==200
        assert ExportTraceServiceResponse.FromString(response.content).partial_success.rejected_spans==0
    else:
        def attr(k,v):
            return {"key":k,"value":{"boolValue" if type(v) is bool else "intValue" if type(v) is int else "stringValue":v}}
        span={"traceId":"a"*32,"spanId":"b"*16,"startTimeUnixNano":str(now-10000000),"endTimeUnixNano":str(now),"attributes":[attr("flagguard.request",True),attr("flagguard.flag.checkout",True),attr("flagguard.segment.checkout",42),attr("http.response.status_code",500)]}
        response=client.post("/v1/traces",json={"resourceSpans":[{"resource":{"attributes":[attr("service.name","payment"),attr("deployment.environment.name","development")]},"scopeSpans":[{"spans":[span]}]}]})
        assert response.status_code==200
        assert response.json()=={}
    result=client.get("/api/v1/analysis",params={"service":"payment","environment":"development","flag":"checkout"},headers={"Authorization":"Bearer admin"}).json()
    assert result["segment_evidence"]["enabled_segments"]["42"]["requests"]==1
    assert result["segment_evidence"]["unknown_enabled_requests"]==0
