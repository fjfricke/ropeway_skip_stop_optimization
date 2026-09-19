"""Fresh Journey dependencies and publishing must preserve uncertainty."""
import json
from pathlib import Path

import pytest

from benchmarks.journey_live_export import publish
from benchmarks.run_thesis_revised_journey_campaign import save_and_publish
from ropeway_skip_stop_optimization.benchmarking.thesis_contract import THESIS_CONTRACT_ID
from ropeway_skip_stop_optimization.benchmarking.thesis_reruns import (
    PROOF_SCOPE, constant_demand_gate, journey_jobs,
)


def references(tmp_path, capacities):
    jobs = {j['id']: j for j in journey_jobs()}
    for k, n in capacities.items():
        folder = tmp_path / str(k)
        folder.mkdir()
        result = dict(run=dict(cabins=k, proof_scope=PROOF_SCOPE, capacity_proven=True,
            proven_feasible_demand=n, proven_infeasible_demand=n + 1,
            probes=[dict(demand=d, outcome=o, case=dict(thesis_contract_id=THESIS_CONTRACT_ID,
                continuation_tick=300_000_000, problem_fingerprint=f'case-{d}'))
                for d, o in ((n, 'feasible'), (n + 1, 'infeasible'))]))
        (folder / 'result.json').write_text(json.dumps(result))
        jobs[f'reference_f2_k{k}'].update(status='complete', attempts=[dict(directory=str(folder))])
    return jobs


def test_constant_gate_requires_all_three_refs_and_preserves_load(tmp_path):
    jobs = references(tmp_path, {20: 70, 25: 90, 30: 101})
    gate = constant_demand_gate('f2', jobs)
    assert gate['status'] == 'passed' and gate['demand'] == 50
    assert set(gate['evidence']) == {'20', '25', '30'}
    jobs['reference_f2_k25']['status'] = 'failed'
    assert constant_demand_gate('f2', jobs)['status'] == 'pending_reference'


def test_constant_gate_blocks_entire_family_if_low_k_cannot_serve(tmp_path):
    jobs = references(tmp_path, {20: 49, 25: 60, 30: 101})
    gate = constant_demand_gate('f2', jobs)
    assert gate['status'] == 'blocked_constant_demand'
    assert gate['demand'] == 50  # Do not silently lower the experiment's demand.


def test_unknown_probe_never_passes_gate(tmp_path):
    jobs = references(tmp_path, {20: 70, 25: 90, 30: 101})
    path = tmp_path / '20/result.json'
    result = json.loads(path.read_text())
    result['run']['probes'][1]['outcome'] = 'unknown'
    path.write_text(json.dumps(result))
    assert constant_demand_gate('f2', jobs)['status'] == 'pending_reference'


def test_live_export_creates_detail_before_result_and_preserves_native_status(tmp_path):
    output, frontend = tmp_path / 'campaign', tmp_path / 'frontend'
    directory = output / 'runs/relative/attempt_001'
    directory.mkdir(parents=True)
    case = dict(topology='t5r', geometry='g500', demand_family='f2', demand_profile='p0',
                objective='journey_time', demand_total=50)
    (directory / 'case_spec.json').write_text(json.dumps(case))
    (directory / 'arguments.json').write_text(json.dumps(dict(method='labelled_arc_flow', cabins=20, operating_mode='skip_stop')))
    (directory / 'events.jsonl').write_text(json.dumps(dict(kind='progress', solver_incumbent=100, certified_lower_bound=80, runner_elapsed_seconds=3))+'\n')
    job = dict(id='relative_f2', family='f2', k=20, kind='relative', mode='skip_stop',
               demand=50, status='running', attempts=[dict(directory=str(directory))])
    state = dict(campaign_id='campaign', identity=dict(contract_id=THESIS_CONTRACT_ID), status='running', jobs=[job])
    (output / 'campaign.json').write_text(json.dumps(state))
    (frontend / 'optimization').mkdir(parents=True)
    (frontend / 'optimization/index.json').write_text(json.dumps(dict(campaigns=[dict(campaign_id='other')])))
    publish(output, state, frontend)
    snapshot = json.loads((frontend / 'optimization/campaign/snapshot.json').read_text())
    row = snapshot['journey_jobs'][0]
    assert row['validated_objective'] is None
    assert row['native_incumbent'] == 100 and row['lower_bound'] == 80 and row['gap'] == .2
    assert row['detail_url'].startswith('/thesis?run=')
    slug = row['detail_url'].split('=')[1]
    detail = frontend / f'thesis/runs/{slug}/detail.json'
    assert detail.is_file()
    assert json.loads((frontend / 'thesis/index.json').read_text())['runs'][0]['status'] == 'running'
    assert len(json.loads((frontend / 'optimization/index.json').read_text())['campaigns']) == 2
    (directory / 'result.json').write_text(json.dumps(dict(method='labelled_arc_flow', run=dict(
        status='complete', independent_validation_status='feasible', independent_validation_objective=100,
        certified_lower_bound=80))))
    job['status'] = state['status'] = 'complete'
    (output / 'campaign.json').write_text(json.dumps(state))
    publish(output, state, frontend)
    row = json.loads((frontend / 'optimization/campaign/snapshot.json').read_text())['journey_jobs'][0]
    assert row['validated_objective'] == 100


