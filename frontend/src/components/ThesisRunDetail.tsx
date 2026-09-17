import { useEffect, useRef, useState } from "react";
import type { ThesisRunSummary } from "../thesisTypes";

type Point = { seconds: number; value: number | null; kind: "native" | "bound" | "validated" };
type Detail = { referenceProbes?: { demand: number; outcome: string; solver_status: string | null; elapsed_seconds: number }[]; schema: string; points: Point[]; diagnostics: Record<string, number>[]; replays: { label: string; file: string }[]; artifacts: string[] };
type Visit = { cabin: number; index: number; station: string; start: number; end: number; arrival: number | null; boarding: number | null; stop: boolean; waiting: number; boarded: number | null; alighted: number | null; load: number | null };
type Replay = { visits: Visit[]; end: number; loadsAvailable: boolean; horizon: number };

function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a"); link.href = url; link.download = name; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function readJson<T>(url: string): Promise<T> {
  const response = await fetch(`${url}?t=${Date.now()}`, { cache: "no-store" });
  if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) throw new Error(`Data unavailable (${response.status}); expected JSON`);
  return response.json() as Promise<T>;
}

export default function ThesisRunDetail({ run, comparison }: { run: ThesisRunSummary; comparison?: ThesisRunSummary }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [notice, setNotice] = useState("");
  const [replayIndex, setReplayIndex] = useState(0);
  const [replay, setReplay] = useState<Replay | null>(null);
  const [baseline, setBaseline] = useState<Replay | null>(null);
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [cabin, setCabin] = useState(0);
  const svg = useRef<SVGSVGElement>(null);
  const base = run.detail?.replace(/[^/]+$/, "");
  useEffect(() => {
    let cancelled = false; let timer: number;
    setDetail(null); setReplay(null); setBaseline(null); setReplayIndex(0); setPlaying(false); setCursor(0);
    async function poll() {
      if (!run.detail) return;
      try {
        const value = await readJson<Detail>(run.detail);
        if (value.schema !== "thesis_run_detail_v1") throw new Error("Unsupported detail schema");
        if (!cancelled) { setDetail(value); setNotice(""); }
      } catch (error) { if (!cancelled) setNotice(String(error)); }
      if (!cancelled && run.status === "running") timer = window.setTimeout(poll, 3000);
    }
    void poll(); return () => { cancelled = true; window.clearTimeout(timer); };
  }, [run.id, run.detail, run.status]);
  useEffect(() => {
    let cancelled = false;
    const item = detail?.replays[replayIndex];
    if (item && base) void readJson<Replay>(base + item.file).then(value => {
      if (!cancelled) { setReplay(value); setCabin(previous => value.visits.some(v => v.cabin === previous) ? previous : value.visits[0]?.cabin ?? 0); }
    }).catch(error => { if (!cancelled) setNotice(String(error)); });
    return () => { cancelled = true; };
  }, [detail, replayIndex, base]);
  useEffect(() => {
    let cancelled = false; setBaseline(null);
    if (comparison?.detail) void readJson<Detail>(comparison.detail).then(async value => {
      const last = value.replays.at(-1);
      if (last) { const plan = await readJson<Replay>(comparison.detail!.replace(/[^/]+$/, "") + last.file); if (!cancelled) setBaseline(plan); }
    }).catch(error => { if (!cancelled) setNotice(String(error)); });
    return () => { cancelled = true; };
  }, [comparison?.id, comparison?.detail]);
  const end = Math.max(replay?.end ?? 0, baseline?.end ?? 0);
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => setCursor(t => Math.min(end, t + 5)), 100);
    return () => window.clearInterval(timer);
  }, [playing, end]);
  useEffect(() => { if (playing && cursor >= end) setPlaying(false); }, [playing, cursor, end]);
  const points = (detail?.points ?? []).filter(p => p.value != null && Number.isFinite(p.value));
  const xmax = Math.max(1, run.elapsedSeconds ?? 0, ...points.map(p => p.seconds));
  const ymax = Math.max(1, ...points.map(p => p.value!));
  const color = { validated: "#157f69", native: "#64748b", bound: "#c76c17" };
  const path = (kind: Point["kind"]) => points.filter(p => p.kind === kind).sort((a, b) => a.seconds - b.seconds).map((p, i) => `${i ? "H" : "M"}${60 + p.seconds / xmax * 760}${i ? "V" : ","}${260 - p.value! / ymax * 220}`).join(" ");
  const diagnostics = detail?.diagnostics.at(-1);
  return <section className="thesis-detail" aria-label="Selected optimization run">
    <p className="eyebrow">Run detail · {run.status}</p>
    <h2>{run.method.replaceAll("_", " ")} · K={run.k} · {run.method === "all_stop_phase" ? `search ceiling N≤${run.demand}` : `N=${run.demand}`}</h2>
    <p>{run.releaseResolutionSeconds} s releases · seed {run.seed} · {run.primalSeedKind ? `start: ${run.primalSeedKind}` : "no imported start"}</p>
    <p>{run.provenance === "main_study" ? "Main study" : "Calibration / regression"}{run.stopReason ? ` · stopped: ${run.stopReason}` : ""}{run.cumulativeSeconds != null ? ` · cumulative stage time ${run.cumulativeSeconds.toFixed(1)} s` : ""}</p>
    {run.supervisedWallSeconds != null && <p>Total process wall time: {run.supervisedWallSeconds.toFixed(2)} s · peak process-tree RSS: {run.peakRssBytes == null ? "unavailable" : `${(run.peakRssBytes / 1024 ** 3).toFixed(2)} GiB`}</p>}
    {run.parentRunId && <p>Parent run: {run.parentRunId} · {run.transferKind ?? "documented transfer"}</p>}
    {notice && <p role="status">{notice} · Last available data is retained.</p>}
    {run.method !== "all_stop_phase" && <><svg ref={svg} viewBox="0 0 880 310" role="img" aria-label="Optimization progress over elapsed seconds">
      <rect width="880" height="310" fill="#fafcfb" />
      <path d="M60 30V260H820" fill="none" stroke="#cbd5da" />
      <text x="60" y="20">{run.method === "evolution" ? "validated passengers served" : "passenger-seconds"}</text>
      <text x="60" y="283">0 s</text><text x="760" y="283">{xmax.toFixed(1)} s</text>
      <text x="5" y="45">{ymax.toFixed(0)}</text>
      {(["native", "bound", "validated"] as const).map(kind => <g key={kind}><path d={path(kind)} stroke={color[kind]} fill="none" strokeWidth="2" />{points.filter(p => p.kind === kind).map((p, i) => <circle key={i} cx={60 + p.seconds / xmax * 760} cy={260 - p.value! / ymax * 220} r="3" fill={color[kind]} />)}</g>)}
    </svg>
    <p>Green: independently validated. Gray: native incumbent, not yet independently checked. Orange: global bound where available.</p>
    </>}
    {run.method === "all_stop_phase" && <>
      <p>Confirmed full-service demand: {run.reference?.provenFeasibleDemand ?? "unavailable"}. Proven infeasible demand: {run.reference?.provenInfeasibleDemand ?? "not yet established"}. {run.reference?.capacityProven ? "Adjacent demands establish the reference capacity." : "The reference capacity remains open."}</p>
      <table><thead><tr><th>Demand</th><th>Outcome</th><th>Solver status</th><th>Elapsed s</th></tr></thead><tbody>{detail?.referenceProbes?.map((probe, i) => <tr key={i}><td>{probe.demand}</td><td>{probe.outcome}</td><td>{probe.solver_status ?? "unavailable"}</td><td>{probe.elapsed_seconds?.toFixed(2)}</td></tr>)}</tbody></table>
    </>}
    <p>Bound scope: {run.boundScope ?? "No global bound"}. {run.method === "evolution" && "Evolution has no global optimality gap."}</p>
    {diagnostics && <p>Evaluations: {diagnostics.evaluations_total} · feasible: {diagnostics.feasible_total} · latest window feasible: {diagnostics.window_feasible_ratio == null ? "unavailable" : `${(diagnostics.window_feasible_ratio * 100).toFixed(1)}%`}</p>}
    <div className="thesis-detail__actions">
      {run.method === "all_stop_phase" ? <button onClick={() => download(`${run.id}.csv`, "demand,outcome,solver_status,elapsed_seconds\n" + (detail?.referenceProbes ?? []).map(p => `${p.demand},${p.outcome},${p.solver_status ?? ""},${p.elapsed_seconds}`).join("\n"), "text/csv")}>Download probes CSV</button> : <><button onClick={() => download(`${run.id}.csv`, "seconds,value,kind\n" + points.map(p => `${p.seconds},${p.value},${p.kind}`).join("\n"), "text/csv")}>Download curve CSV</button>
      <button onClick={() => svg.current && download(`${run.id}.svg`, new XMLSerializer().serializeToString(svg.current), "image/svg+xml")}>Download figure SVG</button></>}
      <button onClick={() => window.print()}>Print / save PDF</button>
      {base && detail?.artifacts.filter(file => ["case_spec.json", "best.json", "result.json", "source_identity.json", "failure.json"].includes(file)).map(file => <a key={file} href={base + file} download>{file}</a>)}
    </div>
    {!!detail?.replays.length && <>
      <h3>Timetable replay</h3>
      <label>Validated plan <select value={replayIndex} onChange={e => { setReplayIndex(Number(e.target.value)); setPlaying(false); }}>{detail.replays.map((item, i) => <option key={item.file} value={i}>{item.label}</option>)}</select></label>
      <p>Exact visit, boarding and alighting times. Historical plans without stored passenger assignments show occupancy as unavailable.</p>
      <div className="thesis-detail__actions"><button onClick={() => setPlaying(!playing)}>{playing ? "Pause" : "Play at 50×"}</button><button onClick={() => { setCursor(0); setPlaying(false); }}>Reset</button>
        <label>Cabin <select value={cabin} onChange={e => setCabin(Number(e.target.value))}>{[...new Set(replay?.visits.map(v => v.cabin))].map(k => <option key={k}>{k}</option>)}</select></label><strong>{cursor.toFixed(1)} s</strong></div>
      <input aria-label="Replay time" type="range" min="0" max={end} step="0.1" value={cursor} onChange={e => { setCursor(Number(e.target.value)); setPlaying(false); }} />
      {replay && <Timetable replay={replay} time={cursor} cabin={cabin} label="Selected plan" />}
      {baseline ? <Timetable replay={baseline} time={cursor} cabin={cabin} label="All-Stop · same K, demand, resolution and operation" /> : <p>No matching All-Stop timetable in this package. A different demand or fleet is not substituted.</p>}
    </>}
  </section>;
}

