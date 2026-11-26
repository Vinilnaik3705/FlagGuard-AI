"""Flagsmith CLI adapter. Explicit target, no shell interpolation."""
import os
import re
import json
import shutil
import subprocess
from . import providers

def run_cli(feature, action="get", segment=None, inspect_only=False):
    if segment is not None and (not isinstance(segment,int) or segment <= 0):
        raise providers.ProviderError("Invalid segment ID")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}", feature):
        raise providers.ProviderError("Invalid feature name")
    if action not in ("get","enable","disable"):
        raise providers.ProviderError("Unsupported CLI action")
    executable = shutil.which(os.getenv("FLAGSMITH_CLI_PATH","flagsmith"))
    if not executable:
        raise providers.ProviderError("Flagsmith CLI not found")
    env = {k:v for k,v in os.environ.items() if not k.startswith("FLAGSMITH_")}
    env["FLAGSMITH_API_KEY"] = providers.required("FLAGSMITH_ADMIN_API_KEY")
    args = ["flag","get",feature] if action=="get" else ["flag","update",feature,"--"+action,"--yes"]
    if segment is not None:
        args += ["--segment",str(segment)]
    args += ["--environment",providers.required("FLAGSMITH_ENVIRONMENT_ID"),"--project",providers.required("FLAGSMITH_PROJECT_ID"),"--api-url","https://api.flagsmith.com","--no-input","--json"]
    try:
        p = subprocess.run([executable,*args],env=env,capture_output=True,text=True,timeout=45,check=False)
    except (OSError,subprocess.TimeoutExpired):
        raise providers.ProviderError("CLI launch failed or timed out") from None
    if p.returncode:
        raise providers.ProviderError(f"CLI exited with code {p.returncode}")
    if action=="get":
        try:
            data=json.loads(p.stdout)
        except ValueError:
            raise providers.ProviderError("Invalid CLI JSON") from None
        if segment is not None:
            if not isinstance(data,dict) or data.get("feature") != feature or data.get("type") != "standard" or type(data.get("enabled")) is not bool or not isinstance(data.get("segment"),dict) or data["segment"].get("id") != segment:
                raise providers.ProviderError("Unexpected segment response")
            return data
        if not isinstance(data,dict) or data.get("feature")!=feature or type(data.get("enabled")) is not bool:
            raise providers.ProviderError("Unexpected CLI response")
        if not inspect_only and (data.get("type")!="standard" or data.get("segment_overrides")!=0 or data.get("identity_overrides")!=0):
            raise providers.ProviderError("Only standard flags without overrides supported")
        return data

def snapshot(feature):
    return run_cli(feature)

def update(feature, enabled):
    run_cli(feature,"enable" if enabled else "disable")

def segment_snapshot(feature, segment):
    return run_cli(feature, "get", segment)

def segment_update(feature, segment, enabled):
    return run_cli(feature, "enable" if enabled else "disable", segment)

def inspect_flag(feature):
    return run_cli(feature, inspect_only=True)
