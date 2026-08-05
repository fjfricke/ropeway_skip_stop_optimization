from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_cases import (
    build_three_station_network_time_refinement_probe,
    build_three_station_time_refinement_artifact,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddAnonymousFlowDecomposer,
    DddAnonymousFlowMaster,
    DddAnonymousFlowStatus,
    DddFixedStart,
    DddLayeredTimeArcKind,
    DddLayeredTimeNetworkBuilder,
    DddNetworkTimeRefinementSolver,
    DddNetworkTimeRefinementStatus,
    DddReferenceSolver,
    DddReferenceToEanMovementPlanAdapter,
    DddRouteDecision,
    DddStrictTimeLiftStatus,
    DddTimeDiscretization,
    DddTimePartition,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    validate_ean_movement_plan_against_artifact,
)


def test_physical_network_builder_creates_sparse_reachable_layer_graph() -> None:
    problem = build_three_station_network_time_refinement_probe()

    network = DddLayeredTimeNetworkBuilder().build(problem)

    assert len(network.nodes) == 3
    assert len(network.arcs) == 6
    assert sum(
        arc.kind is DddLayeredTimeArcKind.SOURCE for arc in network.arcs
    ) == 2
    assert sum(
        arc.kind is DddLayeredTimeArcKind.MOVEMENT for arc in network.arcs
    ) == 2
    assert sum(
        arc.kind is DddLayeredTimeArcKind.SINK for arc in network.arcs
    ) == 2
    assert {node.layer_index for node in network.nodes} == {1, 2}


def test_anonymous_flow_aggregates_shared_cabin_movement_and_decomposes() -> None:
    base = build_three_station_network_time_refinement_probe()
    start = base.movement_problem.starts[0]
    movement = replace(
        base.movement_problem,
        starts=(
            start,
            DddFixedStart(
                cabin_id=1,
                state_id=start.state_id,
                time_seconds=start.time_seconds,
                max_visit_count=start.max_visit_count,
            ),
        ),
    )
    problem = replace(base, movement_problem=movement)
    network = DddLayeredTimeNetworkBuilder().build(problem)

    flow = DddAnonymousFlowMaster().solve(network)
    paths = DddAnonymousFlowDecomposer().decompose(network, flow)

    assert flow.status is DddAnonymousFlowStatus.OPTIMAL
    assert flow.objective_value == pytest.approx(0.0)
    assert {path.cabin_id for path in paths} == {0, 1}
    assert len({path.fingerprint for path in paths}) == 1
    arc_by_id = network.arcs_by_id
    shared_values = tuple(
        item.value
        for item in flow.arc_values
        if arc_by_id[item.arc_id].kind is not DddLayeredTimeArcKind.SOURCE
    )
    assert shared_values == (2, 2)


def test_anonymous_flow_reports_missing_source_projection_as_infeasible() -> None:
    base = build_three_station_network_time_refinement_probe()
    excluded_state_id = base.movement_problem.starts[0].state_id
    first_target_state_id = base.movement_problem.route_options_by_state_id[
        excluded_state_id
    ][0].to_state_id
    problem = base.with_discretization(
        DddTimeDiscretization(
            partitions=tuple(
                DddTimePartition(partition.state_id, (0.0, 1.0))
                if partition.state_id == first_target_state_id
                else partition
                for partition in base.discretization.partitions
            )
        )
    )
    network = DddLayeredTimeNetworkBuilder().build(problem)

    flow = DddAnonymousFlowMaster().solve(network)

    assert flow.status is DddAnonymousFlowStatus.INFEASIBLE
    assert flow.arc_values == ()


def test_physical_network_refinement_closes_gap_in_two_rounds() -> None:
    problem = build_three_station_network_time_refinement_probe()

    result = DddNetworkTimeRefinementSolver().solve(problem)

    assert result.status is DddNetworkTimeRefinementStatus.OPTIMAL
    assert result.global_lower_bound == pytest.approx(1.0)
    assert result.global_upper_bound == pytest.approx(1.0)
    assert result.absolute_gap == pytest.approx(0.0)
    assert len(result.iterations) == 2
    first, second = result.iterations
    assert first.master_lower_bound == pytest.approx(0.0)
    assert first.recovery_objective == pytest.approx(1.0)
    assert first.strict_lift_statuses == (
        DddStrictTimeLiftStatus.EVENT_CELL_INCONSISTENCY,
    )
    assert first.split_state_id == "R_entry_lr"
    assert first.split_boundary_seconds == pytest.approx(44.0909090909091)
    assert second.master_lower_bound == pytest.approx(1.0)
    assert second.strict_lift_statuses == (DddStrictTimeLiftStatus.FEASIBLE,)
    assert second.split_state_id is None
    assert result.schedules[0].objective_value == pytest.approx(1.0)


def test_physical_network_result_passes_complete_ean_validation() -> None:
    problem = build_three_station_network_time_refinement_probe()
    artifact = build_three_station_time_refinement_artifact()
    result = DddNetworkTimeRefinementSolver().solve(problem)
    assert result.reference_solution is not None

    plan = DddReferenceToEanMovementPlanAdapter().build(
        problem=problem.movement_problem,
        solution=result.reference_solution,
        artifact=artifact,
    )
    validation = validate_ean_movement_plan_against_artifact(artifact, plan)

    validation.raise_for_errors()
    assert len(plan.trajectories) == 1
    assert len(plan.trajectories[0].visits) == 2
    assert plan.trajectories[0].visits[0].decision.value == "stop"


def test_physical_probe_matches_exhaustive_exact_objectives() -> None:
    problem = build_three_station_network_time_refinement_probe()
    options_by_id = {
        option.id: option for option in problem.movement_problem.route_options
    }

    exact = DddReferenceSolver(
        stop_after_first_feasible=False,
        max_retained_feasible_solutions=10,
    ).solve(problem.movement_problem)
    objective_values = sorted(
        problem.objective.exact_value(
            tuple(
                visit.route_option_id
                for visit in solution.trajectories[0].visits
            ),
            options_by_id[
                solution.trajectories[0].visits[-1].route_option_id
            ].to_state_id,
            solution.trajectories[0].visits[-1].next_switch_time_seconds,
            tolerance_seconds=1e-9,
        )
        for solution in exact.retained_solutions
    )

    assert len(exact.retained_solutions) == 2
    assert objective_values == pytest.approx([1.0, 2.0])
    assert {
        solution.trajectories[0].visits[0].decision
        for solution in exact.retained_solutions
    } == {DddRouteDecision.STOP, DddRouteDecision.SKIP}
