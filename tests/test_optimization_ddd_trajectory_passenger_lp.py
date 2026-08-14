from dataclasses import replace
from random import Random

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
    DddCpSatPrimalOracle,
    DddEanPassengerPrimalEvaluator,
    DddTrajectoryBoundStatus,
    DddTrajectoryColumnPool,
    DddTrajectoryFactorizedLpOptimizer,
    DddTrajectoryIntegratedLpReferenceOptimizer,
    DddTrajectoryPassengerLpStatus,
    DddTrajectoryPassengerMasterProblem,
    DddTrajectoryPassengerOption,
    DddTrajectoryPassengerRide,
    DddTrajectorySlotCandidate,
    EanArtifactToDddMovementProblemAdapter,
    build_ddd_trajectory_passenger_master_problem,
    build_ddd_trajectory_heuristic_pricing_signal,
    enumerate_ddd_trajectory_load_patterns,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_refinement import (
    _validate_reference_solution,
)
from ropeway_skip_stop_optimization.optimization.ean import EanPassengerObjective


def _ride(
    ride_id: str,
    *,
    cost: float = -8.0,
    segments: tuple[str, ...] = ("segment",),
) -> DddTrajectoryPassengerRide:
    return DddTrajectoryPassengerRide(
        id=ride_id,
        demand_group_id="g",
        upper_bound=1.0,
        objective_delta=cost,
        onboard_segment_ids=segments,
    )


def test_load_pattern_enumeration_finds_capacity_polytope_vertices() -> None:
    option = DddTrajectoryPassengerOption(
        id="option",
        cabin_id=0,
        rides=(_ride("first"), _ride("second")),
    )

    patterns = enumerate_ddd_trajectory_load_patterns(
        option,
        cabin_capacity=1.0,
    )

    counts = {
        tuple(
            round(dict(pattern.ride_counts).get(ride_id, 0.0), 9)
            for ride_id in ("first", "second")
        )
        for pattern in patterns
    }
    assert counts == {(0.0, 0.0), (0.0, 1.0), (1.0, 0.0)}


def test_load_pattern_reference_retains_fractional_extreme_points() -> None:
    option = DddTrajectoryPassengerOption(
        id="fractional",
        cabin_id=0,
        rides=(
            _ride("first", segments=("s12", "s13")),
            _ride("second", segments=("s12", "s23")),
            _ride("third", segments=("s13", "s23")),
        ),
    )

    patterns = enumerate_ddd_trajectory_load_patterns(
        option,
        cabin_capacity=1.0,
    )

    assert any(
        tuple(
            dict(pattern.ride_counts).get(ride_id, 0.0)
            for ride_id in ("first", "second", "third")
        )
        == pytest.approx((0.5, 0.5, 0.5))
        for pattern in patterns
    )


