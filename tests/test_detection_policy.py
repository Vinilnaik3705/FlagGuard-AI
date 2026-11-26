import pytest
from flagguard.core import assess, summarize, policy

def cohorts(a=250,b=50):
    return summarize([{"flags":{"checkout":enabled},"status_code":200,"latency_ms":latency} for enabled,latency in [(True,a),(False,b)] for _ in range(100)],"checkout")

def test_latency_regression():
    groups=cohorts()
    assert groups["enabled"]["p95_latency_ms"]==250
    assert assess(groups)=="investigate_latency_regression"

def test_latency_small_absolute_gap():
    assert assess(cohorts(20,5))=="monitor"

def test_latency_small_sample():
    groups=cohorts()
    groups["enabled"]["latency_samples"]=10
    assert assess(groups)=="monitor"

def test_error_gap():
    groups={"enabled":{"requests":100,"error_rate":6},"disabled":{"requests":100,"error_rate":5}}
    assert assess(groups)=="monitor"
    assert assess(groups,error_gap=1)=="propose_rollback"

def test_configurable_policy(monkeypatch):
    monkeypatch.setenv("FLAGGUARD_ANALYSIS_WINDOW_SECONDS","120")
    monkeypatch.setenv("FLAGGUARD_MIN_COHORT_REQUESTS","50")
    assert policy()["window_seconds"]==120
    assert policy()["minimum"]==50

def test_invalid_policy(monkeypatch):
    monkeypatch.setenv("FLAGGUARD_LATENCY_RATIO","nan")
    with pytest.raises(ValueError):
        policy()
