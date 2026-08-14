from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_cases import (
    build_three_station_network_combined_probe,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddAggregateRouteCount,
    DddAggregateRouteCountLiteral,
    DddAggregateSupportCut,
    DddAnonymousFlowDecomposer,
    DddAnonymousFlowMaster,
    DddAnonymousFlowStatus,
    DddCpSatPrimalOracle,
    DddCpSatLocalExplainabilityClass,
    DddCpSatLocalResourceAnalyzer,
    DddCpSatFixedSupport,
    DddCpSatPrimalStatus,
    DddCpSatMasterCoupling,
    DddFixedStart,
    DddMovementProblem,
    DddMovementState,
    DddNetworkTimeObjective,
    DddNetworkTimeProblem,
    DddLayeredTimeNetworkBuilder,
    DddNetworkTimeRefinementSolver,
    DddNetworkTimeRefinementStatus,
    DddResource,
    DddResourceUsage,
    DddRouteDecision,
    DddRouteOption,
    DddRouteOptionCost,
    DddTimeDiscretization,
    DddTimePartition,
    DddTimedFlowCoverCut,
    build_ddd_cabin_path_core_cut,
    build_ddd_cp_sat_local_explainability_report,
    build_ddd_cp_sat_timed_flow_support,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_refinement import (
    DddNetworkValidationStatus,
    _validate_reference_solution,
)


def test_cp_sat_primal_oracle_finds_valid_combined_schedule() -> None:
    problem = build_three_station_network_combined_probe()

    result = DddCpSatPrimalOracle(
        time_limit_seconds=2.0,
        num_workers=1,
    ).solve(problem)

    assert result.status is DddCpSatPrimalStatus.FEASIBLE
    assert len(result.schedules) == len(problem.movement_problem.starts)
    validation = _validate_reference_solution(
        problem,
        result.schedules,
        tolerance_seconds=1e-9,
    )
    assert validation.status is DddNetworkValidationStatus.FEASIBLE


def test_cp_sat_primal_pool_excludes_previous_route_patterns() -> None:
    problem = build_three_station_network_combined_probe()
    progress: list[tuple[int, float]] = []

    result = DddCpSatPrimalOracle(
        time_limit_seconds=2.0,
        num_workers=1,
        max_candidate_count=3,
    ).solve(
        problem,
        candidate_callback=lambda index, seconds: progress.append((index, seconds)),
    )

    assert result.status is DddCpSatPrimalStatus.FEASIBLE
    assert len(result.candidate_schedules) == 3
    fingerprints = {
        tuple((schedule.cabin_id, schedule.route_option_ids) for schedule in candidate)
        for candidate in result.candidate_schedules
    }
    assert len(fingerprints) == 3
    assert [index for index, _ in progress] == [1, 2, 3]
    assert [seconds for _, seconds in progress] == sorted(
        seconds for _, seconds in progress
    )
    for candidate in result.candidate_schedules:
        validation = _validate_reference_solution(
            problem,
            candidate,
            tolerance_seconds=1e-9,
        )
        assert validation.status is DddNetworkValidationStatus.FEASIBLE


def test_cp_sat_primal_oracle_excludes_archived_route_patterns() -> None:
    problem = build_three_station_network_combined_probe()
    oracle = DddCpSatPrimalOracle(
        time_limit_seconds=2.0,
        num_workers=1,
        max_candidate_count=1,
    )

    first = oracle.solve(problem)
    second = oracle.solve(
        problem,
        excluded_schedules=(first.schedules,),
    )

    assert first.status is DddCpSatPrimalStatus.FEASIBLE
    assert second.status is DddCpSatPrimalStatus.FEASIBLE
    first_routes = tuple(
        (schedule.cabin_id, schedule.route_option_ids) for schedule in first.schedules
    )
    second_routes = tuple(
        (schedule.cabin_id, schedule.route_option_ids) for schedule in second.schedules
    )
    assert second_routes != first_routes


def test_cp_sat_primal_oracle_rejects_duplicate_route_exclusions() -> None:
    problem = build_three_station_network_combined_probe()
    oracle = DddCpSatPrimalOracle(time_limit_seconds=2.0, num_workers=1)
    first = oracle.solve(problem)

    with pytest.raises(ValueError, match="excluded schedules must be unique"):
        oracle.solve(
            problem,
            excluded_schedules=(first.schedules, first.schedules),
        )


def test_cp_sat_primal_oracle_reports_exhausted_route_archive() -> None:
    movement = DddMovementProblem(
        scenario_id="cp_sat_exhausted_probe",
        passenger_service_end_seconds=1.0,
        operational_end_seconds=1.0,
        states=(DddMovementState("A"), DddMovementState("B")),
        starts=(DddFixedStart(0, "A", 0.0, 1),),
        route_options=(
            DddRouteOption(
                id="only_route",
                from_state_id="A",
                to_state_id="B",
                station_id="A",
                decision=DddRouteDecision.SKIP,
                duration_seconds=2.0,
                platform_entry_offset_seconds=None,
                platform_exit_offset_seconds=None,
                exit_switch_offset_seconds=0.0,
                resource_usages=(),
            ),
        ),
        resources=(),
    )
    problem = DddNetworkTimeProblem(
        movement_problem=movement,
        discretization=DddTimeDiscretization((DddTimePartition("B", (0.0, 1.0, 4.0)),)),
        objective=DddNetworkTimeObjective(
            route_option_costs=(DddRouteOptionCost("only_route", 0.0),)
        ),
    )
    oracle = DddCpSatPrimalOracle(time_limit_seconds=2.0, num_workers=1)

    first = oracle.solve(problem)
    exhausted = oracle.solve(problem, excluded_schedules=(first.schedules,))

    assert first.status is DddCpSatPrimalStatus.FEASIBLE
    assert exhausted.status is DddCpSatPrimalStatus.EXHAUSTED
    assert exhausted.search_complete
    assert exhausted.schedules == ()


def test_cp_sat_primal_oracle_proves_full_route_choice_model_infeasible() -> None:
    movement = DddMovementProblem(
        scenario_id="cp_sat_infeasible_probe",
        passenger_service_end_seconds=1.0,
        operational_end_seconds=1.0,
        states=(DddMovementState("A"), DddMovementState("B")),
        starts=(
            DddFixedStart(0, "A", 0.0, 1),
            DddFixedStart(1, "A", 0.0, 1),
        ),
        route_options=(
            DddRouteOption(
                id="only_route",
                from_state_id="A",
                to_state_id="B",
                station_id="A",
                decision=DddRouteDecision.SKIP,
                duration_seconds=2.0,
                platform_entry_offset_seconds=None,
                platform_exit_offset_seconds=None,
                exit_switch_offset_seconds=0.0,
                resource_usages=(
                    DddResourceUsage(
                        resource_id="merge",
                        leader_clear_offset_seconds=0.0,
                        follower_enter_offset_seconds=0.0,
                    ),
                ),
            ),
        ),
        resources=(DddResource("merge", 1.0), DddResource("other", 1.0)),
    )
    problem = DddNetworkTimeProblem(
        movement_problem=movement,
        discretization=DddTimeDiscretization((DddTimePartition("B", (0.0, 1.0, 4.0)),)),
        objective=DddNetworkTimeObjective(
            route_option_costs=(DddRouteOptionCost("only_route", 0.0),)
        ),
    )

    result = DddCpSatPrimalOracle(
        time_limit_seconds=2.0,
        num_workers=1,
    ).solve(problem)

    assert result.status is DddCpSatPrimalStatus.INFEASIBLE
    assert result.schedules == ()

    integrated = DddNetworkTimeRefinementSolver(
        max_iterations=1,
        use_mandatory_resource_rows=False,
        cp_sat_time_limit_seconds=2.0,
        cp_sat_num_workers=1,
    ).solve(problem)

    assert integrated.status is DddNetworkTimeRefinementStatus.EXACT_INFEASIBLE
    assert integrated.iterations[0].cp_sat_status is DddCpSatPrimalStatus.INFEASIBLE

    bootstrapped = DddNetworkTimeRefinementSolver(
        max_iterations=1,
        use_mandatory_resource_rows=False,
        cp_sat_time_limit_seconds=2.0,
        cp_sat_num_workers=1,
        cp_sat_master_coupling=(DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT),
    ).solve(problem)

    assert bootstrapped.status is DddNetworkTimeRefinementStatus.EXACT_INFEASIBLE
    assert bootstrapped.iterations == ()
    assert bootstrapped.cp_sat_bootstrap_status is (DddCpSatPrimalStatus.INFEASIBLE)


def test_cp_sat_fixed_support_preserves_aggregate_route_counts() -> None:
    problem = build_three_station_network_combined_probe()
    free = DddCpSatPrimalOracle(
        time_limit_seconds=2.0,
        num_workers=1,
    ).solve(problem)
    assert free.status is DddCpSatPrimalStatus.FEASIBLE
    counts: dict[tuple[int, str], int] = {}
    for schedule in free.schedules:
        for visit_index, route_option_id in enumerate(schedule.route_option_ids):
            key = (visit_index, route_option_id)
            counts[key] = counts.get(key, 0) + 1
    support = DddCpSatFixedSupport(
        tuple(
            DddAggregateRouteCount(visit_index, route_option_id, count)
            for (visit_index, route_option_id), count in sorted(counts.items())
        )
    )

    fixed = DddCpSatPrimalOracle(
        time_limit_seconds=2.0,
        num_workers=1,
    ).solve(problem, fixed_support=support)

    assert fixed.status is DddCpSatPrimalStatus.FEASIBLE
    assert fixed.fixed_support == support
    fixed_counts: dict[tuple[int, str], int] = {}
    for schedule in fixed.schedules:
        for visit_index, route_option_id in enumerate(schedule.route_option_ids):
            key = (visit_index, route_option_id)
            fixed_counts[key] = fixed_counts.get(key, 0) + 1
    assert fixed_counts == counts


def test_cp_sat_fixed_support_returns_valid_aggregate_infeasibility_core() -> None:
    movement = DddMovementProblem(
        scenario_id="cp_sat_fixed_support_core",
        passenger_service_end_seconds=1.0,
        operational_end_seconds=1.0,
        states=(DddMovementState("A"), DddMovementState("B")),
        starts=(
            DddFixedStart(0, "A", 0.0, 1),
            DddFixedStart(1, "A", 0.0, 1),
        ),
        route_options=(
            DddRouteOption(
                id="bad_skip",
                from_state_id="A",
                to_state_id="B",
                station_id="A",
                decision=DddRouteDecision.SKIP,
                duration_seconds=2.0,
                platform_entry_offset_seconds=None,
                platform_exit_offset_seconds=None,
                exit_switch_offset_seconds=0.0,
                resource_usages=(
                    DddResourceUsage(
                        resource_id="merge",
                        leader_clear_offset_seconds=0.0,
                        follower_enter_offset_seconds=0.0,
                    ),
                ),
            ),
            DddRouteOption(
                id="safe_stop",
                from_state_id="A",
                to_state_id="B",
                station_id="A",
                decision=DddRouteDecision.STOP,
                duration_seconds=2.0,
                platform_entry_offset_seconds=0.0,
                platform_exit_offset_seconds=0.0,
                exit_switch_offset_seconds=0.0,
                resource_usages=(),
            ),
        ),
        resources=(DddResource("merge", 1.0), DddResource("other", 1.0)),
    )
    problem = DddNetworkTimeProblem(
        movement_problem=movement,
        discretization=DddTimeDiscretization((DddTimePartition("B", (0.0, 1.0, 4.0)),)),
        objective=DddNetworkTimeObjective(
            route_option_costs=(
                DddRouteOptionCost("bad_skip", 0.0),
                DddRouteOptionCost("safe_stop", 0.0),
            )
        ),
    )
    free = DddCpSatPrimalOracle(
        time_limit_seconds=2.0,
        num_workers=1,
    ).solve(problem)
    assert free.status is DddCpSatPrimalStatus.FEASIBLE
    support = DddCpSatFixedSupport((DddAggregateRouteCount(0, "bad_skip", 2),))

    fixed = DddCpSatPrimalOracle(
        time_limit_seconds=2.0,
        num_workers=1,
    ).solve(problem, fixed_support=support)

    assert fixed.status is DddCpSatPrimalStatus.INFEASIBLE
    assert fixed.schedules == ()
    assert fixed.infeasible_core
    cut = DddAggregateSupportCut.from_core(fixed.infeasible_core)
    assert cut.literals == fixed.infeasible_core
    assert any(
        literal.route_option_id == "bad_skip" and literal.count == 2
        for literal in cut.literals
    )

    nearest = DddCpSatPrimalOracle(
        time_limit_seconds=2.0,
        num_workers=1,
    ).solve(problem, nearest_support=support)

    assert nearest.status is DddCpSatPrimalStatus.FEASIBLE
    assert nearest.search_complete
    assert nearest.support_distance_primal == 2
    assert nearest.support_distance_lower_bound == 2.0
    assert nearest.distance_center
    nearest_counts: dict[tuple[int, str], int] = {}
    for schedule in nearest.schedules:
        for visit_index, route_option_id in enumerate(schedule.route_option_ids):
            key = (visit_index, route_option_id)
            nearest_counts[key] = nearest_counts.get(key, 0) + 1
    assert nearest_counts[(0, "bad_skip")] == 1
    assert nearest_counts[(0, "safe_stop")] == 1

    timed_problem = DddNetworkTimeProblem(
        movement_problem=movement,
        discretization=problem.discretization,
        objective=DddNetworkTimeObjective(
            route_option_costs=(
                DddRouteOptionCost("bad_skip", 0.0),
                DddRouteOptionCost("safe_stop", 1.0),
            )
        ),
    )
    network = DddLayeredTimeNetworkBuilder().build(timed_problem)
    flow = DddAnonymousFlowMaster(include_mandatory_resource_rows=False).solve(
        network,
        fixed_start_movement_problem=movement,
    )
    assert flow.status is DddAnonymousFlowStatus.OPTIMAL
    paths = DddAnonymousFlowDecomposer().decompose(network, flow)
    cabin_fixed = DddCpSatPrimalOracle(
        time_limit_seconds=2.0,
        num_workers=1,
    ).solve(timed_problem, fixed_cabin_paths=paths)

    assert cabin_fixed.status is DddCpSatPrimalStatus.INFEASIBLE
    assert {literal.cabin_id for literal in cabin_fixed.cabin_path_infeasible_core} == {
        0,
        1,
    }
    assert all(
        literal.route_option_id == "bad_skip"
        for literal in cabin_fixed.cabin_path_infeasible_core
    )
    cabin_path_cut = build_ddd_cabin_path_core_cut(
        paths,
        cabin_fixed.cabin_path_infeasible_core,
    )
    assert cabin_path_cut.provenance == "exact_cp_sat_no_wait_cabin_path_core"
    assert cabin_path_cut.right_hand_side == len(cabin_path_cut.literals) - 1
    assert {literal.cabin_id for literal in cabin_path_cut.literals} == {0, 1}
    assert all(literal.visit_index == 0 for literal in cabin_path_cut.literals)

    integrated_prefix = DddNetworkTimeRefinementSolver(
        max_iterations=2,
        max_prefix_variable_count=100,
        max_tracked_prefix_cabin_count=2,
        max_prefix_visit_index=1,
        use_mandatory_resource_rows=False,
        use_universal_resource_rows=False,
        use_cp_sat_primal_bootstrap=False,
        use_cp_sat_cabin_path_cuts=True,
        use_cp_sat_nearest_support=False,
        cp_sat_time_limit_seconds=2.0,
        cp_sat_num_workers=1,
        cp_sat_retry_interval=1,
    ).solve(timed_problem)

    assert integrated_prefix.iterations[0].cp_sat_cabin_path_status is (
        DddCpSatPrimalStatus.INFEASIBLE
    )
    assert integrated_prefix.iterations[0].cp_sat_cabin_path_core_cabin_ids == (0, 1)
    assert integrated_prefix.iterations[0].cp_sat_cabin_path_core_literal_count == 2
    assert integrated_prefix.iterations[0].cp_sat_cabin_path_cut_literal_count == 2
    assert integrated_prefix.iterations[0].added_cabin_path_core_cut_ids
    assert any(
        cut.provenance == "exact_cp_sat_no_wait_cabin_path_core"
        for cut in integrated_prefix.conflict_cuts
    )

    timed_support = build_ddd_cp_sat_timed_flow_support(network, flow, movement)

    timed = DddCpSatPrimalOracle(
        time_limit_seconds=2.0,
        num_workers=1,
    ).solve(timed_problem, timed_flow_support=timed_support)

    assert timed.status is DddCpSatPrimalStatus.INFEASIBLE
    assert timed.timed_flow_support == timed_support
    assert timed.timed_flow_infeasible_core
    timed_cut = DddTimedFlowCoverCut.from_core(timed.timed_flow_infeasible_core)
    assert timed_cut.resource_ids == ("merge",)
    assert all(literal.minimum_flow == 1 for literal in timed_cut.literals)

    merge_only = DddCpSatPrimalOracle(
        time_limit_seconds=2.0,
        num_workers=1,
    ).solve(
        timed_problem,
        timed_flow_support=timed_support,
        enabled_resource_ids=("merge",),
    )
    other_only = DddCpSatPrimalOracle(
        time_limit_seconds=2.0,
        num_workers=1,
    ).solve(
        timed_problem,
        timed_flow_support=timed_support,
        enabled_resource_ids=("other",),
    )

    assert merge_only.status is DddCpSatPrimalStatus.INFEASIBLE
    assert other_only.status is DddCpSatPrimalStatus.FEASIBLE

    observation = DddCpSatLocalResourceAnalyzer(
        time_limit_seconds=2.0,
        num_workers=1,
    ).analyze(
        timed_problem,
        round_index=1,
        full_support=timed_support,
        core=timed.timed_flow_infeasible_core,
    )
    assert observation.classification is (
        DddCpSatLocalExplainabilityClass.SINGLE_RESOURCE
    )
    assert observation.explaining_resource_ids == ("merge",)
    assert observation.station_ids == ("A",)
    assert observation.resource_windows
    assert observation.resource_windows[0].resource_id == "merge"
    assert observation.probes[0].infeasible_core
    assert observation.probes[0].all_core_literals_touch_enabled_resources
    report = build_ddd_cp_sat_local_explainability_report((observation, observation))
    assert report.observation_count == 2
    assert report.single_resource_count == 2
    assert all(item.excluded_other_support_count == 1 for item in report.cut_coverage)

    strengthened = DddAnonymousFlowMaster(include_mandatory_resource_rows=False).solve(
        network,
        timed_flow_cover_cuts=(timed_cut,),
        fixed_start_movement_problem=movement,
    )

    assert strengthened.status is DddAnonymousFlowStatus.OPTIMAL
    assert (
        sum(
            item.value
            for item in strengthened.arc_values
            if network.arcs_by_id[item.arc_id].partial_arc is not None
            and network.arcs_by_id[item.arc_id].partial_arc.route_option_id
            == "bad_skip"
        )
        <= 1
    )
    assert strengthened.timed_flow_cover_constraint_count == 1
    assert strengthened.timed_flow_threshold_variable_count == len(timed_cut.literals)

    refined_problem = DddNetworkTimeProblem(
        movement_problem=movement,
        discretization=DddTimeDiscretization(
            (DddTimePartition("B", (0.0, 1.0, 3.0, 4.0)),)
        ),
        objective=timed_problem.objective,
    )
    refined_network = DddLayeredTimeNetworkBuilder().build(refined_problem)
    refined = DddAnonymousFlowMaster(include_mandatory_resource_rows=False).solve(
        refined_network,
        timed_flow_cover_cuts=(timed_cut,),
        fixed_start_movement_problem=movement,
    )

    assert refined.status is DddAnonymousFlowStatus.OPTIMAL
    assert (
        sum(
            item.value
            for item in refined.arc_values
            if refined_network.arcs_by_id[item.arc_id].partial_arc is not None
            and refined_network.arcs_by_id[item.arc_id].partial_arc.route_option_id
            == "bad_skip"
        )
        <= 1
    )


def test_cp_sat_fixed_support_cores_structurally_unavailable_count() -> None:
    problem = build_three_station_network_combined_probe()
    movement = problem.movement_problem
    first_start = min(movement.starts, key=lambda item: item.cabin_id)
    first_option = movement.route_options_by_state_id[first_start.state_id][0]
    structurally_available = sum(
        start.state_id == first_start.state_id for start in movement.starts
    )
    impossible_count = structurally_available + 1
    support = DddCpSatFixedSupport(
        (
            DddAggregateRouteCount(
                visit_index=0,
                route_option_id=first_option.id,
                count=impossible_count,
            ),
        )
    )

    result = DddCpSatPrimalOracle(
        time_limit_seconds=2.0,
        num_workers=1,
    ).solve(problem, fixed_support=support)

    assert result.status is DddCpSatPrimalStatus.INFEASIBLE
    assert (
        DddAggregateRouteCountLiteral(
            visit_index=0,
            route_option_id=first_option.id,
            count=impossible_count,
        )
        in result.infeasible_core
    )


def test_fixed_support_coordinator_cuts_infeasible_master_route_counts() -> None:
    movement = DddMovementProblem(
        scenario_id="cp_sat_fixed_support_loop",
        passenger_service_end_seconds=1.0,
        operational_end_seconds=1.0,
        states=(DddMovementState("A"), DddMovementState("B")),
        starts=(
            DddFixedStart(0, "A", 0.0, 1),
            DddFixedStart(1, "A", 0.0, 1),
        ),
        route_options=(
            DddRouteOption(
                id="bad_skip",
                from_state_id="A",
                to_state_id="B",
                station_id="A",
                decision=DddRouteDecision.SKIP,
                duration_seconds=2.0,
                platform_entry_offset_seconds=None,
                platform_exit_offset_seconds=None,
                exit_switch_offset_seconds=0.0,
                resource_usages=(
                    DddResourceUsage(
                        resource_id="merge",
                        leader_clear_offset_seconds=0.0,
                        follower_enter_offset_seconds=0.0,
                    ),
                ),
            ),
            DddRouteOption(
                id="safe_stop",
                from_state_id="A",
                to_state_id="B",
                station_id="A",
                decision=DddRouteDecision.STOP,
                duration_seconds=2.0,
                platform_entry_offset_seconds=0.0,
                platform_exit_offset_seconds=0.0,
                exit_switch_offset_seconds=0.0,
                resource_usages=(),
            ),
        ),
        resources=(DddResource("merge", 1.0),),
    )
    problem = DddNetworkTimeProblem(
        movement_problem=movement,
        discretization=DddTimeDiscretization((DddTimePartition("B", (0.0, 1.0, 4.0)),)),
        objective=DddNetworkTimeObjective(
            route_option_costs=(
                DddRouteOptionCost("bad_skip", 0.0),
                DddRouteOptionCost("safe_stop", 1.0),
            )
        ),
    )

    result = DddNetworkTimeRefinementSolver(
        max_iterations=3,
        use_mandatory_resource_rows=False,
        use_universal_resource_rows=False,
        cp_sat_time_limit_seconds=2.0,
        cp_sat_num_workers=1,
        cp_sat_master_coupling=(DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT),
    ).solve(problem)

    assert result.status is DddNetworkTimeRefinementStatus.OPTIMAL
    assert result.global_lower_bound == 1.0
    assert result.global_upper_bound == 1.0
    assert len(result.aggregate_support_cuts) == 1
    assert len(result.aggregate_distance_cuts) == 1
    assert result.cp_sat_bootstrap_status is DddCpSatPrimalStatus.FEASIBLE
    assert result.cp_sat_bootstrap_candidate_count == 1
    assert result.iterations[0].cp_sat_status is DddCpSatPrimalStatus.INFEASIBLE
    assert result.iterations[0].cp_sat_core_literal_count > 0
    assert result.iterations[0].added_aggregate_support_cut_ids
    assert result.iterations[0].cp_sat_nearest_status is (DddCpSatPrimalStatus.FEASIBLE)
    assert result.iterations[0].cp_sat_nearest_distance_primal == 2
    assert result.iterations[0].cp_sat_nearest_distance_lower_bound == 2.0
    assert result.iterations[0].added_aggregate_distance_cut_ids
    assert result.iterations[0].time_splits == ()
    assert result.iterations[0].recovery_validation_status is (
        DddNetworkValidationStatus.NOT_RUN
    )
    assert result.iterations[1].cp_sat_status is DddCpSatPrimalStatus.FEASIBLE
    assert result.iterations[1].aggregate_support_constraint_count == 2

    timed_covers = DddNetworkTimeRefinementSolver(
        max_iterations=3,
        use_mandatory_resource_rows=False,
        use_universal_resource_rows=False,
        cp_sat_time_limit_seconds=2.0,
        cp_sat_num_workers=1,
        cp_sat_master_coupling=(DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT),
        use_cp_sat_timed_flow_covers=True,
        collect_cp_sat_local_explainability=True,
        cp_sat_local_explainability_time_limit_seconds=2.0,
        use_cp_sat_nearest_support=False,
    ).solve(problem)

    assert timed_covers.status is DddNetworkTimeRefinementStatus.OPTIMAL
    assert timed_covers.aggregate_support_cuts == ()
    assert len(timed_covers.timed_flow_cover_cuts) == 1
    assert timed_covers.iterations[0].cp_sat_timed_flow_core_literal_count > 0
    assert timed_covers.iterations[0].cp_sat_timed_flow_core_resource_ids == ("merge",)
    assert timed_covers.iterations[0].added_timed_flow_cover_cut_ids
    assert timed_covers.iterations[0].cp_sat_local_explainability is not None
    assert timed_covers.iterations[0].cp_sat_local_explainability.classification is (
        DddCpSatLocalExplainabilityClass.SINGLE_RESOURCE
    )
    assert timed_covers.iterations[1].timed_flow_cover_constraint_count == 1
    assert timed_covers.iterations[1].timed_flow_threshold_variable_count > 0

    equality_only = DddNetworkTimeRefinementSolver(
        max_iterations=3,
        use_mandatory_resource_rows=False,
        use_universal_resource_rows=False,
        cp_sat_time_limit_seconds=2.0,
        cp_sat_num_workers=1,
        cp_sat_master_coupling=(DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT),
        use_cp_sat_primal_bootstrap=False,
        use_cp_sat_nearest_support=False,
    ).solve(problem)

    assert equality_only.status is DddNetworkTimeRefinementStatus.OPTIMAL
    assert equality_only.cp_sat_bootstrap_status is DddCpSatPrimalStatus.NOT_RUN
    assert equality_only.aggregate_distance_cuts == ()
    assert equality_only.iterations[0].cp_sat_nearest_status is (
        DddCpSatPrimalStatus.NOT_RUN
    )
