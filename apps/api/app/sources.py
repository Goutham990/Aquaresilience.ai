"""Only network-derived observations: no synthetic data, no silent last-known-good."""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from .models import Evidence, Point

class SourceUnavailable(RuntimeError):
    pass

class HourlyForecast(BaseModel):
    time: list[datetime]
    model_config = ConfigDict(extra="allow")

class ForecastResponse(BaseModel):
    hourly: dict[str, Any]
    hourly_units: dict[str, str] = Field(default_factory=dict)

MARINE = "https://marine-api.open-meteo.com/v1/marine"
WEATHER = "https://api.open-meteo.com/v1/forecast"

async def get_json(client: httpx.AsyncClient, url: str, params: dict | None = None) -> tuple[dict | list, str]:
    for attempt in range(2):
        try:
            res = await client.get(url, params=params, follow_redirects=False)
            if res.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                await asyncio.sleep(0.4)
                continue
            res.raise_for_status()
            data = res.json()
            if not isinstance(data, (dict, list)):
                raise SourceUnavailable("Unexpected root JSON shape")
            return data, str(res.url)
        except (httpx.HTTPError, ValueError) as exc:
            if attempt == 1:
                raise SourceUnavailable(f"{url}: {type(exc).__name__}") from exc
    raise SourceUnavailable("External data source unavailable")

def _parse_hour(hour: str) -> datetime:
    # timezone=UTC is always requested. Never label a time without a timezone.
    return datetime.fromisoformat(hour).replace(tzinfo=timezone.utc)

async def fetch_samples(client: httpx.AsyncClient, points: list[Point], transport: str,
                        departure: datetime, duration_s: float) -> tuple[list[Evidence], float, float | None]:
    if not points:
        raise SourceUnavailable("No route sample coordinates")
    if len(points) > 16:
        raise SourceUnavailable("Route samples exceed bounded request size")
    params_common = {
        "latitude": ",".join(str(p.lat) for p in points),
        "longitude": ",".join(str(p.lon) for p in points),
        "timezone": "UTC", "forecast_hours": 24,
    }
    requests = [(WEATHER, {**params_common, "hourly": "wind_speed_10m"}, "wind_speed_10m", "km/h")]
    if transport == "maritime":
        requests.append((MARINE, {**params_common, "hourly": "wave_height"}, "wave_height", "m"))
    responses = await asyncio.gather(*(get_json(client, url, qs) for url, qs, _, _ in requests))
    evidence: list[Evidence] = []
    fetched_at = datetime.now(timezone.utc)
    peaks: dict[str, list[float]] = {item[2]: [] for item in requests}
    for (url, _, metric, expected_unit), (raw, exact_url) in zip(requests, responses):
        records = raw if isinstance(raw, list) else [raw]
        if len(records) != len(points):
            raise SourceUnavailable("Forecast point count mismatch")
        for i, record in enumerate(records):
            if not isinstance(record, dict):
                raise SourceUnavailable("Unexpected forecast element")
            try:
                parsed = ForecastResponse.model_validate(record)
                times = [_parse_hour(s) for s in parsed.hourly["time"]]
                values = parsed.hourly[metric]
            except (ValidationError, KeyError, TypeError, ValueError) as exc:
                raise SourceUnavailable(f"Invalid {metric} response") from exc
            if parsed.hourly_units.get(metric) != expected_unit:
                raise SourceUnavailable(f"Unexpected {metric} unit; required {expected_unit}")
            if len(times) != len(values) or not times:
                raise SourceUnavailable(f"Incomplete {metric} forecast")
            eta = departure.astimezone(timezone.utc) + timedelta(seconds=duration_s*i/max(1,len(points)-1))
            nearest = min(range(len(times)), key=lambda j: abs((times[j]-eta).total_seconds()))
            if abs((times[nearest]-eta).total_seconds()) > 3600:
                raise SourceUnavailable("No forecast in required ETA window")
            reading = values[nearest]
            if reading is None or not isinstance(reading, (int, float)) or reading < 0:
                raise SourceUnavailable(f"Missing or invalid {metric} reading")
            # All numbers are actual API readings, not local sample values.
            evidence.append(Evidence(point=points[i],source="Open-Meteo", url=exact_url,
                retrieved_at=fetched_at, valid_at=times[nearest],
                metric=metric, value=float(reading), unit=expected_unit))
            peaks[metric].append(float(reading))
    return evidence, max(peaks["wind_speed_10m"]), (
        max(peaks["wave_height"]) if "wave_height" in peaks else None)
