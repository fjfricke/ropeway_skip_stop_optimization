from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_cp_sat import DddFixedKCpSatRunConfig,run_ddd_fixed_k_cp_sat
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import DddIntegratedCpSatConfig

EXAMPLE='five_station_circle_cw_half_skip_no_wait_headway_b_v0'


def test_build_only_reports_domain_without_claiming_bounds(tmp_path):
    result=run_ddd_fixed_k_cp_sat(DddFixedKCpSatRunConfig(EXAMPLE,2,tmp_path,build_only=True))
    assert result['solver_status']=='NOT_RUN'
    assert result['cp_lower_bound'] is None
    assert result['model_stats']['ride_candidates']>0
    assert not result['proven_optimal']
    saved=json.loads((tmp_path/'result.json').read_text())
    assert saved['domain_fingerprint']==result['domain_fingerprint']
    assert (tmp_path/'config.json').exists()


def test_cli_rejects_unsupported_waiting_and_objective(tmp_path):
    root=Path(__file__).parents[1]
    base=[sys.executable,str(root/'benchmarks/run_ddd_fixed_k_cp_sat.py'),'--example',EXAMPLE,'--cabins','2','--output-dir',str(tmp_path)]
    for extra in (['--waiting','1'],['--objective','waiting_time']):
        result=subprocess.run(base+extra,capture_output=True,text=True)
        assert result.returncode!=0


def test_runner_rejects_ambiguous_seed_inputs(tmp_path):
    config=DddFixedKCpSatRunConfig(EXAMPLE,2,tmp_path,primal_seed_result=Path('a'),resume_checkpoint=Path('b'))
    with pytest.raises(ValueError,match='one CP-SAT seed'):
        config.validate()


def test_checkpoint_solver_writes_validated_incumbent(tmp_path):
    result=run_ddd_fixed_k_cp_sat(DddFixedKCpSatRunConfig(EXAMPLE,2,tmp_path,
        solver=DddIntegratedCpSatConfig(total_time_limit_seconds=3,num_workers=1)))
    assert result['solver_status'] in ('FEASIBLE','OPTIMAL')
    assert result['incumbent'] is not None
    checkpoint=json.loads((tmp_path/'incumbent.json').read_text())
    assert checkpoint['incumbent']['objective_tick']==result['incumbent']['objective_tick']
    assert result['total_wall_seconds']>=result['solve_seconds']


def test_old_result_without_waits_is_checked_against_no_wait_physics(tmp_path):
    from test_optimization_ddd_cp_sat_integrated import tiny_problem
    from ropeway_skip_stop_optimization.optimization.ddd.reference import DddReferenceTrajectoryGenerator
    from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_cp_sat import _load_result_trajectories
    _,problem=tiny_problem()
    movement=problem.resolved_trajectory_problem.structural_movement_problem
    trajectory=DddReferenceTrajectoryGenerator().generate(movement).by_cabin_id[0][0]
    raw={'example_id':problem.artifact.scenario_id,'exact_active_cabin_count':1,
        'operating_mode':problem.operating_mode.value,'start_policy':problem.start_policy.value,
        'objective':problem.objective.value,'trajectory_supports':[{'cabin_id':0,
            'route_option_ids':[v.route_option_id for v in trajectory.visits],
            'switch_times_seconds':[v.switch_time_seconds for v in trajectory.visits]}]}
    assert _load_result_trajectories(tmp_path/'legacy.json',problem,raw)==(trajectory,)
    raw['trajectory_supports'][0]['switch_times_seconds'][1]+=0.1
    with pytest.raises(ValueError):
        _load_result_trajectories(tmp_path/'legacy.json',problem,raw)