function Timetable({ replay, time, cabin, label }: { replay: Replay; time: number; cabin: number; label: string }) {
  const visits = replay.visits.filter(v => v.cabin === cabin);
  const current = visits.find(v => v.start <= time && time < v.end);
  const prev = current ? visits.find(v => v.index === current.index - 1)?.load ?? 0 : 0;
  const load = !current || !replay.loadsAvailable ? null : current.boarding != null && time >= current.boarding ? current.load : current.arrival != null && time >= current.arrival ? prev - (current.alighted ?? 0) : prev;
  return <div className="thesis-timetable"><h4>{label}</h4>
    <svg viewBox="0 0 880 90" role="img" aria-label={`${label} cabin ${cabin} timetable`}>
      {visits.map(v => <g key={v.index}><rect x={40 + v.start / replay.end * 790} y="20" width={Math.max(1, (v.end - v.start) / replay.end * 790)} height="25" fill={v.stop ? "#157f69" : "#cbd5da"} stroke="#fafcfb"><title>{v.station} {v.stop ? "STOP" : "SKIP"}: {v.start.toFixed(3)}–{v.end.toFixed(3)} s</title></rect></g>)}
      <line x1={40 + Math.min(time, replay.end) / replay.end * 790} x2={40 + Math.min(time, replay.end) / replay.end * 790} y1="8" y2="58" stroke="#c76c17" strokeWidth="2" /><text x="40" y="80">0 s · green STOP · gray SKIP</text><text x="720" y="80">{replay.end.toFixed(1)} s</text>
    </svg>
    <p>{current ? `${current.station} · ${current.stop ? "STOP" : "SKIP"} · visit ${current.index} · occupancy ${load ?? "unavailable"}` : time < (visits[0]?.start ?? 0) ? "Before dispatch / first recorded movement" : "Recorded trajectory completed"}</p>
    {current && <p>Arrival: {current.arrival?.toFixed(6) ?? "—"} s · boarding: {current.boarding?.toFixed(6) ?? "—"} s · boards {current.boarded ?? "—"} / alights {current.alighted ?? "—"} · waiting {current.waiting} s</p>}
  </div>;
}
