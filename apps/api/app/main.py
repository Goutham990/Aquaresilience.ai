from __future__ import annotations
from contextlib import asynccontextmanager
import json
from datetime import datetime, timezone, timedelta
from typing import Annotated
import asyncpg
import httpx
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from .agent import build_graph
from .models import Mission, Plan, SupplyPreviewRequest, SupplyApprovalRequest
from .sources import SourceUnavailable
from .settings import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool=await asyncpg.create_pool(dsn=settings.database_url,min_size=1,max_size=10)
    app.state.http=httpx.AsyncClient(timeout=httpx.Timeout(12,connect=4),headers={"User-Agent":"AquaResilience-AI/0.1"})
    yield
    await app.state.http.aclose()
    await app.state.pool.close()

app=FastAPI(title="AquaResilience AI",version="0.1.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=[settings.cors_origin],allow_methods=["GET","POST"],allow_headers=["X-API-Key","Content-Type"])

async def require_key(x_api_key: Annotated[str | None, Header()] = None):
    import secrets
    if not x_api_key or not secrets.compare_digest(x_api_key,settings.operator_api_key):
        raise HTTPException(401,"Operator authorization required")

@app.get("/health")
async def health():
    try:
        await app.state.pool.fetchval("SELECT 1")
        return {"backend":"connected","timestamp":datetime.now(timezone.utc).isoformat()}
    except Exception:
        return JSONResponse(status_code=503,content={"backend":"unavailable"})

@app.post("/api/v1/plan",response_model=Plan,dependencies=[Depends(require_key)])
async def plan(mission:Mission):
    try:
        state=await build_graph(app.state.pool,app.state.http).ainvoke({"mission":mission})
        result:Plan=state["plan"]
        await app.state.pool.execute("INSERT INTO plan_audit (mission, plan) VALUES ($1::jsonb,$2::jsonb)",
            mission.model_dump_json(),result.model_dump_json())
        return result
    except SourceUnavailable as exc:
        # Explicit failure; never replace with fake environmental observations.
        raise HTTPException(503,detail={"code":"LIVE_SOURCE_UNAVAILABLE","message":str(exc)})

@app.post("/api/v1/dispatch/preview",dependencies=[Depends(require_key)])
async def preview(request:SupplyPreviewRequest):
    row=await app.state.pool.fetchrow("SELECT available_units,source_id,updated_at FROM inventory WHERE depot_id=$1 AND sku=$2",
                                      request.depot_id,request.sku)
    if row is None:raise HTTPException(409,"No verified live inventory record")
    if row["updated_at"] < datetime.now(timezone.utc)-timedelta(minutes=15):
        raise HTTPException(409,"Inventory record stale; refresh from live operations system")
    return {"proposed_units":min(row["available_units"],request.requested_units),
            "available_units":row["available_units"],"source_id":row["source_id"],
            "updated_at":row["updated_at"],"authorization_required":True}

@app.post("/api/v1/dispatch/approve",dependencies=[Depends(require_key)])
async def approve(request:SupplyApprovalRequest):
    async with app.state.pool.acquire() as connection:
        async with connection.transaction():
            previous=await connection.fetchrow("SELECT id,units FROM dispatch_reservations WHERE idempotency_key=$1",
                                                request.idempotency_key)
            if previous:
                return {"reservation_id":str(previous["id"]),"reserved_units":previous["units"],"idempotent":True}
            row=await connection.fetchrow("SELECT available_units,updated_at FROM inventory WHERE depot_id=$1 AND sku=$2 FOR UPDATE",
                                           request.depot_id,request.sku)
            if row is None or row["updated_at"]<datetime.now(timezone.utc)-timedelta(minutes=15):
                raise HTTPException(409,"Live inventory missing or stale")
            if row["available_units"]<request.requested_units:
                raise HTTPException(409,"Insufficient verified available units")
            await connection.execute("UPDATE inventory SET available_units=available_units-$3,updated_at=now() WHERE depot_id=$1 AND sku=$2",
                                       request.depot_id,request.sku,request.requested_units)
            reserved=await connection.fetchval("""INSERT INTO dispatch_reservations
              (idempotency_key,depot_id,sku,units,operator_id)
              VALUES ($1,$2,$3,$4,$5) RETURNING id""",
                request.idempotency_key,request.depot_id,request.sku,request.requested_units,request.operator_id)
            return {"reservation_id":str(reserved),"reserved_units":request.requested_units,
                    "idempotent":False,"physical_dispatch":False}

class CorridorIn(BaseModel):
    from_node: str = Field(min_length=1)
    to_node: str = Field(min_length=1)
    coordinates: list[tuple[float,float]] = Field(min_length=2)
    source_id: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    attested_at: datetime
    valid_until: datetime

@app.post("/api/v1/corridors",dependencies=[Depends(require_key)])
async def ingest_authorized_corridor(request:CorridorIn):
    # Requires real chart-provenance supplied by operator, never seeded or inferred.
    if request.valid_until<=datetime.now(timezone.utc) or request.attested_at>datetime.now(timezone.utc):
        raise HTTPException(422,"Corridor attestation must be current and valid")
    if len(request.coordinates)>10000 or request.from_node==request.to_node:
        raise HTTPException(422,"Invalid graph corridor")
    feature={"type":"LineString","coordinates":request.coordinates}
    try:
        ident=await app.state.pool.fetchval("""INSERT INTO marine_corridors
          (from_node,to_node,geom,source_id,approved_by,attested_at,valid_until)
          VALUES ($1,$2,ST_SetSRID(ST_GeomFromGeoJSON($3),4326),$4,$5,$6,$7)
          RETURNING id""",request.from_node,request.to_node,json.dumps(feature),
          request.source_id,request.approved_by,request.attested_at,request.valid_until)
        return {"corridor_id":str(ident),"status":"REGISTERED"}
    except asyncpg.PostgresError:
        raise HTTPException(409,"Invalid geometry or duplicate corridor")

@app.get("/api/v1/official/imd/{feed}",dependencies=[Depends(require_key)])
async def official_imd(feed:str):
    from .official import fetch_official_imd, IMD_ENDPOINTS
    if feed not in IMD_ENDPOINTS:
        raise HTTPException(404,"Unsupported IMD feed")
    try:
        return await fetch_official_imd(app.state.http,feed)
    except SourceUnavailable as exc:
        raise HTTPException(503,str(exc))
