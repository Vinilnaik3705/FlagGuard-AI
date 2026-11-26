"""Exercise ingestion, analysis and approval planning without external writes."""
import pytest
from fastapi.testclient import TestClient
from flagguard.main import app
from flagguard import providers, cli_provider

@pytest.mark.parametrize("mode",["unique","ambiguous","missing"])
def test_strict_recovery_flow(monkeypatch,mode):
    settings={"FLAGGUARD_API_KEY":"admin","FLAGGUARD_TELEMETRY_KEY":"ingest",
        "FLAGGUARD_REQUIRE_SEGMENT_EVIDENCE":"true","FLAGGUARD_ENFORCE_TELEMETRY_SCOPE":"true",
        "FLAGGUARD_ALLOWED_SERVICES":"payment","FLAGGUARD_ALLOWED_FEATURE_NAMES":"checkout",
        "FLAGGUARD_TELEMETRY_ENVIRONMENT":"development","FLAGGUARD_ALLOWED_SEGMENT_IDS":"42,43",
        "FLAGGUARD_CANARY_SEGMENT_ID":"43","FLAGSMITH_EXECUTION_PROVIDER":"cli",
        "FLAGGUARD_ENABLE_WRITES":"true","FLAGSMITH_ENVIRONMENT_ID":"mock",
        "FLAGSMITH_PROJECT_ID":"1"}
    for k,v in settings.items(): monkeypatch.setenv(k,v)
    monkeypatch.setattr(providers,"explain",lambda evidence:"Mock explanation")
    snapshots=[]
    def snapshot(feature,segment):
        snapshots.append(segment)
        return {"feature":feature,"enabled":True,"segment":{"id":segment},"type":"standard"}
    def forbidden(*args):
        pytest.fail("Unexpected provider write or environment-wide snapshot")
    monkeypatch.setattr(cli_provider,"segment_snapshot",snapshot)
    monkeypatch.setattr(cli_provider,"snapshot",forbidden)
    monkeypatch.setattr(cli_provider,"update",forbidden)
    monkeypatch.setattr(cli_provider,"segment_update",forbidden)
    client=TestClient(app)
    query={"service":"payment","environment":"development","flag":"checkout"}
    for segment in (None,42,43):
        for i in range(100):
            enabled=segment is not None
            error=enabled and i<30 and (segment==42 or mode=="ambiguous")
            body={"service":"payment","environment":"development","flags":{"checkout":enabled},
                "status_code":500 if error else 200,"latency_ms":10}
            if enabled and not (mode=="missing" and segment==42 and i==0):
                body["segments"]={"checkout":segment}
            assert client.post("/api/v1/telemetry",json=body,headers={"Authorization":"Bearer ingest"}).status_code==200
    response=client.post("/api/v1/investigate",json=query,headers={"Authorization":"Bearer admin"})
    assert response.status_code==200
    result=response.json()
    assert result["recommendation"]=="propose_rollback"
    assert result["executed"] is False
    if mode=="unique":
        assert snapshots==[42]
        assert result["recovery_plan"]["segment_id"]==42
        assert result["recovery_plan"]["status"]=="pending"
    else:
        assert snapshots==[]
        assert result["recovery_plan"] is None
        assert result["recovery_error"]
