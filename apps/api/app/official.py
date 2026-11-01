"""Optional official IMD adapter. Credentials and response access must be provisioned by IMD.
Do not use this as an active hazard signal until the feed schema and validity times
are confirmed against the actual authorized account response.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone
import httpx
from .sources import SourceUnavailable

IMD_ENDPOINTS = {
    "cyclone_track": "https://api.imd.gov.in/api/v1/cyclone_track",
    "port_warning": "https://api.imd.gov.in/api/v1/portwarning",
    "coastal_bulletin": "https://api.imd.gov.in/api/v1/coastalbulletin",
}

async def fetch_official_imd(client: httpx.AsyncClient, kind: str) -> dict:
    if kind not in IMD_ENDPOINTS:
        raise ValueError("Unsupported IMD feed")
    header_name=os.getenv("IMD_AUTH_HEADER")
    header_value=os.getenv("IMD_AUTH_VALUE")
    if not header_name or not header_value:
        raise SourceUnavailable("IMD credentials not configured; official feed disabled")
    # Auth scheme cannot be assumed. Use exactly the scheme assigned by IMD.
    if header_name.lower() not in ("authorization", "x-api-key", "api-key"):
        raise SourceUnavailable("Unsupported credential header configured")
    try:
        res=await client.get(IMD_ENDPOINTS[kind],headers={header_name:header_value},follow_redirects=False)
        res.raise_for_status()
        raw=res.json()
        if not isinstance(raw,(dict,list)):
            raise ValueError("Unexpected IMD response")
        return {"source":"IMD", "endpoint":IMD_ENDPOINTS[kind],
                "retrieved_at":datetime.now(timezone.utc).isoformat(),
                "payload":raw,"quality_status":"UNVALIDATED_FOR_AUTONOMOUS_DECISIONS"}
    except (httpx.HTTPError,ValueError) as exc:
        raise SourceUnavailable("Authorized IMD feed failed or returned unexpected payload") from exc
