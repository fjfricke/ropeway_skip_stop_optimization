import { useState } from 'react';
import './greedy-progress.css';

export type BoundPoint = { seconds: number; ub: number | null; lb: number | null; gap_percent: number | null };
export type Iteration = {
  id: string; k: number; attempt: number; objective: string; status: string; accepted: boolean;
  points: BoundPoint[]; elapsed_seconds: number; construction_start_seconds?: number;
  ub: number | null; lb: number | null; gap_percent: number | null;
  first_solution_seconds: number | null; last_improvement_seconds: number | null;
  summary?: { preparation_seconds?: number; model_build_seconds?: number; search_seconds?: number; validation_seconds?: number; passenger_seconds?: number; model_stats?: { shared_variables?: number; shared_constraints?: number } } | null;
};
export type GreedyProgressData = { iterations: Iteration[] };
export type AllStopReference = { served: number; journey_time_tick: number; used_fleet: number; source: string; optimality_proven: boolean };
type Run = {
  label: string; status: string; objective?: string; elapsed_seconds?: number; updated_unix: number;
  progress?: GreedyProgressData; all_stop_reference?: AllStopReference | null;
  incumbents: { fleet_size: number; served: number; journey_time_tick?: number }[];
};
export type XY = { x: number; y: number | null };
export type Series = { name: string; color: string; points: XY[]; dashed?: boolean; step?: boolean };
export const progressColors = ['#215caa', '#b85e12', '#178372', '#8b4bad', '#6a7715', '#ae465c'];
const fmt = (x: number | null | undefined, digits = 1) => x == null ? '—' : x.toLocaleString('de-DE', { maximumFractionDigits: digits });

export function Curve({ series, xLabel, yLabel, xMax, zero = true }: { series: Series[]; xLabel: string; yLabel: string; xMax?: number; zero?: boolean }) {
  const [hover, setHover] = useState<{ series: string; point: XY } | null>(null);
  const points = series.flatMap(s => s.points).filter(p => p.y != null && Number.isFinite(p.y));
  if (!points.length) return <div className="greedy-empty">Noch keine Messwerte. Eine Schranke oder gültige Lösung erscheint hier, sobald sie vorliegt.</div>;
  const maxX = Math.max(1, xMax ?? 0, ...points.map(p => p.x));
  const low = zero ? 0 : Math.min(...points.map(p => p.y!));
  const high = Math.max(low + 1, ...points.map(p => p.y!));
  const pad = zero ? 0 : (high-low)*0.08;
  const minY = low >= 0 ? Math.max(0, low-pad) : low-pad, maxY = high + (high-low)*0.06;
  const tickX = (i: number) => xLabel === 'Kabinen K' ? Math.round(maxX*i/4) : maxX*i/4;
  const sx = (v: number) => 82 + v/maxX*510;
  const sy = (v: number) => 215 - (v-minY)/(maxY-minY)*177;
  const path = (s: Series) => {
    let prior: XY | null = null;
    return s.points.map(p => {
      if (p.y == null) { prior = null; return ''; }
      const d = prior == null ? `M${sx(p.x)},${sy(p.y)}` : s.step ? `H${sx(p.x)}V${sy(p.y)}` : `L${sx(p.x)},${sy(p.y)}`;
      prior = p; return d;
    }).join(' ');
  };
  return <figure className="greedy-chart">
    <svg viewBox="0 0 625 260" role="img" aria-label={`${yLabel} über ${xLabel}`}>
      {[0, 1, 2, 3, 4].map(i => {
        const y = minY+(maxY-minY)*i/4;
        return <g key={i}><line x1="82" x2="592" y1={sy(y)} y2={sy(y)} className="greedy-gridline"/><text x="74" y={sy(y)+4} textAnchor="end">{fmt(y, high > 100 ? 0 : 1)}</text><text x={sx(tickX(i))} y="235" textAnchor="middle">{fmt(tickX(i))}</text></g>;
      })}
      <text x="82" y="19" className="greedy-axis-title">{yLabel}</text><text x="592" y="254" textAnchor="end">{xLabel}</text>
      {series.map(s => <g key={s.name}><path d={path(s)} fill="none" stroke={s.color} strokeWidth="2" strokeDasharray={s.dashed ? '6 5' : undefined}/>{s.points.map((p,i) => p.y == null ? null : <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r={s.dashed ? 0 : 3} fill={s.color} tabIndex={s.dashed ? -1 : 0} onMouseEnter={() => setHover({series:s.name,point:p})} onFocus={() => setHover({series:s.name,point:p})}><title>{s.name}: {xLabel} {fmt(p.x,3)}, {yLabel} {fmt(p.y,3)}</title></circle>)}</g>)}
    </svg>
    <figcaption>{series.map(s => <span key={s.name}><i style={{borderColor:s.color, borderTopStyle:s.dashed ? 'dashed' : 'solid'}}/>{s.name}</span>)}</figcaption>
    <output className="greedy-hover">{hover ? `${hover.series} · ${xLabel}: ${fmt(hover.point.x,3)} · ${yLabel}: ${fmt(hover.point.y,3)}` : 'Messpunkte berühren oder mit Tab auswählen, um genaue Werte zu sehen.'}</output>
  </figure>;
}

