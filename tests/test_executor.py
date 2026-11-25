from fastapi.testclient import TestClient
import pytest
from flagguard.main import app
from flagguard import executor, providers

@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("FLAGGUARD_DB",str(tmp_path/"test.db"))
    monkeypatch.setenv("FLAGGUARD_API_KEY","test-key")
    monkeypatch.setenv("FLAGSMITH_ENVIRONMENT_ID","demo")
    monkeypatch.setenv("FLAGGUARD_ENABLE_WRITES","true")
    monkeypatch.setenv("FLAGGUARD_ALLOWED_STATE_IDS","42")
    state={"id":42,"enabled":False,"identity":None,"feature_segment":None}
    calls=[]
    def request(method, env, state_id, **kwargs):
        assert env=="demo" and state_id==42
        if method=="PATCH":
            calls.append(kwargs["json"])
            state.update(kwargs["json"])
        return dict(state)
    monkeypatch.setattr(executor,"state_request",request)
    client=TestClient(app,headers={"Authorization":"Bearer test-key"})
    return client,state,calls

def plan(client):
    response=client.post("/api/v1/changes",json={"state_id":42,"enabled":True})
    assert response.status_code==200, response.text
    return "/api/v1/changes/"+response.json()["id"]

def test_approval_and_duplicate(setup):
    client,state,calls=setup
    url=plan(client)
    assert client.post(url+"/execute").status_code==409
    assert client.post(url+"/approval",json={"approve":True}).status_code==200
    assert client.post(url+"/execute").json()["status"]=="verified"
    assert state["enabled"] is True
    assert client.post(url+"/execute").status_code==409
    assert len(calls)==1

def test_stale(setup):
    client,state,calls=setup
    url=plan(client)
    client.post(url+"/approval",json={"approve":True})
    state["enabled"]=True
    assert client.post(url+"/execute").json()["status"]=="stale"
    assert not calls

def test_reject(setup):
    client,state,calls=setup
    url=plan(client)
    client.post(url+"/approval",json={"approve":False})
    assert client.post(url+"/execute").status_code==409
    assert not calls

def test_disabled(setup,monkeypatch):
    client,state,calls=setup
    monkeypatch.setenv("FLAGGUARD_ENABLE_WRITES","false")
    assert client.post("/api/v1/changes",json={"state_id":42,"enabled":True}).status_code==403

def test_provider_failure(setup,monkeypatch):
    client,state,calls=setup
    url=plan(client)
    client.post(url+"/approval",json={"approve":True})
    def fail(*args,**kwargs):
        raise providers.ProviderError("unavailable")
    monkeypatch.setattr(executor,"state_request",fail)
    result=client.post(url+"/execute").json()
    assert result["status"]=="unknown"
    assert not result["executed"]
