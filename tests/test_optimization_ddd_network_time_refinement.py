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
    _format_fixed_live_progress,
    format_ddd_iteration_progress,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddAggregateRouteCountLiteral,
    DddAggregateSupportCut,
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
    DddPartialTimedPath,
    DddReferenceConflict,
    DddReferenceSolver,
    DddReferenceToEanMovementPlanAdapter,
    DddRouteDecision,
    DddRouteOption,
    DddRouteOptionCost,
    DddResourceWindowCutMode,
    DddStrictTimeLiftStatus,
    DddSupportConflictCut,
    DddSupportLiteral,
    DddSupportSelection,
    DddTimeDiscretization,
    DddTimeSplit,
    DddTimeCell,
    DddTimePartition,
    DddTickInterval,
    DddTimedResourceUsageWindow,
    build_ddd_layer_state_earliest_arrival_ticks,
    build_ddd_universal_resource_row,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_refinement import (
    _build_universal_resource_rows_for_conflicts,
    _has_resource_conflict_refinement,
)
from ropeway_skip_stop_optimization.optimization.ddd.lifting_phase import (
    build_ddd_time_split_batch,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddEventCellInconsistency,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    validate_ean_movement_plan_against_artifact,
)


def test_layer_state_earliest_times_clip_initial_network_cells() -> None:
    problem = build_three_station_network_time_refinement_probe()

    earliest = build_ddd_layer_state_earliest_arrival_ticks(problem.movement_problem)
    builder = DddLayeredTimeNetworkBuilder()
    network = builder.build(problem)

    assert earliest
    for node in network.nodes:
        assert node.cell.lower_tick >= earliest[node.layer_index, node.state_id]
    assert builder.last_build_stats.structural_earliest_time_count == len(earliest)
    assert (
        builder.last_build_stats.structurally_pruned_cell_count
        + builder.last_build_stats.structurally_clipped_cell_count
        > 0
    )


def test_network_builder_can_disable_structural_earliest_times() -> None:
    base = build_three_station_network_time_refinement_probe()
    movement = base.movement_problem
    sentinel = (
        movement.operational_end_seconds
        + max(option.duration_seconds for option in movement.route_options)
        + 1.0
    )
    problem = base.with_discretization(
        DddTimeDiscretization(
            tuple(
                DddTimePartition(
                    state_id,
                    (0.0, movement.operational_end_seconds, sentinel),
                )
                for state_id in sorted(
                    {option.to_state_id for option in movement.route_options}
                )
            )
        )
    )

    strengthened = DddLayeredTimeNetworkBuilder().build(problem)
    legacy = DddLayeredTimeNetworkBuilder(use_structural_earliest_times=False).build(
        problem
    )

    assert min(node.cell.lower_tick for node in strengthened.nodes) >= min(
        node.cell.lower_tick for node in legacy.nodes
    )
    assert any(node not in strengthened.nodes for node in legacy.nodes)


def test_physical_network_builder_creates_sparse_reachable_layer_graph() -> None:
    problem = build_three_station_network_time_refinement_probe()

    network = DddLayeredTimeNetworkBuilder().build(problem)

    assert len(network.nodes) == 3
    assert len(network.arcs) == 6
    assert sum(arc.kind is DddLayeredTimeArcKind.SOURCE for arc in network.arcs) == 2
    assert sum(arc.kind is DddLayeredTimeArcKind.MOVEMENT for arc in network.arcs) == 2
    assert sum(arc.kind is DddLayeredTimeArcKind.SINK for arc in network.arcs) == 2
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

    flow = DddAnonymousFlowMaster(include_mandatory_resource_rows=False).solve(network)
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


