from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_cases import (
    build_three_station_network_combined_artifact,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.examples.three_station import (
    build_three_station_scenario,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddCpSatMasterCoupling,
    DddCpSatPrimalOracle,
    DddEanPassengerPrimalEvaluator,
    DddPrimalEvaluationResult,
    DddNetworkTimeRefinementSolver,
    DddNetworkTimeRefinementStatus,
    DddPrimalEvaluationStatus,
    DddReferenceToEanMovementPlanAdapter,
    DddRouteOptionCost,
    DddTrajectorySlotPoolStatus,
    DddTrajectoryBoundStatus,
    DddTrajectoryOptimizerMode,
    DddTrajectoryPassengerLpStatus,
    DddTrajectoryColumnPool,
    DddTrajectorySlotCandidate,
    EanArtifactToDddMovementProblemAdapter,
    build_ddd_passenger_master_problem,
)
from ropeway_skip_stop_optimization.optimization.ean import EanPassengerObjective
from ropeway_skip_stop_optimization.optimization.ddd.network_refinement import (
    _validate_reference_solution,
)


@pytest.mark.parametrize(
    "objective",
    (
        EanPassengerObjective.WAITING_TIME,
        EanPassengerObjective.JOURNEY_TIME,
    ),
)
def test_cp_sat_timetable_receives_exact_fixed_movement_passenger_assignment(
    objective: EanPassengerObjective,
) -> None:
    pytest.importorskip("gurobipy")
    pytest.importorskip("ortools")
    artifact = build_three_station_network_combined_artifact()
    scenario = replace(build_three_station_scenario(), id=artifact.scenario_id)
    movement = EanArtifactToDddMovementProblemAdapter().build(artifact)
    problem = build_initial_ddd_network_problem(movement)
    evaluator = DddEanPassengerPrimalEvaluator(
        scenario=scenario,
        artifact=artifact,
        objective=objective,
        time_limit_seconds=5.0,
    )

    result = DddNetworkTimeRefinementSolver(
        max_iterations=2,
        max_new_time_splits_per_iteration=100,
        cp_sat_time_limit_seconds=5.0,
        cp_sat_max_candidate_count=3,
        trajectory_optimizer_mode=DddTrajectoryOptimizerMode.RESTRICTED_PRIMAL,
    ).solve(problem, primal_evaluator=evaluator)

    assert result.status is DddNetworkTimeRefinementStatus.FEASIBLE_WITH_GAP
    assert result.global_lower_bound == pytest.approx(0.0)
    assert result.global_upper_bound is not None
    assert result.global_upper_bound >= 0.0
    assert result.primal_evaluation is not None
    assert result.primal_evaluation.status is DddPrimalEvaluationStatus.FEASIBLE
    assert result.primal_evaluation.objective_kind is objective
    assert result.primal_evaluation.passenger_plan is not None
    assert result.primal_evaluation.movement_plan is not None
    assert result.iterations[0].cp_sat_candidate_count == 3
    assert result.iterations[0].primal_evaluation_count >= 3
    assert (
        result.iterations[0].trajectory_pool_status
        is DddTrajectorySlotPoolStatus.FEASIBLE
    )
    assert result.iterations[0].trajectory_pool_option_count >= len(movement.starts)
    assert result.iterations[0].trajectory_pool_candidate_count >= 2
    assert (
        result.iterations[0].trajectory_bound_status
        is DddTrajectoryBoundStatus.PRIMAL_POOL_ONLY
    )
    assert result.iterations[0].trajectory_certified_lower_bound is None
    assert all(
        iteration.trajectory_optimizer_mode
        is DddTrajectoryOptimizerMode.RESTRICTED_PRIMAL
        for iteration in result.iterations
    )
    assert all(
        iteration.trajectory_bound_status is DddTrajectoryBoundStatus.PRIMAL_POOL_ONLY
        for iteration in result.iterations
    )
    assert all(
        iteration.trajectory_pool_option_count >= len(movement.starts)
        for iteration in result.iterations
    )
    assert result.iterations[0].trajectory_pool_ride_variable_count > 0
    assert (
        result.iterations[0].trajectory_pool_lp_status
        is DddTrajectoryPassengerLpStatus.OPTIMAL
    )
    assert result.iterations[0].trajectory_pool_lp_objective_value is not None
    assert result.iterations[0].trajectory_pool_lp_dual_fingerprint
    assert result.iterations[0].trajectory_pool_lp_row_separation_complete
    assert (
        result.iterations[0].trajectory_pool_lp_incompatibility_count
        >= result.iterations[0].trajectory_pool_incompatibility_count
    )
    assert result.iterations[0].trajectory_pool_lp_total_seconds > 0.0
    solved_pool_rounds = tuple(
        iteration
        for iteration in result.iterations
        if iteration.trajectory_pool_solved_this_round
    )
    assert solved_pool_rounds
    assert solved_pool_rounds[0].trajectory_pool_master_model_created
    assert solved_pool_rounds[0].trajectory_pool_option_cache_miss_count > 0
    assert (
        solved_pool_rounds[0].trajectory_pool_time_to_first_incumbent_seconds
        is not None
    )
    assert all(
        iteration.trajectory_pool_seconds == 0.0
        for iteration in result.iterations
        if not iteration.trajectory_pool_solved_this_round
    )
    assert len(result.iterations[0].primal_candidate_summaries) >= 3
    candidate_objectives = tuple(
        summary.objective_value
        for summary in result.iterations[0].primal_candidate_summaries
        if summary.objective_value is not None
    )
    assert result.global_upper_bound == min(candidate_objectives)
    assert result.global_upper_bound <= candidate_objectives[0]
    assert result.iterations[0].primal_objective_value == result.global_upper_bound


def test_valid_movement_column_is_retained_when_passenger_recourse_is_unknown() -> None:
    pytest.importorskip("ortools")
    artifact = build_three_station_network_combined_artifact()
    movement = EanArtifactToDddMovementProblemAdapter().build(artifact)
    problem = build_initial_ddd_network_problem(movement)

    class UnknownEvaluator:
        def validate_problem(self, checked_problem: object) -> None:
            assert checked_problem is problem

        def evaluate(
            self,
            checked_problem: object,
            solution: object,
        ) -> DddPrimalEvaluationResult:
            movement_plan = DddReferenceToEanMovementPlanAdapter().build(
                problem=problem.movement_problem,
                solution=solution,
                artifact=artifact,
            )
            return DddPrimalEvaluationResult(
                status=DddPrimalEvaluationStatus.UNKNOWN,
                objective_value=None,
                objective_kind=EanPassengerObjective.JOURNEY_TIME,
                objective_unit="passenger_seconds",
                movement_plan=movement_plan,
                passenger_plan=None,
                solver_status="time_limit",
                passenger_candidate_count=0,
                assignment_variable_count=0,
                served_passenger_count=None,
                unserved_passenger_count=None,
                setup_seconds=0.0,
                solve_seconds=0.0,
                total_seconds=0.0,
            )

        def evaluate_trajectory_pool(self, *args: object) -> object:
            raise AssertionError("one candidate must not trigger recombination")

    result = DddNetworkTimeRefinementSolver(
        max_iterations=1,
        cp_sat_time_limit_seconds=5.0,
        cp_sat_max_candidate_count=1,
        trajectory_optimizer_mode=DddTrajectoryOptimizerMode.RESTRICTED_PRIMAL,
    ).solve(problem, primal_evaluator=UnknownEvaluator())

    assert (
        result.iterations[0].primal_evaluation_status
        is DddPrimalEvaluationStatus.UNKNOWN
    )
    assert result.iterations[0].trajectory_pool_candidate_count == 1
    assert result.iterations[0].trajectory_pool_option_count == len(movement.starts)
    assert (
        result.iterations[0].trajectory_bound_status
        is DddTrajectoryBoundStatus.PRIMAL_POOL_ONLY
    )


def test_restricted_master_reuses_model_when_pool_grows() -> None:
    pytest.importorskip("gurobipy")
    pytest.importorskip("ortools")
    artifact = build_three_station_network_combined_artifact()
    scenario = replace(build_three_station_scenario(), id=artifact.scenario_id)
    movement = EanArtifactToDddMovementProblemAdapter().build(artifact)
    problem = build_initial_ddd_network_problem(movement)
    evaluator = DddEanPassengerPrimalEvaluator(
        scenario=scenario,
        artifact=artifact,
        objective=EanPassengerObjective.JOURNEY_TIME,
        time_limit_seconds=5.0,
    )
    cp_result = DddCpSatPrimalOracle(
        time_limit_seconds=5.0,
        num_workers=1,
        max_candidate_count=3,
    ).solve(problem)
    schedule_sets = cp_result.candidate_schedules
    assert len(schedule_sets) >= 2
    pool = DddTrajectoryColumnPool()

    def add(schedule_set: object) -> int:
        validation = _validate_reference_solution(
            problem,
            schedule_set,
            tolerance_seconds=1e-9,
        )
        assert validation.solution is not None
        evaluation = evaluator.evaluate(problem, validation.solution)
        assert evaluation.movement_plan is not None
        return pool.add_candidate(
            DddTrajectorySlotCandidate(
                schedules=schedule_set,
                reference_solution=validation.solution,
                movement_plan=evaluation.movement_plan,
            )
        )

    assert add(schedule_sets[0]) == len(movement.starts)
    first = evaluator.evaluate_trajectory_pool(problem, pool)
    assert first.pool_result.status is DddTrajectorySlotPoolStatus.FEASIBLE
    assert first.pool_result.master_model_created
    assert first.pool_result.option_cache_hit_count == 0
    assert first.pool_result.option_cache_miss_count == pool.column_count
    assert first.pool_result.added_trajectory_option_count == pool.column_count
    assert (
        first.pool_result.added_ride_variable_count
        == first.pool_result.ride_variable_count
    )
    assert first.pool_result.time_to_first_incumbent_seconds is not None
    first_state = next(iter(pool._master_model_states.values()))
    first_model_id = id(first_state.model)
    first_variable_count = first_state.model.NumVars

    assert add(schedule_sets[1]) > 0
    second = evaluator.evaluate_trajectory_pool(problem, pool)
    second_state = next(iter(pool._master_model_states.values()))
    assert id(second_state.model) == first_model_id
    assert second_state.model.NumVars > first_variable_count
    assert second.pool_result.trajectory_option_count == pool.column_count
    assert not second.pool_result.master_model_created
    assert second.pool_result.option_cache_hit_count > 0
    assert second.pool_result.option_cache_miss_count > 0
    assert second.pool_result.added_trajectory_option_count > 0
    assert second.pool_result.added_ride_variable_count == (
        second.pool_result.ride_variable_count - first.pool_result.ride_variable_count
    )
    assert second.pool_result.time_to_first_incumbent_seconds == 0.0


def test_passenger_evaluator_rejects_unrelated_master_objective() -> None:
    artifact = build_three_station_network_combined_artifact()
    scenario = replace(build_three_station_scenario(), id=artifact.scenario_id)
    movement = EanArtifactToDddMovementProblemAdapter().build(artifact)
    problem = build_initial_ddd_network_problem(movement)
    first_cost = problem.objective.route_option_costs[0]
    priced_problem = replace(
        problem,
        objective=replace(
            problem.objective,
            route_option_costs=(
                DddRouteOptionCost(first_cost.route_option_id, 1.0),
                *problem.objective.route_option_costs[1:],
            ),
        ),
    )
    evaluator = DddEanPassengerPrimalEvaluator(
        scenario=scenario,
        artifact=artifact,
    )

    with pytest.raises(ValueError, match="zero-cost DDD master"):
        evaluator.validate_problem(priced_problem)


def test_anonymous_passenger_master_and_fixed_support_cp_produce_valid_bounds() -> None:
    artifact = build_three_station_network_combined_artifact()
    scenario = replace(build_three_station_scenario(), id=artifact.scenario_id)
    movement = EanArtifactToDddMovementProblemAdapter().build(artifact)
    problem = build_initial_ddd_network_problem(movement)
    objective = EanPassengerObjective.JOURNEY_TIME
    evaluator = DddEanPassengerPrimalEvaluator(
        scenario=scenario,
        artifact=artifact,
        objective=objective,
        time_limit_seconds=5.0,
    )
    passenger_master = build_ddd_passenger_master_problem(
        scenario=scenario,
        artifact=artifact,
        movement_problem=movement,
        objective=objective,
    )

    result = DddNetworkTimeRefinementSolver(
        max_iterations=20,
        max_new_time_splits_per_iteration=100,
        cp_sat_time_limit_seconds=5.0,
        cp_sat_num_workers=1,
        cp_sat_master_coupling=(DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT),
    ).solve(
        problem,
        primal_evaluator=evaluator,
        passenger_master_problem=passenger_master,
    )

    assert result.global_lower_bound is not None
    assert result.global_upper_bound is not None
    assert result.global_lower_bound <= result.global_upper_bound + 1e-6
    assert result.primal_evaluation is not None
    assert result.primal_evaluation.status is DddPrimalEvaluationStatus.FEASIBLE
    assert result.iterations[0].master_passenger_variable_count > 0
    assert result.iterations[0].master_passenger_constraint_count > 0
    assert result.iterations[0].master_served_passenger_count is not None
