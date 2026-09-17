"""Bounded sequential execution of the two revised journey screening series."""
import argparse
import hashlib
import json
import psutil
from pathlib import Path
import subprocess
import sys
import time
import zipfile
from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 46 * 3600 + 1800
FAMILIES = ('f0', 'f2', 'f3', 'f4')
SCOPE = 'FIXED_K_BALANCED_START_ALL_STOP_AND_NESTED_DEMAND'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--_worker', action='store_true')
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if not args._worker:
        if not args.resume:
            out.mkdir(parents=True, exist_ok=False)
            atomic_json(out / 'campaign.json', {'status':'prepared', 'started_epoch':time.time(), 'jobs':[]})
        state = json.loads((out / 'campaign.json').read_text())
        remaining = LIMIT-(time.time()-state['started_epoch'])
        if remaining <= 0:
            raise SystemExit('Original total deadline exhausted')
        session = len(list(out.glob('supervision_*')))+1
        monitor = out / f'supervision_{session:03d}';monitor.mkdir()
        with zipfile.ZipFile(monitor / 'sources.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for base in ('src','benchmarks'):
                for path in sorted((ROOT/base).rglob('*.py')):
                    archive.write(path,path.relative_to(ROOT))
            for name in ('pyproject.toml','uv.lock'):
                if (ROOT/name).exists(): archive.write(ROOT/name,name)
        result = supervise([sys.executable,str(Path(__file__).resolve()),'--output-dir',str(out),'--_worker'],
            monitor,seconds=remaining,memory_bytes=32*1024**3,system_memory_pressure_seconds=30)
        if result['supervisor_reason'] or result['exit_code']: raise SystemExit(1)
        return
    state=json.loads((out/'campaign.json').read_text());state['status']='running'
    handoff_path = out / 'controller_handoff.json'
    if handoff_path.exists():
        handoff = json.loads(handoff_path.read_text())
        if not handoff.get('completed'):
            entry = next(j for j in reversed(state['jobs']) if j['id'] == handoff['job_id'])
            while True:
                try:
                    process = psutil.Process(handoff['pid'])
                    alive = abs(process.create_time()-handoff['create_time']) < 0.01 and process.status() != psutil.STATUS_ZOMBIE
                except psutil.NoSuchProcess:
                    alive = False
                if not alive:
                    break
                if time.time()-state['started_epoch'] >= LIMIT:
                    raise TimeoutError('Original campaign deadline during handoff')
                time.sleep(1)
            result_path = Path(entry['result'])
            entry.update(status='complete' if result_path.exists() else 'failed',
                         wall_seconds=time.time()-entry['started_epoch'],
                         controller_handoff=True)
            handoff['completed'] = True
            atomic_json(handoff_path, handoff)
            atomic_json(out/'campaign.json', state)
    atomic_json(out/'campaign.json',state)

    def execute(key,family,k,demand,method,mode,reference=None):
        prior=[j for j in state['jobs'] if j['id']==key]
        if prior and prior[-1]['status']=='complete':
            return json.loads(Path(prior[-1]['result']).read_text())
        if time.time()-state['started_epoch']+1805 > LIMIT:
            raise TimeoutError('Campaign deadline; remaining jobs pending')
        directory=out/'runs'/key/f'attempt{len(prior)+1:03d}'
        command=[sys.executable,str(ROOT/'benchmarks/run_thesis_experiment.py'),
            '--topology','t5r','--geometry','g500','--demand-family',family,
            '--objective','journey_time','--method',method,'--operating-mode',mode,
            '--cabins',str(k),'--demand',str(demand),'--release-resolution-seconds','15',
            '--time-limit','1800','--workers','12','--memory-limit-gib','32','--seed','0',
            '--output-dir',str(directory)]
        if method=='all_stop_phase':command+=['--capacity-search','--capacity-initial-demand','500']
        else:command+=['--mip-gap','0.01']
        entry={'id':key,'family':family,'k':k,'demand':demand,'mode':mode,'status':'running',
            'started_epoch':time.time(),'result':str(directory/'result.json'), 'reference':reference,
            'resolution_scope':'15 seconds fixed; sensitivity at this new load is not yet established'}
        state['jobs'].append(entry);atomic_json(out/'campaign.json',state)
        process=subprocess.run(command,cwd=ROOT,check=False)
        entry.update(exit_code=process.returncode,wall_seconds=time.time()-entry['started_epoch'],
            status='complete' if process.returncode==0 and (directory/'result.json').exists() else 'failed')
        atomic_json(out/'campaign.json',state)
        if entry['status']=='complete':return json.loads((directory/'result.json').read_text())
        return {}

    refs={}
    try:
        # Reuse the four checked K31 certificates, retaining their evidence hashes.
        for family in FAMILIES:
            path=ROOT/f'results/thesis_journey_revised_references_20260915_v2/{family}_k31/result.json'
            result=json.loads(path.read_text());run=result['run']
            spec=json.loads((path.parent/'case_spec.json').read_text())
            arguments=json.loads((path.parent/'arguments.json').read_text())
            assert all(spec[k]==v for k,v in {'topology':'t5r','geometry':'g500','demand_family':family,
                'demand_profile':'p0','objective':'journey_time','release_resolution_seconds':15}.items())
            assert arguments['cabins']==31 and run['proof_scope']==SCOPE and run['capacity_proven']
            assert run['proven_infeasible_demand']==run['proven_feasible_demand']+1
            refs[(family,31)]={'capacity':run['proven_feasible_demand'],'result':str(path),
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        for family in FAMILIES:
            for k in (10,20,30):
                key=f'reference_{family}_k{k}'
                result=execute(key,family,k,20000,'all_stop_phase','all_stop')
                run=result.get('run',{})
                if run.get('capacity_proven') and run.get('proof_scope')==SCOPE:
                    path=Path(next(j for j in reversed(state['jobs']) if j['id']==key)['result'])
                    refs[(family,k)]={'capacity':run['proven_feasible_demand'],'result':str(path),
                        'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        atomic_json(out/'references.json',{f'{f}_k{k}':v for (f,k),v in refs.items()})
        pending=[]
        queue=[]
        for k in (10,20,30):
            for percent in (25,75):
                for family in ('f2','f4','f3','f0'):
                    ref=refs.get((family,k))
                    if ref is None:
                        pending.append(f'relative_load_{family}_k{k}: exact reference pending');continue
                    demand=max(1,ref['capacity']*percent//100)
                    for mode in ('all_stop','skip_stop'):
                        queue.append((f'relative_{percent}_{family}_k{k}_{mode}',family,k,demand,'labelled_arc_flow',mode,ref))
        for k in (20,30):
            for family in ('f2','f4','f3','f0'):
                ref=refs[(family,31)]
                for mode in ('all_stop','skip_stop'):
                    queue.append((f'constant_half_{family}_k{k}_{mode}',family,k,ref['capacity']//2,'labelled_arc_flow',mode,ref))
        atomic_json(out/'queue.json', {'policy':'relative first; K ascending; 25 before 75; F2,F4,F3,F0; paired modes',
            'jobs':[{'id':q[0],'family':q[1],'k':q[2],'demand':q[3],'mode':q[5]} for q in queue]})
        for task in queue:
            execute(*task)
        state.update(status='complete' if not pending and all(j['status']=='complete' for j in state['jobs']) else 'partial',
            pending=pending,wall_seconds=time.time()-state['started_epoch'])
    except TimeoutError as error:
        state.update(status='partial',stop_reason=str(error))
    finally:
        atomic_json(out/'campaign.json',state)


if __name__=='__main__':main()