export default function GreedyProgressPanel({ runs }: { runs: Record<string, Run> }) {
  const entries = Object.entries(runs);
  const [runId, setRunId] = useState('');
  const [iterationId, setIterationId] = useState('');
  const [follow, setFollow] = useState(true);
  const activeId = runs[runId] ? runId : entries.find(([,r]) => r.status==='running')?.[0] ?? entries[0]?.[0];
  const run = runs[activeId];
  if (!run) return null;
  const iterations = run.progress?.iterations ?? [];
  const iteration = follow ? iterations.at(-1) : iterations.find(i => i.id===iterationId) ?? iterations.at(-1);
  const isJourney = iteration?.objective==='journey_time';
  const divisor = isJourney ? 1e6 : 1;
  const duration = iteration?.elapsed_seconds ?? 0;
  const elapsed = run.status==='running' && iteration && ['building','solving'].includes(iteration.status) ? Math.max(duration, (run.elapsed_seconds ?? 0) + Math.max(0,Date.now()/1000-run.updated_unix) - (iteration.construction_start_seconds ?? 0)) : duration;
  const boundPoints = iteration?.points ?? [];
  const boundSeries: Series[] = [
    {name:'UB · gültige Lösung',color:progressColors[0],step:true,points:boundPoints.map(p => ({x:p.seconds,y:p.ub == null ? null : p.ub/divisor}))},
    {name:'LB · Solver-Schranke',color:progressColors[2],step:true,points:boundPoints.map(p => ({x:p.seconds,y:p.lb == null ? null : p.lb/divisor}))},
  ];
  for (const s of boundSeries) if (s.points.length) s.points.push({...s.points.at(-1)!,x:Math.max(elapsed,s.points.at(-1)!.x)});
  const gaps: XY[] = boundPoints.map(p => ({x:p.seconds,y:p.gap_percent}));
  if (gaps.length) gaps.push({...gaps.at(-1)!,x:Math.max(elapsed,gaps.at(-1)!.x)});
  const references = entries.map(([,r]) => r.all_stop_reference).filter((r): r is AllStopReference => r != null);
  const reference = references[0];
  const sameReference = !!reference && references.length===entries.length && references.every(r => r.served===reference.served && r.journey_time_tick===reference.journey_time_tick && r.used_fleet===reference.used_fleet);
  const maxK = Math.max(1, sameReference ? reference.used_fleet : 0, ...entries.flatMap(([,r]) => r.incumbents.map(p => p.fleet_size)));
  const fleetSeries = (cost: boolean): Series[] => {
    const s: Series[] = entries.map(([id,r],i) => ({name:r.label || id,color:progressColors[i%progressColors.length],points:r.incumbents.map(p => ({x:p.fleet_size,y:cost ? p.journey_time_tick == null ? null : p.journey_time_tick/1e6 : p.served}))}));
    if (sameReference) s.push({name:`All-Stop · K=${reference.used_fleet}`,color:'#777e89',dashed:true,points:[{x:0,y:cost ? reference.journey_time_tick/1e6 : reference.served},{x:maxK,y:cost ? reference.journey_time_tick/1e6 : reference.served}]});
    return s;
  };
  const summary = iteration?.summary;
  return <div className="greedy-dashboard">
    <section className="optimization-panel">
      <div className="panel-heading"><div><p className="eyebrow">Aufbau der Flotte</p><h2>Was bringt jede weitere Kabine?</h2></div><span>Unabhängig validierte, übernommene Fahrpläne</span></div>
      <div className="greedy-two-charts"><Curve series={fleetSeries(false)} xMax={maxK} xLabel="Kabinen K" yLabel="Bediente Personen"/><Curve series={fleetSeries(true)} xMax={maxK} xLabel="Kabinen K" yLabel="Journey-Time-Kosten · Personen-s"/></div>
      <p className="greedy-note">Zeitkosten enthalten Warten und Fahrt sowie die Restzeit bis zum Bedienungsende für unbediente Personen. Weniger ist besser. {sameReference ? <>Gestrichelt: geprüfter All-Stop-Fahrplan mit <strong>{reference.used_fleet} Kabinen</strong>, {fmt(reference.served,0)} bedienten Personen und {fmt(reference.journey_time_tick/1e6)} Personen-s. Kein Referenzoptimum je K; die gespeicherte Passagierzuordnung wurde nicht nachträglich für Journey Time optimiert.</> : 'Eine gemeinsame geprüfte All-Stop-Referenz ist für diese Auswahl nicht verfügbar.'}</p>
    </section>
    <section className="optimization-panel">
      <div className="panel-heading"><div><p className="eyebrow">Einzelner Solveraufruf</p><h2>Einfügung im Detail</h2></div><span>{run.status==='running' ? 'Live · automatische Aktualisierung' : 'Gespeicherter Verlauf'}</span></div>
      <div className="greedy-controls">
        <label>Lauf<select aria-label="Lauf" value={activeId} onChange={e => {setRunId(e.target.value);setIterationId('');}}>{entries.map(([id,r]) => <option key={id} value={id}>{r.label}</option>)}</select></label>
        <label>Einfügung<select aria-label="Einfügung" value={iteration?.id ?? ''} onChange={e => {setIterationId(e.target.value);setFollow(false);}}>{iterations.map(i => <option key={i.id} value={i.id}>K={i.k} · Versuch {i.attempt+1} · {i.status}</option>)}</select></label>
        <label className="greedy-follow"><input type="checkbox" checked={follow} onChange={e => setFollow(e.target.checked)}/>Neueste Einfügung verfolgen</label>
      </div>
      {!iteration ? <p className="greedy-empty">Noch kein Einfügeversuch gespeichert. Ältere Läufe lassen sich aus events.jsonl und result.json importieren.</p> : <>
        <dl className="greedy-facts">
          <div><dt>Status</dt><dd>{iteration.status}{iteration.accepted ? ' · übernommen' : ''}</dd></div>
          <div><dt>UB</dt><dd>{fmt(iteration.ub == null ? null : iteration.ub/divisor)}</dd></div>
          <div><dt>LB</dt><dd>{fmt(iteration.lb == null ? null : iteration.lb/divisor)}</dd></div>
          <div><dt>Gap</dt><dd>{fmt(iteration.gap_percent,2)}{iteration.gap_percent != null ? ' %' : ''}</dd></div>
          <div><dt>Erste Lösung</dt><dd>{fmt(iteration.first_solution_seconds,2)} s</dd></div>
          <div><dt>Letzte Verbesserung</dt><dd>{fmt(iteration.last_improvement_seconds,2)} s</dd></div>
        </dl>
        <div className="greedy-two-charts"><Curve key={`${activeId}:${iteration.id}:bounds`} series={boundSeries} xMax={elapsed} xLabel="Sekunden seit Einfügebeginn" yLabel={isJourney ? 'Journey-Time-Kosten · Personen-s' : 'Unbediente Personen'} zero={false}/><Curve key={`${activeId}:${iteration.id}:gap`} series={[{name:'Relativer Gap',color:progressColors[3],step:true,points:gaps}]} xMax={elapsed} xLabel="Sekunden seit Einfügebeginn" yLabel="Gap · %"/></div>
        <p className="greedy-note">Schranken gelten nur für die vorhandenen festen Trajektorien plus eine neue Kabine. Gap = (UB − LB) / |UB|. Ein kleiner relativer Gap bedeutet nicht, dass der mögliche Gewinn dieser Einfügung fast ausgeschöpft ist. Fehlende Werte bleiben offen; horizontale Abschnitte führen den letzten gemeldeten Wert fort.</p>
        <div className="greedy-timings"><span>Vorbereitung <strong>{fmt(summary?.preparation_seconds,3)} s</strong></span><span>Modellbau <strong>{fmt(summary?.model_build_seconds,3)} s</strong></span><span>Solveraufruf <strong>{fmt(summary?.search_seconds,3)} s</strong></span><span>Validierung <strong>{fmt(summary?.validation_seconds,3)} s</strong></span><span>Variablen / Zeilen <strong>{fmt(summary?.model_stats?.shared_variables,0)} / {fmt(summary?.model_stats?.shared_constraints,0)}</strong></span></div>
        <p className="greedy-note">Zeitanteile werden nach Abschluss ergänzt. Validierung in Solver-Callbacks ist bereits in der Solverlaufzeit enthalten.</p>
      </>}
      {iterations.length > 0 && <details className="greedy-history"><summary>Alle {iterations.length} Einfügeversuche ansehen</summary><div className="greedy-table-wrap"><table><thead><tr><th>Einfügung</th><th>Status</th><th>UB</th><th>LB</th><th>Gap</th><th>Dauer</th></tr></thead><tbody>{iterations.map(i => <tr key={i.id} className={i.id===iteration?.id ? 'selected' : ''}><td><button onClick={() => {setIterationId(i.id);setFollow(false);}}>K={i.k} · Versuch {i.attempt+1}</button></td><td>{i.status}{i.accepted ? ' ✓' : ''}</td><td>{fmt(i.ub == null ? null : i.ub/(i.objective==='journey_time' ? 1e6 : 1))}</td><td>{fmt(i.lb == null ? null : i.lb/(i.objective==='journey_time' ? 1e6 : 1))}</td><td>{fmt(i.gap_percent,2)} %</td><td>{fmt(i.elapsed_seconds,2)} s</td></tr>)}</tbody></table></div></details>}
    </section>
  </div>;
}