def test_anonymous_flow_master_enforces_aggregate_route_count_core_cut() -> None:
    movement = DddMovementProblem(
        scenario_id="aggregate_core_master",
        passenger_service_end_seconds=1.0,
        operational_end_seconds=1.0,
        states=(DddMovementState("A"), DddMovementState("B")),
        starts=(DddFixedStart(0, "A", 0.0, 1),),
        route_options=(
            _skip_option("cheap", "A", "B", 2.0),
            _skip_option("fallback", "A", "B", 2.0),
        ),
        resources=(),
    )
    problem = DddNetworkTimeProblem(
        movement_problem=movement,
        discretization=DddTimeDiscretization((DddTimePartition("B", (0.0, 1.0, 4.0)),)),
        objective=DddNetworkTimeObjective(
            route_option_costs=(
                DddRouteOptionCost("cheap", 0.0),
                DddRouteOptionCost("fallback", 1.0),
            )
        ),
    )
    network = DddLayeredTimeNetworkBuilder().build(problem)
    cut = DddAggregateSupportCut.from_core(
        (DddAggregateRouteCountLiteral(0, "cheap", 1),)
    )

    result = DddAnonymousFlowMaster(include_mandatory_resource_rows=False).solve(
        network, aggregate_support_cuts=(cut,)
    )
    paths = DddAnonymousFlowDecomposer().decompose(network, result)

    assert result.status is DddAnonymousFlowStatus.OPTIMAL
    assert result.objective_value == pytest.approx(1.0)
    assert result.aggregate_support_constraint_count == 1
    assert result.aggregate_threshold_variable_count == 1
    assert paths[0].route_option_ids == ("fallback",)


def test_fixed_start_structural_rows_limit_late_anonymous_visit_flow() -> None:
    movement = DddMovementProblem(
        scenario_id="fixed_start_structural_capacity",
        passenger_service_end_seconds=1.0,
        operational_end_seconds=1.0,
        states=(DddMovementState("A"),),
        starts=(
            DddFixedStart(0, "A", 0.0, 2),
            DddFixedStart(1, "A", 0.0, 1),
        ),
        route_options=(_skip_option("loop", "A", "A", 2.0),),
        resources=(),
    )
    problem = DddNetworkTimeProblem(
        movement_problem=movement,
        discretization=DddTimeDiscretization(
            (DddTimePartition("A", (0.0, 1.0, 4.0, 7.0)),)
        ),
        objective=DddNetworkTimeObjective(
            route_option_costs=(DddRouteOptionCost("loop", -1.0),)
        ),
    )
    # This test isolates the fixed-start capacity rows against the original
    # coarse relaxation. Structural earliest-time clipping is tested
    # independently above and would already remove the artificial late flow.
    network = DddLayeredTimeNetworkBuilder(use_structural_earliest_times=False).build(
        problem
    )

    relaxed = DddAnonymousFlowMaster(include_mandatory_resource_rows=False).solve(
        network
    )
    strengthened = DddAnonymousFlowMaster(include_mandatory_resource_rows=False).solve(
        network, fixed_start_movement_problem=movement
    )

    assert relaxed.objective_value == pytest.approx(-4.0)
    assert strengthened.objective_value == pytest.approx(-3.0)
    assert strengthened.fixed_start_structural_constraint_count == 2


def test_network_builder_attaches_only_universally_active_resource_windows() -> None:
    problem = build_three_station_network_time_refinement_probe()
    builder = DddLayeredTimeNetworkBuilder()

    network = builder.build(problem)

    windows = tuple(window for arc in network.arcs for window in arc.resource_windows)
    assert windows
    assert builder.last_build_stats.resource_usage_window_count == len(windows)
    assert builder.last_build_stats.horizon_optional_resource_usage_count == 1
    assert all(
        window.latest_follower_enter_tick
        <= problem.movement_problem.operational_end_tick
        for window in windows
    )
    assert all(window.timed_arc_id in network.arcs_by_id for window in windows)


def test_mandatory_resource_rows_reject_identical_fixed_start_occupancy() -> None:
    base = build_three_station_network_time_refinement_probe()
    start = base.movement_problem.starts[0]
    initial_option = base.movement_problem.route_options_by_state_id[start.state_id][0]
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
        route_options=tuple(
            option
            for option in base.movement_problem.route_options
            if option.from_state_id != start.state_id or option.id == initial_option.id
        ),
    )
    network = DddLayeredTimeNetworkBuilder().build(
        replace(
            base,
            movement_problem=movement,
            objective=replace(
                base.objective,
                route_option_costs=tuple(
                    cost
                    for cost in base.objective.route_option_costs
                    if cost.route_option_id
                    in {option.id for option in movement.route_options}
                ),
            ),
        )
    )

    result = DddAnonymousFlowMaster().solve(network)

    assert result.status is DddAnonymousFlowStatus.INFEASIBLE
    assert result.mandatory_resource_constraint_count > 0
    assert result.resource_constraint_count == (
        result.mandatory_resource_constraint_count
    )


