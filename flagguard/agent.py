import json
import os
from .cli_executor import prepare_change, Plan
from .segment_evidence import target
from .incident_report import build_report
from contextlib import closing
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StrictBool
from . import providers

class Investigation(BaseModel):
    service: str = Field(min_length=1, max_length=100)
    environment: str = Field(min_length=1, max_length=100)
    flag: str = Field(min_length=1, max_length=100)

class Decision(BaseModel):
    approve: StrictBool

def approval_connection(db):
    conn = db()
    conn.execute("CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, evidence TEXT NOT NULL, status TEXT NOT NULL, created INTEGER DEFAULT (unixepoch()))")
    return conn

def investigate_once(db, analysis, query):
    evidence = analysis(query.service, query.environment, query.flag)
    evidence.update(query.model_dump())
    # Send only aggregate evidence to the external model, not raw logs or credentials.
    try:
        explanation = providers.explain({"groups": evidence["groups"], "recommendation": evidence["recommendation"]})
        source = "groq"
    except providers.ProviderError:
        explanation = "AI unavailable. Review the deterministic recommendation and sampled evidence."
        source = "rule_based"
    recovery_plan = None
    recovery_error = None
    approval_id = None
    if evidence["recommendation"] == "propose_rollback":
        if os.getenv("FLAGSMITH_EXECUTION_PROVIDER") == "cli":
            # Explicit binding between telemetry labels and the configured Flagsmith environment.
            if query.environment != os.getenv("FLAGGUARD_TELEMETRY_ENVIRONMENT", "development") or query.service not in os.getenv("FLAGGUARD_ALLOWED_SERVICES", "").split(","):
                recovery_error = "Telemetry scope not authorized for recovery"
            else:
                try:
                    segment = target(evidence)
                    recovery_plan = prepare_change(db, Plan(feature=query.flag, enabled=False, segment_id=segment))
                except (HTTPException, ValueError) as exc:
                    recovery_error = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
        approval_id = str(uuid4())
        with closing(approval_connection(db)) as conn, conn:
            conn.execute("INSERT INTO approvals(id,evidence,status) VALUES(?,?,?)", (approval_id, json.dumps(evidence), "pending"))
    report=build_report(evidence, explanation, source, recovery_plan, recovery_error)
    return {**evidence, "report":report, "explanation": explanation, "explanation_source": source, "approval_id": approval_id, "recovery_plan": recovery_plan, "recovery_error": recovery_error}



def build_router(authorize, db, analysis):
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(authorize)])

    def connection():
        conn = db()
        conn.execute("CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, evidence TEXT NOT NULL, status TEXT NOT NULL, created INTEGER DEFAULT (unixepoch()))")
        return conn

    @router.get("/flags")
    def flags():
        try:
            return providers.sdk_flags()
        except providers.ProviderError as exc:
            raise HTTPException(502, str(exc)) from None

    @router.post("/investigate")
    def investigate(query: Investigation):
        return investigate_once(db, analysis, query)

    @router.get("/approvals")
    def approvals():
        with closing(connection()) as conn:
            rows = conn.execute("SELECT id,evidence,status,created FROM approvals ORDER BY created DESC LIMIT 100").fetchall()
        return [{"id": r[0], "evidence": json.loads(r[1]), "status": r[2], "created": r[3]} for r in rows]

    @router.post("/approvals/{approval_id}")
    def decide(approval_id: str, decision: Decision):
        status = "approved_pending_executor" if decision.approve else "rejected"
        with closing(connection()) as conn, conn:
            result = conn.execute("UPDATE approvals SET status=? WHERE id=? AND status='pending' AND created >= unixepoch()-600", (status, approval_id))
            if result.rowcount != 1:
                raise HTTPException(409, "Approval missing, expired or already decided")
        return {"id": approval_id, "status": status, "executed": False}

    return router
