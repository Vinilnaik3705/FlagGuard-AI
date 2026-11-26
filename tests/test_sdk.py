import pytest
from flagguard_sdk import Client

def test_validation():
    with pytest.raises(ValueError):
        Client("payment","dev",url="http://example.com",api_key="test")
    c=Client("payment","dev",api_key="test")
    with pytest.raises(ValueError):
        c.record({"checkout":"false"},200,10)
    with pytest.raises(ValueError):
        c.record({"checkout":False},200,float("nan"))

def test_record(monkeypatch):
    import flagguard_sdk as sdk
    import json
    class Response:
        status=200
        def __enter__(self): return self
        def __exit__(self,*args): pass
    class Opener:
        def open(self,req,timeout):
            assert req.full_url=="http://127.0.0.1:8000/api/v1/telemetry"
            assert req.get_header("Authorization")=="Bearer test"
            assert json.loads(req.data)["flags"]=={"checkout":False}
            return Response()
    monkeypatch.setattr(sdk,"build_opener",lambda *args:Opener())
    assert Client("payment","dev",api_key="test").record({"checkout":False},200,10)

def test_network_failure(monkeypatch):
    import flagguard_sdk as sdk
    from urllib.error import URLError
    class Opener:
        def open(self,*args,**kwargs): raise URLError("offline")
    monkeypatch.setattr(sdk,"build_opener",lambda *args:Opener())
    assert Client("payment","dev",api_key="test").record({"checkout":False},200,10) is False
