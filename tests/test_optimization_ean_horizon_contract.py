from dataclasses import replace

import pytest
from ortools.sat.python import cp_model

from test_optimization_ean_movement_plan_validation import (
    _horizon_crossing_headway_artifact_and_plan,
    _platform_exit_wait_occupancy_artifact_and_plan,
)
from test_optimization_ddd_cp_sat_integrated import tiny_problem
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import build_ddd_integrated_cp_sat
from ropeway_skip_stop_optimization.optimization.ddd.ean_plan_adapter import DddReferenceToEanMovementPlanAdapter
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution, DddReferenceTrajectory, build_ddd_reference_visit,
    validate_ddd_reference_solution,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import EanHorizonFormulation
from ropeway_skip_stop_optimization.optimization.ean.horizon_audit import audit_ean_exact_horizon
from ropeway_skip_stop_optimization.optimization.ean.headway_separator import separate_all_headway_violations
from ropeway_skip_stop_optimization.optimization.ean.models import EanHeadwayPairScope
from ropeway_skip_stop_optimization.optimization.ean.plan import EanMovementPlan
from ropeway_skip_stop_optimization.optimization.ean.validation import validate_ean_movement_plan_against_artifact


@pytest.mark.parametrize("offset_tick", [-1, 0, 1])
@pytest.mark.parametrize("tolerance", [0, 1e-6, 1e-5])
@pytest.mark.parametrize("sparse", [False, True])
def test_wait_occupancy_activation_does_not_expand_with_feasibility_tolerance(offset_tick, tolerance, sparse):
    artifact, plan = _horizon_crossing_headway_artifact_and_plan()
    # Second wait entry is H=101; both clears are after H. Shift only the
    # second whole visit, keeping every timing relation and boundary intact.
    delta = offset_tick / 1e6
    visit = plan.trajectories[1].visits[0]
    shifted = replace(visit, **{
        field: getattr(visit, field) + delta for field in (
            "switch_time_seconds", "platform_entry_time_seconds", "platform_exit_time_seconds",
            "exit_switch_time_seconds", "next_switch_time_seconds",
        )
    })
    artifact = replace(artifact, cabin_starts=(
        artifact.cabin_starts[0], replace(artifact.cabin_starts[1], time_seconds=shifted.switch_time_seconds),
    ))
    if sparse:
        artifact = replace(artifact, headway_pairs=(), headway_pair_scope=EanHeadwayPairScope.SPARSE)
    plan = replace(plan, trajectories=(plan.trajectories[0], replace(plan.trajectories[1], visits=(shifted,))))
    report = validate_ean_movement_plan_against_artifact(artifact, plan, tolerance_seconds=tolerance)
    assert report.is_valid == (offset_tick > 0), report
    assert bool(separate_all_headway_violations(artifact, plan, tolerance_seconds=tolerance)) == (offset_tick <= 0)
    # No clipping of the first wait's clearance at H; no loss of tail conflicts.
    assert separate_all_headway_violations(artifact, plan, tolerance_seconds=tolerance, include_after_horizon=True)