def test_native_cp_result_can_seed_existing_arc_flow(tmp_path):
    from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
        prepare_ddd_fixed_k_arc_flow_run,DddFixedKArcFlowRunConfig,_load_ddd_fixed_k_arc_flow_result_seed)
    from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import DddFixedKOperatingMode,DddFixedKStartPolicy
    prepared=prepare_ddd_fixed_k_arc_flow_run(DddFixedKArcFlowRunConfig(EXAMPLE,2,
        DddFixedKOperatingMode.SKIP_STOP,start_policy=DddFixedKStartPolicy.BALANCED_REFERENCE))
    result=run_ddd_fixed_k_cp_sat(DddFixedKCpSatRunConfig(EXAMPLE,2,tmp_path,
        solver=DddIntegratedCpSatConfig(total_time_limit_seconds=3,num_workers=1)),prepared_run=prepared)
    trajectories,upper=_load_ddd_fixed_k_arc_flow_result_seed(tmp_path/'result.json',problem=prepared.problem)
    assert len(trajectories)==2
    assert upper==result['validated_upper_bound']


def test_waiting_lift_preserves_k39_snapshot_and_restores_prefix_exit_occupancy():
    from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
        prepare_ddd_fixed_k_arc_flow_run, DddFixedKArcFlowRunConfig)
    from ropeway_skip_stop_optimization.benchmarking.ddd_cp_sat_waiting import with_exit_waiting
    from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import DddFixedKOperatingMode, DddFixedKStartPolicy
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import validate_ddd_cp_sat_incumbent, validate_ddd_cp_sat_domain
    from ropeway_skip_stop_optimization.optimization.ddd.reference import DddReferenceSolution
    prepared = prepare_ddd_fixed_k_arc_flow_run(DddFixedKArcFlowRunConfig(EXAMPLE,39,
        DddFixedKOperatingMode.SKIP_STOP,start_policy=DddFixedKStartPolicy.BALANCED_REFERENCE))
    lifted = with_exit_waiting(prepared, maximum_seconds=1200,step_seconds=1e-6)
    a,b = prepared.problem,lifted.problem
    assert a.artifact.cabin_starts == b.artifact.cabin_starts
    assert a.passenger_build == b.passenger_build
    assert a.boundary_context.initial_states == b.boundary_context.initial_states
    added=set(b.boundary_context.resource_occurrences)-set(a.boundary_context.resource_occurrences)
    assert len(added)==1
    occupancy=next(iter(added))
    assert occupancy.cabin_id==0 and 'platform_exit' in occupancy.resource_id
    assert occupancy.follower_enter_time_seconds == pytest.approx(7.832536,abs=1e-6)
    validate_ddd_cp_sat_domain(b)
    validate_ddd_cp_sat_incumbent(b,DddReferenceSolution(lifted.seed_trajectories),{},provenance='lift regression')


def test_runner_supports_microsecond_waiting_grid(tmp_path):
    # Integration coverage, not a 3-second guarantee to find an incumbent.
    # The search may legitimately remain UNKNOWN at that short time limit.
    result = run_ddd_fixed_k_cp_sat(DddFixedKCpSatRunConfig(EXAMPLE,2,tmp_path,
        maximum_wait_seconds=1200,solver=DddIntegratedCpSatConfig(total_time_limit_seconds=10,num_workers=1)))
    assert result['incumbent'] is not None
    assert result['domain_manifest']['waiting_policy']['step_seconds']==1e-6
    assert result['model_stats']['free_wait_variables'] > 0
    assert 'wait_ticks' in result['incumbent']['trajectory_supports'][0]


def test_waiting_lift_keeps_all_stop_operating_mode(tmp_path):
    from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import DddFixedKOperatingMode
    result=run_ddd_fixed_k_cp_sat(DddFixedKCpSatRunConfig(EXAMPLE,2,tmp_path,
        operating_mode=DddFixedKOperatingMode.ALL_STOP, maximum_wait_seconds=1200,build_only=True))
    assert result['operating_mode']=='all_stop'
    assert all(o['decision']=='stop' for o in result['domain_manifest']['movement_core']['route_options'])
