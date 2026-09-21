from dataclasses import replace
import json

import pytest

from ropeway_skip_stop_optimization.benchmarking.journey_mip_start import load_all_stop_start, needs_rerun
from ropeway_skip_stop_optimization.benchmarking.thesis_cases import (
    ExperimentCaseSpec, ThesisTopology, ThesisGeometry, ThesisDemandFamily,
    ThesisDemandProfile, ThesisObjective, prepare_fixed_k_experiment,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import run_ddd_fixed_k_arc_flow
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import DddFixedKOperatingMode as Mode


@pytest.mark.parametrize('upper,lower,expected',[(100,100,False),(100,100-1e-9,False),(100,99.999,True),(100,99.5,True),(None,0,True)])
def test_selection_includes_small_positive_gaps(upper,lower,expected):
    assert needs_rerun(dict(validated_upper_bound=upper,certified_lower_bound=lower)) is expected


@pytest.fixture(scope='module')
def prepared(tmp_path_factory):
    spec=ExperimentCaseSpec(ThesisTopology.T5R,ThesisGeometry.G500,ThesisDemandFamily.F2,
                           ThesisDemandProfile.P0,ThesisObjective.JOURNEY_TIME,6,15,0)
    kwargs=dict(cabins=2,time_limit_seconds=30,workers=1,seed=0)
    cfg,ref,_=prepare_fixed_k_experiment(spec,operating_mode=Mode.ALL_STOP,**kwargs)
    tc,target,_=prepare_fixed_k_experiment(spec,operating_mode=Mode.SKIP_STOP,**kwargs)
    result=run_ddd_fixed_k_arc_flow(cfg,prepared_run=ref).to_payload()
    assert result['validated_upper_bound'] is not None
    p=tmp_path_factory.mktemp('start')/'result.json';p.write_text(json.dumps(dict(run=result)))
    return p,ref,target,tc


def test_complete_start_keeps_assignment_and_allows_improvement(prepared):
    p,ref,target,cfg=prepared
    seed=load_all_stop_start(p,ref.problem,target.problem)
    assert seed.objective_value==pytest.approx(json.loads(p.read_text())['run']['validated_upper_bound'])
    result=run_ddd_fixed_k_arc_flow(replace(cfg,use_primal_start=True),prepared_run=target,primal_start=seed).to_payload()
    assert result['primal_seed_objective_value']==pytest.approx(seed.objective_value)
    assert result['validated_upper_bound'] < seed.objective_value - 1
    assert result['seed_kind']=='imported_all_stop'


@pytest.mark.parametrize('change',['demand','fraction','time','unserved'])
def test_import_rejects_corrupt_certificates(prepared,tmp_path,change):
    p,ref,target,_=prepared;r=json.loads(p.read_text());run=r['run']
    if change=='demand':run['fixed_k_problem_manifest']['demand_groups'][0]['count']+=1
    if change=='fraction':run['validated_passenger_plan']['served_rides'][0]['count']=0.5
    if change=='time':run['validated_passenger_plan']['served_rides'][0]['boarding_time_seconds']+=1
    if change=='unserved':run['validated_passenger_plan']['unserved_counts_by_demand_group_id']['fake']=1
    path=tmp_path/'bad.json';path.write_text(json.dumps(r))
    with pytest.raises(ValueError):load_all_stop_start(path,ref.problem,target.problem)


def test_validated_start_survives_missing_final_assignment(prepared,monkeypatch):
    from types import SimpleNamespace
    from ropeway_skip_stop_optimization.benchmarking import ddd_fixed_k_arc_flow as module
    from ropeway_skip_stop_optimization.optimization.ddd.primal_evaluation import DddPrimalEvaluationStatus
    p,ref,target,cfg=prepared
    seed=load_all_stop_start(p,ref.problem,target.problem)
    plan=json.loads(p.read_text())['run']['validated_passenger_plan']
    monkeypatch.setattr(module.DddEanPassengerPrimalEvaluator,'evaluate',
        lambda *args,**kwargs: SimpleNamespace(status=DddPrimalEvaluationStatus.UNKNOWN,objective_value=None,passenger_plan=None))
    result=run_ddd_fixed_k_arc_flow(replace(cfg,use_primal_start=True),prepared_run=target,
        primal_start=seed,primal_start_passenger_plan=plan).to_payload()
    assert result['validated_upper_bound']==pytest.approx(seed.objective_value)
    assert result['validated_passenger_plan']==plan
    assert result['independent_validation_status']=='feasible'


def test_live_summary_identifies_validated_import_without_native_result(tmp_path):
    from benchmarks.export_thesis_frontend import _run_summary
    (tmp_path/'mip_start.json').write_text(json.dumps(dict(validated=True,objective=123)))
    case=dict(topology='t5r',geometry='g500',demand_family='f2',demand_profile='p0',objective='journey_time',demand_total=6)
    summary=_run_summary(tmp_path,dict(status='running',run={}),case,dict(method='labelled_arc_flow',cabins=2))
    assert summary['primalSeedKind']=='imported_all_stop'
    assert summary['primalSeedObjective']==123
    assert not summary['validated'] and summary['journeyTime'] is None
