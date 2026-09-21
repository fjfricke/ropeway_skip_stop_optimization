import { matchingAllStop } from "../thesisPresentation";
import { useStudyCatalog } from "../thesisStudy";
import { useEffect,useState } from 'react';
import ThesisRunDetail from '../components/ThesisRunDetail';
import StudyRunLinks from '../components/StudyRunLinks';
import type { ThesisRunSummary } from '../thesisTypes';
export default function JourneyRunPage({id}:{id:string}){
 const [runs,setRuns]=useState<ThesisRunSummary[]>([]); const [error,setError]=useState('');
 useEffect(()=>{let cancelled=false;let timer:number;
 async function poll(){try{const response=await fetch('/generated/thesis/index.json',{cache:'no-store'});if(!response.ok)throw new Error('Journey detail unavailable');const value=await response.json();if(!cancelled){setRuns(value.runs);if(value.campaignStatus==='running')timer=window.setTimeout(poll,2000);}}catch(e){if(!cancelled)setError(String(e));}}
 poll();return()=>{cancelled=true;window.clearTimeout(timer);};},[id]);
 const {catalog}=useStudyCatalog();
 const execution=catalog?.executions.slice().sort((a,b)=>Number(b.original)-Number(a.original)).find(e=>e.runs.some(r=>r.legacy_id===id));
 const run=runs.find(r=>r.id===id);
 const comparison=run&&matchingAllStop(run,runs.filter(r=>execution?.runs.some(item=>item.legacy_id===r.id)));
 return <main className="optimization-shell"><StudyRunLinks id={id}/>{error?<p role="alert">{error}</p>:run?<><section className="optimization-panel"><h1>Journey run · K{run.k}</h1><p>Demand: {run.demand ?? '—'} · Confirmed served: {run.validated ? run.served ?? '—' : '—'} · Confirmed Journey Time: {run.validated ? run.journeyTime?.toLocaleString() ?? '—' : '—'}</p><p>Lower bound: {run.globalLowerBound?.toLocaleString() ?? '—'} · Gap: {run.validated && run.journeyTime != null && run.journeyTime > 0 && run.globalLowerBound != null ? `${(100*Math.max(0,run.journeyTime-run.globalLowerBound)/run.journeyTime).toFixed(2)}%` : '—'}</p></section><ThesisRunDetail run={run} comparison={comparison}/></>:<p>Loading Journey run…</p>}</main>;
}
