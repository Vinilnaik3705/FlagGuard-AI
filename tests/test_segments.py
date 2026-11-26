import pytest
from fastapi.testclient import TestClient
from flagguard.main import app
from flagguard import cli_provider, providers

@pytest.fixture
def segment_setup(tmp_path, monkeypatch):
    for k,v in {"FLAGGUARD_DB":str(tmp_path/"segments.db"),"FLAGGUARD_API_KEY":"test","FLAGSMITH_EXECUTION_PROVIDER":"cli","FLAGGUARD_ENABLE_WRITES":"true","FLAGGUARD_ALLOWED_FEATURE_NAMES":"new_checkout","FLAGGUARD_ALLOWED_SEGMENT_IDS":"42","FLAGGUARD_CANARY_SEGMENT_ID":"42","FLAGGUARD_ALLOWED_SERVICES":"payment","FLAGGUARD_TELEMETRY_ENVIRONMENT":"development","FLAGSMITH_ENVIRONMENT_ID":"demo","FLAGSMITH_PROJECT_ID":"1"}.items():
        monkeypatch.setenv(k,v)
    state={"feature":"new_checkout","type":"standard","segment":{"id":42,"name":"canary"},"priority":0,"enabled":True,"value":None}
    calls=[]
    def snapshot(feature,segment):
        assert (feature,segment)==("new_checkout",42)
        return dict(state)
    def update(feature,segment,enabled):
        calls.append((feature,segment,enabled))
        state["enabled"]=enabled
    def forbidden(*args):
        pytest.fail("Environment default must not be changed")
    monkeypatch.setattr(cli_provider,"segment_snapshot",snapshot)
    monkeypatch.setattr(cli_provider,"segment_update",update)
    monkeypatch.setattr(cli_provider,"update",forbidden)
    monkeypatch.setattr(providers,"explain",lambda evidence:"Canary incident")
    return TestClient(app,headers={"Authorization":"Bearer test"}),state,calls

def plan(client,segment=42):
    return client.post("/api/v1/cli-changes",json={"feature":"new_checkout","enabled":False,"segment_id":segment})

def test_segment_approval(segment_setup):
    client,state,calls=segment_setup
    p=plan(client).json()
    assert p["segment_id"]==42 and p["status"]=="pending"
    url="/api/v1/cli-changes/"+p["id"]
    assert client.post(url+"/execute").status_code==409
    assert not calls
    assert client.post(url+"/approval",json={"approve":True}).status_code==200
    assert client.post(url+"/execute").json()["status"]=="verified"
    assert calls==[("new_checkout",42,False)]
    assert client.post(url+"/execute").status_code==409

def test_segment_not_allowed(segment_setup):
    client,state,calls=segment_setup
    assert plan(client,43).status_code==403
    assert not calls

def test_segment_stale(segment_setup):
    client,state,calls=segment_setup
    url="/api/v1/cli-changes/"+plan(client).json()["id"]
    client.post(url+"/approval",json={"approve":True})
    state["priority"]=1
    assert client.post(url+"/execute").json()["status"]=="stale"
    assert not calls

def test_segment_scope_revoked(segment_setup,monkeypatch):
    client,state,calls=segment_setup
    url="/api/v1/cli-changes/"+plan(client).json()["id"]
    client.post(url+"/approval",json={"approve":True})
    monkeypatch.setenv("FLAGGUARD_ALLOWED_SEGMENT_IDS","43")
    assert client.post(url+"/execute").status_code==403
    assert not calls

def test_incident_targets_segment(segment_setup):
    client,state,calls=segment_setup
    for enabled in (False,True):
        for _ in range(100):
            assert client.post("/api/v1/telemetry",json={"service":"payment","environment":"development","flags":{"new_checkout":enabled},"status_code":500 if enabled else 200,"latency_ms":10}).status_code==200
    result=client.post("/api/v1/investigate",json={"service":"payment","environment":"development","flag":"new_checkout"}).json()
    assert result["recovery_plan"]["segment_id"]==42
    assert result["recovery_plan"]["target_enabled"] is False
    assert not calls
