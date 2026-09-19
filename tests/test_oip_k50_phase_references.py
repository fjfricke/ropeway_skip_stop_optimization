import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_oip_pattern_waiting import _small_domain


def runner():
    p=Path(__file__).parents[1]/'benchmarks/run_oip_k50_phase_references.py'
    spec=importlib.util.spec_from_file_location('k50_phase_refs',p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m


def fixture(m,tmp_path,monkeypatch):
    source=tmp_path/'source';source.mkdir();(source/'frozen_domains').mkdir()
    parent={'campaign_id':'k50','status':'complete','k_values':[50],'load_contract':m.LOADS,'trials':[]}
    (source/'campaign.json').write_text(json.dumps(parent))
    domain=_small_domain(0)
    groups=[[d.arrival_time.isoformat(),d.origin,d.destination,d.count] for d in domain.scenario.demands]
    for family in m.FAMILIES:
        (source/'frozen_domains'/f'{family}.json').write_text(json.dumps({'demand_groups':groups,
            'comparison_fingerprint':domain.comparison_fingerprint,'headway_contract':m.HEADWAY_CONTRACT}))
    monkeypatch.setattr(m,'prepare_oip_pattern_waiting_pilot',lambda **kw:SimpleNamespace(domain=domain))
    return source,domain


def test_build_only_preserves_source_and_publishes_three_planned_references(tmp_path,monkeypatch):
    m=runner();source,domain=fixture(m,tmp_path,monkeypatch)
    original=(source/'campaign.json').read_bytes();out=tmp_path/'refs';front=tmp_path/'front'
    monkeypatch.setattr(m,'_run_one',lambda *a:pytest.fail('build-only called solver'))
    monkeypatch.setattr(sys,'argv',['run','--source-campaign',str(source),'--output',str(out),'--frontend-root',str(front),'--build-only'])
    m.main();manifest=json.loads((out/'campaign.json').read_text())
    assert len(manifest['reference_runs'])==3
    assert all(t['status']=='planned' and not t['attempts'] for t in manifest['reference_runs'].values())
    assert (source/'campaign.json').read_bytes()==original
    display=json.loads((front/'k50/snapshot.json').read_text())
    assert display['status']=='complete' and display['trials']==[]
    assert display['supplementary_phase_references']['status']=='prepared'
    for f,n in m.LOADS.items():
        cmd=m.command(f,tmp_path/f)
        assert cmd[cmd.index('--fixed-k')+1]=='50'
        assert cmd[cmd.index('--demand-total')+1]==str(n)
        assert '--start-checkpoint' not in cmd


def test_contract_mismatch_rejected(tmp_path,monkeypatch):
    m=runner();source,_=fixture(m,tmp_path,monkeypatch)
    p=source/'frozen_domains/f2.json';j=json.loads(p.read_text());j['comparison_fingerprint']='wrong';p.write_text(json.dumps(j))
    with pytest.raises(ValueError,match='frozen K50'):m.prepare(source)


def test_resume_runs_only_references_and_retains_unknown(tmp_path,monkeypatch):
    m=runner();source,domain=fixture(m,tmp_path,monkeypatch)
    out=tmp_path/'refs';front=tmp_path/'front';original=(source/'campaign.json').read_bytes()
    base=['run','--source-campaign',str(source),'--output',str(out),'--frontend-root',str(front)]
    monkeypatch.setattr(sys,'argv',base+['--build-only']);m.main()
    calls=[]
    def solve(cmd,directory,seconds,args):
        f=cmd[cmd.index('--family')+1];calls.append(f);assert seconds==300
        if f=='f3':
            (directory/'phase_search.json').write_text(json.dumps({'status':'UNKNOWN','served_upper_bound':5000}))
            return {'exit_code':1}
        (directory/'result.json').write_text(json.dumps({'validation_status':'valid','served_passengers':12,
            'journey_time_seconds':100,'served_upper_bound':15,'served_optimal_over_phase':False,'common_phase_seconds':0}))
        (directory/'manifest.json').write_text(json.dumps({'fixed_k':50,'comparison_fingerprint':domain.comparison_fingerprint}))
        return {'exit_code':0}
    monkeypatch.setattr(m,'_run_one',solve);monkeypatch.setattr(m,'_publish_run',lambda *a:None)
    monkeypatch.setattr(sys,'argv',base+['--run','--resume']);m.main()
    assert calls==list(m.FAMILIES)
    manifest=json.loads((out/'campaign.json').read_text());assert manifest['reference_runs']['f3']['status']=='unknown'
    assert manifest['reference_runs']['f3']['served'] is None
    calls.clear();m.main();assert calls==['f3']
    assert (source/'campaign.json').read_bytes()==original
