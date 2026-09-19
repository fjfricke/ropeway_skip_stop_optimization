"""K50 is a separate fleet sensitivity at unchanged K62 demand, without seeds."""
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_oip_fixed_mix_campaign import runner
from test_oip_pattern_waiting import _small_domain


def args_for(tmp_path, k=50):
    return SimpleNamespace(output=tmp_path/'k50', calibration=tmp_path/'calibration.json',
                           families=['f2','f3','f0'], formulations=['nowait_templates'],
                           reuse_reference_root=None, reference_time_limit_seconds=300,
                           trial_time_limit_seconds=300, workers=12, seed=0,
                           memory_limit_gib=32, fixed_k=k, comparison_campaign=tmp_path/'k62')


def test_fifteen_k50_mixtures_and_commands_have_no_reference_or_hint(tmp_path):
    module = runner(); args = args_for(tmp_path)
    manifest = module.manifest_for(args, {'f2':2266,'f3':5430,'f0':7606})
    assert manifest['k_values'] == [50]
    assert manifest['reference_runs'] == {}
    assert manifest['configuration']['reference_bound_stopping'] is False
    assert len(manifest['trials']) == 15
    assert [tuple(t['fixed_type_counts'].values()) for t in manifest['trials'][:5]] == list(module.K50_MIXES)
    for trial in manifest['trials']:
        assert sum(trial['fixed_type_counts'].values()) == 50
        assert trial['comparison_trial_id'].endswith('_k62')
        cmd = module.mixture_command(trial, None, tmp_path/'attempt', args)
        assert cmd[cmd.index('--fixed-k')+1] == '50'
        assert all(flag not in cmd for flag in ['--start-checkpoint','--all-stop-reference','--stop-if-cannot-beat-reference'])
        assert cmd[cmd.index('--time-limit')+1] == '300'
    # Original K62 preparation keeps its reference evaluations and cutoff policy.
    original = module.manifest_for(args_for(tmp_path,62), {'f2':2266,'f3':5430,'f0':7606})
    assert original['k_values'] == [62] and len(original['reference_runs']) == 3
    assert original['trials'][1]['stop_if_cannot_beat_reference']


def source_fixture(module, tmp_path):
    domain = _small_domain(0)
    groups = [(d.arrival_time.isoformat(),d.origin,d.destination,d.count) for d in domain.scenario.demands]
    loads = {f:sum(g[3] for g in groups) for f in ['f2','f3','f0']}
    args = args_for(tmp_path,62);args.output=tmp_path/'k62'
    manifest = module.manifest_for(args,loads);manifest['status']='complete'
    for t in manifest['trials']: t['status']='complete'
    args.output.mkdir()
    (args.output/'campaign.json').write_text(json.dumps(manifest))
    (args.output/'frozen_domains').mkdir()
    for f in loads:
        (args.output/'frozen_domains'/f'{f}.json').write_text(json.dumps({
            'demand_groups':groups, 'demand_fingerprint':hashlib.sha256(json.dumps(groups,separators=(',',':')).encode()).hexdigest(),
        }))
    return args.output,domain,loads


def test_comparison_rejects_changed_demand_and_incomplete_source(tmp_path):
    m=runner();path,domain,loads=source_fixture(m,tmp_path)
    comparison,_=m.load_k62_comparison(path,list(loads),loads)
    assert comparison['role']=='display_only_previous_fleet'
    with pytest.raises(ValueError,match='demand'):
        m.load_k62_comparison(path,list(loads),{**loads,'f2':loads['f2']+1})
    f=path/'campaign.json';d=json.loads(f.read_text());d['trials'][0]['status']='running';f.write_text(json.dumps(d))
    with pytest.raises(ValueError,match='missing completed'):
        m.load_k62_comparison(path,list(loads),loads)


def test_build_only_freezes_k50_without_starting_solves(tmp_path,monkeypatch):
    m=runner();source,domain,loads=source_fixture(m,tmp_path)
    source_before=(source/'campaign.json').read_bytes()
    monkeypatch.setattr(m,'verify_cal_o_adoption',lambda *a: {f:{'load_120':n,'source_hashes':{},'certificate':{}} for f,n in loads.items()})
    seen=[]
    def prepare(**kwargs):
        seen.append(kwargs['cabin_count'])
        return SimpleNamespace(domain=domain)
    monkeypatch.setattr(m,'prepare_oip_pattern_waiting_pilot',prepare)
    monkeypatch.setattr(m,'_run_one',lambda *a: pytest.fail('build-only must not start a solver'))
    monkeypatch.setattr(sys,'argv',['runner','--fixed-k','50','--comparison-campaign',str(source),
                                   '--output',str(tmp_path/'new'),'--frontend-root',str(tmp_path/'frontend'),'--build-only'])
    m.main()
    d=json.loads((tmp_path/'new'/'campaign.json').read_text())
    assert seen == [50,50,50]
    assert d['status']=='prepared' and len(d['trials'])==15 and not d['reference_runs']
    assert all(not t['attempts'] and t['status']=='planned' for t in d['trials'])
    assert (source/'campaign.json').read_bytes()==source_before
    assert json.loads((tmp_path/'frontend'/'new'/'snapshot.json').read_text())['k_values']==[50]
