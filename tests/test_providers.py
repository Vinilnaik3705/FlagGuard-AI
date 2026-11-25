import pytest
from flagguard import providers

def test_missing_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY",raising=False)
    with pytest.raises(providers.ProviderError,match="Missing GROQ_API_KEY"):
        providers.groq_models()

def test_management_headers(monkeypatch):
    monkeypatch.setenv("FLAGSMITH_ADMIN_API_KEY","test-secret")
    monkeypatch.setenv("FLAGSMITH_ENVIRONMENT_ID","demo")
    def fake(method,url,headers,**kwargs):
        assert method=="GET"
        assert url.endswith("/environments/demo/")
        assert headers["Authorization"]=="Api-Key test-secret"
        return {}
    monkeypatch.setattr(providers,"request",fake)
    assert providers.management_environment()=={}

def test_ai(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY","test-secret")
    def fake(method,url,headers,**kwargs):
        assert method=="POST"
        assert "monitor" in kwargs["json"]["messages"][1]["content"]
        return {"choices":[{"message":{"content":"Continue monitoring"}}]}
    monkeypatch.setattr(providers,"request",fake)
    assert providers.explain({"recommendation":"monitor"})=="Continue monitoring"
