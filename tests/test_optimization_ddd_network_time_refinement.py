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
    DddMovementProblem,
    DddMovementState,
    DddNetworkTimeObjective,
    DddNetworkTimeProblem,
    DddNetworkTimeRefinementSolver,
    DddNetworkTimeRefinementStatus,
    DddNetworkValidationStatus,
    DddReferenceSolver,
    DddReferenceToEanMovementPlanAdapter,
    DddRouteDecision,
    DddRouteOption,
    DddRouteOptionCost,
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


def test_network_problem_rejects_incomplete_partition_domain() -> None:
    base = build_three_station_network_time_refinement_probe()
    excluded_state_id = base.movement_problem.starts[0].state_id
    first_target_state_id = base.movement_problem.route_options_by_state_id[
        excluded_state_id
    ][0].to_state_id
    incomplete = DddTimeDiscretization(
        partitions=tuple(
            DddTimePartition(
                partition.state_id,
                (0.0, base.movement_problem.operational_end_seconds),
            )
            if partition.state_id == first_target_state_id
            else partition
            for partition in base.discretization.partitions
        )
    )

    with pytest.raises(ValueError, match="sentinel must exceed"):
        base.with_discretization(incomplete)


@pytest.mark.parametrize(
    ("boundaries", "message"),
    (
        ((1.0, 70.0, 130.0), "must start at zero"),
        ((0.0, 69.0, 130.0), "must contain the operational horizon"),
    ),
)
def test_network_problem_requires_complete_partition_boundaries(
    boundaries: tuple[float, ...],
    message: str,
) -> None:
    base = build_three_station_network_time_refinement_probe()
    partition = base.discretization.partitions[0]
    incomplete = DddTimeDiscretization(
        partitions=tuple(
            DddTimePartition(item.state_id, boundaries)
            if item.state_id == partition.state_id
            else item
            for item in base.discretization.partitions
        )
    )

    with pytest.raises(ValueError, match=message):
        base.with_discretization(incomplete)


def test_partition_rejects_boundaries_collapsed_by_time_normalization() -> None:
    partition = DddTimePartition("state", (0.0, 1.0, 1.0 + 1e-13))

    with pytest.raises(ValueError, match="increase strictly"):
        partition.validate()


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
    assert first.cell_lift_statuses == (
        DddStrictTimeLiftStatus.EVENT_CELL_INCONSISTENCY,
    )
    assert (
        first.recovery_validation_status
        is DddNetworkValidationStatus.FEASIBLE
    )
    assert (
        first.cell_lift_validation_status
        is DddNetworkValidationStatus.NOT_RUN
    )
    assert first.split_state_id == "R_entry_lr"
    assert first.split_boundary_seconds == pytest.approx(44.0909090909091)
    assert second.master_lower_bound == pytest.approx(1.0)
    assert second.cell_lift_statuses == (DddStrictTimeLiftStatus.FEASIBLE,)
    assert (
        second.cell_lift_validation_status
        is DddNetworkValidationStatus.FEASIBLE
    )
    assert second.split_state_id is None
    assert result.schedules[0].objective_value == pytest.approx(1.0)


def test_cell_lift_does_not_certify_incomplete_horizon() -> None:
    states = tuple(DddMovementState(state_id) for state_id in ("A", "B", "C"))
    movement = DddMovementProblem(
        scenario_id="horizon_validation_probe",
        passenger_service_end_seconds=10.0,
        operational_end_seconds=10.0,
        states=states,
        starts=(DddFixedStart(0, "A", 0.0, 2),),
        route_options=(
            _skip_option("ab", "A", "B", 10.0),
            _skip_option("bc", "B", "C", 1.0),
        ),
        resources=(),
    )
    problem = DddNetworkTimeProblem(
        movement_problem=movement,
        discretization=DddTimeDiscretization(
            (
                DddTimePartition("B", (0.0, 10.0, 21.0)),
                DddTimePartition("C", (0.0, 10.0, 11.0, 21.0)),
            )
        ),
        objective=DddNetworkTimeObjective(
            route_option_costs=(
                DddRouteOptionCost("ab", 0.0),
                DddRouteOptionCost("bc", 1.0),
            )
        ),
    )

    result = DddNetworkTimeRefinementSolver().solve(problem)

    assert result.status is DddNetworkTimeRefinementStatus.UNKNOWN_NO_INCUMBENT
    assert result.global_upper_bound is None
    iteration = result.iterations[0]
    assert iteration.cell_lift_statuses == (DddStrictTimeLiftStatus.FEASIBLE,)
    assert (
        iteration.cell_lift_validation_status
        is DddNetworkValidationStatus.HORIZON_INCOMPLETE
    )


def test_full_validation_classifies_resource_conflict() -> None:
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

    result = DddNetworkTimeRefinementSolver().solve(
        replace(base, movement_problem=movement)
    )

    assert result.status is DddNetworkTimeRefinementStatus.UNKNOWN_NO_INCUMBENT
    assert result.global_upper_bound is None
    assert (
        result.iterations[-1].cell_lift_validation_status
        is DddNetworkValidationStatus.RESOURCE_CONFLICT
    )
    assert "resource conflicts" in (
        result.iterations[-1].cell_lift_validation_detail or ""
    )


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


def _skip_option(
    option_id: str,
    from_state_id: str,
    to_state_id: str,
    duration_seconds: float,
) -> DddRouteOption:
    return DddRouteOption(
        id=option_id,
        from_state_id=from_state_id,
        to_state_id=to_state_id,
        station_id="probe_station",
        decision=DddRouteDecision.SKIP,
        duration_seconds=duration_seconds,
        platform_entry_offset_seconds=None,
        platform_exit_offset_seconds=None,
        exit_switch_offset_seconds=duration_seconds,
        resource_usages=(),
    )
