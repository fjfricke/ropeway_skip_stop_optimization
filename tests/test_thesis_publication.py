"""Publication must preserve evidence, uncertainty, identities and exact demand times."""
import json
from pathlib import Path
from datetime import time
import pytest
from benchmarks.thesis_publication import publish_campaign, directory_for, series_for
from benchmarks.run_thesis_revised_journey_campaign import thesis_jobs
from benchmarks.thesis_replay_export import scenario_json, journey_payload
from ropeway_skip_stop_optimization.benchmarking.thesis_contract import THESIS_CONTRACT_ID


def test_final_matrix():
    jobs=thesis_jobs()
    assert len(jobs)==84
    assert sum(j['kind']=='reference' for j in jobs)==20
    assert sum(j['kind']=='relative' for j in jobs)==48
    assert sum(j['kind']=='constant' for j in jobs)==16


def test_catalog_resume_and_separate_execution_preserve_unknown(tmp_path):
    generated=tmp_path/'public'; source=tmp_path/'one';source.mkdir()
    state=dict(campaign_id='one',status='running',identity={'contract_id':THESIS_CONTRACT_ID},
        jobs=[dict(id='relative',kind='relative',family='f2',k=10,status='unknown',attempts=[{'directory':'runs/attempt_1'}])])
    (source/'campaign.json').write_text(json.dumps(state))
    first=publish_campaign(source,generated)
    assert first['runs'][0]['replay_url'] is None
    publish_campaign(source,generated)
    cat=json.loads((generated/'study/index.json').read_text())
    assert len(cat['executions'])==1
    state.update(campaign_id='two',status='prepared')
    second=tmp_path/'two';second.mkdir();(second/'campaign.json').write_text(json.dumps(state))
    publish_campaign(second,generated)
    assert len(json.loads((generated/'study/index.json').read_text())['executions'])==2
    assert (source/'campaign.json').read_text()==json.dumps({**state,'campaign_id':'one','status':'running'})


def test_relocation_and_unsupported_contract(tmp_path):
    assert directory_for(tmp_path/'campaign',{'directory':'/missing/host/campaign/runs/a'})==tmp_path/'campaign/runs/a'
    assert series_for({'identity':{'contract_id':'old'},'jobs':[]}) is None


def test_journey_checked_certificate_replay_without_solving():
    source=Path(__file__).resolve().parents[1]/'results/thesis_journey_geometric_20260919/runs/relative_25_f0_k10_skip_stop/attempt_001'
    if not source.exists(): pytest.skip('Saved thesis artifact not installed')
    result=json.loads((source/'result.json').read_text())
    scenario,movement,passengers,replay,_=journey_payload(source,result)
    groups=result['run']['fixed_k_problem_manifest']['demand_groups']
    assert sum(d['count'] for d in scenario['demands'])==sum(g['count'] for g in groups)
    anchor=time.fromisoformat(scenario['service_start_time'])
    anchor_seconds=anchor.hour*3600+anchor.minute*60+anchor.second
    for d,g in zip(scenario['demands'],groups):
        t=time.fromisoformat(d['arrival_time'])
        assert t.hour*3600+t.minute*60+t.second-anchor_seconds==g['release_time_seconds']
    assert any(time.fromisoformat(d['arrival_time']).second for d in scenario['demands'])
    assert sum(r['count'] for r in passengers['served_rides'])==sum(g['count'] for g in groups)
    assert {e['cabin_id'] for e in replay['events']}=={t['cabin_id'] for t in movement['trajectories']}
    assert replay['model_end_seconds']==2664
    result['run']['independent_validation_status']='unknown'
    with pytest.raises(ValueError): journey_payload(source,result)


def test_oip_copied_snapshot_uses_public_attempt_identity(tmp_path):
    generated=tmp_path/'public'
    source=tmp_path/'campaign'
    attempt=source/'trial'/'attempt_1'
    attempt.mkdir(parents=True)
    state=dict(campaign_id='campaign',status='complete',contract_id=THESIS_CONTRACT_ID,
               study_variant='fixed_mixes',k_values=[62],trials=[dict(id='trial',status='unknown',
               attempts=[dict(directory='trial/attempt_1',run_campaign_id='campaign__trial__a1')])])
    (source/'campaign.json').write_text(json.dumps(state))
    (attempt/'snapshot.json').write_text(json.dumps({'campaign_id':'internal-id','status':'unknown'}))
    publish_campaign(source,generated)
    target=generated/'optimization/campaign__trial__a1/snapshot.json'
    assert json.loads(target.read_text())['campaign_id']=='campaign__trial__a1'
    assert json.loads((attempt/'snapshot.json').read_text())['campaign_id']=='internal-id'
    # A cached/copy-only export must also restore the external identity.
    target.write_text(json.dumps({'campaign_id':'internal-id','status':'unknown'}))
    publish_campaign(source,generated)
    assert json.loads(target.read_text())['campaign_id']=='campaign__trial__a1'
