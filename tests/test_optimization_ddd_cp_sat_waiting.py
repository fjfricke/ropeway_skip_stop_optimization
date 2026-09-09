import json

import pytest
from ortools.sat.python import cp_model

from test_optimization_ddd_cp_sat_integrated import tiny_problem, fixed_ip
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig, DddIntegratedCpSatOptimizer, build_ddd_integrated_cp_sat)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_passenger import DddCpSatCostEncoding
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    validate_ddd_cp_sat_incumbent, validate_ddd_cp_sat_domain, stable_fingerprint,
    write_ddd_cp_sat_checkpoint, read_ddd_cp_sat_checkpoint)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution, DddReferenceTrajectory, build_ddd_reference_visit,
    validate_ddd_reference_solution)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import ddd_seconds_to_tick, ddd_tick_to_seconds
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup


def enumerate_waiting(problem):
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    policy = problem.resolved_trajectory_problem.waiting_policy
    assert len(movement.starts) == 1
    start = movement.starts[0]
    def walk(state, tick, visits):
        if tick > movement.operational_end_tick:
            sol = DddReferenceSolution((DddReferenceTrajectory(start.cabin_id, tuple(visits)),))
            try:
                validate_ddd_reference_solution(movement, sol, waiting_policy=policy)
            except ValueError:
                return
            yield sol
            return
        for option in movement.route_options_by_state_id[state]:
            for wait in (policy.wait_values_seconds(option.station_id) if option.decision.value == 'stop' else (0,)):
                visit = build_ddd_reference_visit(start=start, visit_index=len(visits),
                    switch_time_seconds=ddd_tick_to_seconds(tick), option=option,
                    operational_end_seconds=movement.operational_end_seconds, wait_seconds=wait, tolerance_seconds=1e-9)
                yield from walk(option.to_state_id, ddd_seconds_to_tick(visit.next_switch_time_seconds), visits + [visit])
    return tuple(walk(start.state_id, start.time_tick, []))


@pytest.mark.parametrize('encoding', list(DddCpSatCostEncoding))
def test_waiting_global_matches_exhaustive_movements_and_integer_assignment(encoding):
    scenario, problem = tiny_problem(horizon=75, maximum_wait=2, waiting_step=1,
        groups=(EanDemandGroup('late', 'A', 'B', 23, 2),))
    solutions = enumerate_waiting(problem)
    expected = min(fixed_ip(scenario, problem, sol)[0] for sol in solutions)
    result = DddIntegratedCpSatOptimizer(DddIntegratedCpSatConfig(
        total_time_limit_seconds=10, cost_encoding=encoding)).solve(problem)
    assert result.proven_optimal
    assert result.validated_upper_bound == pytest.approx(expected, abs=1e-6)
    assert sum(result.incumbent.ride_counts.values()) == 2
    assert result.incumbent.solution.trajectories[0].visits[0].wait_seconds == 1


def test_microsecond_wait_admits_release_at_actual_departure_and_round_trips(tmp_path, monkeypatch):
    scenario, problem = tiny_problem(horizon=80, maximum_wait=1200, waiting_step=1e-6,
        groups=(EanDemandGroup('late', 'A', 'B', 22.090910, 2),))
    # Production validation must not enumerate the 1.2-billion-value grid.
    from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import DddTrajectoryWaitingPolicy
    monkeypatch.setattr(DddTrajectoryWaitingPolicy, 'wait_values_seconds', lambda *a: pytest.fail('enumerated wait grid'))
    result = DddIntegratedCpSatOptimizer(DddIntegratedCpSatConfig(total_time_limit_seconds=10)).solve(problem)
    assert result.proven_optimal
    assert sum(result.incumbent.ride_counts.values()) == 2
    assert result.incumbent.solution.trajectories[0].visits[0].wait_seconds == 1e-6
    assert fixed_ip(scenario, problem, result.incumbent.solution)[0] == pytest.approx(result.validated_upper_bound, abs=1e-6)
    path = tmp_path/'wait.json'
    write_ddd_cp_sat_checkpoint(path, problem=problem, manifest=result.domain_manifest, incumbent=result.incumbent)
    restored = read_ddd_cp_sat_checkpoint(path, problem=problem, manifest=result.domain_manifest)
    assert restored.solution == result.incumbent.solution
    fixed = DddIntegratedCpSatOptimizer().solve(problem, fixed_movement=restored.solution)
    assert fixed.proven_optimal and fixed.validated_upper_bound == result.validated_upper_bound
    assert fixed.incumbent.solution == restored.solution
    payload = json.loads(path.read_text())
    payload['incumbent']['trajectory_supports'][0]['wait_ticks'][0] += 1
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='wait representations'):
        read_ddd_cp_sat_checkpoint(path, problem=problem, manifest=result.domain_manifest)


