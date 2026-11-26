"""Conservative recovery targeting using application-reported evaluation metadata."""
import os
from .core import assess

def segment_evidence(events, flag, rules):
    groups={}
    unknown=0
    for e in events:
        if e["flags"].get(flag) is not True:
            continue
        segment=e.get("segments",{}).get(flag)
        if type(segment) is not int or segment<=0:
            unknown+=1
            continue
        g=groups.setdefault(str(segment),{"requests":0,"errors":0})
        g["requests"]+=1
        g["errors"]+=int(e["status_code"]>=500)
    for g in groups.values():
        g["error_rate"]=100*g["errors"]/g["requests"]
    return {"enabled_segments":groups,"unknown_enabled_requests":unknown}

def target(evidence):
    if os.getenv("FLAGGUARD_REQUIRE_SEGMENT_EVIDENCE")!="true":
        segment=os.getenv("FLAGGUARD_CANARY_SEGMENT_ID")
        return int(segment) if segment else None
    attribution=evidence.get("segment_evidence",{})
    groups=attribution.get("enabled_segments",{})
    stable=evidence.get("groups",{}).get("disabled",{})
    rules=evidence.get("policy",{})
    if attribution.get("unknown_enabled_requests")!=0 or not groups or not rules:
        raise ValueError("Missing or incomplete segment evidence")
    allowed={s.strip() for s in os.getenv("FLAGGUARD_ALLOWED_SEGMENT_IDS","").split(",")}
    candidates=[]
    for segment,g in groups.items():
        if g["requests"]<rules["minimum"]:
            raise ValueError("Insufficient per-segment evidence")
        if assess({"enabled":g,"disabled":stable},**rules)=="propose_rollback":
            candidates.append(segment)
    if len(candidates)!=1 or candidates[0] not in allowed:
        raise ValueError("Ambiguous or unauthorized recovery segment")
    return int(candidates[0])