def test_resource_window_inner_loop_resolves_before_physical_lifting() -> None:
    base = build_three_station_network_time_refinement_probe()
    start = base.movement_problem.starts[0]
    initial_option = base.movement_problem.route_options_by_state_id[start.state_id][0]
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
        route_options=tuple(
            option
            for option in base.movement_problem.route_options
            if option.from_state_id != start.state_id or option.id == initial_option.id
        ),
    )
    problem = replace(
        base,
        movement_problem=movement,
        objective=replace(
            base.objective,
            route_option_costs=tuple(
                cost
                for cost in base.objective.route_option_costs
                if cost.route_option_id
                in {option.id for option in movement.route_options}
            ),
        ),
    )

    result = DddNetworkTimeRefinementSolver(
        use_mandatory_resource_rows=False,
        use_cp_sat_primal_oracle=False,
        resource_window_cut_mode=DddResourceWindowCutMode.ENTRY_COUNT,
    ).solve(problem)

    assert result.status is DddNetworkTimeRefinementStatus.RELAXATION_INFEASIBLE
    assert len(result.iterations) == 1
    iteration = result.iterations[0]
    assert iteration.resource_window_resolve_count == 1
    assert iteration.resource_window_added_count > 0
    assert iteration.resource_window_entry_row_count > 0
    assert iteration.cp_sat_status.value == "not_run"


def test_flow_master_accepts_proved_additional_universal_resource_row() -> None:
    base = build_three_station_network_time_refinement_probe()
    start = base.movement_problem.starts[0]
    initial_option = base.movement_problem.route_options_by_state_id[start.state_id][0]
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
        route_options=tuple(
            option
            for option in base.movement_problem.route_options
            if option.from_state_id != start.state_id or option.id == initial_option.id
        ),
    )
    network = DddLayeredTimeNetworkBuilder().build(
        replace(
            base,
            movement_problem=movement,
            objective=replace(
                base.objective,
                route_option_costs=tuple(
                    cost
                    for cost in base.objective.route_option_costs
                    if cost.route_option_id
                    in {option.id for option in movement.route_options}
                ),
            ),
        )
    )
    source_arcs = tuple(
        arc for arc in network.arcs if arc.kind is DddLayeredTimeArcKind.SOURCE
    )
    first_arc = next(arc for arc in source_arcs if arc.cabin_id == 0)
    second_arc = next(
        arc
        for arc in source_arcs
        if arc.cabin_id == 1
        and arc.partial_arc is not None
        and first_arc.partial_arc is not None
        and arc.partial_arc.route_option_id == first_arc.partial_arc.route_option_id
    )
    first_window = first_arc.resource_windows[0]
    second_window = next(
        window
        for window in second_arc.resource_windows
        if window.resource_id == first_window.resource_id
    )
    row = build_ddd_universal_resource_row(first_window, second_window)
    assert row is not None

    result = DddAnonymousFlowMaster(include_mandatory_resource_rows=False).solve(
        network, resource_rows=(row,)
    )

    assert result.status is DddAnonymousFlowStatus.INFEASIBLE
    assert result.mandatory_resource_constraint_count == 0
    assert result.additional_resource_constraint_count == 1


