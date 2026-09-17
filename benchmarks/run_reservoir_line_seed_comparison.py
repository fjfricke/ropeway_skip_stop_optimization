"""Frozen six-run R2 seed comparison, bounded to 31 minutes including reports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json

ROOT = Path(__file__).resolve().parents[1]


def summarize(out):
    rows = []
    for directory in sorted(out.glob('s[012]_*')):
        p = directory / 'result.json'
        if not p.exists():
            rows.append({'run': directory.name, 'status': 'incomplete'})
            continue
        result = json.loads(p.read_text())
        events = result['events']
        pop = [e for e in events if e['kind'] == 'population']
        cuts = {}
        for t in (30, 60, 120, 300):
            prior = [e for e in events if e['kind'] == 'fleet_frontier' and e['elapsed_seconds'] <= t]
            frontier = {}
            for event in prior:
                frontier[str(event['fleet_size'])] = event
            mixed = [e for e in frontier.values() if any(p != 'all_stop' for p in e['pattern_ids'])]
            cuts[str(t)] = {
                'best_native_served': max((e['served'] for e in prior if e['origin'] != 'reference'), default=None),
                'best_mixed_served': max((e['served'] for e in mixed), default=None),
                'largest_valid_mixed_k': max((e['fleet_size'] for e in mixed), default=None),
                'fleet_frontier': frontier,
            }
        rows.append({'run':directory.name, 'status':'complete', 'cuts':cuts,
                     'evaluations':result['evaluations'], 'feasible':result['feasible_evaluations'],
                     'served':result['best']['passengers']['served'] if result['best'] else None,
                     'last_frontier_seconds':max((e['elapsed_seconds'] for e in events if e['kind']=='fleet_frontier' and e['origin']!='reference'),default=None),
                     'last_population':pop[-1] if pop else None})
    atomic_json(out / 'summary.json', rows)
    lines = ['# R2: All-Stop seed comparison', '',
             'Same physical domain, mixed_global, population 32, eight offspring, 25% exploration parents. Six sequential 300-second runs. Only imported population seed differs. All-stop remains an allowed pattern in both conditions.', '',
             '| Run | Validated served | Evaluations | Valid | Last per-K improvement (s) |',
             '|---|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f"| {r['run']} | {r.get('served')} | {r.get('evaluations')} | {r.get('feasible')} | {r.get('last_frontier_seconds')} |")
    lines += ['', 'The JSON summary includes per-K pattern/dispatch frontiers at 30, 60, 120 and 300 seconds and final populations. Imported seeds are reported separately from native discoveries. No global optimization proof is inferred.']
    (out / 'report.md').write_text('\n'.join(lines)+'\n')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--all-stop',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    started=time.time(); deadline=started+1860
    frozen=out/'sources';(frozen/'benchmarks').mkdir(parents=True)
    shutil.copytree(ROOT/'src', frozen/'src', ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    runner=frozen/'benchmarks/run_reservoir_line_evolution.py'
    shutil.copy2(ROOT/'benchmarks/run_reservoir_line_evolution.py',runner)
    shutil.copy2(__file__,frozen/'benchmarks'/Path(__file__).name)
    shutil.copy2(a.reference,out/'reference.json');shutil.copy2(a.all_stop,out/'all_stop.json')
    manifest={'started_unix':started,'deadline_unix':deadline,'runs':[],
              'source_hashes':{str(f.relative_to(frozen)):hashlib.sha256(f.read_bytes()).hexdigest() for f in frozen.rglob('*.py')}}
    env=dict(os.environ);env['PYTHONPATH']=str(frozen/'src')
    for seed in (0,1,2):
        for seeded in ((True,False) if seed%2==0 else (False,True)):
            name=f's{seed}_'+('seeded' if seeded else 'unseeded')
            if time.time()+300 > deadline:
                manifest['stop_reason']='GLOBAL_DEADLINE';break
            d=out/name;d.mkdir()
            command=[sys.executable,str(runner),'--_worker','--reference-checkpoint',str(out/'reference.json'),
                     '--output',str(d),'--engine','ga','--operator-profile','mixed_global',
                     '--dispatch-window-end','300','--time-limit','300','--workers','12','--memory-limit-gib','32',
                     '--seed',str(seed),'--passenger-time-limit','2','--exploration-parent-probability','0.25']
            command += ['--initial-checkpoint',str(out/'all_stop.json')] if seeded else ['--no-reference-initialization']
            entry={'name':name,'command':command,'status':'running'};manifest['runs'].append(entry)
            atomic_json(out/'campaign.json',manifest)
            entry['supervisor']=supervise(command,d,seconds=300,memory_bytes=32*1024**3,
                global_deadline=deadline,system_memory_pressure_seconds=30,env=env)
            entry['status']='complete' if (d/'result.json').exists() else 'incomplete'
            atomic_json(out/'campaign.json',manifest);summarize(out)
    manifest['finished_unix']=time.time();manifest['complete']=len(manifest['runs'])==6 and all(x['status']=='complete' for x in manifest['runs'])
    atomic_json(out/'campaign.json',manifest);summarize(out)


if __name__=='__main__':main()
