"""Bound request sizes and rates for the single-process demo server."""
import os
import time
from collections import deque
from starlette.responses import JSONResponse

class RequestLimits:
    def __init__(self, app):
        self.app = app
        self.windows = {"telemetry": deque(), "admin": deque()}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path, method = scope["path"], scope["method"]
        telemetry = path in ("/api/v1/telemetry", "/api/v2/telemetry", "/v1/traces")
        command = path == "/api/v1/command"
        if os.getenv("FLAGGUARD_RATE_LIMIT_ENABLED") == "true" and (telemetry or command):
            key = "telemetry" if telemetry else "admin"
            limit = int(os.getenv("FLAGGUARD_TELEMETRY_RPM", "3000") if telemetry else os.getenv("FLAGGUARD_COMMAND_RPM", "30"))
            now = time.monotonic()
            window = self.windows[key]
            while window and window[0] <= now - 60:
                window.popleft()
            if len(window) >= limit:
                return await JSONResponse({"detail":"Request rate exceeded"},429,headers={"Retry-After":"60"})(scope,receive,send)
            window.append(now)
        if method not in ("POST","PUT","PATCH"):
            return await self.app(scope,receive,send)
        maximum = 2_000_000 if path == "/v1/traces" else 32_768
        chunks = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunks.extend(message.get("body",b""))
            if len(chunks) > maximum:
                return await JSONResponse({"detail":"Payload too large"},413)(scope,receive,send)
            if not message.get("more_body",False):
                break
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type":"http.request","body":bytes(chunks),"more_body":False}
            return await receive()
        await self.app(scope,replay,send)
