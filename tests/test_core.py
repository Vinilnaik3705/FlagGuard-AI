from flagguard.core import summarize, assess

def test_variant_failure():
    events=[{"flags":{"checkout":False},"status_code":200}]*100+[{"flags":{"checkout":True},"status_code":500}]*100
    assert assess(summarize(events,"checkout"))=="propose_rollback"

def test_shared_failure():
    assert assess({"enabled":{"requests":100,"error_rate":30},"disabled":{"requests":100,"error_rate":30}})=="investigate_shared_failure"

def test_small_sample():
    assert assess({})=="insufficient_evidence"
