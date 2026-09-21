"""Repeat unresolved Journey comparisons with validated matching All-Stop starts."""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from ropeway_skip_stop_optimization.benchmarking.journey_mip_start import needs_rerun
from ropeway_skip_stop_optimization.benchmarking.thesis_contract import THESIS_CONTRACT_ID, source_digest, solver_versions
from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json
try:
    from benchmarks.run_thesis_revised_journey_campaign import save_and_publish
    from benchmarks.thesis_publication import directory_for
except ImportError:
    from run_thesis_revised_journey_campaign import save_and_publish
    from thesis_publication import directory_for

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(source, output, identity):
    state = json.loads((source/'campaign.json').read_text())
    if state['status'] != 'complete':
        raise ValueError('Source campaign must be complete')
    jobs = []
    sources = {j['id']: j for j in state['jobs']}
    for original in state['jobs']:
        if original['kind']=='reference' or original['status']!='complete':
            continue
        result_path = directory_for(source, original['attempts'][-1])/'result.json'
        result = json.loads(result_path.read_text())
        if not needs_rerun(result['run']):
            continue
        if original['mode'] != 'skip_stop':
            raise ValueError('Unresolved All-Stop controls require separate handling')
        baseline = sources[original['id'].replace('skip_stop','all_stop')]
        if baseline['status']!='complete' or baseline['demand']!=original['demand']:
            raise ValueError('No completed matching All-Stop control')
        baseline_path = directory_for(source, baseline['attempts'][-1])/'result.json'
        reference = json.loads(baseline_path.read_text())
        if reference['run'].get('validated_upper_bound') is None:
            raise ValueError('All-Stop control has no validated objective')
        if result['case']['thesis_contract_id'] != THESIS_CONTRACT_ID:
            raise ValueError('Source contract differs')
        frozen = output/'inputs'/original['id']
        frozen.mkdir(parents=True)
        (frozen/'all_stop.json').write_bytes(baseline_path.read_bytes())
        case_path = result_path.parent/'case_spec.json'
        (frozen/'case_spec.json').write_bytes(case_path.read_bytes())
        job = deepcopy(original)
        job.update(status='pending', attempts=[], all_stop_start=str(frozen/'all_stop.json'),
                   case_spec=str(frozen/'case_spec.json'), source_result=str(result_path),
                   source_sha256=digest(result_path), all_stop_sha256=digest(baseline_path),
                   case_sha256=digest(case_path), previous_gap=result['run'].get('relative_gap'),
                   all_stop_objective=reference['run']['validated_upper_bound'])
        job.pop('reason',None)
        jobs.append(job)
    if not jobs:
        raise ValueError('No unresolved comparisons')
    return dict(schema=2,campaign_id=output.name,status='prepared',jobs=jobs,identity=identity,
                source_campaign=str(source),source_campaign_sha256=digest(source/'campaign.json'),
                study=state['study'],label='Journey Time · All-Stop MIP starts',
                experiment_variant='all_stop_mip_start',execution_started_unix=None,
                wall_limit_seconds=len(jobs)*1800+1800,
                selection_rule='positive certified gap beyond numerical zero (max 1e-6 absolute, 1e-10 relative), or no incumbent/bound')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--build-only',action='store_true')
    parser.add_argument('--_worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    out=args.output_dir.resolve(); path=out/'campaign.json';frontend=ROOT/'frontend/public/generated'
    identity=dict(contract_id=THESIS_CONTRACT_ID,source_digest=source_digest(ROOT),solver_versions=solver_versions())
    if path.exists():
        if not (args.resume or args._worker):parser.error('Use --resume')
        state=json.loads(path.read_text())
        if state['identity']!=identity:parser.error('Source/contract changed')
    else:
        if args.resume or args.source is None:parser.error('New campaign requires --source')
        if out.exists() and any(out.iterdir()):parser.error('Output must be empty')
        state=prepare(args.source.resolve(),out,identity)
    for j in state['jobs']:
        for key, hash_key in [('all_stop_start','all_stop_sha256'),('case_spec','case_sha256')]:
            if digest(Path(j[key]))!=j[hash_key]:raise ValueError('Frozen input changed')
    save_and_publish(path,state,frontend)
    if not args.run or args.build_only:
        print(f"Prepared {len(state['jobs'])} comparisons: {path}");return
    if state['execution_started_unix'] is None:
        state['execution_started_unix']=time.time();state['deadline_unix']=time.time()+state['wall_limit_seconds']
        atomic_json(path,state)
    if not args._worker:
        if state['deadline_unix']<=time.time():raise ValueError('Original deadline exhausted')
        monitor=out/f'supervision_{time.time_ns()}';monitor.mkdir()
        outcome=supervise([sys.executable,str(Path(__file__).resolve()),'--output-dir',str(out),'--resume','--run','--_worker'],
                          monitor,seconds=state['deadline_unix']-time.time(),memory_bytes=32*1024**3,system_memory_pressure_seconds=30)
        if outcome['supervisor_reason'] or outcome['exit_code']:
            state=json.loads(path.read_text());state.update(status='interrupted',supervisor=outcome)
            for j in state['jobs']:
                if j['status']=='running':j['status']='interrupted'
            save_and_publish(path,state,frontend);raise SystemExit(1)
        return
    if any(j['status'] in ('failed','interrupted','running') for j in state['jobs']):
        raise ValueError('Interrupted/failed attempts require explicit review; no automatic retry')
    state['status']='running'
    for job in state['jobs']:
        if job['status']=='complete':continue
        if time.time()+1805>state['deadline_unix']:
            state['status']='partial';break
        directory=out/'runs'/job['id']/f"attempt_{len(job['attempts'])+1:03d}"
        command=[sys.executable,str(ROOT/'benchmarks/run_thesis_experiment.py'),'--case-spec',job['case_spec'],
                 '--method','labelled_arc_flow','--operating-mode','skip_stop','--cabins',str(job['k']),
                 '--time-limit','1800','--workers','12','--memory-limit-gib','32','--seed','0','--mip-gap','0.01',
                 '--all-stop-mip-start',job['all_stop_start'],'--log-search-progress','--output-dir',str(directory)]
        attempt=dict(directory=str(directory),command=command,started_unix=time.time());job['attempts'].append(attempt);job['status']='running'
        save_and_publish(path,state,frontend)
        process=subprocess.Popen(command,cwd=ROOT)
        while process.poll() is None:
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:save_and_publish(path,state,frontend)
        attempt.update(exit_code=process.returncode,finished_unix=time.time())
        job['status']='complete' if process.returncode==0 and (directory/'result.json').exists() else 'failed'
        save_and_publish(path,state,frontend)
        if job['status']=='failed':state['status']='partial';break
    else:state['status']='complete'
    save_and_publish(path,state,frontend)


if __name__=='__main__':main()