@pytest.mark.parametrize("offset_tick", [-1, 0, 1])
def test_merge_at_horizon_agrees_between_cp_ddd_and_independent_ean(offset_tick):
    # STOP exits at 24.181818; SKIP wants to merge 0.5 s later, below headway.
    horizon = 24.681818
    scenario, problem = tiny_problem(horizon=horizon,
        starts=(0, horizon - 4 + offset_tick / 1e6),
        maximum_wait=1200, waiting_step=1e-6, groups=())
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    policy = problem.resolved_trajectory_problem.waiting_policy
    trajectories = []
    options = {}
    for start, decision in zip(movement.starts, ("stop", "skip")):
        option = next(o for o in movement.route_options_by_state_id[start.state_id] if o.decision.value == decision)
        options[start.cabin_id] = option
        visit = build_ddd_reference_visit(start=start, visit_index=0, switch_time_seconds=start.time_seconds,
            option=option, operational_end_seconds=horizon, tolerance_seconds=1e-9)
        trajectories.append(DddReferenceTrajectory(start.cabin_id, (visit,)))
    solution = DddReferenceSolution(tuple(trajectories))
    if offset_tick <= 0:
        with pytest.raises(ValueError, match="resource conflicts"):
            validate_ddd_reference_solution(movement, solution, waiting_policy=policy)
    else:
        validate_ddd_reference_solution(movement, solution, waiting_policy=policy)
    adapter = DddReferenceToEanMovementPlanAdapter(waiting_policy=policy)
    plan = EanMovementPlan(scenario.id, horizon, horizon,
        tuple(adapter.build_trajectory(problem=movement, trajectory=t) for t in trajectories),
        horizon_formulation=EanHorizonFormulation.EXACT_TIME_ACTIVATION)
    assert validate_ean_movement_plan_against_artifact(problem.artifact, plan, tolerance_seconds=1e-5).is_valid == (offset_tick > 0)
    built = build_ddd_integrated_cp_sat(problem)
    for (c, v, oid), literal in built.movement.selection_by_key.items():
        built.movement.model.add(literal == int(v == 0 and oid == options[c].id))
    for var in built.movement.wait_steps_by_key.values():
        built.movement.model.add(var == 0)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    solver.parameters.num_search_workers = 1
    status = solver.solve(built.movement.model)
    assert status == (cp_model.OPTIMAL if offset_tick > 0 else cp_model.INFEASIBLE)
    audit = audit_ean_exact_horizon(problem.artifact, plan)
    assert audit.continuation_status == "NOT_PROVEN"
    assert audit.exported_headway_violations


def test_clean_exported_tail_does_not_certify_unmodeled_future():
    artifact, plan = _horizon_crossing_headway_artifact_and_plan()
    artifact = replace(artifact, cabin_starts=artifact.cabin_starts[:1],
        switch_visits=artifact.switch_visits[:1], headway_candidates=artifact.headway_candidates[:1], headway_pairs=())
    plan = replace(plan, trajectories=plan.trajectories[:1])
    audit = audit_ean_exact_horizon(artifact, plan)
    assert audit.finite_validation.is_valid
    assert not audit.exported_headway_violations
    assert audit.visits_clearing_after_horizon == 1
    assert audit.continuation_status == "NOT_PROVEN"


@pytest.mark.parametrize("sparse", [False, True])
def test_rounded_wait_entry_on_h_uses_exported_events_not_raw_offsets(sparse):
    artifact, plan = _horizon_crossing_headway_artifact_and_plan()
    # The raw physical offset is 0.4 us above the canonical rounded offset.
    # Rebuilding it would incorrectly deactivate the second entry at H=101.
    timing = replace(artifact.timings[0], min_platform_entry_to_platform_exit_seconds=1.0000004)
    artifact = replace(artifact, timings=(timing,))
    if sparse:
        artifact = replace(artifact, headway_pairs=(), headway_pair_scope=EanHeadwayPairScope.SPARSE)
    report = validate_ean_movement_plan_against_artifact(artifact, plan, tolerance_seconds=1e-5)
    assert {e.code for e in report.errors} == {"EAN_HEADWAY_VIOLATION"}


def test_exact_prefix_cannot_omit_remaining_active_visits():
    artifact, plan = _platform_exit_wait_occupancy_artifact_and_plan()
    plan = replace(plan, horizon_formulation=EanHorizonFormulation.EXACT_TIME_ACTIVATION)
    report = validate_ean_movement_plan_against_artifact(artifact, plan)
    assert "EAN_HORIZON_COVERAGE_MISSING" in {e.code for e in report.errors}
    empty = replace(plan, trajectories=tuple(replace(t, visits=()) for t in plan.trajectories))
    report = validate_ean_movement_plan_against_artifact(artifact, empty)
    assert "EAN_HORIZON_COVERAGE_MISSING" in {e.code for e in report.errors}
