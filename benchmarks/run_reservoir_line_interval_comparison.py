"""Three frozen 300s GA runs; 16 minute wall ceiling, no automatic extensions."""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json

ROOT = Path(__file__).resolve().parents[1]


def summarize(out):
    rows = []
    for name in ('legacy', 'intervals', 'intervals_waiting'):
        path = out/name/'result.json'
        if not path.exists():
            rows.append({'run': name, 'status': 'pending_or_incomplete'})
            continue
        result = json.loads(path.read_text())
        events = result['events']
        cuts = {}
        for t in (30,60,120,180,300):
            ordinary = [e for e in events if e['kind']=='fleet_frontier' and e['elapsed_seconds']<=t]
            mixed = [e for e in events if e['kind']=='mixed_fleet_frontier' and e['elapsed_seconds']<=t]
            cuts[str(t)] = {'served': max((e['served'] for e in ordinary), default=None),
                'mixed_served': max((e['served'] for e in mixed), default=None),
                'largest_valid_mixed_k': max((e['fleet_size'] for e in mixed), default=None)}
        rows.append({'run': name, 'status': 'complete', 'cuts': cuts,
            'evaluations': result['evaluations'], 'feasible': result['feasible_evaluations'],
            'served': result['best']['passengers']['served'] if result['best'] else None,
            'evaluation_totals': result['evaluation_totals'],
            'repair_spent_seconds': result['repair_spent_seconds'],
            'last_global_improvement_seconds': max((e['elapsed_seconds'] for e in events if e['kind']=='incumbent'), default=None),
            'last_mixed_frontier_seconds': max((e['elapsed_seconds'] for e in events if e['kind']=='mixed_fleet_frontier'), default=None),
            'runner_wall_seconds': result['runner_total_wall_seconds']})
    atomic_json(out/'summary.json', rows)
    lines = ['# R2: Dispatchintervalle und Waiting-Fallback', '',
        'Drei sequenzielle 300-s-Läufe, Seed 0, ohne importierten Startplan. '
        'Waiting ab 0 s ist explizit dieselbe Quelldomäne; zwei Verfahren nutzen ausschließlich No-Wait. '
        'Ein diagnostischer Vergleich, keine Aussage über statistische Überlegenheit.', '',
        '| Verfahren | 30 s | 60 s | 120 s | 180 s | Ende | letzter globaler Fortschritt (s) |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for row in rows:
        cuts = row.get('cuts', {})
        vals = [cuts.get(str(t), {}).get('served') for t in (30,60,120,180)]
        lines.append('| '+row['run']+' | '+' | '.join(str(x) for x in [*vals,row.get('served'),row.get('last_global_improvement_seconds')])+' |')
    lines += ['', 'Die JSON-Auswertung enthält getrennte gemischte Fahrplanfronten, K, '
              'Reparaturstatus und Zeitanteile. `UNKNOWN`/Budgets sind keine Unzulässigkeitsnachweise. '
              'Die All-Stop-Kontrolle steht in `preflight.json`.']
    (out/'report.md').write_text('\n'.join(lines)+'\n')


def preflight(out):
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import load_reference
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import validate_reservoir_cp_plan
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (
        ReservoirLineConfig, ReservoirLineVariant, ReservoirLinePreparation,
        ReservoirLineCatalogProfile, prepare_line_problem)
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution import genome_from_plan, LineEvolutionEvaluator
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.interval_decoder import IntervalDispatchDecoder
    domain, _ = load_reference(out/'reference.json')
    _, baseline = load_reference(out/'all_stop.json')
    p = replace(domain.problem, waiting_policy=replace(domain.problem.waiting_policy, earliest_wait_time_seconds=0.0))
    if sum(g.count for g in p.demand_groups) != 3074 or p.available_fleet_count != 50 or p.boundary_policy is None:
        raise ValueError('unexpected R2 comparison domain')
    prepared = prepare_line_problem(p, ReservoirLineConfig(dispatch_window_end_seconds=300,
        maximum_cabins=50, variant=ReservoirLineVariant.INTERVALS,
        preparation=ReservoirLinePreparation.ENCODING_SPECIFIC,
        catalog_profile=ReservoirLineCatalogProfile.RELEVANT))
    if len({t.pattern_id for t in prepared.templates}) != 14:
        raise ValueError('R2 comparison requires all 14 relevant patterns')
    metrics = validate_reservoir_cp_plan(p, baseline)
    g = genome_from_plan(p, prepared, baseline)
    replay, _ = IntervalDispatchDecoder(p, prepared).decode(g)
    if not replay.feasible or replay.genome != g:
        raise ValueError('all-stop replay changed under insertion')
    evaluated = LineEvolutionEvaluator(p, prepared, dispatch_decoder='intervals').evaluate(g)
    if metrics.served != 2496 or evaluated.passengers.served != metrics.served:
        raise ValueError('all-stop fixed-timetable passenger value changed')
    atomic_json(out/'preflight.json', {'physical_fingerprint':p.fingerprint,
        'baseline_metrics':asdict(metrics), 'reoptimized_served':evaluated.passengers.served,
        'catalog_size':14, 'all_stop_is_decoder_fixed_point':True,
        'waiting_policy':asdict(p.waiting_policy), 'baseline_is_initial_seed':False})


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--all-stop', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    started=time.time();deadline=started+960
    frozen=out/'sources';(frozen/'benchmarks').mkdir(parents=True)
    shutil.copytree(ROOT/'src', frozen/'src', ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    runner=frozen/'benchmarks/run_reservoir_line_evolution.py'
    shutil.copy2(ROOT/'benchmarks/run_reservoir_line_evolution.py',runner)
    shutil.copy2(__file__,frozen/'benchmarks'/Path(__file__).name)
    for name in ('pyproject.toml','uv.lock'):
        shutil.copy2(ROOT/name,frozen/name)
    shutil.copy2(args.reference,out/'reference.json');shutil.copy2(args.all_stop,out/'all_stop.json')
    manifest={'started_unix':started,'deadline_unix':deadline,'runs':[],
        'source_hashes':{str(f.relative_to(frozen)):hashlib.sha256(f.read_bytes()).hexdigest()
                         for f in sorted(frozen.rglob('*')) if f.is_file()}}
    atomic_json(out/'campaign.json',manifest)
    preflight(out)
    env=dict(os.environ);env['PYTHONPATH']=str(frozen/'src')
    for name,decoder,repair in (('legacy','legacy',0),('intervals','intervals',0),('intervals_waiting','intervals',5)):
        if time.time()+300>deadline:
            manifest['stop_reason']='GLOBAL_DEADLINE';break
        directory=out/name;directory.mkdir()
        command=[sys.executable,str(runner),'--_worker','--reference-checkpoint',str(out/'reference.json'),
            '--output',str(directory),'--engine','ga','--operator-profile','mixed_global',
            '--dispatch-window-end','300','--time-limit','300','--workers','12','--memory-limit-gib','32',
            '--seed','0','--no-reference-initialization','--dispatch-decoder',decoder,
            '--waiting-repair-seconds',str(repair),'--waiting-budget-fraction','0.2','--earliest-wait-seconds','0']
        entry={'name':name,'command':command,'status':'running'};manifest['runs'].append(entry)
        atomic_json(out/'campaign.json',manifest)
        entry['supervisor']=supervise(command,directory,seconds=300,memory_bytes=32*1024**3,
            global_deadline=deadline,system_memory_pressure_seconds=30,env=env)
        entry['status']='complete' if (directory/'result.json').exists() else 'incomplete'
        atomic_json(out/'campaign.json',manifest);summarize(out)
    manifest['finished_unix']=time.time()
    manifest['complete']=len(manifest['runs'])==3 and all(x['status']=='complete' for x in manifest['runs'])
    atomic_json(out/'campaign.json',manifest);summarize(out)


if __name__=='__main__':
    main()
