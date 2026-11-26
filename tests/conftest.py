"""Keep test configuration independent from developer shell credentials."""
import os
import pytest

@pytest.fixture(autouse=True)
def isolate_flagguard_environment(monkeypatch, tmp_path):
    for name in tuple(os.environ):
        if name.startswith(("FLAGGUARD_", "FLAGSMITH_", "GROQ_", "LLM_")):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FLAGGUARD_DB", str(tmp_path / "isolated.db"))
    monkeypatch.setenv("FLAGGUARD_ENABLE_WRITES", "false")
