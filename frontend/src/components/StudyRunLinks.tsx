import { AppLink } from '../App';
import { useStudyCatalog } from '../thesisStudy';
export default function StudyRunLinks({id}:{id:string}){
 const {catalog}=useStudyCatalog();
 const execution=catalog?.executions.slice().sort((a,b)=>Number(b.original)-Number(a.original)).find(e=>e.id===id||e.runs.some(r=>r.id===id||r.legacy_id===id));
 const run=execution?.runs.find(r=>r.id===id||r.legacy_id===id);
 const audit=catalog?.replay_audit?.find(a=>a.id===run?.id&&a.source_stamp===run?.replay_stamp);
 if(!execution)return null;
 return <section className="optimization-panel" aria-label="Run navigation">
 {run&&<><AppLink href={execution.url}>← {execution.label}</AppLink>{' · '}{run.replay_url?<AppLink href={run.replay_url}>Play best validated incumbent →</AppLink>:<span>No validated timetable available</span>}
 {execution.runs.filter(r=>r.run_id===run.run_id).length>1&&<details><summary>Attempts</summary><ul>{execution.runs.filter(r=>r.run_id===run.run_id).map(r=><li key={r.id}>{r.detail_url&&<AppLink href={r.detail_url}>Attempt {r.attempt}</AppLink>} · {r.status}</li>)}</ul></details>}</>}
 {!run&&<AppLink href={`/calibration-live?campaign=${encodeURIComponent(execution.id)}`}>Calibration & reference sources →</AppLink>}
 {run?.contract_note&&<p>{run.contract_note}</p>}
 {audit?.status==="unsafe"&&<p role="alert">Additional physical replay check: {audit.violations} conflicts reported. The stored solver certificate is unchanged. Open the replay to inspect the conflicts.</p>}
 </section>;
}
