from collections import defaultdict
import math
import os

def policy():
    def number(name, default, low, high, cast=float):
        value=cast(os.getenv(name,str(default)))
        if not math.isfinite(value) or not low<=value<=high:
            raise ValueError("Invalid detection policy: "+name)
        return value
    return {
        "window_seconds":number("FLAGGUARD_ANALYSIS_WINDOW_SECONDS",300,30,3600,int),
        "minimum":number("FLAGGUARD_MIN_COHORT_REQUESTS",100,20,5000,int),
        "threshold":number("FLAGGUARD_ERROR_THRESHOLD_PERCENT",5,0,100),
        "error_gap":number("FLAGGUARD_ERROR_GAP_POINTS",2,0,100),
        "latency_ratio":number("FLAGGUARD_LATENCY_RATIO",2,1.1,100),
        "latency_delta_ms":number("FLAGGUARD_LATENCY_DELTA_MS",100,1,86400000),
    }

def summarize(events, flag):
    groups = defaultdict(lambda: {"requests": 0, "errors": 0})
    latencies=defaultdict(list)
    for e in events:
        if flag not in e["flags"]:
            continue
        cohort="enabled" if e["flags"][flag] else "disabled"
        g=groups[cohort]
        g["requests"] += 1
        g["errors"] += int(e["status_code"] >= 500)
        latency=e.get("latency_ms")
        if type(latency) in (float,int) and math.isfinite(latency) and latency>=0:
            latencies[cohort].append(latency)
    result={}
    for k,v in groups.items():
        item={**v,"error_rate":100*v["errors"]/v["requests"]}
        values=sorted(latencies[k])
        if values:
            item.update(latency_samples=len(values),p95_latency_ms=values[math.ceil(.95*len(values))-1])
        result[k]=item
    return result

def assess(groups, minimum=100, threshold=5, error_gap=2, latency_ratio=2, latency_delta_ms=100):
    a,b=groups.get("enabled",{}),groups.get("disabled",{})
    if min(a.get("requests",0),b.get("requests",0))<minimum:
        return "insufficient_evidence"
    if a["error_rate"]>threshold and b["error_rate"]>threshold:
        return "investigate_shared_failure"
    if a["error_rate"]>threshold and a["error_rate"]-b["error_rate"]>=error_gap and a["error_rate"]>b["error_rate"]:
        return "propose_rollback"
    if min(a.get("latency_samples",0),b.get("latency_samples",0))>=minimum:
        x,y=a["p95_latency_ms"],b["p95_latency_ms"]
        if x>=latency_ratio*y and x-y>=latency_delta_ms:
            return "investigate_latency_regression"
    return "monitor"
