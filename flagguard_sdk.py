"""Server-side, dependency-free FlagGuard telemetry client."""
import json
import math
import os
import asyncio
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import URLError
from urllib.parse import urlsplit

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

class Client:
    def __init__(self, service, environment, url=None, api_key=None, timeout=2):
        self.service, self.environment = service, environment
        self.url = (url or os.getenv("FLAGGUARD_URL", "http://127.0.0.1:8000")).rstrip("/")
        self.key = api_key or os.getenv("FLAGGUARD_TELEMETRY_KEY") or os.getenv("FLAGGUARD_API_KEY")
        self.timeout = timeout
        u = urlsplit(self.url)
        if not u.hostname or u.username or u.password or u.query or u.fragment or (u.scheme != "https" and not (u.scheme == "http" and u.hostname in ("localhost","127.0.0.1","::1"))):
            raise ValueError("HTTPS required except for local development")
        if not self.key or not all(isinstance(x,str) and 0 < len(x) <= 100 for x in (service,environment)):
            raise ValueError("Missing key or invalid service/environment")
        if not 0 < timeout <= 10:
            raise ValueError("Invalid timeout")
    def record(self, flags, status_code, latency_ms):
        if not isinstance(flags,dict) or not all(isinstance(k,str) and type(v) is bool for k,v in flags.items()):
            raise ValueError("Pass actual evaluated boolean flags")
        if type(status_code) is not int or not 100 <= status_code <= 599 or isinstance(latency_ms,bool) or not isinstance(latency_ms,(int,float)) or not math.isfinite(latency_ms) or latency_ms < 0:
            raise ValueError("Invalid request outcome")
        payload = json.dumps(dict(service=self.service,environment=self.environment,flags=flags,status_code=status_code,latency_ms=latency_ms)).encode()
        req = Request(self.url+"/api/v1/telemetry", data=payload, headers={"Authorization":"Bearer "+self.key,"Content-Type":"application/json"},method="POST")
        try:
            with build_opener(NoRedirect()).open(req,timeout=self.timeout) as response:
                return 200 <= response.status < 300
        except (URLError,OSError):
            return False
    async def arecord(self, flags, status_code, latency_ms):
        return await asyncio.to_thread(self.record, flags, status_code, latency_ms)
