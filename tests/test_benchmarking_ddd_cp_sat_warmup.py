from dataclasses import replace

import pytest
from ortools.sat.python import cp_model

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig, prepare_ddd_fixed_k_arc_flow_run,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_cp_sat_waiting import with_exit_waiting
from ropeway_skip_stop_optimization.benchmarking.ddd_cp_sat_warmup import with_empty_warmup
from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_cp_sat import (
    DddFixedKCpSatRunConfig, run_ddd_fixed_k_cp_sat,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import (
    DddFixedKOperatingMode, DddFixedKStartPolicy,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig, DddIntegratedCpSatOptimizer, build_ddd_integrated_cp_sat,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import validate_ddd_cp_sat_domain
from ropeway_skip_stop_optimization.optimization.ddd.reference import DddReferenceSolution

EXAMPLE = 'five_station_circle_cw_half_skip_no_wait_headway_b_v0'


@pytest.fixture(scope='module')
def pair():
    original = prepare_ddd_fixed_k_arc_flow_run(DddFixedKArcFlowRunConfig(EXAMPLE, 39,
        DddFixedKOperatingMode.SKIP_STOP, start_policy=DddFixedKStartPolicy.BALANCED_REFERENCE))
    original = with_exit_waiting(original, maximum_seconds=1200, step_seconds=1e-6)
    return original, with_empty_warmup(original, seconds=300)


def test_warmup_preserves_snapshot_physics_and_service_duration(pair):
    original, warm = pair
    a, b = original.problem, warm.problem
    assert a.boundary_context == b.boundary_context
    assert a.artifact.cabin_starts == b.artifact.cabin_starts
    assert a.resolved_trajectory_problem.waiting_policy == b.resolved_trajectory_problem.waiting_policy
    ma, mb = a.resolved_trajectory_problem.structural_movement_problem, b.resolved_trajectory_problem.structural_movement_problem
    assert ma.route_options == mb.route_options
    assert ma.resources == mb.resources
    assert all(y.max_visit_count > x.max_visit_count for x, y in zip(ma.starts, mb.starts))
    assert b.artifact.config.horizon_seconds == b.artifact.config.model_end_seconds == 1500
    assert sum(g.count for g in b.passenger_build.demand_groups) == 1280
    assert all(g.release_time_seconds == 300 for g in b.passenger_build.demand_groups)
    assert sum(g.count * (b.artifact.config.horizon_seconds - g.release_time_seconds)
               for g in b.passenger_build.demand_groups) == 1280 * 1200
    assert validate_ddd_cp_sat_domain(a) != validate_ddd_cp_sat_domain(b)
    assert warm.seed_trajectories == ()


def test_fixed_warmup_movement_cost_matches_independent_ip_and_rejects_early_boarding(pair):
    from test_optimization_ddd_cp_sat_integrated import fixed_ip
    _, warm = pair
    problem = warm.problem
    # Use a newly generated all-stop trajectory for one cabin: do not extend
    # an uncertified finite multi-cabin reference.
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import solution_from_cp_sat_payload
    original = prepare_ddd_fixed_k_arc_flow_run(DddFixedKArcFlowRunConfig(EXAMPLE, 1,
        DddFixedKOperatingMode.SKIP_STOP, start_policy=DddFixedKStartPolicy.BALANCED_REFERENCE))
    warm = with_empty_warmup(with_exit_waiting(original, maximum_seconds=1200, step_seconds=1e-6), seconds=300)
    problem = warm.problem
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    start = movement.starts[0]
    tick, state = start.time_tick, start.state_id
    ids, ticks = [], []
    while tick <= movement.operational_end_tick:
        option = next(o for o in movement.route_options_by_state_id[state] if o.decision.value == 'stop')
        ticks.append(tick); ids.append(option.id)
        tick += option.duration_tick; state = option.to_state_id
    solution = solution_from_cp_sat_payload(problem, {'trajectory_supports': [
        {'cabin_id': 0, 'route_option_ids': ids, 'switch_times_tick': ticks}]})
    result = DddIntegratedCpSatOptimizer(DddIntegratedCpSatConfig(
        total_time_limit_seconds=20)).solve(problem, fixed_movement=solution)
    assert result.solver_status == 'OPTIMAL'
    assert result.objective_constant_tick == 1280 * 1200 * 1000000
    ip_cost, _ = fixed_ip(warm.scenario, problem, solution)
    assert result.validated_upper_bound == pytest.approx(ip_cost, abs=1e-6)
    assert sum(result.incumbent.ride_counts.values()) > 0
    built = build_ddd_integrated_cp_sat(problem, fixed_movement=solution)
    candidate = next(q for q in problem.passenger_build.ride_candidates
                     if q.cabin_id == 0 and q.board_visit_index == 0)
    # Cabin 0's first stop departs well before t=300 in this fixed movement.
    built.movement.model.add(built.passengers.ride_count[candidate.id] >= 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10
    solver.parameters.num_search_workers = 1
    assert solver.solve(built.movement.model) == cp_model.INFEASIBLE


@pytest.mark.parametrize('seconds', [-1, float('inf'), float('nan'), 0.0000001, 86400])
def test_warmup_rejects_invalid_times(pair, seconds):
    with pytest.raises(ValueError):
        with_empty_warmup(pair[0], seconds=seconds)


def test_zero_warmup_is_identity(pair):
    assert with_empty_warmup(pair[0], seconds=0) is pair[0]


def test_runner_records_transformed_domain(tmp_path):
    result = run_ddd_fixed_k_cp_sat(DddFixedKCpSatRunConfig(EXAMPLE, 2, tmp_path,
        maximum_wait_seconds=1200, warmup_seconds=300, build_only=True))
    assert result['warmup_seconds'] == 300
    assert result['domain_manifest']['tick_horizons'] == [1500000000, 1500000000]
    assert result['solver_status'] == 'NOT_RUN'
