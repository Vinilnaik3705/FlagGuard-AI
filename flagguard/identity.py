"""Supabase identity verification; never grants legacy administrator access."""
import os
from uuid import UUID
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException

def identity(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer ") or not 1 <= len(authorization[7:]) <= 8192:
        raise HTTPException(401,"Access token required")
    url=os.getenv("SUPABASE_URL","").rstrip("/")
    key=os.getenv("SUPABASE_PUBLISHABLE_KEY","")
    parsed=urlsplit(url)
    if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or not key:
        raise HTTPException(503,"Identity provider not configured")
    try:
        with httpx.Client(timeout=10,follow_redirects=False) as client:
            response=client.get(url+"/auth/v1/user",headers={"apikey":key,"Authorization":authorization})
        if response.status_code in (400,401,403):
            raise HTTPException(401,"Invalid access token")
        if response.status_code!=200:
            raise HTTPException(503,"Identity provider unavailable")
        user=response.json()
        if user.get("role")!="authenticated" or user.get("is_anonymous") or not user.get("email_confirmed_at"):
            raise HTTPException(403,"Verified email account required")
        return {"id":str(UUID(user["id"])),"email":user.get("email")}
    except (httpx.RequestError,ValueError,KeyError,TypeError,AttributeError):
        raise HTTPException(503,"Identity verification unavailable") from None

router=APIRouter(prefix="/api/v2/auth")
@router.get("/me")
def me(user=Depends(identity)):
    return user
