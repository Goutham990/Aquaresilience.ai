'use client';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Grid } from '@react-three/drei';
import { useMemo } from 'react';
import * as THREE from 'three';
export type Position = {lat:number;lon:number};
export type Evidence={point:Position;source:string;url:string;retrieved_at:string;valid_at:string;metric:string;value:number;unit:string};
export type Candidate={candidate_id:string;coordinates:number[][];distance_m:number;duration_s:number;source:string;corridor_ids:string[];blocked_reasons:string[];peak_wind_kmh:number|null;peak_wave_m:number|null;evidence:Evidence[]};
export type Plan={status:'ADVISORY_ONLY'|'BLOCKED'|'DATA_UNAVAILABLE'|'NO_APPROVED_CORRIDOR';selected:Candidate|null;candidates:Candidate[];warnings:string[];briefing:string;evaluated_at:string;human_approval_required:boolean};

function Path({candidate,origin,selected}:{candidate:Candidate;origin:Position;selected:boolean}){
  const geometry=useMemo(()=>{
    const coords=candidate.coordinates.map(c=>new THREE.Vector3(
      (c[0]-origin.lon)*111.32*Math.cos(origin.lat*Math.PI/180),0.08,
      -(c[1]-origin.lat)*111.32));
    return new THREE.TubeGeometry(new THREE.CatmullRomCurve3(coords),Math.min(300,Math.max(15,coords.length*2)),0.07,6,false);
  },[candidate,origin]);
  return <mesh geometry={geometry}><meshStandardMaterial color={candidate.blocked_reasons.length?'#e65f5f':selected?'#21e5bb':'#78a7c5'} emissive={selected?'#085342':'#000000'}/></mesh>;
}
function Hazard({e,origin}:{e:Evidence;origin:Position}){
  return <mesh position={[(e.point.lon-origin.lon)*111.32*Math.cos(origin.lat*Math.PI/180),0.32,-(e.point.lat-origin.lat)*111.32]}>
    <cylinderGeometry args={[0.12,0.12,0.65,10]}/><meshStandardMaterial color="#fb5b5b" emissive="#661818"/>
  </mesh>;
}
export default function Scene({plan,origin,maxWind,maxWave}:{plan:Plan|null;origin:Position|null;maxWind:number;maxWave:number|null}){
  const candidates=plan?.candidates??[];
  const hazardEvidence=candidates.flatMap(c=>c.evidence.filter(e=>
    (e.metric==='wind_speed_10m' && e.value>maxWind)||
    (e.metric==='wave_height'&&maxWave!==null&&e.value>maxWave)));
  return <div className="h-[440px] w-full rounded-xl overflow-hidden border border-[#34566e] bg-[#071421]">
    {origin?<Canvas camera={{position:[0,18,19],fov:48}}>
      <ambientLight intensity={1.4}/><directionalLight position={[4,15,7]} intensity={2}/>
      <Grid args={[200,200]} cellSize={1} cellColor="#16384b" sectionColor="#31596e" fadeDistance={55}/>
      {candidates.map(c=><Path key={c.candidate_id} candidate={c} origin={origin} selected={plan?.selected?.candidate_id===c.candidate_id}/>)}
      {hazardEvidence.map((e,i)=><Hazard key={i} e={e} origin={origin}/>)}
      <OrbitControls makeDefault enableDamping/>
    </Canvas>:<div className="h-full flex items-center justify-center text-[#8cafc3]">Submit a real mission to render georeferenced trajectories.</div>}
  </div>;
}
