# AquaResilience AI — Forge '26 engineering starter

**Status:** evidence-based, non-certifying decision-support prototype. Not an approved navigation, rescue dispatch, hydrodynamic storm-surge, or emergency alert system. All routes require authorized human review. This repository contains **no seeded inventory**, **no seeded marine network**, **no hardcoded weather feeds**, and **no mock responses**.

## What works in this starter

- Live Open-Meteo hourly atmospheric + marine forecast sampling, checked at route-sample ETA rather than pretending one site represents a whole mission.
- Real road-route alternatives from the OSRM demo service (low-rate hackathon evaluation only).
- Maritime candidate paths from an **operator-approved** PostGIS corridor graph, with three bounded alternatives and no invented sea path.
- LangGraph state flow: candidate planner → hazard inspector → deterministic feasibility guard → optional structured OpenAI triage → evidence-only briefing.
- Fully typed FastAPI `/api/v1/plan`, 3D React Three Fiber route dashboard, request provenance, recurring 30-second re-evaluation while the dashboard is open.
- SQL-backed inventory preview and human-authorized, idempotent, transactionally protected reservation; it does **not** send vessels or execute physical shipment.
- Optional IMD cyclone/port/coastal bulletin adapter, disabled until a real IMD credential scheme has been provisioned. Raw IMD JSON is labelled `UNVALIDATED_FOR_AUTONOMOUS_DECISIONS`, not used in the live routing guard.

## Setup (local)

Requirements: Docker with Compose, Python 3.12+, Node.js 20.9+ (Node.js 22 recommended), npm.

```bash
cp .env.example .env
# Generate a real secret, then edit .env: openssl rand -hex 32
# Set an optional real OPENAI_API_KEY to enable structured risk triage.
docker compose up -d postgis redis
cd apps/api
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
# The backend loads settings from the current .env; copy the root .env here or export vars:
cp ../../.env .env
uvicorn app.main:app --reload --port 8000
```

Second terminal:

```bash
cd apps/web
npm install
# NEXT_PUBLIC_API_BASE defaults to http://localhost:8000 in development.
npm run dev
```

Open `http://localhost:3000`. Enter the actual operator API key, actual origin/destination coordinates, a real time, and the operational safety limits supplied by the responsible operator. The frontend intentionally starts with **blank fields** and displays **no generated measurements** before a successful source-backed request.

### Database state

Database schema initializes from `sql/001_schema.sql` on the **first** empty Postgres volume initialization. It inserts no records. If the DB volume already exists, apply the schema manually using `psql`.

- No marine paths appear until authorized personnel upload **real, sourced, valid** corridor geometries through `POST /api/v1/corridors`.
- The graph requires matching node IDs at segment endpoints. Upload lines consistently oriented from `from_node` to `to_node`; source and attestation details must reflect genuine chart material.
- Inventory endpoints return HTTP 409 until an actual operational system has populated `inventory` and kept `updated_at` fresh. In production, link a warehouse system to this live SQL table or event-driven ingestion service.
- The API key is a demo operator credential, not a substitute for production OIDC, role-based authorization, signed chart attestation, or approval workflows.

## Endpoint index

- `GET /health`: live database connection check.
- `POST /api/v1/plan`: source-backed planning, with `X-API-Key` header and validated `Mission` JSON.
- `POST /api/v1/corridors`: authorized, provenance-labelled marine graph registration (NOT a certification that uploaded chart paths are safe).
- `POST /api/v1/dispatch/preview`: live inventory snapshot, stale data refused.
- `POST /api/v1/dispatch/approve`: authenticated human command that reserves inventory atomically and idempotently. Physical deployment is not triggered.
- `GET /api/v1/official/imd/cyclone_track`: optional authenticated IMD source with strict unvalidated label (also `port_warning` and `coastal_bulletin`).
- OpenAPI documentation: `http://localhost:8000/docs`.

The `Mission` contract is published at `/openapi.json` and can be operated via `/docs`; no example mission coordinates are seeded. `departure_at` must be an ISO 8601 offset-aware time within the forecast planning horizon.

## Real data source configuration

