from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.examples.three_station import (
    build_three_station_scenario,
)
from ropeway_skip_stop_optimization.examples.three_station_ean import (
    build_three_station_ean_config,
    build_three_station_ean_pattern_definition,
)
from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.benchmarking.ddd_cases import (
    build_three_station_two_cabin_merge_artifact,
    build_three_station_two_cabin_merge_probe_objective,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddDelayedConflictSolver,
    DddExactLiftStatus,
    DddExactSupportLifter,
    DddFixedStart,
    DddIterativeStatus,
    DddMovementProblem,
    DddMovementState,
    DddReferenceSolver,
    DddReferenceStatus,
    DddReferenceToEanMovementPlanAdapter,
    DddResource,
    DddResourceUsage,
    DddRouteDecision,
    DddRouteOption,
    DddSupportMaster,
    DddSupportMasterStatus,
    DddSupportConflictCut,
    DddSupportLiteral,
    DddSupportSelection,
    EanArtifactToDddMovementProblemAdapter,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanCabinStart,
    EanCabinStartBuilder,
    EanCabinStartKind,
    EanCirculationPattern,
    EanConfig,
    EanFormulationConfig,
    EanHorizonFormulation,
    EanMovementFeasibilityProblem,
    EanMovementNetwork,
    EanOptimizationConfig,
    EanOptimizer,
    EanRouteDecision,
    EanSolveConfig,
    EanTimeBoundFormulation,
    SparseHeadwayPairBuilder,
    AllPairsHeadwayPairBuilder,
    StationWaitingMode,
    network_ean_builder_for_pattern,
    validate_ean_movement_plan_against_artifact,
)
from ropeway_skip_stop_optimization.optimization.ean.headway_separator import (
    separate_all_headway_violations,
)


def test_reference_solver_finds_unique_stop_skip_mix_without_label_symmetry() -> None:
    problem = _two_cabin_single_visit_problem(
        route_options=(
            _route_option("stop", DddRouteDecision.STOP, usage_offset=2.0),
            _route_option("skip", DddRouteDecision.SKIP, usage_offset=6.0),
        )
    )

    result = DddReferenceSolver(stop_after_first_feasible=False).solve(problem)

    assert result.status is DddReferenceStatus.FEASIBLE
    assert result.solution is not None
    assert result.metrics.search_complete
    assert result.metrics.feasible_solution_count == 1
    assert result.metrics.cross_conflict_pruned_count == 2
    assert result.metrics.symmetry_pruned_count > 0
    assert {
        visit.decision
        for trajectory in result.solution.trajectories
        for visit in trajectory.visits
    } == {DddRouteDecision.STOP, DddRouteDecision.SKIP}


def test_reference_solver_proves_unavoidable_merge_conflict_infeasible() -> None:
    problem = _two_cabin_single_visit_problem(
        route_options=(
            _route_option("stop", DddRouteDecision.STOP, usage_offset=2.0),
        )
    )

    result = DddReferenceSolver().solve(problem)

    assert result.status is DddReferenceStatus.INFEASIBLE
    assert result.solution is None
    assert result.metrics.search_complete
    assert result.metrics.cross_conflict_pruned_count == 1


def test_reference_solver_detects_same_cabin_conflict_between_rotations() -> None:
    option = replace(
        _route_option("stop", DddRouteDecision.STOP, usage_offset=0.0),
        duration_seconds=4.0,
        exit_switch_offset_seconds=3.0,
    )
    problem = DddMovementProblem(
        scenario_id="same_cabin_rotation_conflict",
        passenger_service_end_seconds=4.0,
        operational_end_seconds=4.0,
        states=(DddMovementState("A"),),
        starts=(DddFixedStart(0, "A", 0.0, 2),),
        route_options=(option,),
        resources=(DddResource("merge", 5.0),),
    )

    result = DddReferenceSolver().solve(problem)

    assert result.status is DddReferenceStatus.INFEASIBLE
    assert result.metrics.self_conflict_pruned_count == 1
    assert result.metrics.generated_trajectory_count == 0


