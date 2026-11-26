"""OTLP/HTTP JSON and protobuf receiver for explicitly tagged request spans."""
import json
import time
from .telemetry_scope import allowed
from contextlib import closing
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest, ExportTraceServiceResponse

def proto_attrs(items):
    result=[]
    for item in items:
        kind=item.value.WhichOneof("value")
        names={"string_value":"stringValue","bool_value":"boolValue","int_value":"intValue"}
        if kind in names:
            result.append({"key":item.key,"value":{names[kind]:getattr(item.value,kind)}})
    return result

def proto_data(body):
    req=ExportTraceServiceRequest()
    req.ParseFromString(body)
    return {"resourceSpans":[{"resource":{"attributes":proto_attrs(r.resource.attributes)},"scopeSpans":[{"spans":[{"traceId":s.trace_id.hex(),"spanId":s.span_id.hex(),"startTimeUnixNano":s.start_time_unix_nano,"endTimeUnixNano":s.end_time_unix_nano,"attributes":proto_attrs(s.attributes),"status":{"code":s.status.code}} for s in scope.spans]} for scope in r.scope_spans]} for r in req.resource_spans]}

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
                            segments={}
                            for k,v in a.items():
                                if k.startswith("flagguard.segment."):
                                    if type(v) is str and v.isascii() and v.isdigit() and len(v)<=16:
                                        v=int(v)
                                    if type(v) is not int or not 0<v<=9007199254740991:
                                        raise ValueError("Invalid segment ID")
                                    segments[k[len("flagguard.segment."):]]=v
                            event=Event(service=ra["service.name"],environment=ra.get("deployment.environment.name",ra.get("deployment.environment")),flags=flags,segments=segments,status_code=int(status),latency_ms=(end-start)*1000)
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
        content_type=request.headers.get("content-type","").split(";")[0].strip()
        if content_type not in ("application/json","application/x-protobuf") or request.headers.get("content-encoding","identity")!="identity":
            raise HTTPException(415,"Only uncompressed OTLP HTTP JSON or protobuf supported")
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>2_000_000: raise HTTPException(413,"Payload too large")
        try:
            data=proto_data(bytes(body)) if content_type=="application/x-protobuf" else json.loads(body)
            if not isinstance(data,dict) or not isinstance(data.get("resourceSpans"),list): raise ValueError()
            result=await run_in_threadpool(ingest,data)
            if content_type=="application/x-protobuf":
                response=ExportTraceServiceResponse()
                partial=result.get("partialSuccess")
                if partial:
                    response.partial_success.rejected_spans=int(partial["rejectedSpans"])
                    response.partial_success.error_message=partial["errorMessage"]
                return Response(content=response.SerializeToString(),media_type=content_type)
            return result
        except (DecodeError,ValueError,TypeError,KeyError,AttributeError,RecursionError):
            raise HTTPException(400,"Invalid OTLP payload") from None
    return router
