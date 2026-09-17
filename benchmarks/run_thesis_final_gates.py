"""Final bounded reference controls and profile pilots; never the main study."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--_worker', action='store_true')
    args = parser.parse_args()
    if not args._worker:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        result = supervise([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--_worker'], args.output_dir,
                           seconds=960, memory_bytes=32 * 1024**3, system_memory_pressure_seconds=30)
        if result['supervisor_reason'] or result['exit_code']:
            raise SystemExit(1)
        return
    # Budgets are maxima including setup and validation; jobs are sequential.
    tasks = [(f'journey_t5r_{f}_all_stop_r5', 't5r', f, 10, n, 5, 'journey_time', 'labelled_arc_flow', 'all_stop', 30)
             for f, n in [('f0', 510), ('f3', 360), ('f4', 772)]]
    tasks += [(f'evolution_{t}_{f}_r15', t, f, k, n, 15, 'unserved', 'evolution', 'skip_stop', seconds)
              for t, f, k, n, seconds in [('t5r','f2',62,3204,45), ('t6r','f2',75,3231,45),
                  ('t5r','f0',62,8800,180), ('t5r','f3',62,4400,180), ('t6r','f0',75,4400,180)]]
    state = {'schema':'thesis_final_gates_v1','status':'running','jobs':[]}
    started = time.time()
    for name, topology, family, k, demand, resolution, objective, method, mode, seconds in tasks:
        if time.time() - started + seconds + 5 >= 960:
            state['jobs'].append({'id':name,'status':'skipped','reason':'deadline'})
            continue
        entry = {'id':name,'status':'running'}; state['jobs'].append(entry)
        atomic_json(args.output_dir / 'checks.json', state)
        command = [sys.executable, str(ROOT / 'benchmarks/run_thesis_experiment.py'), '--topology', topology,
                   '--geometry','g500','--demand-family',family,'--objective',objective,'--method',method,
                   '--operating-mode',mode,'--demand',str(demand),'--cabins',str(k),
                   '--release-resolution-seconds',str(resolution),'--time-limit',str(seconds),'--workers','12',
                   '--output-dir',str(args.output_dir / name)]
        if method == 'evolution': command += ['--catalog','od_endpoints_v1']
        before = time.time(); process = subprocess.run(command, cwd=ROOT, check=False)
        entry.update(status='complete' if process.returncode == 0 else 'failed', exitCode=process.returncode, wallSeconds=time.time()-before)
        atomic_json(args.output_dir / 'checks.json',state)
    state.update(status='complete' if all(j['status']=='complete' for j in state['jobs']) else 'partial',wallSeconds=time.time()-started)
    atomic_json(args.output_dir / 'checks.json', state)


if __name__ == '__main__':
    main()
