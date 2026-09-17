"""Resume G500 full-fleet references and materialize evidence-gated Evo recipes."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import zipfile
from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json

ROOT=Path(__file__).resolve().parents[1]
FAMILIES=('f2','f3','f0')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--_worker',action='store_true')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument(
        '--all-stop-capacity-encoding',
        choices=('integrated', 'phase_cells'),
        default='integrated',
    )
    args=parser.parse_args();out=args.output_dir.resolve()
    if not args._worker and not args.resume:
        out.mkdir(parents=True,exist_ok=False)
        with zipfile.ZipFile(out/'sources.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for base in ('src','benchmarks'):
                for path in sorted((ROOT/base).rglob('*.py')):archive.write(path,path.relative_to(ROOT))
            for name in ('pyproject.toml','uv.lock'):
                if (ROOT/name).exists():archive.write(ROOT/name,name)
        atomic_json(out/'preparation_manifest.json',{'stage_seconds':1800,'total_seconds':14700,
            'workers':12,'memory_gib':32,'profiles':list(FAMILIES),'topologies':['t5r','t6r'],
            'all_stop_capacity_encoding':args.all_stop_capacity_encoding,
            'source_sha256':hashlib.sha256((out/'sources.zip').read_bytes()).hexdigest()})
        metrics=supervise([sys.executable,str(Path(__file__).resolve()),'--output-dir',str(out),'--_worker',
            '--all-stop-capacity-encoding',args.all_stop_capacity_encoding],out,
            seconds=14700,memory_bytes=32*1024**3,system_memory_pressure_seconds=30)
        if metrics['exit_code'] or metrics['supervisor_reason']:raise SystemExit(1)
        return
    if not args._worker:
        previous_manifest=json.loads((out/'preparation_manifest.json').read_text())
        previous_state=json.loads((out/'preparation.json').read_text())
        elapsed=max(0,time.time()-(out/'sources.zip').stat().st_mtime)
        remaining=max(0,previous_manifest['total_seconds']-elapsed)
        atomic_json(out/'campaign_amendment.json',{'excluded_profiles':['f4'],'reason':'user_excluded_local_demand_profile','remaining_deadline_budget_seconds':remaining})
        encoding=previous_manifest.get('all_stop_capacity_encoding',args.all_stop_capacity_encoding)
        metrics=supervise([sys.executable,str(Path(__file__).resolve()),'--output-dir',str(out),'--_worker','--resume',
            '--all-stop-capacity-encoding',encoding],out,seconds=remaining,memory_bytes=32*1024**3,system_memory_pressure_seconds=30)
        if metrics['exit_code'] or metrics['supervisor_reason']:raise SystemExit(1)
        return
    inventory=json.loads((ROOT/'results/thesis_capacity_reference_inventory_20260916.json').read_text())
    old_state=json.loads((out/'preparation.json').read_text()) if args.resume else {'jobs':[]}
    completed={j['id']:j for j in old_state['jobs'] if j['status']=='complete'}
    excluded=[dict(j,status='excluded_by_user') for j in old_state['jobs'] if '_f4_' in j['id']]
    atomic_json(out/'excluded_jobs.json',excluded)
    state={'status':'running','jobs':[]};groups=[];started=time.time()
    for topology,k in (('t5r',62),('t6r',75)):
        for family in FAMILIES:
            previous=[x for x in inventory if x[:4]==[topology,family,15,k]]
            cap=10000 if family=='f2' else 50000
            usable=[]
            for row in previous:
                directory=ROOT/row[7]
                spec=json.loads((directory/'case_spec.json').read_text())
                native=json.loads((directory/'result.json').read_text()).get('run',{})
                upper=native.get('proven_infeasible_demand')
                native_upper=upper is None or any(p.get('demand')==upper and p.get('outcome')=='infeasible' and p.get('solver_status')=='INFEASIBLE' for p in native.get('probes',[]))
                if spec.get('demand_total')==cap and native_upper:usable.append(row)
            previous=usable
            key=f'reference_{topology}_{family}_r15' 
            directory=out/key
            command=[sys.executable,str(ROOT/'benchmarks/run_thesis_experiment.py'),'--topology',topology,
                '--geometry','g500','--demand-family',family,'--objective','unserved','--method','all_stop_phase',
                '--operating-mode','all_stop','--cabins',str(k),'--demand',str(cap),'--capacity-search',
                '--capacity-initial-demand','1000','--release-resolution-seconds','15','--time-limit','1800',
                '--workers','12','--memory-limit-gib','32','--all-stop-capacity-encoding',
                args.all_stop_capacity_encoding,'--output-dir',str(directory)]
            for row in previous:command+=['--capacity-reference-dir',str(ROOT/row[7])]
            if key in completed:
                entry=dict(completed[key]);state['jobs'].append(entry)
            else:
                entry={'id':key,'status':'running','reused_reference_count':len(previous)};state['jobs'].append(entry)
                atomic_json(out/'preparation.json',state)
                before=time.time();process=subprocess.run(command,cwd=ROOT,check=False)
                entry.update(status='complete' if process.returncode==0 else 'failed',exit_code=process.returncode,wall_seconds=time.time()-before)
            result_path=directory/'result.json';native={}
            if result_path.exists():native=json.loads(result_path.read_text()).get('run',{})
            lower=native.get('proven_feasible_demand') or 0;exact=bool(native.get('capacity_proven'))
            entry.update(capacity_proven=exact,lower=lower,upper_exclusive=native.get('proven_infeasible_demand'))
            groups.append({'id':f'capacity_{topology}_{family}_g500_p0','topology':topology,'family':family,
                'objective':'unserved','resolution_seconds':15,'k_values':[k,k+1,math.ceil(1.1*k)],
                'seeds':[0,1,2],'stage_seconds':1800,'demand':max(1,lower),'max_demand_levels':5,
                'demandBasis':'exact_reference_capacity' if exact else 'validated_reference_lower_bound',
                'reference':{'result':str(result_path),'sha256':hashlib.sha256(result_path.read_bytes()).hexdigest() if result_path.exists() else None,
                    'lower':lower,'upperExclusive':native.get('proven_infeasible_demand'),'exact':exact,
                    'scope':native.get('proof_scope')},
                'blockers':([] if exact else ['exact_all_stop_reference_pending'])+['capacity_resolution_evidence_review_pending']})
            atomic_json(out/'preparation.json',state)
    evidence=ROOT/'results/thesis_g500_completion_20260915/resolution_evidence.json'
    manifest={'schema':'thesis_study_v1','status':'gated','workers':12,'memory_gib':32,'groups':groups,
        'geometry':'g500','operation':'no_wait','catalog':'od_endpoints_v1',
        'source_resolution_evidence':str(evidence),
        'source_resolution_sha256':hashlib.sha256(evidence.read_bytes()).hexdigest() if evidence.exists() else None,
        'greedy_comparisons':['no_wait','waiting_120_seconds'],
        'maximum_stage_budget_seconds':sum(g['stage_seconds']*len(g['seeds'])*len(g['k_values'])*8 for g in groups)}
    atomic_json(out/'evo_manifest_pending_review.json',manifest)
    state.update(status='complete' if all(j['status']=='complete' for j in state['jobs']) else 'partial',wall_seconds=time.time()-started)
    atomic_json(out/'preparation.json',state)


if __name__=='__main__':main()
