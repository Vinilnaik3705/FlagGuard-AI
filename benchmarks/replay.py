"""Seeded offline detection benchmark. No network, provider writes or LLM calls.
Run from repository root: python -m benchmarks.replay
"""
import json
import random
import statistics
from flagguard.core import summarize, assess

SCENARIOS=("healthy","canary_error","shared_error","canary_latency","low_volume")
EXPECTED={"healthy":"monitor","canary_error":"propose_rollback","shared_error":"investigate_shared_failure","canary_latency":"investigate_latency_regression","low_volume":"insufficient_evidence"}

def traffic(seed,scenario):
    rng=random.Random(seed)
    events=[]
    for second in range(120):
        for _ in range(2 if scenario=="low_volume" else 100):
            enabled=rng.random()<.1
            failure=.005
            latency=50
            if second>=30:
                if scenario=="canary_error" and enabled: failure=.30
                if scenario=="shared_error": failure=.30
                if scenario=="canary_latency" and enabled: latency=250
            events.append((second,{"flags":{"checkout":enabled},"status_code":500 if rng.random()<failure else 200,"latency_ms":latency+rng.uniform(0,10)}))
    return events

def global_rule(events):
    if len(events)<100: return "insufficient_evidence"
    if sum(e["status_code"]>=500 for e in events)/len(events)>.05:
        return "investigate_shared_failure"
    return "monitor"

def replay(events,method):
    first=None
    final="insufficient_evidence"
    alerts=[]
    interval=60 if method=="manual_proxy" else 15
    for second in range(interval-1,120,interval):
        window=[e for t,e in events if second-29<=t<=second]
        final=assess(summarize(window,"checkout")) if method=="flagguard" else global_rule(window)
        if final not in ("monitor","insufficient_evidence"):
            alerts.append({"second":second,"recommendation":final})
            if first is None: first=second
    return {"final":final,"first_alert_second":first,"alerts":alerts}

def run(seeds=20):
    output={}
    for method in ("manual_proxy","global_rule","flagguard"):
        rows=[]
        for scenario in SCENARIOS:
            for seed in range(seeds):
                result=replay(traffic(seed,scenario),method)
                incident=scenario in ("canary_error","shared_error","canary_latency")
                valid=[a for a in result["alerts"] if a["second"]>=30]
                delay=valid[0]["second"]-30 if incident and valid else None
                rows.append({"scenario":scenario,"seed":seed,"incident":incident,"delay_seconds":delay,"false_alert":any(a["second"]<30 for a in result["alerts"]) or (not incident and bool(result["alerts"])),"correct_final":result["final"]==EXPECTED[scenario],"final":result["final"]})
        incidents=[r for r in rows if r["incident"]]
        delays=[r["delay_seconds"] for r in incidents if r["delay_seconds"] is not None]
        negatives=[r for r in rows if not r["incident"]]
        output[method]={"runs":len(rows),"incident_detection_rate":len(delays)/len(incidents),"negative_run_false_alert_rate":sum(r["false_alert"] for r in negatives)/len(negatives),"final_classification_accuracy":sum(r["correct_final"] for r in rows)/len(rows),"mean_simulated_detection_seconds":statistics.mean(delays) if delays else None,"detected_incidents":len(delays),"total_incidents":len(incidents),"runs_detail":rows}
    return {"experiment":{"seeds":seeds,"duration_seconds":120,"fault_onset_second":30,"window_seconds":30,"manual_proxy_poll_seconds":60,"automated_poll_seconds":15,"note":"Offline simulation; manual proxy is a scheduled global rule, not measured human performance. No MTTR, AI latency, or real provider execution measured."},"results":output}

if __name__=="__main__":
    print(json.dumps(run(),indent=2))
