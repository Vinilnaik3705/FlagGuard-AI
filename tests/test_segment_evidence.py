import pytest
from flagguard.core import policy
from flagguard.segment_evidence import segment_evidence,target

def evidence():
    events=[]
    for segment,errors in [(42,30),(43,0)]:
        for i in range(100):
            events.append({"flags":{"checkout":True},"segments":{"checkout":segment},"status_code":500 if i<errors else 200})
    rules=policy()
    rules.pop("window_seconds")
    return {"segment_evidence":segment_evidence(events,"checkout",rules),"groups":{"disabled":{"requests":1000,"error_rate":0}},"policy":rules}

@pytest.fixture
def strict(monkeypatch):
    monkeypatch.setenv("FLAGGUARD_REQUIRE_SEGMENT_EVIDENCE","true")
    monkeypatch.setenv("FLAGGUARD_ALLOWED_SEGMENT_IDS","42,43")

def test_unique_segment(strict):
    assert target(evidence())==42

def test_missing_attribution(strict):
    e=evidence()
    e["segment_evidence"]["unknown_enabled_requests"]=1
    with pytest.raises(ValueError):
        target(e)

def test_ambiguous_segments(strict):
    e=evidence()
    e["segment_evidence"]["enabled_segments"]["43"]["error_rate"]=30
    with pytest.raises(ValueError):
        target(e)

def test_small_segment(strict):
    e=evidence()
    e["segment_evidence"]["enabled_segments"]["43"]["requests"]=10
    with pytest.raises(ValueError):
        target(e)

def test_unauthorized_segment(strict,monkeypatch):
    monkeypatch.setenv("FLAGGUARD_ALLOWED_SEGMENT_IDS","43")
    with pytest.raises(ValueError):
        target(evidence())

def test_legacy_target(monkeypatch):
    monkeypatch.setenv("FLAGGUARD_CANARY_SEGMENT_ID","42")
    assert target({})==42
