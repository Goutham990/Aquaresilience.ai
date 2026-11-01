"""Bounded, evidence-first LangGraph. LLM never controls approval or navigation."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import TypedDict
import asyncpg
import httpx
from langgraph.graph import StateGraph, END, START
from langchain_core.tools import tool
from .models import Candidate, Mission, Plan, Triage, Transport
from .routing import road_candidates, marine_candidates, evenly_sample
from .sources import fetch_samples, SourceUnavailable
from .settings import settings

@tool
async def check_wave_hazard(coordinates: list[list[float]], departure_at: str,
                            duration_s: float, max_wave_m: float, max_wind_kmh: float) -> dict:
    """Check actual time-aligned forecast at georeferenced maritime route samples."""
    from datetime import datetime
    async with httpx.AsyncClient(timeout=12.0,headers={"User-Agent":"AquaResilience-AI/0.1"}) as client:
        evidence, peak_wind, peak_wave = await fetch_samples(client,evenly_sample(coordinates),
            "maritime",datetime.fromisoformat(departure_at),duration_s)
    return {"safe_by_vessel_limits":peak_wind <= max_wind_kmh and peak_wave <= max_wave_m,
            "peak_wind_kmh":peak_wind,"peak_wave_m":peak_wave,
            "evidence":[e.model_dump(mode="json") for e in evidence]}

@tool
async def recalculate_maritime_route(mission_json: str) -> dict:
    """Calculate alternatives ONLY from currently approved PostGIS maritime corridors."""
    mission=Mission.model_validate_json(mission_json)
    if mission.transport != Transport.MARITIME:
        raise ValueError("Maritime-only tool")
    pool=await asyncpg.create_pool(dsn=settings.database_url,min_size=1,max_size=2)
    try:
        candidates=await marine_candidates(pool,mission)
        return {"candidates":[c.model_dump(mode="json") for c in candidates],
                "status":"OK" if candidates else "NO_APPROVED_CORRIDOR"}
    finally:
        await pool.close()

class AgentState(TypedDict, total=False):
    mission: Mission
    candidates: list[Candidate]
    evaluated: list[Candidate]
    warnings: list[str]
    status: str
    selected: Candidate | None
    triage: Triage | None
    plan: Plan

async def _llm_classify(plan_status: str, candidates: list[Candidate],warnings: list[str]) -> Triage | None:
    if not settings.openai_api_key: return None
    from langchain_openai import ChatOpenAI
    # The LLM is constrained to structured classification; the factual briefing is programmatic.
    bounded=[{"id":c.candidate_id,"blocked":c.blocked_reasons,
              "wind_kmh":c.peak_wind_kmh,"wave_m":c.peak_wave_m} for c in candidates]
    try:
        llm=ChatOpenAI(api_key=settings.openai_api_key,model=settings.openai_model,timeout=9,max_retries=0)
        obj=await llm.with_structured_output(Triage).ainvoke([
            ("system","Classify priority from supplied observations only. No new facts, places, "
             "measurements or routes. Provide only evidence indices present in the input; "
             "never recommend execution without human approval."),
            ("user",str({"plan_status":plan_status,"candidate_facts":bounded,"warnings":warnings}))])
        # Ignore generated freeform briefing; only use validated categorical triage.
        if obj.evidence_ids: return None  # prompt does not expose numbered evidence.
        return obj
    except Exception:
        return None  # LLM failure cannot change validated route feasibility.

def build_graph(pool:asyncpg.Pool,client:httpx.AsyncClient):
    async def plan_routes(state:AgentState)->dict:
        mission=state["mission"]
        if mission.transport==Transport.MARITIME:
            candidates=await marine_candidates(pool,mission)
            return {"candidates":candidates,"status":"OK" if candidates else "NO_APPROVED_CORRIDOR"}
        return {"candidates":await road_candidates(client,mission),"status":"OK"}

    async def inspect_hazards(state:AgentState)->dict:
        mission=state["mission"]
        evaluated=[]
        warnings=[]
        for candidate in state.get("candidates",[]):
            if candidate.duration_s>mission.max_route_hours*3600:
                candidate.blocked_reasons.append("TRAVEL_TIME_EXCEEDS_OPERATIONAL_LIMIT")
                evaluated.append(candidate)
                continue
            try:
                evidence,wind,wave=await fetch_samples(client,evenly_sample(candidate.coordinates),
                    mission.transport.value,mission.departure_at,candidate.duration_s)
                candidate.evidence=evidence;candidate.peak_wind_kmh=wind;candidate.peak_wave_m=wave
                if wind>mission.max_wind_kmh:
                    candidate.blocked_reasons.append("WIND_EXCEEDS_VESSEL_OR_VEHICLE_LIMIT")
                if mission.transport==Transport.MARITIME and wave>mission.max_wave_m:
                    candidate.blocked_reasons.append("WAVE_EXCEEDS_VESSEL_LIMIT")
            except SourceUnavailable as exc:
                candidate.blocked_reasons.append("FORECAST_UNAVAILABLE")
                warnings.append(str(exc))
            evaluated.append(candidate)
        return {"evaluated":evaluated,"warnings":warnings}

    def verify_and_select(state:AgentState)->dict:
        evaluated=state.get("evaluated",[])
        mission=state["mission"]
        warnings=state.get("warnings",[])
        if state["status"]=="NO_APPROVED_CORRIDOR":
            return {"status":"NO_APPROVED_CORRIDOR","selected":None,"warnings":warnings}
        safe=[c for c in evaluated if not c.blocked_reasons]
        if safe:
            candidate=min(safe,key=lambda c:c.duration_s)
            warnings.append("HUMAN_APPROVAL_REQUIRED")
            warnings.append("LIVE_ASSET_POSITION_NOT_VERIFIED; ROUTE_STARTS_AT_OPERATOR_SUPPLIED_ORIGIN")
            if mission.transport==Transport.ROAD:
                warnings.append("ROAD_FLOOD_AND_CLOSURE_DATA_NOT_VERIFIED")
            else:
                warnings.append("NAUTICAL_CHARTS_DEPTH_NOTICES_AND_PORT_CLEARANCE_NOT_VERIFIED")
            return {"status":"ADVISORY_ONLY","selected":candidate,"warnings":warnings}
        if any("FORECAST_UNAVAILABLE" in c.blocked_reasons for c in evaluated):
            return {"status":"DATA_UNAVAILABLE","selected":None,"warnings":warnings}
        return {"status":"BLOCKED","selected":None,"warnings":warnings}

    async def intelligence(state:AgentState)->dict:
        obj=await _llm_classify(state["status"],state.get("evaluated",[]),state["warnings"])
        return {"triage":obj}

    def final(state:AgentState)->dict:
        selected=state.get("selected")
        status=state["status"]
        triage=state.get("triage")
        if selected:
            briefing=(f"Candidate {selected.candidate_id} is a NON-AUTHORIZED advisory. "
                f"Route {selected.distance_m/1000:.2f} km; estimated travel "
                f"{selected.duration_s/60:.0f} minutes. Verified forecast sample max wind "
                f"{selected.peak_wind_kmh:.1f} km/h. "
                + (f"Max significant wave height {selected.peak_wave_m:.2f} m. "
                   if selected.peak_wave_m is not None else "")
                + "An authorized human must review all missing safety layers before dispatch.")
        else:
            briefing=f"No actionable route issued. State: {status}. Confirm missing sources/corridors before retrying."
        if triage:
            briefing+=f" AI triage category: {triage.priority}."
        plan=Plan(status=status,selected=selected,candidates=state.get("evaluated",[]),
            warnings=state["warnings"],briefing=briefing,
            evaluated_at=datetime.now(timezone.utc))
        return {"plan":plan}

    graph=StateGraph(AgentState)
    graph.add_node("candidate_planner",plan_routes)
    graph.add_node("hazard_inspector",inspect_hazards)
    graph.add_node("feasibility_guard",verify_and_select)
    graph.add_node("llm_triage",intelligence)
    graph.add_node("briefing",final)
    graph.add_edge(START,"candidate_planner")
    graph.add_edge("candidate_planner","hazard_inspector")
    graph.add_edge("hazard_inspector","feasibility_guard")
    graph.add_edge("feasibility_guard","llm_triage")
    graph.add_edge("llm_triage","briefing")
    graph.add_edge("briefing",END)
    return graph.compile()
