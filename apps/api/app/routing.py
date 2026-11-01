from __future__ import annotations
import math
from datetime import datetime, timezone
from typing import Any
import asyncpg
import httpx
import networkx as nx
from .models import Candidate, Mission, Point
from .sources import get_json, SourceUnavailable
from .settings import settings

def haversine(a: Point, b: Point) -> float:
    r = 6_371_000.0  # Earth geometric radius, not data/mock measurement.
    aa, bb = map(math.radians, (a.lat, b.lat))
    dl, dg = map(math.radians, (b.lat-a.lat, b.lon-a.lon))
    x = math.sin(dl/2)**2 + math.cos(aa)*math.cos(bb)*math.sin(dg/2)**2
    return 2*r*math.asin(min(1, math.sqrt(x)))

def poly_distance(coords: list[list[float]]) -> float:
    return sum(haversine(Point(lat=a[1],lon=a[0]),Point(lat=b[1],lon=b[0]))
               for a,b in zip(coords,coords[1:]))

def evenly_sample(coords: list[list[float]], max_samples: int = 12) -> list[Point]:
    if len(coords)<2:
        raise SourceUnavailable("Route geometry has fewer than 2 points")
    # Interpolate by travelled distance, not by vertex index.
    d = [0.0]
    for a,b in zip(coords,coords[1:]):
        d.append(d[-1]+haversine(Point(lat=a[1],lon=a[0]),Point(lat=b[1],lon=b[0])))
    if d[-1] == 0:
        raise SourceUnavailable("Degenerate route")
    result=[]
    for i in range(max_samples):
        target=d[-1]*i/(max_samples-1)
        j=next((j for j in range(len(d)-1) if d[j]<=target<=d[j+1]),len(d)-2)
        alpha=(target-d[j])/(d[j+1]-d[j]) if d[j+1]>d[j] else 0
        lon=coords[j][0]+alpha*(coords[j+1][0]-coords[j][0])
        lat=coords[j][1]+alpha*(coords[j+1][1]-coords[j][1])
        result.append(Point(lat=lat,lon=lon))
    return result

async def road_candidates(client: httpx.AsyncClient, mission: Mission) -> list[Candidate]:
    a,b=mission.origin,mission.destination
    url=f"{settings.osrm_base.rstrip('/')}/route/v1/driving/{a.lon},{a.lat};{b.lon},{b.lat}"
    raw, _ = await get_json(client,url,{"alternatives":"true","overview":"full","geometries":"geojson"})
    if not isinstance(raw,dict) or raw.get("code")!="Ok":
        raise SourceUnavailable("OSRM could not calculate route")
    waypoints=raw.get("waypoints",[])
    if len(waypoints)!=2 or any(float(w.get("distance",float("inf")))>100 for w in waypoints):
        raise SourceUnavailable("At least one location is too far from a mapped road access point")
    output=[]
    for i,route in enumerate(raw.get("routes",[])[:3]):
        coords=route["geometry"]["coordinates"]
        if len(coords)<2: continue
        output.append(Candidate(candidate_id=f"road-{i}", coordinates=coords,
            duration_s=route["duration"],distance_m=route["distance"],source="OSRM/OSM"))
    if not output:
        raise SourceUnavailable("No road route")
    return output

async def marine_candidates(pool: asyncpg.Pool,mission: Mission) -> list[Candidate]:
    # Only actively approved real corridors from PostGIS; DB ships with ZERO seeded corridors.
    rows = await pool.fetch("""
        SELECT id::text, from_node, to_node, ST_AsGeoJSON(geom)::jsonb AS geojson,
               ST_Length(geom::geography) AS length_m
        FROM marine_corridors
        WHERE valid_until > now() AND approved_by IS NOT NULL
          AND ST_Intersects(geom, ST_Expand(ST_MakeEnvelope($1,$2,$3,$4,4326), 0.5))
        LIMIT 3000
    """, min(mission.origin.lon,mission.destination.lon),min(mission.origin.lat,mission.destination.lat),
         max(mission.origin.lon,mission.destination.lon),max(mission.origin.lat,mission.destination.lat))
    if not rows: return []
    graph=nx.DiGraph()
    node_coords: dict[str,Point] = {}
    for row in rows:
        geom=row["geojson"]
        if isinstance(geom,str):
            import json
            geom=json.loads(geom)
        coords=geom["coordinates"]
        if len(coords)<2: continue
        start,end=Point(lon=coords[0][0],lat=coords[0][1]),Point(lon=coords[-1][0],lat=coords[-1][1])
        # Shared graph node IDs must have matching real positions; do not
        # connect geometries with a coincident label but different endpoints.
        if (row["from_node"] in node_coords and
            haversine(node_coords[row["from_node"]],start)>25):
            continue
        if (row["to_node"] in node_coords and
            haversine(node_coords[row["to_node"]],end)>25):
            continue
        node_coords[row["from_node"]]=start;node_coords[row["to_node"]]=end
        graph.add_edge(row["from_node"],row["to_node"],coordinates=coords,
                       corridor_id=row["id"],weight=float(row["length_m"]))
    if not graph.nodes: return []
    start=min(node_coords,key=lambda node:haversine(node_coords[node], mission.origin))
    end=min(node_coords,key=lambda node:haversine(node_coords[node], mission.destination))
    if haversine(node_coords[start],mission.origin)>25 or haversine(node_coords[end],mission.destination)>25:
        return [] # No invented connector from a vessel to the approved graph.
    try:
        paths=nx.shortest_simple_paths(graph,start,end,weight="weight")
        output=[]
        for i,path in enumerate(paths):
            if i>=3: break
            segment_attrs=[graph[u][v] for u,v in zip(path,path[1:])]
            coords=[]
            for e in segment_attrs:
                coords.extend(e["coordinates"] if not coords else e["coordinates"][1:])
            if len(coords)<2: continue
            distance=poly_distance(coords)
            output.append(Candidate(candidate_id=f"marine-{i}",coordinates=coords,
                duration_s=distance/(mission.cruise_kmh*1000/3600), distance_m=distance,
                source="approved PostGIS corridor graph",
                corridor_ids=[e["corridor_id"] for e in segment_attrs]))
        return output
    except (nx.NetworkXNoPath,nx.NodeNotFound):
        return []