| Provider | Live endpoint and usage | Authentication or permission |
| --- | --- | --- |
| Open-Meteo marine | `https://marine-api.open-meteo.com/v1/marine` — `wave_height`, hourly, georeferenced | Terms and quotas apply; commercial use may require a subscription |
| Open-Meteo weather | `https://api.open-meteo.com/v1/forecast` — `wind_speed_10m`, hourly | Terms and quotas apply |
| IMD | `https://api.imd.gov.in/api/v1/cyclone_track`, `/portwarning`, `/coastalbulletin` | Official authorization needed; configure `IMD_AUTH_HEADER` and `IMD_AUTH_VALUE` exactly as assigned |
| INCOIS OSF | `https://www.incois.gov.in/site/services/osf.jsp` | Service is documented, but machine-readable integration requires an agreed feed/source contract; NOT implemented as a guessed URL |
| Bhuvan flood/cyclone | `https://bhuvan-app1.nrsc.gov.in/disaster/disaster.php` | Discover accessible authoritative WMS/WFS layers and their rights; NOT silently mixed into route approval |
| OSRM | `https://router.project-osrm.org` | Public demo only; must self-host for production |
| Maritime charts | Approved operator-supplied live PostGIS graph | Requires formal navigational source validation, governance, expiry and licensing |
| Warehouse / fleet | Authorized SQL/event sources | Connect real operations; no sample records |

**Critical distinction:** Open-Meteo wave height is **not storm surge**. The prototype does not fabricate coastal surge depths or claim safety from modeled 8-km tidal conditions. Flood route safety needs geospatial inundation and closure verification; the code returns `ADVISORY_ONLY` and explicit warnings.

## Safety invariants

1. No source response → no unqualified recommendation. No approved graph → no marine route.
2. Source units, hour arrays, sample count, and time distance to ETA are checked.
3. Candidate route hazard thresholds come from mission operator inputs; no universal limits are made up.
4. The LLM categorizes evidence but cannot approve a route; generated factual narrative is discarded.
5. All route states include operator-approval requirements. Physical dispatch is not automated.
6. Inventory reservations use row-level locks + a caller-provided idempotency key. Concurrency may still require stricter retry policies under scaled deployments.
7. Request audit and source URLs are recorded. Never put API credentials in the frontend build or provenance records.

## Known scope limitations / production hardening

This is runnable starter architecture, **not a deployed production system or safety certification**. Automated hydrodynamic surge prediction, Bhuvan raster-to-geometry spatial intersection, chart correctness checks, authenticated AIS, vehicle live positioning, sea-route closure notices, IMD alert schema mapping, actual fleet dispatch, authentication roles, Celery/Redis task workers, audit event signatures, high-availability routing, congestion and bridge closure feeds, webhook ingestion and multi-tenant isolation remain integration work. A working three-dimensional route representation is included, but terrain height is a reference plane, not a genuine digital elevation model. Never claim they are complete.

Suggested deployment progression: self-host OSRM; obtain and integrate licensed hydrographic corridors and approved nautical depth/notice data; ingest official IMD and INCOIS under explicit access agreements; ingest Bhuvan time-stamped, datum-aware raster/vector inundation layers; connect real inventory and fleet systems; configure OAuth2/OIDC authorization and human approval; add PostGIS raster/vector intersections and validated hydrodynamics; deploy Celery+Redis and Redis-backed SSE/WebSockets; measure latency and correctness under real feed failures.

## Judge-oriented test strategy (no dummy operational data)

- Run a real `POST /api/v1/plan` with the current endpoints during judging and show `Evidence.url`, `valid_at`, and actual API JSON in a separate browser tab.
- Deliberately revoke an API provider connection to show `503 LIVE_SOURCE_UNAVAILABLE` instead of fictional values.
- Attempt a maritime mission on an empty database and show `NO_APPROVED_CORRIDOR`.
- Submit a request with invalid negative operating thresholds to show Pydantic `422`.
- Show empty live inventory (`409`) rather than a generated supply count.
- Register real sourced maritime data and show paths only after authorized graph records exist.
- Demonstrate forecast refresh and a changed recommended candidate if genuine forecasts or authorized corridor updates cause one.
- Do **not** promise a hazard change during the 3-minute demo if no actual event occurs. The UI is honest about operational reality.

## Relevant public documentation

- https://open-meteo.com/en/docs/marine-weather-api
- https://open-meteo.com/en/docs
- https://api.imd.gov.in/public/api_reference.html
- https://www.incois.gov.in/site/services/osf.jsp
- https://bhuvan.nrsc.gov.in/wiki/index.php/How_to_use_WMS_services
- https://project-osrm.org/docs/v26.6.1/http
