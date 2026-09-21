import { useEffect, useState } from 'react';
export type StudyRun = { contract_note?: string; id: string; run_id: string; legacy_id: string; attempt: number; replay_stamp?:string; status: string; latest: boolean; family?: string; k?: number; detail_url: string | null; replay_url: string | null; label?: string; served?: number; capacity?: number; scope?: string };
export type StudyExecution = { id: string; series: string; label: string; status: string; original: boolean; url: string; runs: StudyRun[]; calibrations: StudyRun[]; capacity_evidence?: {family:string;capacity:number;excluded:number;load:number;proof:string}[]; calibration_source_url?: string };
export type StudyCatalog = { replay_audit?: {id:string;status:string;source_stamp:string;violations:number}[]; calibration_runs?: {id:string;label:string;status:string;url:string;history_url:string}[]; series: {id:string;label:string}[]; executions: StudyExecution[] };
export function useStudyCatalog() {
  const [catalog,setCatalog]=useState<StudyCatalog|null>(null);
  const [error,setError]=useState<string|null>(null);
  useEffect(()=>{let stop=false;let timer:number;
    async function poll(){try{
      const response=await fetch(`/generated/study/index.json?t=${Date.now()}`,{cache:'no-store'});
      if(!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Thesis catalogue unavailable. Run the documented frontend export.');
      const data=await response.json() as StudyCatalog;
      try { const audit=await fetch("/generated/study/replay-audit.json",{cache:"no-store"}); if(audit.ok&&audit.headers.get("content-type")?.includes("application/json")) data.replay_audit=await audit.json(); } catch { /* Audit is optional for a new execution. */ }
      if(!stop){setCatalog(data);setError(null);timer=window.setTimeout(poll,data.executions.some(e=>e.status==='running')?2000:15000);}
    }catch(e){if(!stop){setError(String(e));timer=window.setTimeout(poll,5000);}}}
    poll();return()=>{stop=true;window.clearTimeout(timer);};
  },[]);return {catalog,error};
}
