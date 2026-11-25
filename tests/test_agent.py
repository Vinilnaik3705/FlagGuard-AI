from fastapi.testclient import TestClient
from flagguard.main import app
from flagguard import providers


def test_workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("FLAGGUARD_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("FLAGGUARD_API_KEY", "test-key")
    monkeypatch.setattr(providers, "explain", lambda evidence: "Review cohort failures.")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-key"}
    query = {"service": "checkout", "environment": "development", "flag": "new_checkout"}
    assert client.post("/api/v1/investigate", json=query).status_code == 401
    for enabled in (False, True):
        for _ in range(100):
            event = {"service": "checkout", "environment": "development", "flags": {"new_checkout": enabled}, "status_code": 500 if enabled else 200, "latency_ms": 10}
            assert client.post("/api/v1/telemetry", json=event, headers=headers).status_code == 200
    result = client.post("/api/v1/investigate", json=query, headers=headers).json()
    assert result["recommendation"] == "propose_rollback"
    assert result["explanation_source"] == "groq"
    url = "/api/v1/approvals/" + result["approval_id"]
    decision = client.post(url, json={"approve": True}, headers=headers)
    assert decision.status_code == 200
    assert decision.json()["executed"] is False
    assert client.post(url, json={"approve": True}, headers=headers).status_code == 409


def test_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("FLAGGUARD_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("FLAGGUARD_API_KEY", "test-key")
    def fail(evidence):
        raise providers.ProviderError("unavailable")
    monkeypatch.setattr(providers, "explain", fail)
    result = TestClient(app).post("/api/v1/investigate", headers={"Authorization": "Bearer test-key"}, json={"service": "checkout", "environment": "development", "flag": "new_checkout"}).json()
    assert result["explanation_source"] == "rule_based"
    assert result["approval_id"] is None
