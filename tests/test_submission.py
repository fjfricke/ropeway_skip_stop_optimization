"""Submission selection and checks must not depend on the original host."""
import json
from pathlib import Path

import pytest

from ropeway_skip_stop_optimization.submission import (
    CAMPAIGNS, resolve_recorded, selected_journey, sha256, verify_manifest,
)


def test_rebase_even_when_original_exists(tmp_path):
    old = tmp_path/'old'/CAMPAIGNS[0]/'runs'/'one'
    old.mkdir(parents=True)
    new = tmp_path/'new folder'/CAMPAIGNS[0]
    assert resolve_recorded(new, str(old)) == new/'runs'/'one'
    assert resolve_recorded(new, 'runs/one') == new/'runs'/'one'
    with pytest.raises(ValueError, match='relocate'):
        resolve_recorded(new, '/somewhere/unrelated/data.json')
    with pytest.raises(ValueError, match='relative'):
        resolve_recorded(new, '../outside')


@pytest.fixture
def package(tmp_path):
    for c in CAMPAIGNS: (tmp_path/c).mkdir()
    jobs = [dict(id=f'case{i}', kind='relative', k=10, demand=20, status='complete',
                 attempts=[dict(directory=f'runs/case{i}')]) for i in range(64)]
    for c, rows in zip(CAMPAIGNS[:2], (jobs, jobs[:22])):
        (tmp_path/c/'campaign.json').write_text(json.dumps(dict(status='complete', jobs=rows)))
        for job in rows:
            p=tmp_path/c/job['attempts'][0]['directory']/'result.json'
            p.parent.mkdir(parents=True); p.write_text('{}')
    manifest=dict(schema=1, campaigns=list(CAMPAIGNS),
        journey_selection=selected_journey(tmp_path), service_selection=[],
        files=[dict(path=str(p.relative_to(tmp_path)),bytes=p.stat().st_size,sha256=sha256(p))
               for p in tmp_path.rglob('*') if p.is_file()])
    path=tmp_path/'submission_manifest.json'
    path.write_text(json.dumps(manifest))
    return path


def test_selection_and_portable_inventory(package):
    manifest=verify_manifest(package)
    assert len(manifest['journey_selection']) == 64
    assert sum(r['replacement'] for r in manifest['journey_selection']) == 22


@pytest.mark.parametrize('change', ['missing', 'changed', 'extra', 'selection'])
def test_broken_package_stops_export(package, change):
    target=package.parent/CAMPAIGNS[0]/'runs/case0/result.json'
    if change=='missing': target.unlink()
    if change=='changed': target.write_text('[]') # equal byte count; hash must catch this
    if change=='extra': (target.parent/'unexpected.json').write_text('{}')
    if change=='selection':
        m=json.loads(package.read_text()); m['journey_selection'][0]['replacement']=False
        package.write_text(json.dumps(m))
    with pytest.raises(ValueError): verify_manifest(package)


def test_invalid_replacement_is_rejected(package):
    path=package.parent/CAMPAIGNS[1]/'campaign.json'
    state=json.loads(path.read_text()); state['jobs'][0]['demand']=21
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match='replacement'): selected_journey(package.parent)


def test_published_selection_replaces_cases_without_hiding_history(tmp_path):
    from benchmarks.submission_export import finalize_selection
    def write(path, value):
        path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value))
    old_runs=[dict(id='old1',run_id='one'),dict(id='old2',run_id='two')]
    new_runs=[dict(id='new1',run_id='one')]
    executions=[dict(id=c,series='journey',label=c,original=True,runs=runs)
                for c,runs in zip(CAMPAIGNS[:2],(old_runs,new_runs))]
    write(tmp_path/'study/index.json',dict(executions=executions))
    for c, rows in zip(CAMPAIGNS[:2],([dict(id='one',value=1),dict(id='two',value=2)], [dict(id='one',value=3)])):
        write(tmp_path/'optimization'/c/'snapshot.json',dict(journey_jobs=rows))
    write(tmp_path/'optimization/index.json',dict(campaigns=[]))
    manifest=dict(code_commit='abc',journey_selection=[dict(id='one',replacement=True)],service_selection=[])
    finalize_selection(tmp_path,manifest)
    catalog=json.loads((tmp_path/'study/index.json').read_text())
    assert len(catalog['executions'])==3
    selected=next(e for e in catalog['executions'] if e['original'])
    assert {r['id'] for r in selected['runs']}=={'new1','old2'}
    assert catalog['executions'][0]['runs']==old_runs
    snapshot=json.loads((tmp_path/'optimization/thesis_journey_selected/snapshot.json').read_text())
    assert snapshot['journey_jobs']==[dict(id='one',value=3),dict(id='two',value=2)]
    manifest['files']=[dict(path='old.json',sha256='x')]
    manifest['replay_checks']=[dict(id='old1',status='unsafe',result_file='old.json',sha256='x')]
    finalize_selection(tmp_path,manifest)
    catalog=json.loads((tmp_path/'study/index.json').read_text())
    assert len(catalog['executions'])==3
    assert 'superseded' in catalog['executions'][0]['runs'][0]['contract_note']
    manifest['replay_checks'][0]['id']='new1'
    with pytest.raises(ValueError,match='Reported timetable'):
        finalize_selection(tmp_path,manifest)



def test_failed_verification_does_not_touch_existing_exports(package,tmp_path):
    from benchmarks.submission_export import export_submission
    generated=tmp_path/'generated'; generated.mkdir()
    sentinel=generated/'previous.txt'; sentinel.write_text('keep')
    (package.parent/CAMPAIGNS[0]/'campaign.json').unlink()
    with pytest.raises(ValueError,match='Missing'):
        export_submission(package,generated)
    assert sentinel.read_text()=='keep'