def test_reference_solver_keeps_post_horizon_clearance_for_active_usage() -> None:
    option = replace(
        _route_option("stop", DddRouteDecision.STOP, usage_offset=4.0),
        resource_usages=(
            DddResourceUsage(
                resource_id="merge",
                leader_clear_offset_seconds=8.0,
                follower_enter_offset_seconds=4.0,
            ),
        ),
    )
    problem = replace(
        _two_cabin_single_visit_problem(route_options=(option,)),
        passenger_service_end_seconds=5.0,
        operational_end_seconds=5.0,
    )

    result = DddReferenceSolver().solve(problem)

    assert result.status is DddReferenceStatus.INFEASIBLE
    assert result.metrics.cross_conflict_pruned_count == 1


def test_reference_solver_ignores_usage_whose_follower_entry_is_after_horizon() -> None:
    option = replace(
        _route_option("stop", DddRouteDecision.STOP, usage_offset=8.0),
        resource_usages=(
            DddResourceUsage(
                resource_id="merge",
                leader_clear_offset_seconds=4.0,
                follower_enter_offset_seconds=8.0,
            ),
        ),
    )
    problem = replace(
        _two_cabin_single_visit_problem(route_options=(option,)),
        passenger_service_end_seconds=5.0,
        operational_end_seconds=5.0,
    )

    result = DddReferenceSolver().solve(problem)

    assert result.status is DddReferenceStatus.FEASIBLE
    assert result.solution is not None
    assert not any(
        visit.resource_occurrences
        for trajectory in result.solution.trajectories
        for visit in trajectory.visits
    )


def test_reference_generator_rejects_insufficient_certified_visit_bound() -> None:
    option = replace(
        _route_option("stop", DddRouteDecision.STOP, usage_offset=0.0),
        duration_seconds=4.0,
        exit_switch_offset_seconds=3.0,
        resource_usages=(),
    )
    problem = DddMovementProblem(
        scenario_id="insufficient_visit_bound",
        passenger_service_end_seconds=4.0,
        operational_end_seconds=4.0,
        states=(DddMovementState("A"),),
        starts=(DddFixedStart(0, "A", 0.0, 1),),
        route_options=(option,),
        resources=(),
    )

    with pytest.raises(ValueError, match="visit bound exhausted"):
        DddReferenceSolver().solve(problem)


def test_ean_adapter_builds_pair_independent_no_wait_problem() -> None:
    artifact = _registered_sparse_artifact(
        "three_station_half_no_skip_no_wait_v0"
    )

    problem = EanArtifactToDddMovementProblemAdapter().build(artifact)

    assert len(problem.starts) == 15
    assert len(problem.states) == 4
    assert len(problem.route_options) == 4
    assert problem.resources
    assert not artifact.headway_pairs
    assert all(start.max_visit_count > 0 for start in problem.starts)


def test_ean_adapter_rejects_waiting_before_enumeration() -> None:
    artifact = _registered_sparse_artifact("three_station_v0")

    with pytest.raises(ValueError, match="does not yet support station waiting"):
        EanArtifactToDddMovementProblemAdapter().build(artifact)


def test_reference_plan_for_registered_example_passes_complete_sparse_validation() -> None:
    artifact = _registered_sparse_artifact(
        "three_station_half_no_skip_no_wait_v0"
    )
    problem = EanArtifactToDddMovementProblemAdapter().build(artifact)
    result = DddReferenceSolver().solve(problem)
    assert result.solution is not None

    plan = DddReferenceToEanMovementPlanAdapter().build(
        problem=problem,
        solution=result.solution,
        artifact=artifact,
    )

    validate_ean_movement_plan_against_artifact(artifact, plan).raise_for_errors()
    assert len(plan.trajectories) == len(problem.starts)
    assert sum(len(item.visits) for item in plan.trajectories) < len(
        artifact.switch_visits
    )


def test_tiny_stop_skip_oracle_and_continuous_ean_agree_on_feasibility() -> None:
    pytest.importorskip("gurobipy")
    scenario = build_three_station_scenario()
    base_config = build_three_station_ean_config(scenario)
    config = replace(
        base_config,
        horizon_seconds=100.0,
        station_configs=tuple(
            replace(station, waiting_mode=StationWaitingMode.NO_WAITING)
            for station in base_config.station_configs
        ),
    )
    artifact = network_ean_builder_for_pattern(
        pattern_definition=build_three_station_ean_pattern_definition(),
        start_builder=_SingleFixedStartBuilder(),
    ).build(scenario, config)
    problem = EanArtifactToDddMovementProblemAdapter().build(artifact)

    reference = DddReferenceSolver(stop_after_first_feasible=False).solve(problem)
    ean = EanOptimizer(
        EanSolveConfig(
            optimization_config=EanOptimizationConfig(
                formulation=EanFormulationConfig(
                    horizon=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
                    time_bounds=EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS,
                )
            )
        )
    ).solve(EanMovementFeasibilityProblem(artifact))

    assert reference.status is DddReferenceStatus.FEASIBLE
    assert reference.metrics.search_complete
    assert reference.metrics.feasible_solution_count == 3
    assert ean.metadata.status == "optimal"
    assert ean.movement_plan is not None


