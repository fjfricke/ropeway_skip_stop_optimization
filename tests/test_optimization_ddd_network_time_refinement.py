from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_cases import (
    build_three_station_network_combined_artifact,
    build_three_station_network_combined_probe,
    build_three_station_network_time_refinement_probe,
    build_three_station_time_refinement_artifact,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_progress import (
    format_ddd_iteration_progress,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddAnonymousFlowDecomposer,
    DddAnonymousFlowMaster,
    DddAnonymousFlowResult,
    DddAnonymousFlowStatus,
    DddAnonymousFlowValue,
    DddAnonymousFlowWarmStartProjector,
    DddAnonymousPrefixFlowValue,
    DddFixedStart,
    DddLayeredTimeArcKind,
    DddLayeredTimeArc,
    DddLayeredTimeNetwork,
    DddLayeredTimeNetworkBuilder,
    DddLayeredTimeNode,
    DddMovementProblem,
    DddMovementState,
    DddNetworkTimeObjective,
    DddNetworkTimeProblem,
    DddNetworkTimeRefinementSolver,
    DddNetworkTimeRefinementProgressStage,
    DddNetworkTimeRefinementStatus,
    DddNetworkValidationStatus,
    DddPartialTimedArc,
    DddReferenceSolver,
    DddReferenceToEanMovementPlanAdapter,
    DddRouteDecision,
    DddRouteOption,
    DddRouteOptionCost,
    DddStrictTimeLiftStatus,
    DddSupportConflictCut,
    DddSupportLiteral,
    DddSupportSelection,
    DddTimeDiscretization,
    DddTimeCell,
    DddTimePartition,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_refinement import (
    _build_time_split_batch,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddEventCellInconsistency,
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


def test_decomposition_reserves_all_labelled_prefixes_before_anonymous_tails() -> None:
    cells = {
        state_id: DddTimeCell(state_id, 0.0, 1.0)
        for state_id in ("A", "B", "M", "P", "Q")
    }
    nodes = {
        "A": DddLayeredTimeNode(1, "A", cells["A"]),
        "B": DddLayeredTimeNode(1, "B", cells["B"]),
        "M": DddLayeredTimeNode(2, "M", cells["M"]),
        "P": DddLayeredTimeNode(3, "P", cells["P"]),
        "Q": DddLayeredTimeNode(3, "Q", cells["Q"]),
    }

    def partial(
        visit_index: int,
        route_option_id: str,
        source_state_id: str,
        target_state_id: str,
    ) -> DddPartialTimedArc:
        return DddPartialTimedArc(
            visit_index=visit_index,
            route_option_id=route_option_id,
            from_state_id=source_state_id,
            to_state_id=target_state_id,
            source_cell_id=(
                None if visit_index == 0 else cells[source_state_id].id
            ),
            target_cell=cells[target_state_id],
        )

    arcs = (
        DddLayeredTimeArc(
            "source_0",
            DddLayeredTimeArcKind.SOURCE,
            None,
            nodes["A"].id,
            0,
            partial(0, "source_0", "start_0", "A"),
            0.0,
        ),
        DddLayeredTimeArc(
            "source_1",
            DddLayeredTimeArcKind.SOURCE,
            None,
            nodes["B"].id,
            1,
            partial(0, "source_1", "start_1", "B"),
            0.0,
        ),
        DddLayeredTimeArc(
            "prefix_0",
            DddLayeredTimeArcKind.MOVEMENT,
            nodes["A"].id,
            nodes["M"].id,
            None,
            partial(1, "prefix_0", "A", "M"),
            0.0,
        ),
        DddLayeredTimeArc(
            "prefix_1",
            DddLayeredTimeArcKind.MOVEMENT,
            nodes["B"].id,
            nodes["M"].id,
            None,
            partial(1, "prefix_1", "B", "M"),
            0.0,
        ),
        DddLayeredTimeArc(
            "required_by_1",
            DddLayeredTimeArcKind.MOVEMENT,
            nodes["M"].id,
            nodes["P"].id,
            None,
            partial(2, "a_required_by_1", "M", "P"),
            0.0,
        ),
        DddLayeredTimeArc(
            "alternative_for_0",
            DddLayeredTimeArcKind.MOVEMENT,
            nodes["M"].id,
            nodes["Q"].id,
            None,
            partial(2, "z_alternative_for_0", "M", "Q"),
            0.0,
        ),
        DddLayeredTimeArc(
            "sink_p",
            DddLayeredTimeArcKind.SINK,
            nodes["P"].id,
            None,
            None,
            None,
            0.0,
        ),
        DddLayeredTimeArc(
            "sink_q",
            DddLayeredTimeArcKind.SINK,
            nodes["Q"].id,
            None,
            None,
            None,
            0.0,
        ),
    )
    network = DddLayeredTimeNetwork(
        nodes=tuple(nodes.values()),
        arcs=arcs,
        cabin_ids=(0, 1),
    )
    result = DddAnonymousFlowResult(
        status=DddAnonymousFlowStatus.OPTIMAL,
        objective_value=0.0,
        best_bound=0.0,
        arc_values=tuple(DddAnonymousFlowValue(arc.id, 1) for arc in arcs),
        prefix_arc_values=(
            DddAnonymousPrefixFlowValue(0, "prefix_0"),
            DddAnonymousPrefixFlowValue(1, "prefix_1"),
            DddAnonymousPrefixFlowValue(1, "required_by_1"),
        ),
        variable_count=len(arcs),
        constraint_count=0,
        prefix_variable_count=3,
        conflict_constraint_count=1,
        tracked_prefix_cabin_count=2,
        warm_start_arc_variable_count=0,
        warm_start_prefix_variable_count=0,
        warm_start_projected_cabin_count=0,
        warm_start_complete_cabin_count=0,
    )

    paths = DddAnonymousFlowDecomposer().decompose(network, result)

    assert paths[0].route_option_ids[-1] == "z_alternative_for_0"
    assert paths[1].route_option_ids[-1] == "a_required_by_1"


def test_network_builder_reuses_unchanged_transition_fragments() -> None:
    problem = build_three_station_network_time_refinement_probe()
    builder = DddLayeredTimeNetworkBuilder()

    first = builder.build(problem)
    first_stats = builder.last_build_stats
    repeated = builder.build(problem)
    repeated_stats = builder.last_build_stats

    assert repeated == first
    assert first_stats.transition_cache_misses > 0
    assert repeated_stats.invalidated_state_count == 0
    assert repeated_stats.partition_cache_misses == 0
    assert repeated_stats.transition_cache_misses == 0
    assert repeated_stats.transition_cache_hits > 0

    partition = problem.discretization.partitions[0]
    first_cell = partition.cells[0]
    split = (first_cell.lower_seconds + first_cell.upper_seconds) / 2.0
    refined = problem.with_discretization(
        problem.discretization.split(
            state_id=partition.state_id,
            boundary_seconds=split,
            tolerance_seconds=0.0,
        )
    )
    builder.build(refined)

    assert builder.last_build_stats.invalidated_state_count == 1
    assert builder.last_build_stats.transition_cache_hits > 0
    assert builder.last_build_stats.transition_cache_misses > 0


def test_anonymous_flow_warm_start_projects_routes_to_refined_cells() -> None:
    problem = build_three_station_network_time_refinement_probe()
    builder = DddLayeredTimeNetworkBuilder()
    network = builder.build(problem)
    initial = DddAnonymousFlowMaster().solve(network)
    paths = DddAnonymousFlowDecomposer().decompose(network, initial)
    partition = problem.discretization.partition(paths[0].arcs[0].to_state_id)
    first_cell = partition.cells[0]
    split = (first_cell.lower_seconds + first_cell.upper_seconds) / 2.0
    refined = problem.with_discretization(
        problem.discretization.split(
            state_id=partition.state_id,
            boundary_seconds=split,
            tolerance_seconds=0.0,
        )
    )
    refined_network = builder.build(refined)

    warm_start = DddAnonymousFlowWarmStartProjector().project(
        refined,
        refined_network,
        paths,
    )
    resolved = DddAnonymousFlowMaster().solve(
        refined_network,
        warm_start=warm_start,
    )

    assert warm_start.projected_cabin_count == len(paths)
    assert warm_start.arc_values
    assert resolved.status is DddAnonymousFlowStatus.OPTIMAL
    assert resolved.warm_start_projected_cabin_count == len(paths)
    assert resolved.warm_start_arc_variable_count == len(warm_start.arc_values)

    excluded = DddSupportConflictCut(
        id="exclude_projected_support",
        literals=tuple(
            DddSupportLiteral(paths[0].cabin_id, visit_index, option_id)
            for visit_index, option_id in enumerate(
                paths[0].route_option_ids[:2]
            )
        ),
        resource_id="test_resource",
        violation_seconds=1.0,
    )
    blocked = DddAnonymousFlowWarmStartProjector().project(
        refined,
        refined_network,
        paths,
        cuts=(excluded,),
    )

    assert blocked.projected_cabin_count == 0
    assert not blocked.arc_values


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

    result = DddNetworkTimeRefinementSolver(max_iterations=2).solve(
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


def test_physical_combined_refinement_closes_time_and_conflict_gap() -> None:
    problem = build_three_station_network_combined_probe()

    result = DddNetworkTimeRefinementSolver().solve(problem)

    assert result.status is DddNetworkTimeRefinementStatus.OPTIMAL
    assert result.global_lower_bound == pytest.approx(4.0)
    assert result.global_upper_bound == pytest.approx(4.0)
    assert len(result.iterations) == 4
    first, second, third, fourth = result.iterations
    assert first.split_state_id == "R_entry_lr"
    assert first.split_boundary_seconds == pytest.approx(73.8818181818)
    assert second.split_state_id == "R_entry_lr"
    assert second.split_boundary_seconds == pytest.approx(53.9409090912)
    assert (
        third.cell_lift_validation_status
        is DddNetworkValidationStatus.RESOURCE_CONFLICT
    )
    assert third.conflict_count == 2
    assert len(third.added_cut_ids) == 2
    assert fourth.conflict_constraint_count == 2
    assert fourth.tracked_prefix_cabin_count == 2
    assert fourth.prefix_variable_count == 6
    assert fourth.maximum_prefix_visit_index == 1
    assert fourth.average_prefix_visit_index == pytest.approx(1.0)
    assert fourth.network_build_seconds >= 0.0
    assert fourth.master_solve_seconds >= 0.0
    assert fourth.decomposition_seconds >= 0.0
    assert fourth.recovery_seconds >= 0.0
    assert fourth.lifting_and_validation_seconds >= 0.0
    assert fourth.round_seconds >= 0.0
    assert (
        fourth.cell_lift_validation_status
        is DddNetworkValidationStatus.FEASIBLE
    )
    assert any(
        literal.visit_index == 1
        for cut in result.conflict_cuts
        for literal in cut.literals
    )
    assert tuple(len(schedule.route_option_ids) for schedule in result.schedules) == (
        2,
        1,
    )
    assert result.reference_solution is not None
    final_selection = DddSupportSelection(result.reference_solution.trajectories)
    assert all(not cut.excludes(final_selection) for cut in result.conflict_cuts)

    artifact = build_three_station_network_combined_artifact()
    plan = DddReferenceToEanMovementPlanAdapter().build(
        problem=problem.movement_problem,
        solution=result.reference_solution,
        artifact=artifact,
    )
    validate_ean_movement_plan_against_artifact(artifact, plan).raise_for_errors()


def test_network_refinement_optimizations_can_be_disabled() -> None:
    result = DddNetworkTimeRefinementSolver(
        reuse_network_fragments=False,
        use_projected_warm_start=False,
    ).solve(build_three_station_network_combined_probe())

    assert result.status is DddNetworkTimeRefinementStatus.OPTIMAL
    assert all(
        iteration.warm_start_projected_cabin_count == 0
        for iteration in result.iterations
    )


def test_network_refinement_emits_terminal_progress_data() -> None:
    problem = build_three_station_network_combined_probe()
    events = []

    result = DddNetworkTimeRefinementSolver().solve(
        problem,
        progress_callback=events.append,
    )

    finished = [
        event
        for event in events
        if event.stage is DddNetworkTimeRefinementProgressStage.ROUND_FINISHED
    ]
    assert len(finished) == len(result.iterations) == 4
    assert finished[-1].iteration == result.iterations[-1]
    assert {
        DddNetworkTimeRefinementProgressStage.ROUND_STARTED,
        DddNetworkTimeRefinementProgressStage.MASTER_STARTED,
        DddNetworkTimeRefinementProgressStage.MASTER_FINISHED,
        DddNetworkTimeRefinementProgressStage.ROUND_FINISHED,
    } <= {event.stage for event in events}
    rendered = format_ddd_iteration_progress(result.iterations[-1])
    assert "LB/UB=4/4" in rendered
    assert "prefix=2c/6v/d1" in rendered
    assert "conflicts=0/+0/2" in rendered
    assert "splits=0:none" in rendered


def test_time_split_batch_is_deterministic_deduplicated_and_bounded() -> None:
    discretization = DddTimeDiscretization(
        (
            DddTimePartition("A", (0.0, 10.0)),
            DddTimePartition("B", (0.0, 10.0)),
        )
    )
    inconsistencies = (
        _inconsistency("B", 7.0, selected_cell_id="B-late"),
        _inconsistency("A", 6.0, selected_cell_id="A-late"),
        _inconsistency("A", 3.0, selected_cell_id="A-early"),
        _inconsistency("A", 3.0 + 5e-10, selected_cell_id="A-duplicate"),
    )

    splits, refined = _build_time_split_batch(
        discretization,
        inconsistencies,
        max_splits=2,
        tolerance_seconds=1e-9,
    )

    assert tuple((split.state_id, split.boundary_seconds) for split in splits) == (
        ("A", pytest.approx(3.0)),
        ("A", pytest.approx(6.0)),
    )
    assert refined.partition("A").boundaries_seconds == pytest.approx(
        (0.0, 3.0, 6.0, 10.0)
    )
    assert refined.partition("B") == discretization.partition("B")


def test_network_refinement_rejects_nonpositive_time_split_batch() -> None:
    with pytest.raises(ValueError, match="max_new_time_splits_per_iteration"):
        DddNetworkTimeRefinementSolver(
            max_new_time_splits_per_iteration=0
        ).solve(build_three_station_network_time_refinement_probe())


def test_decomposition_consumes_the_prefix_flow_that_satisfies_cuts() -> None:
    problem = build_three_station_network_combined_probe()
    result = DddNetworkTimeRefinementSolver().solve(problem)
    final_problem = problem.with_discretization(result.final_discretization)
    network = DddLayeredTimeNetworkBuilder().build(final_problem)

    flow = DddAnonymousFlowMaster().solve(network, cuts=result.conflict_cuts)
    paths = DddAnonymousFlowDecomposer().decompose(network, flow)

    assert flow.prefix_arc_values
    selected_literals = {
        DddSupportLiteral(path.cabin_id, visit_index, option_id)
        for path in paths
        for visit_index, option_id in enumerate(path.route_option_ids)
    }
    assert all(
        not all(literal in selected_literals for literal in cut.literals)
        for cut in result.conflict_cuts
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


def _inconsistency(
    state_id: str,
    boundary_seconds: float,
    *,
    selected_cell_id: str,
) -> DddEventCellInconsistency:
    return DddEventCellInconsistency(
        state_id=state_id,
        selected_cell_id=selected_cell_id,
        exact_source_time_seconds=boundary_seconds,
        required_source_lower_seconds=boundary_seconds,
        required_source_upper_seconds=boundary_seconds,
        split_boundary_seconds=boundary_seconds,
        failed_target_cell_id="target",
    )
