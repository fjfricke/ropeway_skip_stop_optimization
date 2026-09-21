"""Build submission views in isolation, then install only complete exports."""
from argparse import Namespace
from copy import deepcopy
from pathlib import Path
import shutil
import tempfile

from ropeway_skip_stop_optimization.benchmarking.frontend_results import atomic_json
from ropeway_skip_stop_optimization.submission import CAMPAIGNS, read, verify_manifest


def finalize_selection(generated, manifest):
    catalog = read(generated/'study/index.json')
    catalog['executions'] = [e for e in catalog['executions'] if e['id'] != 'thesis_journey_selected']
    executions = {e['id']: e for e in catalog['executions']}
    original, replacement = (executions[c] for c in CAMPAIGNS[:2])
    selected = deepcopy(original)
    selected.update(id='thesis_journey_selected', label='Journey · reported selection',
                    url='/optimization/thesis_journey_selected', original=True)
    replace_ids = {r['id'] for r in manifest['journey_selection'] if r['replacement']}
    selected['runs'] = [r for r in original['runs'] if r.get('run_id') not in replace_ids] + replacement['runs']
    for execution in (original, replacement):
        execution['original'] = False
    catalog['executions'].append(selected)
    catalog['submission_code_commit'] = manifest['code_commit']
    checks = {r['id']: r for r in manifest['service_selection'] if r['additional_contract_check']}
    for execution in catalog['executions']:
        if execution['series'].startswith('oip_'):
            execution['passenger_contract'] = 'Same cabin; later destination STOP allowed by the service deadline.'
        for run in execution['runs']:
            if run.get('run_id') in checks:
                run['contract_note'] = 'Rechecked under the service contract: later destination STOPs are allowed; Journey uses the first destination visit.'
    # Frozen replay checks refer to raw result hashes, not host-dependent mtimes.
    audits = {r['id']: r for r in manifest.get('replay_checks', [])}
    file_hashes = {r['path']: r['sha256'] for r in manifest.get('files', [])}
    selected_ids = {r['id'] for e in catalog['executions'] if e['original'] for r in e['runs'] if r.get('latest', True)}
    published_audit = {}
    for execution in catalog['executions']:
        for run in execution['runs']:
            audit = audits.get(run['id'])
            if not audit: continue
            if file_hashes.get(audit['result_file']) != audit['sha256']:
                raise ValueError(f'Replay check source differs: {run["id"]}')
            if audit['status'] != 'safe':
                if run['id'] in selected_ids:
                    raise ValueError(f'Reported timetable fails replay check: {run["id"]}')
                run['contract_note'] = 'Historical attempt: replay spacing check failed. This attempt is superseded and is not part of the reported selection.'
            published_audit[run['id']] = {**audit, 'source_stamp': run.get('replay_stamp')}
    atomic_json(generated/'study/replay-audit.json', list(published_audit.values()))
    atomic_json(generated/'study/index.json', catalog)
    snapshot = read(generated/'optimization'/CAMPAIGNS[0]/'snapshot.json')
    newer = read(generated/'optimization'/CAMPAIGNS[1]/'snapshot.json')
    by_id = {r['id']: r for r in newer['journey_jobs']}
    snapshot['journey_jobs'] = [by_id.get(r['id'], r) for r in snapshot['journey_jobs']]
    snapshot.update(campaign_id=selected['id'], label=selected['label'])
    atomic_json(generated/'optimization'/selected['id']/'snapshot.json', snapshot)
    index_path = generated/'optimization/index.json'
    index = read(index_path)
    index['campaigns'] = [c for c in index['campaigns'] if c['campaign_id'] != selected['id']]
    index['campaigns'].append({k:v for k,v in snapshot.items() if k not in ('journey_jobs','trials','events','constant_gates')})
    atomic_json(index_path, index)
    # K50 stored the then-current K62 comparison. Display the submitted latest
    # attempts, while keeping that original snapshot in the immutable raw data.
    k50_path = generated/'optimization'/CAMPAIGNS[3]/'snapshot.json'
    k62_path = generated/'optimization'/CAMPAIGNS[2]/'snapshot.json'
    if k50_path.exists() and k62_path.exists():
        k50, k62 = read(k50_path), read(k62_path)
        comparison = k50.get('comparison_campaign')
        if comparison:
            latest = {r['trial_id']: r for r in k62['trials']}
            comparison['trials'] = [{key: latest[row['trial_id']].get(key, value)
                                     for key, value in row.items()}
                                    for row in comparison['trials']]
            comparison['role'] = 'display_only_submission_selection'
            comparison['source_hashes'] = {
                CAMPAIGNS[2]+'/campaign.json': file_hashes[CAMPAIGNS[2]+'/campaign.json']}
            atomic_json(k50_path, k50)
    atomic_json(generated/'study/submission-selection.json', {
        'journey': manifest['journey_selection'], 'service': manifest['service_selection']})


def export_submission(manifest_path: Path, generated: Path):
    # This happens before touching generated data; old exports cannot mask errors.
    print('Verifying raw submission files…', flush=True)
    manifest = verify_manifest(manifest_path)
    root = manifest_path.resolve().parent
    generated = generated.resolve()
    generated.parent.mkdir(parents=True, exist_ok=True)
    try:
        from .thesis_publication import export_sources
    except ImportError:
        from thesis_publication import export_sources
    with tempfile.TemporaryDirectory(prefix='.submission-export-', dir=generated.parent) as temporary:
        staging = Path(temporary)
        export_sources(Namespace(frontend_root=staging,
            source=[root/c for c in CAMPAIGNS[:4]],
            calibration_source=[root/CAMPAIGNS[4]], supplement=[root/CAMPAIGNS[5]], prune=False))
        finalize_selection(staging, manifest)
        generated.mkdir(parents=True, exist_ok=True)
        # Replace only generated study outputs; preserve unrelated scenario examples.
        for name in ('study', 'optimization', 'thesis'):
            destination = generated/name
            backup = staging/(name+'.previous')
            if destination.exists(): destination.rename(backup)
            try:
                (staging/name).rename(destination)
            except BaseException:
                if backup.exists(): backup.rename(destination)
                raise
            if backup.exists(): shutil.rmtree(backup)
    print('Submission ready: http://127.0.0.1:5174/thesis', flush=True)
