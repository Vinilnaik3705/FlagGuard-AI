from fastapi.testclient import TestClient
import pytest
from flagguard.main import app
from flagguard import providers, cli_provider

@pytest.fixture
def setup(tmp_path, monkeypatch):
    for k,v in {"FLAGGUARD_DB":str(tmp_path/"test.db"),"FLAGGUARD_API_KEY":"test","FLAGSMITH_EXECUTION_PROVIDER":"cli","FLAGGUARD_ENABLE_WRITES":"true","FLAGGUARD_ALLOWED_FEATURE_NAMES":"new_checkout","FLAGGUARD_ALLOWED_SERVICES":"astronomy-payment","FLAGGUARD_TELEMETRY_ENVIRONMENT":"development","FLAGSMITH_ENVIRONMENT_ID":"demo","FLAGSMITH_PROJECT_ID":"1"}.items():
        monkeypatch.setenv(k,v)
    monkeypatch.setattr(providers,"explain",lambda evidence:"Investigate feature")
    state={"feature":"new_checkout","enabled":True}
    calls=[]
    monkeypatch.setattr(cli_provider,"snapshot",lambda feature:dict(state))
    def update(feature,enabled):
        calls.append((feature,enabled))
        state["enabled"]=enabled
    monkeypatch.setattr(cli_provider,"update",update)
    client=TestClient(app,headers={"Authorization":"Bearer test"})
    for enabled in (False,True):
        for _ in range(100):
            assert client.post("/api/v1/telemetry",json={"service":"astronomy-payment","environment":"development","flags":{"new_checkout":enabled},"status_code":500 if enabled else 200,"latency_ms":10}).status_code==200
    return client,state,calls

def investigate(client):
    return client.post("/api/v1/investigate",json={"service":"astronomy-payment","environment":"development","flag":"new_checkout"}).json()

def test_recovery_plan(setup):
    client,state,calls=setup
    result=investigate(client)
    plan=result["recovery_plan"]
    assert plan["target_enabled"] is False and plan["status"]=="pending"
    assert not calls
    assert investigate(client)["recovery_plan"]["id"]==plan["id"]
    url="/api/v1/cli-changes/"+plan["id"]
    assert client.post(url+"/execute").status_code==409
    assert client.post(url+"/approval",json={"approve":True}).status_code==200
    assert client.post(url+"/execute").json()["status"]=="verified"
    assert calls==[("new_checkout",False)]
    assert client.post(url+"/execute").status_code==409

def test_scope_blocked(setup,monkeypatch):
    client,state,calls=setup
    monkeypatch.setenv("FLAGGUARD_ALLOWED_SERVICES","other")
    result=investigate(client)
    assert result["recovery_plan"] is None
    assert result["recovery_error"]=="Telemetry scope not authorized for recovery"
    assert not calls

def test_writes_disabled(setup,monkeypatch):
    client,state,calls=setup
    monkeypatch.setenv("FLAGGUARD_ENABLE_WRITES","false")
    assert investigate(client)["recovery_plan"] is None
    assert not calls

def test_stale_plan(setup):
    client,state,calls=setup
    plan=investigate(client)["recovery_plan"]
    url="/api/v1/cli-changes/"+plan["id"]
    client.post(url+"/approval",json={"approve":True})
    state["enabled"]=False
    assert client.post(url+"/execute").json()["status"]=="stale"
    assert not calls

def test_rejected_plan(setup):
    client,state,calls=setup
    url="/api/v1/cli-changes/"+investigate(client)["recovery_plan"]["id"]
    client.post(url+"/approval",json={"approve":False})
    assert client.post(url+"/execute").status_code==409
    assert not calls
