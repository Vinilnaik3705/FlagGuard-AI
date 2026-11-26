"""Verify application health from fresh telemetry after a verified incident rollback."""
import json
from contextlib import closing
from .core import summarize, policy

def verify_recoveries(db):
    rules=policy()
    with closing(db()) as conn, conn:
        exists=lambda name: conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone()
        if not all(exists(n) for n in ("monitor_incidents","cli_changes","audit_log")):
            return
        rows=conn.execute("SELECT id,result FROM monitor_incidents ORDER BY id DESC LIMIT 100").fetchall()
        now=conn.execute("SELECT unixepoch()").fetchone()[0]
        for incident_id,raw in rows:
            result=json.loads(raw)
            plan=result.get("recovery_plan")
            if not plan or result.get("recommendation")!="propose_rollback":
                continue
            if result.get("recovery_health",{}).get("status") in ("healthy","unhealthy","inconclusive"):
                continue
            change=conn.execute("SELECT status,feature,target FROM cli_changes WHERE id=?",(plan["id"],)).fetchone()
            if not change or change[0]!="verified" or change[1]!=result.get("flag") or change[2]!=0:
                continue
            completed=conn.execute("SELECT max(created) FROM audit_log WHERE entity='cli_change' AND entity_id=? AND action='result' AND status='verified'",(plan["id"],)).fetchone()[0]
            if completed is None:
                continue
            # Freeze the investigation policy for this recovery, even if workspace settings change.
            rules={**policy(),**(result.get("policy") or {})}
            rules["window_seconds"]=result.get("window_seconds",rules["window_seconds"])
            # Observe only post-execution telemetry, excluding the ambiguous completion second.
            deadline=completed+rules["window_seconds"]
            events=conn.execute("SELECT payload FROM events WHERE service=? AND environment=? AND received>? AND received<=? ORDER BY received,id LIMIT 10001",(result["service"],result["environment"],completed,min(now,deadline))).fetchall()
            groups=summarize([json.loads(e[0]) for e in events[:10000]],result["flag"])
            off=groups.get("disabled",{})
            on=groups.get("enabled",{})
            status="observing"
            if len(events)>10000:
                status="inconclusive"
            elif now>=deadline:
                if off.get("requests",0)<rules["minimum"]:
                    status="inconclusive"
                elif on.get("requests",0)>0:
                    status="inconclusive"
                elif off["error_rate"]>rules["threshold"]:
                    status="unhealthy"
                else:
                    status="healthy"
            result["recovery_health"]={"status":status,"groups":groups,"verified_at":completed,"checked_at":now,"deadline":deadline,"minimum_requests":rules["minimum"],"error_threshold_percent":rules["threshold"]}
            conn.execute("UPDATE monitor_incidents SET result=? WHERE id=? AND result=?",(json.dumps(result),incident_id,raw))
