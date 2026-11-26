import sqlite3
from contextlib import closing
from flagguard import monitor

def test_monitor_deduplicates(tmp_path, monkeypatch):
    monkeypatch.setenv("FLAGGUARD_ALLOWED_SERVICES","payment")
    monkeypatch.setenv("FLAGGUARD_ALLOWED_FEATURE_NAMES","checkout")
    monkeypatch.setenv("FLAGGUARD_TELEMETRY_ENVIRONMENT","development")
    def db():
        return sqlite3.connect(tmp_path/"monitor.db")
    calls=[]
    def investigate(db,analysis,query):
        calls.append(query.flag)
        return {"recommendation":"propose_rollback"}
    monkeypatch.setattr(monitor,"investigate_once",investigate)
    analysis=lambda *args: {"recommendation":"propose_rollback"}
    monitor.scan(db,analysis)
    monitor.scan(db,analysis)
    assert calls==["checkout"]
    with closing(db()) as conn:
        assert conn.execute("SELECT count(*) FROM monitor_incidents").fetchone()[0]==1

def test_monitor_healthy(tmp_path,monkeypatch):
    monkeypatch.setenv("FLAGGUARD_ALLOWED_SERVICES","payment")
    monkeypatch.setenv("FLAGGUARD_ALLOWED_FEATURE_NAMES","checkout")
    def db():
        return sqlite3.connect(tmp_path/"monitor.db")
    def unexpected(*args):
        raise AssertionError("Healthy traffic should not trigger AI")
    monkeypatch.setattr(monitor,"investigate_once",unexpected)
    monitor.scan(db,lambda *args: {"recommendation":"monitor"})
