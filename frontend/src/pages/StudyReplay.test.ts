// @ts-expect-error Node built-ins are supplied by Vitest, outside the browser tsconfig.
import { existsSync, readFileSync } from 'node:fs';
import { expect,it } from 'vitest';
import { layoutForScenario } from '../scenarioLayout';
import { eanCabinMarkersAtTime, groupEventsByCabin, buildEanPassengerState } from '../components/EanReplayView';
import { certifyReplaySafety } from '../safety';
const examples=[
 ['thesis_journey_geometric_20260919__relative_25_f0_k10_skip_stop__a1',10],
 ['oip_fixed_mixes_geometric_120_20260918__f2_mix_0_31_31_k62__a1',62],
 ['oip_fixed_mixes_geometric_k50_20260919__f2_mix_0_25_25_k50__a1',50],
] as const;
for(const [id,count] of examples){
 const base=`public/generated/study/runs/${id}`;
 it.skipIf(!existsSync(`${base}/viewer.json`))(`replays ${count} cabins at zero and during operation`,()=>{
 const read=(name:string)=>JSON.parse(readFileSync(`${base}/${name}.json`,'utf8'));
 const scenario=read('scenario'), replay=read('ean_replay'), movement=read('ean_result'), service=read('milp_result');
 const layout=layoutForScenario(scenario), events=groupEventsByCabin(replay.events);
 for(const time of [0,.001,15,730,1464,2364,2664]){
 const passengers=buildEanPassengerState(scenario,service.passenger_plan,time,1e-5);
 const markers=eanCabinMarkersAtTime(scenario,layout,events,time,passengers.cabinLoadsById);
 expect(markers).toHaveLength(count);
 expect(markers.every(m=>Number.isFinite(m.x)&&Number.isFinite(m.y))).toBe(true);
 }
 const report=certifyReplaySafety({scenario,artifact:read('ean_input'),movementPlan:movement,fleetPlan:service.fleet_plan,replay});
 expect(report.diagnostics).not.toContain('EAN build artifact is missing');
 expect(report.status, JSON.stringify(report.diagnostics)).toBe('safe');
 });
}
