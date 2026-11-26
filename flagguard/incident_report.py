"""Deterministic report structure; AI commentary is never an authorization."""
def build_report(evidence, explanation, source, plan, error):
    groups=evidence.get("groups",{})
    a,b=groups.get("enabled",{}),groups.get("disabled",{})
    recommendation=evidence["recommendation"]
    total=sum(g["requests"] for g in groups.values())
    failures=sum(g["errors"] for g in groups.values())
    gap=round(a["error_rate"]-b["error_rate"],4) if "error_rate" in a and "error_rate" in b else None
    latency_gap=round(a["p95_latency_ms"]-b["p95_latency_ms"],4) if "p95_latency_ms" in a and "p95_latency_ms" in b else None
    titles={"propose_rollback":"Feature-associated error regression","investigate_shared_failure":"Shared application failure","investigate_latency_regression":"Feature-associated latency regression","insufficient_evidence":"Insufficient cohort evidence","monitor":"No configured threshold violation"}
    return {
        "schema_version":1,
        "title":titles.get(recommendation,"Review telemetry"),
        "scope":{k:evidence.get(k) for k in ("service","environment","flag")},
        "observations":{"requests":total,"server_errors":failures,"error_gap_percentage_points":gap,"p95_gap_ms":latency_gap,"groups":groups,"window_seconds":evidence.get("window_seconds"),"policy":evidence.get("policy"),"segment_evidence":evidence.get("segment_evidence")},
        "assessment":{"recommendation":recommendation,"causation_established":False},
        "commentary":{"source":source,"text":explanation,"authoritative":False},
        "recovery":{"plan_id":plan["id"] if plan else None,"segment_id":plan.get("segment_id") if plan else None,"state_at_investigation":plan["status"] if plan else "not_prepared","blocker":error,"requires_human_approval":True,"executed":False},
        "limitations":["Observational cohort comparison does not establish causation.","Telemetry is bounded by the analysis window and sampling limit.","Recovery status is a snapshot at investigation time; consult the change and incident records for current status."]
    }