def test_display_failure_preserves_campaign_state(tmp_path, monkeypatch):
    from benchmarks import run_thesis_revised_journey_campaign as runner
    monkeypatch.setattr(runner, 'publish', lambda *a: (_ for _ in ()).throw(OSError('disk unavailable')))
    state = dict(status='complete', jobs=[])
    save_and_publish(tmp_path / 'campaign.json', state, tmp_path / 'frontend')
    saved = json.loads((tmp_path / 'campaign.json').read_text())
    assert saved['status'] == 'complete'
    assert saved['live_error'] == 'disk unavailable'


def test_export_keeps_previously_published_history(tmp_path):
    from benchmarks.export_thesis_frontend import export
    output = tmp_path / 'frontend'
    output.mkdir()
    old = dict(id='old', groupId='historical', status='complete', contractId='old', studyMembership='archive')
    (output / 'archive-index.json').write_text(json.dumps(dict(runs=[old])))
    export((tmp_path / 'empty',), output, preserve_existing=True)
    assert json.loads((output / 'archive-index.json').read_text())['runs'] == [old]


def test_completed_calibration_does_not_shadow_previous_index(tmp_path):
    from benchmarks.export_thesis_frontend import export
    source = tmp_path / 'campaign/run'
    source.mkdir(parents=True)
    case = dict(topology='t5r', geometry='g500', demand_family='f0', demand_profile='p0',
                objective='journey_time', demand_total=1021, thesis_contract_id=THESIS_CONTRACT_ID)
    (source / 'case_spec.json').write_text(json.dumps(case))
    (source / 'arguments.json').write_text(json.dumps(dict(method='all_stop_phase', cabins=10)))
    (source / 'result.json').write_text(json.dumps(dict(run=dict(
        schema='fixed_k_capacity_search_v1', cabins=10, capacity_proven=True,
        proven_feasible_demand=1020, proven_infeasible_demand=1021, probes=[]))))
    dest = tmp_path / 'frontend'
    first = export((source.parent,), dest, preserve_existing=True)
    second = export((source.parent,), dest, preserve_existing=True)
    assert len(first['runs']) == len(second['runs']) == 1
    assert second['runs'][0]['status'] == 'complete'
    assert second['runs'][0]['reference']['capacityProven']


def test_resume_skips_deferred_jobs_without_launching_solver(tmp_path, monkeypatch):
    import sys
    from benchmarks import run_thesis_revised_journey_campaign as runner
    output = tmp_path / 'campaign'
    output.mkdir()
    identity = dict(contract_id=THESIS_CONTRACT_ID, source_digest='test', solver_versions={})
    monkeypatch.setattr(runner, 'source_digest', lambda root: 'test')
    monkeypatch.setattr(runner, 'solver_versions', lambda: {})
    monkeypatch.setattr(runner, 'publish', lambda *a: None)
    monkeypatch.setattr(runner, 'run_and_publish', lambda *a: pytest.fail('deferred solver started'))
    jobs = journey_jobs()
    for job in jobs:
        job['status'] = 'deferred' if job['kind'] != 'reference' and job['k'] in (15, 25) else 'complete'
    state = dict(identity=identity, status='running', jobs=jobs, execution_started_unix=1, deadline_unix=1)
    (output / 'campaign.json').write_text(json.dumps(state))
    monkeypatch.setattr(sys, 'argv', ['runner', '--output-dir', str(output), '--run', '--_worker'])
    runner.main()
    assert json.loads((output / 'campaign.json').read_text())['status'] == 'complete'


def test_dynamic_deferral_keeps_active_and_finished_attempts(tmp_path):
    from benchmarks.run_thesis_revised_journey_campaign import apply_control
    jobs = [dict(id=str(i), status=status, attempts=attempts) for i,status,attempts in (
        (0,'pending_reference',[]), (1,'running',[{}]), (2,'complete',[{}]))]
    (tmp_path/'control.json').write_text(json.dumps(dict(deferred_job_ids=['0','1','2'],reason='User deferral')))
    apply_control(tmp_path,dict(jobs=jobs))
    assert [j['status'] for j in jobs] == ['deferred','running','complete']
