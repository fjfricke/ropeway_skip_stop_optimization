"""Fixed-dispatch waiting-only probes of frozen NSGA-II proposals."""
from __future__ import annotations
import argparse
from dataclasses import asdict, replace
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time

from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import load_reference
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    validate_reservoir_cp_plan, write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (
    ReservoirLineConfig, ReservoirLineVariant, ReservoirLinePreparation,
    ReservoirLineFormulation, ReservoirLineMode, ReservoirLineCatalogProfile, prepare_line_problem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution import (
    GenomeFactory, decode_no_wait, genome_from_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.waiting_repair import solve_waiting_only_repair

ROOT=Path(__file__).resolve().parents[1]


def select_candidates(campaign, baseline):
    by_genome={}
    for path in sorted(campaign.glob('s[012]_*/events.jsonl')):
        # A concurrent last partial line is ignored. The selected payload is frozen.
        for line in path.read_text().splitlines():
            try: event=json.loads(line)
            except ValueError: continue
            if event.get('kind')!='population': continue
            for member in event['members']:
                potential=member.get('potential')
                if not potential or potential['assigned']<=baseline or member['conflicts']<=0: continue
                by_genome[member['identity']]={**member, 'source_run':path.parent.name,
                    'source_elapsed_seconds':event['elapsed_seconds']}
    values=list(by_genome.values())
    if not values: raise ValueError('no collision-bearing candidates above the validated reference')
    chosen=[]
    criteria=(
        ('near_reference', lambda x:(x['conflicts'],x['overlap_ticks'],-x['potential']['assigned'])),
        ('maximum_potential', lambda x:(-x['potential']['assigned'],x['conflicts'],x['overlap_ticks'])),
        ('complementary_patterns', lambda x:(-(x['pattern_counts'].get('stop_B_D',0)+x['pattern_counts'].get('stop_C_E',0))/x['fleet_size'], x['conflicts'], -x['potential']['assigned'])),
    )
    for name,key in criteria:
        remaining=[x for x in values if x['identity'] not in {y['identity'] for y in chosen}]
        if remaining: chosen.append({**min(remaining,key=key),'name':name})
    return chosen


def with_waiting_release(problem, seconds):
    if seconds is None:
        return problem
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError('earliest waiting time must be finite and nonnegative')
    updated = replace(problem, waiting_policy=replace(problem.waiting_policy,
        earliest_wait_time_seconds=seconds))
    updated.validate()
    return updated


def prepare(problem):
    return prepare_line_problem(problem, ReservoirLineConfig(
        dispatch_window_end_seconds=300, passenger_service_start_seconds=300,
        variant=ReservoirLineVariant.INTERVALS, preparation=ReservoirLinePreparation.ENCODING_SPECIFIC,
        formulation=ReservoirLineFormulation.SHARED_ROUNDS, mode=ReservoirLineMode.EXACT_SERVICE,
        catalog_profile=ReservoirLineCatalogProfile.RELEVANT, maximum_cabins=problem.available_fleet_count))


def worker(args):
    out=args.output;started=time.perf_counter()
    domain,_=load_reference(args.reference);problem=with_waiting_release(domain.problem, args.earliest_wait_seconds)
    prepared=prepare(problem);factory=GenomeFactory(problem,prepared)
    data=json.loads(args.candidate.read_text())
    genome=factory.from_dispatches(data['pattern_ids'], data['dispatch_ticks'])
    movement=decode_no_wait(problem,prepared,genome)
    plan=movement.plan or movement.relaxed_timetable
    if plan is None: raise ValueError(f'candidate could not be decoded: {movement.reason}')
    atomic_json(out/'input.json',{'candidate':data,'physical_fingerprint':problem.fingerprint,
        'source_physical_fingerprint':domain.problem.fingerprint,
        'decoded_conflicts':len(movement.conflicts),'decoded_overlap_ticks':movement.total_overlap_ticks,
        'waiting_policy':asdict(problem.waiting_policy),'fixed_dispatch_ticks':data['dispatch_ticks'],
        'versions':{name:importlib.metadata.version(name) for name in ('ortools','gurobipy')}})
    def emit(event):
        atomic_json(out/'progress.json',event)
        with (out/'events.jsonl').open('a') as stream: stream.write(json.dumps(event)+'\n')
    result=solve_waiting_only_repair(problem,plan,dispatch_end_tick=prepared.dispatch_window_end_tick,
        time_limit_seconds=max(0.001,args.seconds-(time.perf_counter()-started)-2),
        workers=12,seed=0,passenger_seconds=10,event_callback=emit,
        movement_callback=lambda plan:write_reservoir_cp_checkpoint(out/'movement.json',problem,plan),
        checkpoint_callback=lambda plan:write_reservoir_cp_checkpoint(out/'best.json',problem,plan),
        log_path=out/'cp_sat.log')
    final=result.pop('plan');result['plan']=asdict(final) if final is not None else None
    result['runner_wall_seconds']=time.perf_counter()-started
    result['original_potential']=data.get('potential')
    atomic_json(out/'result.json',result)


def summarize(out, baseline):
    manifest=json.loads((out/'campaign.json').read_text());rows=[]
    lines=['# Waiting-Reparatur mit festen Dispatchzeiten','',
        'Alle Kabinen, vollständigen Routenfolgen und Dispatchzeiten bleiben unverändert. '
        'Nur Exit-Waiting wird innerhalb des festgelegten Waiting-Vertrags erlaubt. '
        'Der CP-SAT-Lauf sucht eine erste gültige Bewegung; anschließend wird die ganzzahlige Passagierzuordnung optimiert. '
        'Ein Scheitern gilt nur für diesen festen Kandidaten, diese Rundenzahl und diese Waiting-Regeln.', '',
        f'Gültige No-Wait-All-Stop-Referenz: {baseline} bediente Personen.', '',
        '| Kandidat | K | Vorher: Potenzial | Vorher: Konflikte | Ergebnis | Gültig bedient | Aufbau / Timing (s) |',
        '|---|---:|---:|---:|---|---:|---|']
    for entry in manifest['runs']:
        name=entry['name'];data=json.loads((out/'candidates'/f'{name}.json').read_text())
        path=out/name/'result.json';r=json.loads(path.read_text()) if path.exists() else {}
        metrics=r.get('metrics',{});pot=data.get('potential',{}).get('assigned',baseline if name=='all_stop_control' else None)
        row={'name':name,'fleet':data['fleet_size'],'potential':pot,'conflicts':data.get('conflicts'),
             'status':r.get('status',entry['status']),'served':metrics.get('served'),
             'build_seconds':r.get('build_seconds'),'timing_seconds':r.get('timing_seconds'),
             'total_wait_tick':r.get('total_wait_tick'),'positive_wait_visits':r.get('positive_wait_visits'),
             'supervisor':entry.get('supervisor')}
        rows.append(row)
        lines.append(f"| {name} | {row['fleet']} | {pot} | {row['conflicts']} | {row['status']} | {row['served']} | {row['build_seconds']} / {row['timing_seconds']} |")
    lines+=['','Die Potenzialspalte ist keine gültige Bedienung. OPTIMAL im reinen CP-SAT-Machbarkeitsmodell '
            'ist kein Kapazitätsoptimum. Ein beliebiger erster reparierter Fahrplan muss nicht die beste '
            'Bedienung unter Waiting haben. UNKNOWN und Ressourcenabbrüche sind keine Unzulässigkeitsbeweise.', '',
            '## Grenzen', '',
            f"Positives Waiting ist ab Sekunde {manifest.get('earliest_wait_seconds',300):g} erlaubt; bis zu 1.200 Sekunden je zulässigem STOP, "
            'begrenzt außerdem durch Rückkehr und den unveränderten Lebenszyklus. Die erste vollständige Umlaufrückkehr '
            'am oder nach der Bedienungsdeadline bleibt die letzte. Keine zusätzliche Runde, kein Entfernen einer Kabine, '
            'keine Dispatchverschiebung und keine neuen Muster. Ein INFEASIBLE ist daher kein Ausschluss aller Fahrpläne '
            'derselben Stationsmasken bei anderen Rundenzahlen oder anderen Betriebsregeln.']
    atomic_json(out/'summary.json',rows);(out/'report.md').write_text('\n'.join(lines)+'\n')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-campaign',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repeat-probe',type=Path,help='reuse exactly the previously frozen candidates')
    parser.add_argument('--earliest-wait-seconds',type=float,default=None)
    parser.add_argument('--reference',type=Path)
    parser.add_argument('--candidate',type=Path)
    parser.add_argument('--seconds',type=float,default=120)
    parser.add_argument('--_worker',action='store_true')
    args=parser.parse_args()
    if args._worker:
        worker(args);return
    if not args.source_campaign: parser.error('--source-campaign required')
    if args.seconds<=12: parser.error('--seconds must exceed 12')
    source=args.source_campaign.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    domain,_=load_reference(source/'reference.json');_,control=load_reference(source/'all_stop.json')
    problem=with_waiting_release(domain.problem,args.earliest_wait_seconds)
    baseline=validate_reservoir_cp_plan(problem,control).served
    if args.repeat_probe:
        previous=json.loads((args.repeat_probe/'campaign.json').read_text())
        if Path(previous['source_campaign']).resolve()!=source:
            raise ValueError('repeat probe and source campaign do not match')
        candidates=[json.loads((args.repeat_probe/'candidates'/f'{name}.json').read_text())
                    for name in ('all_stop_control','near_reference','maximum_potential','complementary_patterns')]
    else:
        candidates=select_candidates(source,baseline)
        prep=prepare(problem);g=genome_from_plan(problem,prep,control)
        candidates.insert(0,{'name':'all_stop_control','fleet_size':g.fleet_size,'pattern_ids':g.pattern_ids,
            'dispatch_ticks':g.dispatch_ticks(GenomeFactory(problem,prep).minimum_gap),
            'conflicts':0,'potential':{'assigned':baseline}})
    (out/'candidates').mkdir()
    for c in candidates:
        path=out/'candidates'/f"{c['name']}.json"
        if args.repeat_probe:
            shutil.copy2(args.repeat_probe/'candidates'/path.name,path)
        else:
            atomic_json(path,c)
    frozen=out/'sources';(frozen/'benchmarks').mkdir(parents=True)
    shutil.copytree(ROOT/'src',frozen/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    runner=frozen/'benchmarks'/Path(__file__).name;shutil.copy2(__file__,runner)
    shutil.copy2(source/'reference.json',out/'reference.json')
    for name in ('uv.lock','pyproject.toml'): shutil.copy2(ROOT/name,frozen/name)
    manifest={'state':'waiting_for_nsga2','queued_unix':time.time(),'source_campaign':str(source),'runs':[],
        'baseline_served':baseline,'search_scope':'FIXED_DISPATCH_WAITING_ONLY',
        'repeat_probe':str(args.repeat_probe.resolve()) if args.repeat_probe else None,
        'source_physical_fingerprint':domain.problem.fingerprint,
        'physical_fingerprint':problem.fingerprint,
        'earliest_wait_seconds':problem.waiting_policy.earliest_wait_time_seconds,
        'waiting_policy':asdict(problem.waiting_policy),
        'candidate_hashes':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in (out/'candidates').glob('*.json')},
        'source_hashes':{str(p.relative_to(frozen)):hashlib.sha256(p.read_bytes()).hexdigest() for p in frozen.rglob('*') if p.is_file()}}
    atomic_json(out/'campaign.json',manifest)
    while json.loads((source/'campaign.json').read_text()).get('finished_unix') is None:
        if time.time()-manifest['queued_unix']>3600:
            manifest['state']='WAIT_TIMEOUT';atomic_json(out/'campaign.json',manifest);return
        time.sleep(1)
    started=time.time();deadline=started+60+args.seconds*(len(candidates)-1)+60
    manifest.update(state='running',started_unix=started,deadline_unix=deadline)
    env=dict(os.environ);env['PYTHONPATH']=str(frozen/'src')
    for c in candidates:
        name=c['name'];seconds=60 if name=='all_stop_control' else args.seconds
        if time.time()+seconds>deadline:
            manifest['state']='GLOBAL_DEADLINE';break
        d=out/name;d.mkdir()
        command=[sys.executable,str(runner),'--_worker','--reference',str(out/'reference.json'),
            '--candidate',str(out/'candidates'/f'{name}.json'),'--output',str(d),'--seconds',str(seconds)]
        if args.earliest_wait_seconds is not None:
            command += ['--earliest-wait-seconds',str(args.earliest_wait_seconds)]
        entry={'name':name,'status':'running','command':command};manifest['runs'].append(entry)
        atomic_json(out/'campaign.json',manifest)
        entry['supervisor']=supervise(command,d,seconds=seconds,memory_bytes=32*1024**3,
            global_deadline=deadline,system_memory_pressure_seconds=30,env=env)
        entry['status']='complete' if (d/'result.json').exists() else 'incomplete'
        atomic_json(out/'campaign.json',manifest);summarize(out,baseline)
    manifest.update(state='finished',finished_unix=time.time(),
        complete=len(manifest['runs'])==len(candidates) and all(r['status']=='complete' for r in manifest['runs']))
    atomic_json(out/'campaign.json',manifest);summarize(out,baseline)


if __name__=='__main__': main()
