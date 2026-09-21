import { AppLink } from '../App';
import { useStudyCatalog } from '../thesisStudy';
export default function StudyOverview(){
 const {catalog,error}=useStudyCatalog();
 return <main className="optimization-shell"><header className="optimization-hero"><div><p className="eyebrow">Thesis experiments</p><h1>Three experiment series</h1></div><p>Results, solver progress and the best validated timetable.</p></header>
 {error&&<p role="alert">{error}</p>}
 {!catalog&&!error&&<p>Loading campaigns…</p>}
 <section className="campaign-grid">{catalog?.series.map(series=>{
 const executions=catalog.executions.filter(e=>e.series===series.id).sort((a,b)=>Number(b.original)-Number(a.original)||b.id.localeCompare(a.id));
 const original=executions.find(e=>e.original)??executions[0];
 return <article className="campaign-card" key={series.id}><h2>{series.label}</h2><p>{series.id==='journey'?'Fixed starts · full service · Journey Time':'Free initial positions · No-Wait · maximum served'}</p>
 {original?<><span className={`run-state run-state--${original.status}`}>{original.status}</span><p><AppLink href={original.url}>Open thesis results →</AppLink></p></>:<p>No execution published yet.</p>}
 {executions.length>1&&<details><summary>All executions ({executions.length})</summary><ul>{executions.map(e=><li key={e.id}><AppLink href={e.url}>{e.original?'Thesis execution':e.id}</AppLink> · {e.status}</li>)}</ul></details>}
 </article>;})}</section>
 <section className="optimization-panel"><h2>Reproduce the experiments</h2><p>Use the experiment README for installation, frozen matrices, calibration sources, fresh runs and resume.</p><a href="/generated/study/README.md">Read or download the reproduction guide</a></section></main>;
}