def test_two_cabin_merge_fixture_has_exactly_three_valid_supports() -> None:
    artifact = build_three_station_two_cabin_merge_artifact()
    problem = EanArtifactToDddMovementProblemAdapter().build(artifact)

    result = DddReferenceSolver(
        stop_after_first_feasible=False,
        max_retained_feasible_solutions=10,
    ).solve(problem)

    assert result.status is DddReferenceStatus.FEASIBLE
    assert result.metrics.generated_trajectory_count == 4
    assert result.metrics.combination_attempt_count == 6
    assert result.metrics.cross_conflict_pruned_count == 1
    assert result.metrics.feasible_solution_count == 3
    assert result.metrics.search_complete
    decision_supports = {
        tuple(trajectory.visits[0].decision for trajectory in solution.trajectories)
        for solution in result.retained_solutions
    }
    assert decision_supports == {
        (DddRouteDecision.STOP, DddRouteDecision.STOP),
        (DddRouteDecision.SKIP, DddRouteDecision.STOP),
        (DddRouteDecision.SKIP, DddRouteDecision.SKIP),
    }
    converter = DddReferenceToEanMovementPlanAdapter()
    for solution in result.retained_solutions:
        plan = converter.build(
            problem=problem,
            solution=solution,
            artifact=artifact,
        )
        validate_ean_movement_plan_against_artifact(
            artifact,
            plan,
        ).raise_for_errors()


def test_two_cabin_merge_fixture_rejects_only_target_stop_skip_support() -> None:
    artifact = build_three_station_two_cabin_merge_artifact()
    problem = EanArtifactToDddMovementProblemAdapter().build(artifact)
    result = DddReferenceSolver(
        stop_after_first_feasible=False,
        max_retained_feasible_solutions=10,
    ).solve(problem)
    stop_stop = next(
        solution
        for solution in result.retained_solutions
        if all(
            trajectory.visits[0].decision is DddRouteDecision.STOP
            for trajectory in solution.trajectories
        )
    )
    plan = DddReferenceToEanMovementPlanAdapter().build(
        problem=problem,
        solution=stop_stop,
        artifact=artifact,
    )
    second_trajectory = next(
        trajectory for trajectory in plan.trajectories if trajectory.cabin_id == 1
    )
    second_visit = second_trajectory.visits[0]
    timing = next(
        timing for timing in artifact.timings if timing.switch_id == second_visit.switch_id
    )
    invalid_second_visit = replace(
        second_visit,
        decision=EanRouteDecision.SKIP,
        platform_entry_time_seconds=None,
        platform_exit_time_seconds=None,
        exit_switch_time_seconds=(
            second_visit.switch_time_seconds
            + timing.skip_entry_to_exit_switch_seconds
        ),
        next_switch_time_seconds=(
            second_visit.switch_time_seconds
            + timing.skip_entry_to_exit_switch_seconds
            + timing.rope_to_next_switch_seconds
        ),
    )
    invalid_plan = replace(
        plan,
        trajectories=tuple(
            replace(trajectory, visits=(invalid_second_visit,))
            if trajectory.cabin_id == 1
            else trajectory
            for trajectory in plan.trajectories
        ),
    )

    violations = separate_all_headway_violations(artifact, invalid_plan)
    report = validate_ean_movement_plan_against_artifact(artifact, invalid_plan)

    assert len(violations) == 1
    assert violations[0].pair.checkpoint_id == "exit_switch::M_entry_lr"
    assert violations[0].violation_seconds == pytest.approx(0.2181818182)
    assert {issue.code for issue in report.issues} == {"EAN_HEADWAY_VIOLATION"}


