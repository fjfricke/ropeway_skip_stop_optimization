/** Check every published best timetable without starting any optimizer. */
import { readFileSync, existsSync, writeFileSync } from 'node:fs';
import { certifyReplaySafety } from '../src/safety';
import { layoutForScenario } from '../src/scenarioLayout';
import { eanCabinMarkersAtTime, groupEventsByCabin } from '../src/components/EanReplayView';
const root='public/generated';
const read=(path:string)=>JSON.parse(readFileSync(path,'utf8'));
const catalog=read(`${root}/study/index.json`);
const outcomes=[];
const seen=new Set<string>();
for(const execution of catalog.executions){
 for(const run of execution.runs){
  if(!run.replay_url || seen.has(run.id))continue;
  seen.add(run.id);
  const path=`${root}/study/runs/${run.id}`;
  const scenario=read(`${path}/scenario.json`), movement=read(`${path}/ean_result.json`), replay=read(`${path}/ean_replay.json`), service=read(`${path}/milp_result.json`);
  const report=certifyReplaySafety({scenario,artifact:read(`${path}/ean_input.json`),movementPlan:movement,fleetPlan:service.fleet_plan,replay});
  const layout=layoutForScenario(scenario), events=groupEventsByCabin(replay.events);
  const counts=[0,15,1464,2364,2664].map(t=>eanCabinMarkersAtTime(scenario,layout,events,t,new Map()).length);
  const viewer=read(`${path}/viewer.json`);
  const links=Object.values(viewer.families[0].variants[0].artifact_sets[0].artifacts) as string[];
  const missing=links.filter(link=>!existsSync(`public${link}`));
  outcomes.push({id:run.id,source_stamp:read(`${path}/receipt.json`).stamp,status:report.status,violations:report.totalViolationCount,violation_details:report.violations,diagnostics:report.diagnostics,counts,expected:movement.trajectories.length,missing});
 }
 console.log(`${execution.id}: checked ${outcomes.filter(x=>x.id.startsWith(execution.id)).length} replays`);
}
writeFileSync(`${root}/study/replay-audit.json`,JSON.stringify(outcomes,null,2));
const failures=outcomes.filter(x=>x.status!=='safe'||x.missing.length||x.counts.some(n=>n!==x.expected));
console.log(JSON.stringify({checked:outcomes.length,failed:failures.length,failures}));
process.exitCode=failures.length?1:0;
