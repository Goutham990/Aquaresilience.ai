from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, model_validator

class Transport(str, Enum):
    ROAD = "road"
    MARITIME = "maritime"

class Point(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)

class Mission(BaseModel):
    origin: Point
    destination: Point
    transport: Transport
    departure_at: datetime
    max_wind_kmh: float = Field(gt=0)
    max_wave_m: float | None = Field(default=None, gt=0)
    cruise_kmh: float | None = Field(default=None, gt=0)
    max_route_hours: float = Field(gt=0, le=24)

    @model_validator(mode="after")
    def mission_constraints(self):
        now = datetime.now(timezone.utc)
        if self.departure_at.tzinfo is None:
            raise ValueError("departure_at must include a timezone")
        if not (now.timestamp() - 300 <= self.departure_at.timestamp() <= now.timestamp() + 23*3600):
            raise ValueError("Departure must be recent or within the available 24h planning horizon")
        if self.transport == Transport.MARITIME and (self.max_wave_m is None or self.cruise_kmh is None):
            raise ValueError("Maritime planning requires explicit vessel max_wave_m and cruise_kmh")
        return self

class Evidence(BaseModel):
    point: Point
    source: str
    url: str
    retrieved_at: datetime
    valid_at: datetime
    metric: str
    value: float
    unit: str

class Candidate(BaseModel):
    candidate_id: str
    coordinates: list[list[float]]  # GeoJSON order [longitude,latitude]
    distance_m: float = Field(gt=0)
    duration_s: float = Field(gt=0)
    source: str
    corridor_ids: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    peak_wind_kmh: float | None = None
    peak_wave_m: float | None = None
    evidence: list[Evidence] = Field(default_factory=list)

class Plan(BaseModel):
    status: Literal["ADVISORY_ONLY", "BLOCKED", "DATA_UNAVAILABLE", "NO_APPROVED_CORRIDOR"]
    selected: Candidate | None
    candidates: list[Candidate]
    warnings: list[str]
    briefing: str
    evaluated_at: datetime
    human_approval_required: bool = True

class Triage(BaseModel):
    priority: Literal["routine", "elevated", "critical", "unknown"]
    briefing: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[int] = Field(default_factory=list)

class SupplyPreviewRequest(BaseModel):
    depot_id: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    requested_units: int = Field(gt=0)

class SupplyApprovalRequest(SupplyPreviewRequest):
    idempotency_key: str = Field(min_length=12, max_length=128)
    operator_id: str = Field(min_length=1)