def test_two_cabin_merge_oracle_and_eager_ean_agree_on_feasibility() -> None:
    pytest.importorskip("gurobipy")
    artifact = build_three_station_two_cabin_merge_artifact(
        headway_pair_builder=AllPairsHeadwayPairBuilder(),
    )
    problem = EanArtifactToDddMovementProblemAdapter().build(artifact)

    reference = DddReferenceSolver(stop_after_first_feasible=False).solve(problem)
    ean = EanOptimizer(
        EanSolveConfig(
            optimization_config=EanOptimizationConfig(
                formulation=EanFormulationConfig(
                    horizon=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
                    time_bounds=EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS,
                )
            )
        )
    ).solve(EanMovementFeasibilityProblem(artifact))

    assert reference.status is DddReferenceStatus.FEASIBLE
    assert reference.metrics.feasible_solution_count == 3
    assert artifact.headway_pairs
    assert ean.metadata.status == "optimal"
    assert ean.movement_plan is not None
    validate_ean_movement_plan_against_artifact(
        artifact,
        ean.movement_plan,
    ).raise_for_errors()


def test_support_master_lift_add_cut_and_resolve_two_cabin_fixture() -> None:
    artifact = build_three_station_two_cabin_merge_artifact()
    problem = EanArtifactToDddMovementProblemAdapter().build(artifact)
    objective = build_three_station_two_cabin_merge_probe_objective(problem)
    master = DddSupportMaster(problem)

    first_master = master.solve(objective=objective)

    assert first_master.status is DddSupportMasterStatus.OPTIMAL
    assert first_master.selection is not None
    assert _first_decisions(first_master.selection) == (
        DddRouteDecision.STOP,
        DddRouteDecision.SKIP,
    )
    first_lift = DddExactSupportLifter().lift(problem, first_master.selection)
    assert first_lift.status is DddExactLiftStatus.CONFLICT
    assert len(first_lift.conflicts) == 1
    assert first_lift.conflicts[0].violation_seconds == pytest.approx(0.2181818182)
    assert len(first_lift.cuts) == 1
    cut = first_lift.cuts[0]
    assert cut.right_hand_side == 1
    assert len(cut.literals) == 2
    assert cut.excludes(first_master.selection)

    second_master = master.solve(objective=objective, cuts=(cut,))

    assert second_master.status is DddSupportMasterStatus.OPTIMAL
    assert second_master.selection is not None
    assert _first_decisions(second_master.selection) != (
        DddRouteDecision.STOP,
        DddRouteDecision.SKIP,
    )
    second_lift = DddExactSupportLifter().lift(problem, second_master.selection)
    assert second_lift.status is DddExactLiftStatus.FEASIBLE
    assert second_lift.solution is not None
    plan = DddReferenceToEanMovementPlanAdapter().build(
        problem=problem,
        solution=second_lift.solution,
        artifact=artifact,
    )
    validate_ean_movement_plan_against_artifact(artifact, plan).raise_for_errors()


def test_prefix_cut_removes_only_the_proven_infeasible_fixture_support() -> None:
    artifact = build_three_station_two_cabin_merge_artifact()
    problem = EanArtifactToDddMovementProblemAdapter().build(artifact)
    reference = DddReferenceSolver(
        stop_after_first_feasible=False,
        max_retained_feasible_solutions=10,
    ).solve(problem)
    master = DddSupportMaster(problem)
    first_master = master.solve(
        objective=build_three_station_two_cabin_merge_probe_objective(problem)
    )
    assert first_master.selection is not None
    lift = DddExactSupportLifter().lift(problem, first_master.selection)
    cut = lift.cuts[0]

    assert master.candidate_support_count == 4
    assert all(
        not cut.excludes(DddSupportSelection(solution.trajectories))
        for solution in reference.retained_solutions
    )
    after_cut = master.solve(cuts=(cut,))
    assert after_cut.cut_rejected_support_count == 1


