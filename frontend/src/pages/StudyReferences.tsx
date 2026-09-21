import CalibrationLivePage from "./CalibrationLivePage";
import { AppLink } from '../App';
import { useStudyCatalog } from '../thesisStudy';
export default function StudyReferences(){
 const {catalog,error}=useStudyCatalog();const selected=new URLSearchParams(window.location.search).get('campaign');
 const source=new URLSearchParams(window.location.search).get('source');
 if(source && catalog?.calibration_runs?.some(c=>c.id===source)) return <><p><AppLink href="/calibration-live">← All references</AppLink></p><CalibrationLivePage dataRoot={`/generated/study/calibrations/${encodeURIComponent(source)}`} /><p><a href={`/generated/study/calibrations/${encodeURIComponent(source)}/history.json`}>Complete saved probe history</a></p></>;
 return <main className="optimization-shell"><header className="optimization-hero"><div><p className="eyebrow">Evidence used in the thesis</p><h1>Calibrations & references</h1></div></header>
 <p>Capacity calibration establishes the largest fully served demand. OIP reference evaluations maximize served at the experiment demand with an evenly spaced fleet and a free common phase. They do not optimize individual initial positions.</p>
 {error&&<p role="alert">{error}</p>}
 {!selected&&catalog?.calibration_runs?.map(c=><section className="optimization-panel" key={c.id}><h2>{c.label}</h2><p>{c.id} · {c.status}</p><AppLink href={c.url}>Open calibration progress →</AppLink></section>)}
 {selected&&<AppLink href="/calibration-live">Show all sources</AppLink>}
 {catalog?.executions.filter(e=>!selected||e.id===selected).map(e=><section className="optimization-panel" key={e.id}><h2>{e.label} · {e.original?'Thesis execution':e.id}</h2><AppLink href={e.url}>Open campaign →</AppLink>
 {e.capacity_evidence&&<><h3>CAL-O · regular fleet, free common phase · K62</h3><table className="pattern-screening__table"><thead><tr><th>Family</th><th>Proven Nmax</th><th>Excluded N</th><th>120% experiment demand</th></tr></thead><tbody>{e.capacity_evidence.map(c=><tr key={c.family}><td>{c.family.toUpperCase()}</td><td>{c.capacity}</td><td>{c.excluded}</td><td>{c.load}</td></tr>)}</tbody></table><p>Geometric headways: the documented All-Stop equivalence preserves these capacity proofs. K50 uses the same absolute demands, not a new K50 calibration.</p></>}
 {e.calibration_source_url&&<p><a href={e.calibration_source_url}>CAL-O capacity provenance and geometric-contract adoption evidence</a></p>}
 <table className="pattern-screening__table"><thead><tr><th>Reference</th><th>K</th><th>Scope</th><th>Progress / result</th><th>Timetable</th></tr></thead><tbody>{e.calibrations.map(r=><tr key={r.id}><td>{r.label}</td><td>{r.k}</td><td>{r.scope==='fixed_start_capacity'?'Fixed-start All-Stop capacity':'Regular All-Stop · experiment demand'}</td><td>{r.detail_url&&<AppLink href={r.detail_url}>Open evidence →</AppLink>}</td><td>{r.replay_url?<AppLink href={r.replay_url}>Play →</AppLink>:'—'}</td></tr>)}</tbody></table>
 </section>)}</main>;
}
