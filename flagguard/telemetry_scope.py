"""Restrict the shared ingestion credential to explicitly configured event scopes."""
import os

def allowed(event):
    if os.getenv("FLAGGUARD_ENFORCE_TELEMETRY_SCOPE") != "true":
        return True
    services={v.strip() for v in os.getenv("FLAGGUARD_ALLOWED_SERVICES","").split(",") if v.strip()}
    flags={v.strip() for v in os.getenv("FLAGGUARD_ALLOWED_FEATURE_NAMES","").split(",") if v.strip()}
    environment=os.getenv("FLAGGUARD_TELEMETRY_ENVIRONMENT","").strip()
    return bool(services and flags and environment and event.service in services and event.environment==environment and set(event.flags)<=flags)