def test_factorized_and_integrated_passenger_lps_are_equivalent() -> None:
    problem = DddTrajectoryPassengerMasterProblem(
        cabin_ids=(0,),
        demand_by_group_id={"g": 0.5},
        options=(
            DddTrajectoryPassengerOption("a", 0, (_ride("ride"),)),
            DddTrajectoryPassengerOption("b", 0, ()),
        ),
        cabin_capacity=1.0,
        objective_constant=10.0,
    )

    factorized = DddTrajectoryFactorizedLpOptimizer().solve(problem)
    integrated_optimizer = DddTrajectoryIntegratedLpReferenceOptimizer()
    integrated = integrated_optimizer.solve(problem)
    repeated = integrated_optimizer.solve(problem)

    assert factorized.status is DddTrajectoryPassengerLpStatus.OPTIMAL
    assert integrated.status is DddTrajectoryPassengerLpStatus.OPTIMAL
    assert factorized.objective_value == pytest.approx(6.0)
    assert integrated.objective_value == pytest.approx(factorized.objective_value)
    assert integrated.ride_values_by_id == pytest.approx(factorized.ride_values_by_id)
    assert integrated.pattern_count == 3
    assert integrated.bound_status is DddTrajectoryBoundStatus.PRIMAL_POOL_ONLY
    assert integrated.certified_lower_bound is None
    assert integrated.duals is not None
    assert integrated.duals.demand_raw_by_group_id["g"] == pytest.approx(-8.0)
    assert integrated.duals.demand_marginal_value_by_group_id["g"] == pytest.approx(8.0)
    assert repeated.duals is not None
    assert repeated.duals.fingerprint == integrated.duals.fingerprint
    assert repeated.master_fingerprint == integrated.master_fingerprint
    patterns = tuple(
        pattern
        for option in problem.options
        for pattern in enumerate_ddd_trajectory_load_patterns(
            option,
            cabin_capacity=problem.cabin_capacity,
        )
    )
    for pattern in patterns:
        demand_coefficient = sum(count for _, count in pattern.ride_counts)
        reduced_cost = (
            pattern.objective_delta
            - integrated.duals.cabin_choice_raw_by_cabin_id[0]
            - integrated.duals.demand_raw_by_group_id["g"] * demand_coefficient
        )
        assert reduced_cost >= -1e-7
        if integrated.pattern_values_by_id[pattern.id] > 1e-7:
            assert reduced_cost == pytest.approx(0.0, abs=1e-7)


def test_integrated_demand_dual_matches_finite_difference() -> None:
    problem = DddTrajectoryPassengerMasterProblem(
        cabin_ids=(0,),
        demand_by_group_id={"g": 0.5},
        options=(
            DddTrajectoryPassengerOption("a", 0, (_ride("ride"),)),
            DddTrajectoryPassengerOption("b", 0, ()),
        ),
        cabin_capacity=1.0,
        objective_constant=10.0,
    )
    optimizer = DddTrajectoryIntegratedLpReferenceOptimizer()
    baseline = optimizer.solve(problem)
    epsilon = 1e-4
    perturbed = optimizer.solve(problem.with_demand_rhs("g", 0.5 + epsilon))

    assert baseline.objective_value is not None
    assert perturbed.objective_value is not None
    assert baseline.duals is not None
    finite_difference = (perturbed.objective_value - baseline.objective_value) / epsilon
    assert finite_difference == pytest.approx(
        baseline.duals.demand_raw_by_group_id["g"],
        abs=1e-6,
    )


def test_factorized_and_integrated_lps_preserve_option_conflicts() -> None:
    problem = DddTrajectoryPassengerMasterProblem(
        cabin_ids=(0, 1),
        demand_by_group_id={"g": 2.0},
        options=(
            DddTrajectoryPassengerOption("a", 0, (_ride("ride_a", cost=-5.0),)),
            DddTrajectoryPassengerOption("a_empty", 0, ()),
            DddTrajectoryPassengerOption("b", 1, (_ride("ride_b", cost=-5.0),)),
            DddTrajectoryPassengerOption("b_empty", 1, ()),
        ),
        cabin_capacity=1.0,
        objective_constant=20.0,
        incompatibility_pairs=(("a", "b"),),
    )

    factorized = DddTrajectoryFactorizedLpOptimizer().solve(problem)
    integrated = DddTrajectoryIntegratedLpReferenceOptimizer().solve(problem)

    assert factorized.objective_value == pytest.approx(15.0)
    assert integrated.objective_value == pytest.approx(15.0)
    assert integrated.duals is not None
    assert integrated.duals.incompatibility_raw_by_pair["a", "b"] <= 0.0