def test_delayed_conflict_solver_closes_fixture_in_two_rounds() -> None:
    artifact = build_three_station_two_cabin_merge_artifact()
    problem = EanArtifactToDddMovementProblemAdapter().build(artifact)

    result = DddDelayedConflictSolver().solve(
        problem,
        objective=build_three_station_two_cabin_merge_probe_objective(problem),
    )

    assert result.status is DddIterativeStatus.FEASIBLE
    assert result.solution is not None
    assert result.final_lift_complete
    assert result.candidate_support_count == 4
    assert len(result.cuts) == 1
    assert len(result.iterations) == 2
    assert result.iterations[0].conflict_count == 1
    assert len(result.iterations[0].added_cut_ids) == 1
    assert result.iterations[1].conflict_count == 0
    plan = DddReferenceToEanMovementPlanAdapter().build(
        problem=problem,
        solution=result.solution,
        artifact=artifact,
    )
    validate_ean_movement_plan_against_artifact(artifact, plan).raise_for_errors()


def test_delayed_conflict_solver_reports_unfinished_lift_at_iteration_limit() -> None:
    artifact = build_three_station_two_cabin_merge_artifact()
    problem = EanArtifactToDddMovementProblemAdapter().build(artifact)

    result = DddDelayedConflictSolver(max_iterations=1).solve(
        problem,
        objective=build_three_station_two_cabin_merge_probe_objective(problem),
    )

    assert result.status is DddIterativeStatus.ITERATION_LIMIT
    assert result.solution is None
    assert not result.final_lift_complete
    assert len(result.cuts) == 1
    assert len(result.iterations) == 1


def test_support_master_rejects_cut_with_unknown_literal() -> None:
    artifact = build_three_station_two_cabin_merge_artifact()
    problem = EanArtifactToDddMovementProblemAdapter().build(artifact)
    master = DddSupportMaster(problem)
    cut = DddSupportConflictCut(
        id="unknown",
        literals=(
            DddSupportLiteral(0, 0, "unknown_route"),
            DddSupportLiteral(1, 0, "unknown_route"),
        ),
        resource_id="exit_switch::M_entry_lr",
        violation_seconds=1.0,
    )

    with pytest.raises(ValueError, match="references unknown literals"):
        master.solve(cuts=(cut,))


@dataclass(frozen=True)
class _SingleFixedStartBuilder(EanCabinStartBuilder):
    def build(
        self,
        scenario: Scenario,
        config: EanConfig,
        network: EanMovementNetwork,
        pattern: EanCirculationPattern,
    ) -> tuple[EanCabinStart, ...]:
        return (
            EanCabinStart(
                cabin_id=0,
                first_switch_id=pattern.state_ids[0],
                kind=EanCabinStartKind.FIXED,
                time_seconds=0.0,
            ),
        )


def _registered_sparse_artifact(example_id: str):
    example = get_example(example_id)
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    builder = replace(
        example.build_ean_artifact_builder(scenario, config),
        headway_pair_builder=SparseHeadwayPairBuilder(),
    )
    return builder.build(scenario, config)


def _two_cabin_single_visit_problem(
    *,
    route_options: tuple[DddRouteOption, ...],
) -> DddMovementProblem:
    problem = DddMovementProblem(
        scenario_id="two_cabin_single_visit",
        passenger_service_end_seconds=9.0,
        operational_end_seconds=9.0,
        states=(DddMovementState("A"),),
        starts=(
            DddFixedStart(0, "A", 0.0, 1),
            DddFixedStart(1, "A", 0.0, 1),
        ),
        route_options=route_options,
        resources=(DddResource("merge", 3.0),),
    )
    problem.validate()
    return problem


def _route_option(
    option_id: str,
    decision: DddRouteDecision,
    *,
    usage_offset: float,
) -> DddRouteOption:
    return DddRouteOption(
        id=option_id,
        from_state_id="A",
        to_state_id="A",
        station_id="S",
        decision=decision,
        duration_seconds=10.0,
        platform_entry_offset_seconds=(1.0 if decision is DddRouteDecision.STOP else None),
        platform_exit_offset_seconds=(2.0 if decision is DddRouteDecision.STOP else None),
        exit_switch_offset_seconds=3.0,
        resource_usages=(
            DddResourceUsage(
                resource_id="merge",
                leader_clear_offset_seconds=usage_offset,
                follower_enter_offset_seconds=usage_offset,
            ),
        ),
    )


def _first_decisions(
    selection: DddSupportSelection,
) -> tuple[DddRouteDecision, ...]:
    return tuple(
        trajectory.visits[0].decision
        for trajectory in sorted(
            selection.trajectories,
            key=lambda item: item.cabin_id,
        )
    )
