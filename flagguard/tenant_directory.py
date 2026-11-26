"""Tenant directory only; operational resources remain on the legacy API."""
import os
from uuid import UUID,uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from .identity import identity

def connect():
    import psycopg
    url=os.getenv("DATABASE_URL")
    if not url:
        raise HTTPException(503,"Workspace database not configured")
    try:
        return psycopg.connect(url,connect_timeout=10,prepare_threshold=None,sslmode="require")
    except psycopg.Error:
        raise HTTPException(503,"Workspace database unavailable") from None

class CreateWorkspace(BaseModel):
    model_config=ConfigDict(extra="forbid",str_strip_whitespace=True)
    name:str=Field(min_length=1,max_length=100)

router=APIRouter(prefix="/api/v2/workspaces")

@router.get("")
def list_workspaces(user=Depends(identity)):
    with connect() as conn:
        rows=conn.execute("SELECT w.id,w.name,m.role FROM flagguard_private.workspaces w JOIN flagguard_private.members m ON m.workspace_id=w.id WHERE m.user_id=%s ORDER BY w.created_at DESC",(user["id"],)).fetchall()
    return [{"id":str(r[0]),"name":r[1],"role":r[2]} for r in rows]

@router.post("",status_code=201)
def create_workspace(body:CreateWorkspace,user=Depends(identity)):
    workspace_id=uuid4()
    with connect() as conn:
        # Serialize creation by identity to bound the number of owned workspaces.
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",(user["id"],))
        count=conn.execute("SELECT count(*) FROM flagguard_private.members WHERE user_id=%s AND role='owner'",(user["id"],)).fetchone()[0]
        if count>=5:
            raise HTTPException(409,"Workspace creation limit reached")
        conn.execute("INSERT INTO flagguard_private.workspaces(id,name) VALUES(%s,%s)",(workspace_id,body.name))
        conn.execute("INSERT INTO flagguard_private.members(workspace_id,user_id,role) VALUES(%s,%s,'owner')",(workspace_id,user["id"]))
    return {"id":str(workspace_id),"name":body.name,"role":"owner"}

@router.get("/{workspace_id}")
def get_workspace(workspace_id:UUID,user=Depends(identity)):
    with connect() as conn:
        row=conn.execute("SELECT w.id,w.name,m.role FROM flagguard_private.workspaces w JOIN flagguard_private.members m ON m.workspace_id=w.id WHERE w.id=%s AND m.user_id=%s",(workspace_id,user["id"])).fetchone()
    if not row:
        raise HTTPException(404,"Workspace not found")
    return {"id":str(row[0]),"name":row[1],"role":row[2]}