def test_factorized_and_integrated_lps_match_on_random_tiny_instances() -> None:
    random = Random(7)
    factorized_optimizer = DddTrajectoryFactorizedLpOptimizer()
    integrated_optimizer = DddTrajectoryIntegratedLpReferenceOptimizer()

    for instance_index in range(10):
        options = []
        for cabin_id in range(2):
            for option_index in range(2):
                option_id = f"c{cabin_id}_o{option_index}"
                rides = tuple(
                    DddTrajectoryPassengerRide(
                        id=f"{option_id}_r{ride_index}",
                        demand_group_id=f"g{ride_index}",
                        upper_bound=float(random.randint(1, 2)),
                        objective_delta=-float(random.randint(1, 9)),
                        onboard_segment_ids=(
                            "s0",
                            *(("s1",) if random.randint(0, 1) else ()),
                        ),
                    )
                    for ride_index in range(2)
                )
                options.append(DddTrajectoryPassengerOption(option_id, cabin_id, rides))
        problem = DddTrajectoryPassengerMasterProblem(
            cabin_ids=(0, 1),
            demand_by_group_id={
                "g0": float(random.randint(1, 3)),
                "g1": float(random.randint(1, 3)),
            },
            options=tuple(options),
            cabin_capacity=2.0,
            objective_constant=float(100 + instance_index),
            incompatibility_pairs=(("c0_o0", "c1_o0"),),
        )

        factorized = factorized_optimizer.solve(problem)
        integrated = integrated_optimizer.solve(problem)

        assert factorized.objective_value == pytest.approx(
            integrated.objective_value,
            abs=1e-7,
        )


def test_real_column_pool_builds_factorized_lp_below_integer_pool_value() -> None:
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
        max_candidate_count=2,
    ).solve(problem)
    pool = DddTrajectoryColumnPool()
    for schedules in cp_result.candidate_schedules:
        validation = _validate_reference_solution(
            problem,
            schedules,
            tolerance_seconds=1e-9,
        )
        assert validation.solution is not None
        evaluation = evaluator.evaluate(problem, validation.solution)
        assert evaluation.movement_plan is not None
        pool.add_candidate(
            DddTrajectorySlotCandidate(
                schedules=schedules,
                reference_solution=validation.solution,
                movement_plan=evaluation.movement_plan,
            )
        )
    master_problem = build_ddd_trajectory_passenger_master_problem(
        problem=problem,
        artifact=artifact,
        passenger_build=evaluator.passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        column_pool=pool,
        complete_incompatibility_separation=True,
    )
    lp_result = DddTrajectoryFactorizedLpOptimizer().solve(master_problem)
    pool_evaluation = evaluator.evaluate_trajectory_pool(problem, pool)
    integer_result = pool_evaluation.pool_result

    assert master_problem.fingerprint
    assert len(master_problem.options) == pool.column_count
    assert lp_result.status is DddTrajectoryPassengerLpStatus.OPTIMAL
    assert lp_result.objective_value is not None
    assert integer_result.restricted_objective_value is not None
    assert lp_result.objective_value <= integer_result.restricted_objective_value + 1e-6
    assert lp_result.bound_status is DddTrajectoryBoundStatus.PRIMAL_POOL_ONLY
    assert lp_result.certified_lower_bound is None
    assert pool_evaluation.lp_result is not None
    assert pool_evaluation.lp_result.status is DddTrajectoryPassengerLpStatus.OPTIMAL
    assert pool_evaluation.lp_result.duals is not None
    assert pool_evaluation.lp_result.duals.fingerprint
    assert pool_evaluation.lp_result.row_separation_complete
    assert (
        pool_evaluation.lp_result.incompatibility_constraint_count
        >= integer_result.incompatibility_constraint_count
    )
    pricing_signal = build_ddd_trajectory_heuristic_pricing_signal(
        movement_problem=movement,
        artifact=artifact,
        passenger_build=evaluator.passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        lp_result=pool_evaluation.lp_result,
    )
    repeated_signal = evaluator.build_trajectory_pricing_signal(
        problem,
        pool_evaluation.lp_result,
    )
    assert pricing_signal.preferences
    assert pricing_signal.fingerprint == repeated_signal.fingerprint
    assert pricing_signal.dual_fingerprint == (
        pool_evaluation.lp_result.duals.fingerprint
    )