def test_exact_conflict_separator_finds_empty_core_universal_row() -> None:
    first_cell = DddTimeCell.from_ticks("A", 0, 1)
    second_cell = DddTimeCell.from_ticks("B", 0, 1)
    first_node = DddLayeredTimeNode(1, "A", first_cell)
    second_node = DddLayeredTimeNode(1, "B", second_cell)
    first_partial = DddPartialTimedArc(
        visit_index=0,
        route_option_id="first",
        from_state_id="start_a",
        to_state_id="A",
        source_cell_id=None,
        target_cell=first_cell,
    )
    second_partial = DddPartialTimedArc(
        visit_index=0,
        route_option_id="second",
        from_state_id="start_b",
        to_state_id="B",
        source_cell_id=None,
        target_cell=second_cell,
    )
    first_source = DddLayeredTimeArc(
        id="source_a",
        kind=DddLayeredTimeArcKind.SOURCE,
        source_node_id=None,
        target_node_id=first_node.id,
        cabin_id=0,
        partial_arc=first_partial,
        lower_bound_cost=0.0,
        resource_windows=(
            DddTimedResourceUsageWindow(
                timed_arc_id="source_a",
                resource_id="merge",
                source_interval=DddTickInterval(0, 11),
                follower_enter_offset_tick=0,
                leader_clear_offset_tick=0,
                headway_tick=6,
            ),
        ),
    )
    second_source = DddLayeredTimeArc(
        id="source_b",
        kind=DddLayeredTimeArcKind.SOURCE,
        source_node_id=None,
        target_node_id=second_node.id,
        cabin_id=1,
        partial_arc=second_partial,
        lower_bound_cost=0.0,
        resource_windows=(
            DddTimedResourceUsageWindow(
                timed_arc_id="source_b",
                resource_id="merge",
                source_interval=DddTickInterval(5, 6),
                follower_enter_offset_tick=0,
                leader_clear_offset_tick=0,
                headway_tick=6,
            ),
        ),
    )
    network = DddLayeredTimeNetwork(
        nodes=(first_node, second_node),
        arcs=(
            first_source,
            second_source,
            DddLayeredTimeArc(
                "sink_a",
                DddLayeredTimeArcKind.SINK,
                first_node.id,
                None,
                None,
                None,
                0.0,
            ),
            DddLayeredTimeArc(
                "sink_b",
                DddLayeredTimeArcKind.SINK,
                second_node.id,
                None,
                None,
                None,
                0.0,
            ),
        ),
        cabin_ids=(0, 1),
    )
    paths = (
        DddPartialTimedPath(0, (first_partial,)),
        DddPartialTimedPath(1, (second_partial,)),
    )
    conflict = DddReferenceConflict("merge", 0, 0, 1, 0, 1e-6)

    proofs = _build_universal_resource_rows_for_conflicts(
        network,
        paths,
        (conflict,),
    )

    assert len(proofs) == 1
    row, conflict_indices = proofs[0]
    assert conflict_indices == (0,)
    assert row.right_hand_side == 1
    result = DddAnonymousFlowMaster().solve(
        network,
        resource_rows=(row,),
    )
    assert result.status is DddAnonymousFlowStatus.INFEASIBLE


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
            source_cell_id=(None if visit_index == 0 else cells[source_state_id].id),
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
            for visit_index, option_id in enumerate(paths[0].route_option_ids[:2])
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

    result = DddNetworkTimeRefinementSolver(use_cp_sat_primal_oracle=False).solve(
        problem
    )

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
    assert first.recovery_validation_status is DddNetworkValidationStatus.FEASIBLE
    assert first.cell_lift_validation_status is DddNetworkValidationStatus.NOT_RUN
    assert first.split_state_id == "R_entry_lr"
    assert first.split_boundary_seconds == pytest.approx(44.0909090909091)
    assert second.master_lower_bound == pytest.approx(1.0)
    assert second.cell_lift_statuses == (DddStrictTimeLiftStatus.FEASIBLE,)
    assert second.cell_lift_validation_status is DddNetworkValidationStatus.FEASIBLE
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

    result = DddNetworkTimeRefinementSolver(use_cp_sat_primal_oracle=False).solve(
        problem
    )

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

    result = DddNetworkTimeRefinementSolver(
        max_iterations=2,
        use_mandatory_resource_rows=False,
        use_cp_sat_primal_oracle=False,
    ).solve(replace(base, movement_problem=movement))

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
    assert len(result.iterations) == 3
    first, second, third = result.iterations
    assert first.split_state_id == "R_entry_lr"
    assert first.split_boundary_seconds == pytest.approx(73.8818181818)
    assert second.split_state_id == "R_entry_lr"
    assert second.split_boundary_seconds == pytest.approx(53.9409090912)
    assert third.cell_lift_validation_status is DddNetworkValidationStatus.FEASIBLE
    assert third.conflict_count == 0
    assert third.conflict_constraint_count == 0
    assert third.tracked_prefix_cabin_count == 0
    assert third.prefix_variable_count == 0
    assert third.resource_constraint_count > 0
    assert third.mandatory_resource_constraint_count == (
        third.resource_constraint_count
    )
    assert third.network_build_seconds >= 0.0
    assert third.master_solve_seconds >= 0.0
    assert third.decomposition_seconds >= 0.0
    assert third.recovery_seconds >= 0.0
    assert third.lifting_and_validation_seconds >= 0.0
    assert third.round_seconds >= 0.0
    assert not result.conflict_cuts
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
    assert len(finished) == len(result.iterations) == 3
    assert finished[-1].iteration == result.iterations[-1]
    assert finished[-1].global_lower_bound == result.global_lower_bound
    assert finished[-1].global_upper_bound == result.global_upper_bound
    assert {
        DddNetworkTimeRefinementProgressStage.ROUND_STARTED,
        DddNetworkTimeRefinementProgressStage.MASTER_STARTED,
        DddNetworkTimeRefinementProgressStage.MASTER_PROGRESS,
        DddNetworkTimeRefinementProgressStage.MASTER_FINISHED,
        DddNetworkTimeRefinementProgressStage.ROUND_FINISHED,
    } <= {event.stage for event in events}
    rendered = format_ddd_iteration_progress(result.iterations[-1])
    assert "LB/UB=4/4" in rendered
    assert "prefix=0c/0v/d0" in rendered
    assert "conflicts=0/+0/0" in rendered
    assert "resource_rows=" in rendered
    assert "splits=0:0t/0r:none" in rendered
    assert "cp=" in rendered
    assert "master=optimal/" in rendered
    master_events = [
        event
        for event in events
        if event.stage is DddNetworkTimeRefinementProgressStage.MASTER_PROGRESS
    ]
    assert master_events
    assert all(event.master_progress is not None for event in master_events)
    assert result.iterations[-1].master_progress_snapshots

    fixed_first = _format_fixed_live_progress(
        event=master_events[0],
        stage="master@1s",
        master_incumbent=123.0,
        master_best_bound=4.0,
    )
    fixed_second = _format_fixed_live_progress(
        event=master_events[0],
        stage="primal_oracle_candidate_found",
        master_incumbent=1234567.0,
        master_best_bound=40.0,
    )
    assert len(fixed_first) == len(fixed_second)
    assert "LB=" in fixed_first
    assert "UB=" in fixed_first
    assert "INC=" in fixed_first
    assert "GAP=" in fixed_first


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

    splits, refined = build_ddd_time_split_batch(
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
        DddNetworkTimeRefinementSolver(max_new_time_splits_per_iteration=0).solve(
            build_three_station_network_time_refinement_probe()
        )


def test_resource_time_split_counts_as_a_valid_conflict_refinement() -> None:
    assert _has_resource_conflict_refinement(
        time_splits=(DddTimeSplit("state", 1.0),),
        new_cuts=(),
        new_resource_rows=(),
    )


def test_decomposition_consumes_the_prefix_flow_that_satisfies_cuts() -> None:
    problem = build_three_station_network_combined_probe()
    result = DddNetworkTimeRefinementSolver(use_mandatory_resource_rows=False).solve(
        problem
    )
    final_problem = problem.with_discretization(result.final_discretization)
    network = DddLayeredTimeNetworkBuilder().build(final_problem)

    flow = DddAnonymousFlowMaster(include_mandatory_resource_rows=False).solve(
        network, cuts=result.conflict_cuts
    )
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


def test_cp_sat_core_cut_can_reference_sparse_deep_route_literal() -> None:
    problem = build_three_station_network_combined_probe()
    network = DddLayeredTimeNetworkBuilder().build(problem)
    initial = DddAnonymousFlowMaster(include_mandatory_resource_rows=False).solve(
        network
    )
    path = DddAnonymousFlowDecomposer().decompose(network, initial)[0]
    assert len(path.route_option_ids) >= 2
    cut = DddSupportConflictCut(
        id="cp_sparse_deep_literal",
        literals=(
            DddSupportLiteral(
                path.cabin_id,
                1,
                path.route_option_ids[1],
            ),
        ),
        resource_id="cp_sat_joint_cabin_paths",
        violation_seconds=1.0,
        provenance="exact_cp_sat_no_wait_cabin_path_core",
    )

    resolved = DddAnonymousFlowMaster(include_mandatory_resource_rows=False).solve(
        network,
        cuts=(cut,),
    )

    assert resolved.status in {
        DddAnonymousFlowStatus.OPTIMAL,
        DddAnonymousFlowStatus.INFEASIBLE,
    }
    assert resolved.conflict_constraint_count == 1
    assert resolved.prefix_variable_count > 0


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
            tuple(visit.route_option_id for visit in solution.trajectories[0].visits),
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
