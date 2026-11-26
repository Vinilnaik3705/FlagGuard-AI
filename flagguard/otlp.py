"""OTLP/HTTP JSON receiver for explicitly tagged request spans."""
import json
import time
from .telemetry_scope import allowed
from contextlib import closing
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

def attrs(items):
    out={}
    for item in items:
        value=item.get("value",{})
        for kind in ("stringValue","boolValue","intValue"):
            if kind in value:
                out[item["key"]]=value[kind]
    return out

def build_otlp_router(authorize,db,Event):
    router=APIRouter(dependencies=[Depends(authorize)])
    def ingest(data):
        rejected=0
        now=time.time()
        with closing(db()) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS otlp_seen (trace_id TEXT, span_id TEXT, received REAL, PRIMARY KEY(trace_id,span_id))")
            conn.execute("DELETE FROM otlp_seen WHERE received < ?",(now-86400,))
            for resource in data["resourceSpans"]:
                ra=attrs(resource.get("resource",{}).get("attributes",[]))
                for scope in resource.get("scopeSpans",[]):
                    for span in scope.get("spans",[]):
                        try:
                            a=attrs(span.get("attributes",[]))
                            if a.get("flagguard.request") is not True:
                                continue
                            flags={k[len("flagguard.flag."):]:v for k,v in a.items() if k.startswith("flagguard.flag.") and type(v) is bool}
                            if not flags: raise ValueError()
                            end=int(span["endTimeUnixNano"])/1e9
                            start=int(span["startTimeUnixNano"])/1e9
                            if not now-300<=end<=now+30 or start>end: raise ValueError()
                            status=a.get("http.response.status_code",a.get("http.status_code"))
                            if status is None:
                                grpc=a.get("rpc.grpc.status_code")
                                if grpc is not None: status=200 if int(grpc)==0 else 500
                                elif span.get("status",{}).get("code") in (2,"STATUS_CODE_ERROR"): status=500
                                else: raise ValueError()
                            event=Event(service=ra["service.name"],environment=ra.get("deployment.environment.name",ra.get("deployment.environment")),flags=flags,status_code=int(status),latency_ms=(end-start)*1000)
                            if not allowed(event): raise ValueError("Telemetry scope not authorized")
                            trace, sid=span["traceId"],span["spanId"]
                            if not isinstance(trace,str) or not isinstance(sid,str) or len(trace)!=32 or len(sid)!=16 or not int(trace,16) or not int(sid,16): raise ValueError()
                        except (ValueError,TypeError,KeyError,AttributeError):
                            rejected+=1
                            continue
                        if conn.execute("INSERT OR IGNORE INTO otlp_seen VALUES(?,?,?)",(trace.lower(),sid.lower(),now)).rowcount:
                            conn.execute("INSERT INTO events(service,environment,payload,received) VALUES(?,?,?,?)",(event.service,event.environment,event.model_dump_json(),end))
        return {"partialSuccess":{"rejectedSpans":str(rejected),"errorMessage":"Invalid, expired or unauthorized tagged spans"}} if rejected else {}
    @router.post("/v1/traces")
    async def traces(request:Request):
        if request.headers.get("content-type","").split(";")[0].strip()!="application/json" or request.headers.get("content-encoding","identity")!="identity":
            raise HTTPException(415,"Only uncompressed OTLP JSON supported")
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>2_000_000: raise HTTPException(413,"Payload too large")
        try:
            data=json.loads(body)
            if not isinstance(data,dict) or not isinstance(data.get("resourceSpans"),list): raise ValueError()
            return await run_in_threadpool(ingest,data)
        except (ValueError,TypeError,KeyError,AttributeError):
            raise HTTPException(400,"Invalid OTLP JSON") from None
    return router
