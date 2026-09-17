"""Sequential, supervised K31 reference preparation for revised journey series."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import zipfile
from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--_worker', action='store_true')
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if not args._worker:
        out.mkdir(parents=True, exist_ok=False)
        with zipfile.ZipFile(out / 'sources.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for base in ('src', 'benchmarks'):
                for path in sorted((ROOT / base).rglob('*.py')):
                    archive.write(path, path.relative_to(ROOT))
            for name in ('pyproject.toml', 'uv.lock'):
                if (ROOT / name).exists():
                    archive.write(ROOT / name, name)
        atomic_json(out / 'preparation_manifest.json', {
            'topology':'t5r', 'geometry':'g500', 'release_resolution_seconds':15,
            'reference_k':31, 'families':['f0','f2','f3','f4'],
            'reference_scope':'FIXED_K_BALANCED_START_ALL_STOP_AND_NESTED_DEMAND',
            'seconds_per_reference':1800, 'total_seconds':7320,
            'workers':12, 'memory_gib':32,
            'sources_sha256':hashlib.sha256((out / 'sources.zip').read_bytes()).hexdigest(),
            'purpose':'Full capacity at K31, without multiplying demand by 0.5',
        })
        (out / "supervision").mkdir()
        result = supervise([sys.executable, str(Path(__file__).resolve()), '--output-dir', str(out), '--_worker'],
                           out / 'supervision', seconds=7320, memory_bytes=32*1024**3,
                           system_memory_pressure_seconds=30)
        if result['supervisor_reason'] or result['exit_code']:
            raise SystemExit(1)
        return
    started = time.time()
    state = {'status':'running', 'jobs':[]}
    for family in ('f0', 'f2', 'f3', 'f4'):
        entry = {'family':family, 'k':31, 'status':'running'}
        state['jobs'].append(entry)
        if time.time()-started+1800 > 7320:
            entry.update(status='pending', reason='deadline')
            continue
        atomic_json(out / 'preparation.json', state)
        command = [sys.executable, str(ROOT / 'benchmarks/run_thesis_experiment.py'),
                   '--topology','t5r','--geometry','g500','--demand-family',family,
                   '--objective','journey_time','--method','all_stop_phase','--operating-mode','all_stop',
                   '--cabins','31','--demand','20000','--capacity-search','--capacity-initial-demand','500',
                   '--release-resolution-seconds','15','--time-limit','1800','--workers','12',
                   '--memory-limit-gib','32','--output-dir',str(out / f'{family}_k31')]
        before = time.time()
        process = subprocess.run(command, cwd=ROOT, check=False)
        entry.update(status='complete' if process.returncode==0 else 'failed', exit_code=process.returncode,
                     wall_seconds=time.time()-before)
        path=out / f'{family}_k31/result.json'
        if path.exists():
            run=json.loads(path.read_text()).get('run', {})
            entry.update({k:run.get(k) for k in ('capacity_proven','proven_feasible_demand','proven_infeasible_demand')})
        atomic_json(out / 'preparation.json',state)
    state.update(status='complete' if all(j['status']=='complete' for j in state['jobs']) else 'partial',
                 wall_seconds=time.time()-started)
    atomic_json(out / 'preparation.json',state)


if __name__ == '__main__':
    main()
