import os, secrets, sqlite3, json
from contextlib import closing
from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel, Field
from .core import summarize, assess

app = FastAPI(title="FlagGuard AI", version="0.1.0")

def authorize(authorization: str = Header(default="")):
    key = os.environ.get("FLAGGUARD_API_KEY")
    if not key or not secrets.compare_digest(authorization, "Bearer "+key):
        raise HTTPException(401, "Invalid or unconfigured credentials")

def db():
    conn = sqlite3.connect(os.environ.get("FLAGGUARD_DB","flagguard.db"))
    conn.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, service TEXT, environment TEXT, payload TEXT, received REAL DEFAULT (unixepoch()))")
    return conn

class Event(BaseModel):
    service: str = Field(min_length=1,max_length=100)
    environment: str = Field(min_length=1,max_length=100)
    status_code: int = Field(ge=100,le=599)
    latency_ms: float = Field(ge=0)
    flags: dict[str,bool]

@app.get("/api/health")
def health():
    return {"status":"ok"}

@app.post("/api/v1/telemetry", dependencies=[Depends(authorize)])
def ingest(event: Event):
    with closing(db()) as conn, conn:
        conn.execute("INSERT INTO events(service,environment,payload) VALUES(?,?,?)",(event.service,event.environment,event.model_dump_json()))
    return {"accepted":True}

@app.get("/api/v1/analysis", dependencies=[Depends(authorize)])
def analysis(service: str, environment: str, flag: str):
    with closing(db()) as conn:
        rows=conn.execute("SELECT payload FROM events WHERE service=? AND environment=? AND received >= unixepoch()-300 ORDER BY id DESC LIMIT 10000",(service,environment)).fetchall()
    groups=summarize([json.loads(r[0]) for r in rows],flag)
    return {"groups":groups,"recommendation":assess(groups),"window_seconds":300,"executed":False}
from .agent import build_router
app.include_router(build_router(authorize, db, analysis))
from .executor import build_executor_router
app.include_router(build_executor_router(authorize, db))
from .cli_executor import build_cli_router
app.include_router(build_cli_router(authorize, db))
from .monitor import scan, build_monitor_router
import asyncio
import logging
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    async def loop():
        while True:
            try:
                await asyncio.to_thread(scan, db, analysis)
            except Exception:
                logging.getLogger(__name__).exception("Monitoring scan failed")
            await asyncio.sleep(15)
    task = asyncio.create_task(loop()) if os.getenv("FLAGGUARD_MONITOR_ENABLED") == "true" else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

app.router.lifespan_context = lifespan
app.include_router(build_monitor_router(authorize, db))

from .commands import build_command_router
app.include_router(build_command_router(authorize, db, analysis))

from .otlp import build_otlp_router
app.include_router(build_otlp_router(authorize, db, Event))

from pathlib import Path
from fastapi.responses import FileResponse

@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(Path(__file__).with_name("dashboard.html"), media_type="text/html", headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff","X-Frame-Options":"DENY"})
