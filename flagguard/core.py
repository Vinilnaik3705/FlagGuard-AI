from collections import defaultdict

def summarize(events, flag):
    groups = defaultdict(lambda: {"requests": 0, "errors": 0})
    for e in events:
        if flag not in e["flags"]:
            continue
        g = groups["enabled" if e["flags"][flag] else "disabled"]
        g["requests"] += 1
        g["errors"] += int(e["status_code"] >= 500)
    return {k: {**v, "error_rate": 100*v["errors"]/v["requests"]} for k,v in groups.items()}

def assess(groups, minimum=100, threshold=5):
    a,b = groups.get("enabled", {}), groups.get("disabled", {})
    if min(a.get("requests",0),b.get("requests",0)) < minimum:
        return "insufficient_evidence"
    if a["error_rate"] > threshold and b["error_rate"] > threshold:
        return "investigate_shared_failure"
    if a["error_rate"] > threshold and a["error_rate"] > b["error_rate"]:
        return "propose_rollback"
    return "monitor"