@pytest.mark.parametrize('second_decision, feasible', [('stop', False), ('skip', True)])
def test_wait_position_blocks_follower_but_does_not_block_separate_bypass(second_decision, feasible):
    _, problem = tiny_problem(horizon=60, starts=(0,15), maximum_wait=20, groups=())
    built = build_ddd_integrated_cp_sat(problem)
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    options = {o.id:o for o in movement.route_options}
    for (c, v, oid), lit in built.movement.selection_by_key.items():
        if v == 0:
            built.movement.model.add(lit == int(options[oid].decision.value == ('stop' if c == 0 else second_decision)))
    built.movement.model.add(built.movement.wait_steps_by_key[0,0] == 20)
    solver = cp_model.CpSolver(); solver.parameters.max_time_in_seconds=5
    status = solver.solve(built.movement.model)
    assert (status in (cp_model.FEASIBLE,cp_model.OPTIMAL)) == feasible
    if not feasible:
        assert status == cp_model.INFEASIBLE


def test_waiting_can_extend_past_horizon_but_cannot_fake_passenger_service():
    _, problem = tiny_problem(horizon=80, maximum_wait=1200, waiting_step=1e-6,
        groups=(EanDemandGroup('ab','A','B',0,2),))
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    start = movement.starts[0]
    stop = next(o for o in movement.route_options_by_state_id[start.state_id] if o.decision.value=='stop')
    visit = build_ddd_reference_visit(start=start,visit_index=0,switch_time_seconds=0,option=stop,
        operational_end_seconds=80,wait_seconds=1200,tolerance_seconds=1e-9)
    solution = DddReferenceSolution((DddReferenceTrajectory(0,(visit,)),))
    result = DddIntegratedCpSatOptimizer().solve(problem, fixed_movement=solution)
    assert result.proven_optimal
    assert result.incumbent.unserved_counts['ab'] == 2
    assert result.validated_upper_bound == 160
    assert result.incumbent.solution.trajectories[0].visits[0].next_switch_time_seconds > 1200
    # Even an optimal finite problem with a long terminal wait proves no
    # continuation after H; consumers must not infer it from OPTIMAL.
    assert result.to_payload()['horizon_contract'] == 'closed_event_entry_horizon_v1'
    assert result.to_payload()['continuation_status'] == 'NOT_PROVEN'


def test_wait_bound_and_grid_change_domain_identity():
    _, a = tiny_problem(maximum_wait=2, waiting_step=1)
    _, b = tiny_problem(maximum_wait=2, waiting_step=.5)
    _, c = tiny_problem(maximum_wait=3, waiting_step=1)
    assert len({stable_fingerprint(validate_ddd_cp_sat_domain(p)) for p in (a,b,c)}) == 3


def test_wait_at_destination_does_not_delay_alighting_or_charge_it_twice():
    scenario, problem = tiny_problem(horizon=80, maximum_wait=1200, waiting_step=1e-6,
        groups=(EanDemandGroup('ab','A','B',0,2),))
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    start = movement.starts[0]
    a = next(o for o in movement.route_options_by_state_id[start.state_id] if o.decision.value=='stop')
    first = build_ddd_reference_visit(start=start,visit_index=0,switch_time_seconds=0,option=a,
        operational_end_seconds=80,wait_seconds=5,tolerance_seconds=1e-9)
    b = next(o for o in movement.route_options_by_state_id[a.to_state_id] if o.decision.value=='stop')
    second = build_ddd_reference_visit(start=start,visit_index=1,switch_time_seconds=first.next_switch_time_seconds,option=b,
        operational_end_seconds=80,wait_seconds=30,tolerance_seconds=1e-9)
    solution=DddReferenceSolution((DddReferenceTrajectory(0,(first,second)),))
    result=DddIntegratedCpSatOptimizer().solve(problem,fixed_movement=solution)
    expected=2*(first.next_switch_time_seconds+b.platform_entry_offset_seconds)
    assert result.proven_optimal
    assert result.validated_upper_bound==pytest.approx(expected,abs=1e-6)
    assert fixed_ip(scenario,problem,solution)[0]==pytest.approx(expected,abs=1e-6)
    assert sum(result.incumbent.ride_counts.values())==2
