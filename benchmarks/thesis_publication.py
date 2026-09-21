"""Publish the three thesis series and checked viewer artifacts without solving."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from urllib.parse import quote

from ropeway_skip_stop_optimization.benchmarking.frontend_results import atomic_json, _index_lock
from ropeway_skip_stop_optimization.benchmarking.thesis_contract import THESIS_CONTRACT_ID
from ropeway_skip_stop_optimization.submission import resolve_recorded
try:
    from .thesis_replay_export import export_replay, safety_input, repair_initial_context
    from .export_thesis_frontend import _slug
except ImportError:
    from thesis_replay_export import export_replay, safety_input, repair_initial_context
    from export_thesis_frontend import _slug

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_SOURCES=('thesis_journey_geometric_20260919','oip_fixed_mixes_geometric_120_20260918','oip_fixed_mixes_geometric_k50_20260919')
SERIES={'journey':'Journey','oip_k62':'OIP · K62','oip_k50':'OIP · K50'}


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def series_for(state):
    if state.get('identity',{}).get('contract_id')==THESIS_CONTRACT_ID and 'jobs' in state: return 'journey'
    if state.get('contract_id')==THESIS_CONTRACT_ID and state.get('study_variant','').startswith('fixed'):
        return f"oip_k{state['k_values'][0]}"
    if state.get('contract_id')==THESIS_CONTRACT_ID and state.get('headway_contract')=='geometric_shared_entry_exit_v1' and state.get('k_values') in ([50],[62]):
        return f"oip_k{state['k_values'][0]}"
    return None


def directory_for(source, attempt):
    return resolve_recorded(source, attempt['directory'])


def publish_campaign(source: Path, generated: Path):
    state=read(source/'campaign.json',{})
    series=series_for(state)
    if series not in SERIES: return
    cid=state['campaign_id']; study=generated/'study'; study.mkdir(parents=True,exist_ok=True)
    execution=dict(id=cid,series=series,label=SERIES[series],status=state['status'],url=f'/optimization/{quote(cid)}',
        original=cid in DEFAULT_SOURCES,runs=[],calibrations=[])
    errors=[]
    rows=state.get('jobs',state.get('trials',[]))
    if isinstance(rows,dict): rows=list(rows.values())
    refs=state.get('reference_runs',[])
    if isinstance(refs,dict):
        refs=[{**v,'id':f'reference_{f}','family':f,'attempts':[{'directory':f'references/{f}','run_campaign_id':f'{cid}__reference__{f}'}]} for f,v in refs.items()]
    rows=list(rows)+[r for r in refs if r.get('status')=='complete']
    # Persist supplementary reference source in a sidecar, never in solver evidence.
    sidecar=read(study/f'{cid}.supplement.json',{})
    supplement=sidecar.get('reference_runs',[])
    if isinstance(supplement,dict):
        supplement=[{**r,'id':f'phase_reference_{f}','family':f,'attempts':[{**a,'directory':str(Path(sidecar['source'])/a['directory']),'run_campaign_id':r['run_campaign_id']} for a in r['attempts']]} for f,r in supplement.items()]
    rows+=supplement
    for row in rows:
        if row.get('status')=='deferred': continue
        attempts=row.get('attempts',[])
        rid=row.get('id',row.get('trial_id',row.get('family','reference')))
        if not attempts:
            execution['runs'].append(dict(id=rid,status=row.get('status','planned'),detail_url=None,replay_url=None)); continue
        for n,attempt in enumerate(attempts):
            folder=directory_for(source,attempt)
            public_id=attempt.get('run_campaign_id') or f"{cid}__{rid}__a{n+1}"
            journey=series=='journey'
            slug=_slug(folder) if journey else public_id
            detail_url=f'/thesis?run={slug}' if journey else f'/optimization/{quote(public_id)}'
            if not journey:
                for name in ('detail.json','snapshot.json'):
                    target_file=generated/'optimization'/public_id/name
                    if (folder/name).exists() and (not target_file.exists() or (folder/name).stat().st_mtime_ns>target_file.stat().st_mtime_ns):
                        target_file.parent.mkdir(parents=True,exist_ok=True)
                        if name=='snapshot.json': atomic_json(target_file,{**read(folder/name),'campaign_id':public_id})
                        else: shutil.copy2(folder/name,target_file)
                snapshot_file=generated/'optimization'/public_id/'snapshot.json'
                saved_snapshot=read(snapshot_file)
                if saved_snapshot and saved_snapshot.get('campaign_id')!=public_id:
                    atomic_json(snapshot_file,{**saved_snapshot,'campaign_id':public_id})
            item=dict(id=public_id,run_id=rid,attempt=n+1,status=attempt.get('status',row.get('status')),
                family=row.get('family'),k=row.get('k',row.get('available_fleet_count',row.get('fixed_k',state.get('k_values',[None])[0]))),
                detail_url=detail_url,replay_url=None,latest=n==len(attempts)-1)
            target=study/'runs'/public_id
            stat_files=[p for p in (folder/'result.json',folder/'manifest.json',folder/'scenario.json') if p.exists()]
            stamp=hashlib.sha256(json.dumps([('export_version',3), *[(p.name,p.stat().st_size,p.stat().st_mtime_ns) for p in stat_files]]).encode()).hexdigest()
            receipt=read(target/'receipt.json',{})
            if receipt.get('stamp')!=stamp or receipt.get('error'):
                target.mkdir(parents=True,exist_ok=True)
                try:
                    artifact=export_replay(folder,target,f'/generated/study/runs/{public_id}',family=row.get('family'),
                        demand=row.get('demand_total',row.get('demand')),k=item['k'])
                    if artifact:
                        viewer=dict(schema_version=2,generated_at=None,families=[dict(id='thesis',label=SERIES[series],variants=[dict(id=public_id,label=rid,example_id=public_id,example_label=rid,description='Best independently validated timetable',tags=[],default_artifact_set='best',artifact_sets=[artifact])])],
                            source_label=f"{SERIES[series]} · {rid} · attempt {n+1}",back_url=detail_url)
                        atomic_json(target/'viewer.json',viewer)
                    receipt=dict(stamp=stamp,valid=bool(artifact))
                except (ValueError,KeyError,TypeError,FileNotFoundError) as exc:
                    receipt=dict(stamp=stamp,valid=False,error=str(exc)); errors.append(f'{public_id}: {exc}')
                atomic_json(target/'receipt.json',receipt)
            if receipt.get('error'): errors.append(f"{public_id}: {receipt['error']}")
            if receipt.get('valid') and receipt.get('context_version')!=2:
                scenario=read(target/'scenario.json'); movement=read(target/'ean_result.json'); service=read(target/'milp_result.json')
                atomic_json(target/'ean_replay.json',repair_initial_context(scenario,movement,read(target/'ean_replay.json'),service.get('fleet_plan')))
                if service.get('fleet_plan'):
                    movement['fleet_plan']=service['fleet_plan']; atomic_json(target/'ean_result.json',movement)
                receipt['context_version']=2; atomic_json(target/'receipt.json',receipt)
            if receipt.get('valid') and not (target/'ean_input.json').exists():
                atomic_json(target/'ean_input.json',safety_input(read(target/'scenario.json'),read(target/'ean_result.json')))
                viewer=read(target/'viewer.json')
                viewer['families'][0]['variants'][0]['artifact_sets'][0]['artifacts']['ean_input']=f'/generated/study/runs/{public_id}/ean_input.json'
                atomic_json(target/'viewer.json',viewer)
            if receipt.get('valid'): item['replay_url']=f'/?replay={quote(public_id)}'
            item['replay_error']=receipt.get('error')
            item['replay_stamp']=receipt.get('stamp')
            item['legacy_id']=slug
            execution['runs'].append(item)
            if row.get('kind')=='reference' or row in refs or row in supplement:
                execution['calibrations'].append({**item,'label':rid,'capacity':row.get('capacity'),
                    'served':row.get('served_passengers',row.get('served')), 'scope':'fixed_start_capacity' if journey else 'regular_phase_at_experiment_demand'})
    execution['replay_errors']=sorted(set(errors))
    if state.get('calibration_adoption'):
        atomic_json(study/f'{cid}.calibration.json',state['calibration_adoption'])
        execution['calibration_source_url']=f'/generated/study/{cid}.calibration.json'
        execution['capacity_evidence']=[{'family':f,'capacity':v['capacity'],'excluded':v['source_evidence']['proven_infeasible_demand'],'load':v['load_120'],'proof':v['proof']} for f,v in state['calibration_adoption'].items()]
    # Supplement snapshot survives subsequent parent publication.
    snapshot_path=generated/'optimization'/cid/'snapshot.json'
    snapshot=read(snapshot_path)
    if snapshot:
        snapshot.update(study_membership='current_thesis',series_id=series)
        if sidecar: snapshot['supplementary_phase_references']=sidecar
        atomic_json(snapshot_path,snapshot)
    with _index_lock(study/'.index.lock'):
        catalog=read(study/'index.json',dict(schema=1,executions=[]))
        catalog['executions']=[e for e in catalog['executions'] if e['id']!=cid]+[execution]
        catalog['series']=[dict(id=s,label=label) for s,label in SERIES.items()]
        atomic_json(study/'index.json',catalog)
    guide=ROOT/'docs/experiments/README.md'
    if guide.exists():
        (study/'README.md').write_text(guide.read_text().replace('../results/thesis_frontend_publication_20260920.md','publication-report.md'))
        for origin, name in [('docs/experiments/HISTORY.md','HISTORY.md'),('docs/results/thesis_frontend_publication_20260920.md','publication-report.md')]:
            if (ROOT/origin).exists(): shutil.copy2(ROOT/origin,study/name)
    return execution


def publish_calibration(source,generated):
    state=read(source/'campaign.json'); refs=read(source/'references.json')
    if not state or not refs or refs.get('contract_id')!='oip_regular_phase_short_1ms_v1': return
    study=generated/'study'; target=study/'calibrations'/source.name
    atomic_json(target/'campaign.json',state); atomic_json(target/'references.json',refs)
    probes=[]
    for path in sorted(source.glob('*/attempt_*/probes.json')):
        probes.append(dict(family=path.parent.parent.name,attempt=path.parent.name,probes=read(path)))
    atomic_json(target/'history.json',probes)
    study.mkdir(parents=True,exist_ok=True)
    with _index_lock(study/'.index.lock'):
        catalog=read(study/'index.json',dict(schema=1,executions=[],series=[dict(id=s,label=l) for s,l in SERIES.items()]))
        catalog['calibration_runs']=[c for c in catalog.get('calibration_runs',[]) if c['id']!=source.name]+[
            dict(id=source.name,label='CAL-O · regular fleet, free common phase',status=state['status'],
                url=f'/calibration-live?source={quote(source.name)}',history_url=f'/generated/study/calibrations/{source.name}/history.json')]
        atomic_json(study/'index.json',catalog)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--submission-manifest',type=Path,help='Verify and publish the frozen raw-data submission')
    p.add_argument('--source',type=Path,action='append',help='Completed or running campaign; repeatable')
    p.add_argument('--frontend-root',type=Path,default=ROOT/'frontend/public/generated')
    p.add_argument('--calibration-source',type=Path,action='append')
    p.add_argument('--supplement',type=Path,action='append',help='Completed K50 phase-reference campaign')
    p.add_argument('--prune',action='store_true',help='Remove unregistered frontend run exports, retaining examples and raw results')
    args=p.parse_args()
    if args.submission_manifest:
        if args.source or args.calibration_source or args.supplement or args.prune:
            p.error('--submission-manifest cannot be combined with source overrides or --prune')
        try:
            from .submission_export import export_submission
        except ImportError:
            from submission_export import export_submission
        export_submission(args.submission_manifest, args.frontend_root)
        return
    export_sources(args)


def export_sources(args):
    generated=args.frontend_root.resolve()
    for calibration in args.calibration_source or [ROOT/'results/oip_exact_phase_short_k62_20260918']:
        publish_calibration(calibration.resolve(),generated)
    for supplement in args.supplement or []:
        supplemental=read(supplement/'campaign.json')
        parent=read(resolve_recorded(supplement, supplemental['configuration']['source_campaign'])/'campaign.json') if 'configuration' in supplemental else None
        if parent is None: raise ValueError('Missing supplement source campaign')
        atomic_json(generated/'study'/f"{parent['campaign_id']}.supplement.json",dict(status=supplemental['status'],reference_runs=supplemental['reference_runs'],source=str(supplement.resolve())))
    sources=args.source or [ROOT/'results'/s for s in DEFAULT_SOURCES]
    for source in sources:
        state=read(source/'campaign.json',{})
        if series_for(state)=='journey':
            try:
                from .journey_live_export import publish
            except ImportError:
                from journey_live_export import publish
            publish(source.resolve(),state,generated)
        else:
            atomic_json(generated/'optimization'/state['campaign_id']/'snapshot.json',state)
            for row in state.get('trials',[]):
                for attempt in row.get('attempts',[]):
                    folder=directory_for(source,attempt)
                    target=generated/'optimization'/attempt['run_campaign_id']
                    for name in ('detail.json','snapshot.json'):
                        if (folder/name).exists():
                            target.mkdir(parents=True,exist_ok=True); shutil.copy2(folder/name,target/name)
            for f,row in state.get('reference_runs',{}).items():
                target=generated/'optimization'/f"{state['campaign_id']}__reference__{f}"
                for name in ('detail.json','snapshot.json'):
                    if (source/'references'/f/name).exists():
                        target.mkdir(parents=True,exist_ok=True); shutil.copy2(source/'references'/f/name,target/name)
        execution=publish_campaign(source.resolve(),generated)
        if not execution: raise ValueError(f'Unsupported thesis campaign: {source}')
        print(f"{execution['id']}: {sum(bool(r['replay_url']) for r in execution['runs'])} checked replays; {len(execution['replay_errors'])} errors",flush=True)
        for error in execution['replay_errors']: print(error,flush=True)
    catalog=read(generated/'study/index.json')
    errors=[x for e in catalog['executions'] for x in e['replay_errors']]
    if errors: raise SystemExit('Replay export errors: cleanup blocked')
    if args.prune:
        keep={e['id'] for e in catalog['executions']}|{r['id'] for e in catalog['executions'] for r in e['runs']}
        opt=generated/'optimization'
        for child in opt.iterdir():
            if child.is_dir() and child.name not in keep: shutil.rmtree(child)
        idx=read(opt/'index.json',{'campaigns':[]})
        idx['campaigns']=[{**r,'study_membership':'current_thesis'} for r in idx['campaigns'] if r['campaign_id'] in keep]
        atomic_json(opt/'index.json',idx)
        thesis=generated/'thesis'; tids={r['legacy_id'] for e in catalog['executions'] if e['series']=='journey' for r in e['runs'] if r.get('legacy_id')}
        if (thesis/'runs').exists():
            for child in (thesis/'runs').iterdir():
                if child.is_dir() and child.name not in tids: shutil.rmtree(child)
        idx=read(thesis/'index.json',{})
        idx['runs']=[r for r in idx.get('runs',[]) if r['id'] in tids]
        atomic_json(thesis/'index.json',idx)
        (thesis/'archive-index.json').unlink(missing_ok=True)
        if (generated/'evolution-live').is_dir(): shutil.rmtree(generated/'evolution-live')

if __name__=='__main__': main()
