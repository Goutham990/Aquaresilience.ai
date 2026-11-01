'use client';
import dynamic from 'next/dynamic';
import {useCallback,useEffect,useRef,useState} from 'react';
import type {Plan,Position} from '../components/Scene';
const Scene=dynamic(()=>import('../components/Scene'),{ssr:false});
type Mission={origin:Position;destination:Position;transport:'road'|'maritime';departure_at:string;max_wind_kmh:number;max_wave_m?:number;cruise_kmh?:number;max_route_hours:number};
const API=process.env.NEXT_PUBLIC_API_BASE??'http://localhost:8000';
export default function Command(){
  const [token,setToken]=useState('');
  const [fromLat,setFromLat]=useState('');const [fromLon,setFromLon]=useState('');
  const [toLat,setToLat]=useState('');const [toLon,setToLon]=useState('');
  const [transport,setTransport]=useState<'road'|'maritime'>('road');
  const [wind,setWind]=useState('');const [wave,setWave]=useState('');const [speed,setSpeed]=useState('');
  const [departure,setDeparture]=useState('');const [hours,setHours]=useState('');
  const [plan,setPlan]=useState<Plan|null>(null);const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);const [origin,setOrigin]=useState<Position|null>(null);
  const missionRef=useRef<Mission|null>(null);
  const tokenRef=useRef('');tokenRef.current=token;
  const inFlight=useRef(false);
  const execute=useCallback(async(m:Mission)=>{
    if(inFlight.current)return;
    inFlight.current=true;setBusy(true);setError('');
    try{
      const res=await fetch(`${API}/api/v1/plan`,{method:'POST',headers:{'Content-Type':'application/json','X-API-Key':tokenRef.current},body:JSON.stringify(m),cache:'no-store'});
      const json:unknown=await res.json();
      if(!res.ok)throw new Error(JSON.stringify(json));
      const next=json as Plan;
      if(!next.status||!Array.isArray(next.candidates))throw new Error('Invalid API payload');
      setPlan(next);setOrigin(m.origin);
    }catch(e){setError(e instanceof Error?e.message:'Unknown backend failure');setPlan(null)}
    finally{setBusy(false);inFlight.current=false}
  },[]);
  function submit(e:React.FormEvent<HTMLFormElement>){
    e.preventDefault();
    const m:Mission={origin:{lat:Number(fromLat),lon:Number(fromLon)},destination:{lat:Number(toLat),lon:Number(toLon)},
      transport,departure_at:new Date(departure).toISOString(),max_wind_kmh:Number(wind),max_route_hours:Number(hours),
      ...(transport==='maritime'?{max_wave_m:Number(wave),cruise_kmh:Number(speed)}:{})};
    missionRef.current=m;void execute(m);
  }
  useEffect(()=>{
    // Recurring REAL network reevaluation, never fake WebSocket ticks.
    const id=setInterval(()=>{if(missionRef.current){const m=missionRef.current;void execute({...m,departure_at:new Date(Math.max(Date.parse(m.departure_at),Date.now())).toISOString()})}},30_000);
    return()=>clearInterval(id);
  },[execute]);
  const nums=(value:string)=>Number.isFinite(Number(value))&&value.trim()!=='';
  const valid=Boolean(token&&departure&&[fromLat,fromLon,toLat,toLon,wind,hours].every(nums)&&
     (transport==='road'||[wave,speed].every(nums)));
  return <main className="max-w-[1550px] mx-auto p-5 lg:p-8">
    <header className="mb-6 flex flex-wrap justify-between gap-3 items-center">
      <div><div className="text-xs tracking-[.3em] text-teal-400">FORGE '26 / EMERGENCY INTELLIGENCE</div>
        <h1 className="text-3xl font-bold mt-2">AquaResilience AI</h1><p className="text-[#9cb8ca]">Verified live forecasts. Autonomous planning. Human-controlled deployment.</p></div>
      <div className="border border-[#376e74] rounded-lg p-3 text-sm text-teal-200">RESEARCH DECISION SUPPORT — NOT NAVIGATION CLEARANCE</div>
    </header>
    <div className="grid grid-cols-1 lg:grid-cols-[340px_minmax(0,1fr)] gap-4">
      <form onSubmit={submit} className="panel grid gap-3 content-start">
        <h2 className="font-semibold text-lg">Mission & operating limits</h2>
        <label><span className="label">Operator API key (not stored)</span><input type="password" value={token} onChange={e=>setToken(e.target.value)} required/></label>
        <label><span className="label">Mode</span><select value={transport} onChange={e=>setTransport(e.target.value as 'road'|'maritime')}><option value="road">Overland / OSRM</option><option value="maritime">Maritime / approved corridors</option></select></label>
        <div className="grid grid-cols-2 gap-2">
          {([[fromLat,setFromLat,'Origin latitude'],[fromLon,setFromLon,'Origin longitude'],[toLat,setToLat,'Target latitude'],[toLon,setToLon,'Target longitude']] as const).map(([v,set,label])=><label key={label}><span className="label">{label}</span><input type="number" step="any" required value={v} onChange={e=>set(e.target.value)}/></label>)}
        </div>
        <label><span className="label">Departure (local)</span><input type="datetime-local" required value={departure} onChange={e=>setDeparture(e.target.value)}/></label>
        <label><span className="label">Maximum route hours (operator)</span><input type="number" step="any" min="0.01" max="24" value={hours} onChange={e=>setHours(e.target.value)} required/></label>
        <label><span className="label">Maximum acceptable wind (km/h)</span><input type="number" step="any" min="0.01" value={wind} onChange={e=>setWind(e.target.value)} required/></label>
        {transport==='maritime'&&<><label><span className="label">Vessel max wave height (m)</span><input type="number" min="0.01" step="any" value={wave} onChange={e=>setWave(e.target.value)} required/></label>
          <label><span className="label">Vessel cruise speed (km/h)</span><input type="number" min="0.01" step="any" value={speed} onChange={e=>setSpeed(e.target.value)} required/></label></>}
        <button disabled={!valid||busy} type="submit">{busy?'Fetching live intelligence…':'Calculate evidence-linked plan'}</button>
        <div className="muted">After submission, the app re-fetches actual external forecasts and re-evaluates the mission every 30 seconds while open. No synthetic scenario is used.</div>
      </form>
      <div className="grid gap-4 content-start">
        <div className="panel"><div className="flex justify-between pb-3"><h2 className="font-semibold">3D georeferenced mission trajectories</h2><span className="muted">Green: recommended · Red: blocked</span></div>
          <Scene plan={plan} origin={origin} maxWind={Number(wind)} maxWave={transport==='maritime'?Number(wave):null}/>
          <div className="muted mt-2">Visualization uses a level reference plane, not an elevation model or simulated flood depth.</div>
        </div>
        {error&&<div className="panel border-red-700 text-red-200" role="alert">Live source or API failure: {error}</div>}
        <div className="panel"><h2 className="font-semibold mb-3">Operational decision / provenance</h2>
          {!plan?<p className="muted">No operational results until live data is requested.</p>:<>
            <div className="mb-3 font-bold text-xl">{plan.status}</div><p>{plan.briefing}</p>
            <p className="muted mt-2">Evaluated: {new Date(plan.evaluated_at).toLocaleString()}</p>
            {plan.warnings.length>0&&<p className="mt-3 text-amber-200">Restrictions: {plan.warnings.join(' · ')}</p>}
            {plan.candidates.map(c=><div key={c.candidate_id} className="border-t border-[#2d5166] mt-3 pt-3">
              <strong>{c.candidate_id}</strong> · {c.blocked_reasons.length?'BLOCKED':'CONDITIONALLY FEASIBLE'}
              <div className="muted">Source: {c.source} · {c.distance_m.toFixed(0)} actual route meters · {c.evidence.length} live forecast samples</div>
              {c.blocked_reasons.length>0&&<div className="text-red-300 text-sm">{c.blocked_reasons.join(', ')}</div>}
              {c.evidence.length>0&&<div className="text-xs text-[#9cb8ca]">Source: {c.evidence[0].source} · Forecast valid: {new Date(c.evidence[0].valid_at).toLocaleString()} · <a className="underline" href={c.evidence[0].url} target="_blank" rel="noreferrer">Request provenance</a></div>}
            </div>)}
          </>}
        </div>
      </div>
    </div>
  </main>;
}
