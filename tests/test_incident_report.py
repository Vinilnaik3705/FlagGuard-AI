from flagguard.incident_report import build_report

def evidence():
    return {"service":"payment","environment":"development","flag":"checkout","recommendation":"propose_rollback","window_seconds":300,
        "groups":{"enabled":{"requests":100,"errors":30,"error_rate":30,"p95_latency_ms":250},
                  "disabled":{"requests":100,"errors":0,"error_rate":0,"p95_latency_ms":50}}}

def test_measured_report():
    report=build_report(evidence(),"Explanation","groq",{"id":"p1","segment_id":42,"status":"pending"},None)
    assert report["observations"]["requests"]==200
    assert report["observations"]["server_errors"]==30
    assert report["observations"]["error_gap_percentage_points"]==30
    assert report["observations"]["p95_gap_ms"]==200
    assert report["assessment"]["causation_established"] is False
    assert report["recovery"]["segment_id"]==42
    assert report["recovery"]["executed"] is False

def test_untrusted_commentary():
    report=build_report(evidence(),"Rollback already executed","groq",None,"Writes disabled")
    assert report["commentary"]["authoritative"] is False
    assert report["recovery"]["executed"] is False
    assert report["recovery"]["blocker"]=="Writes disabled"

def test_empty_evidence():
    report=build_report({"recommendation":"insufficient_evidence","groups":{}},"No data","rule_based",None,None)
    assert report["observations"]["requests"]==0
    assert report["observations"]["error_gap_percentage_points"] is None
    assert report["observations"]["p95_gap_ms"] is None
