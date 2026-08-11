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
    DddEanPassengerPrimalEvaluator,
    DddNetworkTimeRefinementSolver,
    DddNetworkTimeRefinementStatus,
    DddPrimalEvaluationStatus,
    DddRouteOptionCost,
    DddTrajectorySlotPoolStatus,
    EanArtifactToDddMovementProblemAdapter,
    build_ddd_passenger_master_problem,
)
from ropeway_skip_stop_optimization.optimization.ean import EanPassengerObjective


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
        max_iterations=1,
        max_new_time_splits_per_iteration=100,
        cp_sat_time_limit_seconds=5.0,
        cp_sat_max_candidate_count=3,
        use_trajectory_slot_pool=True,
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
    assert result.iterations[0].trajectory_pool_ride_variable_count > 0
    assert len(result.iterations[0].primal_candidate_summaries) >= 3
    candidate_objectives = tuple(
        summary.objective_value
        for summary in result.iterations[0].primal_candidate_summaries
        if summary.objective_value is not None
    )
    assert result.global_upper_bound == min(candidate_objectives)
    assert result.global_upper_bound <= candidate_objectives[0]
    assert result.iterations[0].primal_objective_value == result.global_upper_bound


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
        cp_sat_master_coupling=(
            DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT
        ),
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
