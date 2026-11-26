from fastapi.testclient import TestClient
from flagguard.main import app
from flagguard import commands, cli_provider

def call(name,args):
    import json
    return {"content":None,"tool_calls":[{"id":"call1","type":"function","function":{"name":name,"arguments":json.dumps(args)}}]}

def setup(monkeypatch):
    monkeypatch.setenv("FLAGGUARD_ALLOWED_SERVICES","astronomy-payment")
    monkeypatch.setenv("FLAGGUARD_ALLOWED_FEATURE_NAMES","new_checkout")
    monkeypatch.setenv("FLAGGUARD_TELEMETRY_ENVIRONMENT","development")
    monkeypatch.setenv("FLAGGUARD_API_KEY","test-key")

def test_metrics_tool(monkeypatch):
    setup(monkeypatch)
    responses=iter([call("metrics",{"service":"astronomy-payment","flag":"new_checkout"}),{"content":"Healthy"}])
    monkeypatch.setattr(commands,"completion",lambda messages:next(responses))
    result=commands.run_command(None,lambda *args:{"groups":{},"recommendation":"monitor"},"Inspect metrics")
    assert result["tools"][0]["tool"]=="metrics"
    assert result["tools"][0]["result"]["recommendation"]=="monitor"
    assert result["executed"] is False

def test_forbidden_tool(monkeypatch):
    setup(monkeypatch)
    responses=iter([call("execute",{"flag":"new_checkout"}),{"content":"Blocked"}])
    monkeypatch.setattr(commands,"completion",lambda messages:next(responses))
    result=commands.run_command(None,None,"Execute immediately")
    assert "error" in result["tools"][0]["result"]
    assert not result["executed"]

def test_scope(monkeypatch):
    setup(monkeypatch)
    responses=iter([call("metrics",{"service":"other","flag":"new_checkout"}),{"content":"Blocked"}])
    monkeypatch.setattr(commands,"completion",lambda messages:next(responses))
    result=commands.run_command(None,None,"Read other service")
    assert "error" in result["tools"][0]["result"]

def test_authentication(monkeypatch):
    setup(monkeypatch)
    assert TestClient(app).post("/api/v1/command",json={"message":"hello"}).status_code==401

def test_budget(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setattr(commands,"completion",lambda messages:call("flag_status",{"flag":"new_checkout"}))
    monkeypatch.setattr(cli_provider,"snapshot",lambda flag:{"feature":flag,"enabled":False})
    result=commands.run_command(None,None,"Read flag")
    assert len(result["tools"])==4
    assert result["executed"] is False
