from dataclasses import replace
from random import Random

import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_cases import (
    build_three_station_exhaustive_bound_artifact,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.examples.three_station import (
    build_three_station_scenario,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddExhaustiveTrajectoryLimitError,
    DddExhaustiveTrajectoryMasterBuilder,
    DddTrajectoryBoundStatus,
    DddTrajectoryConflictRowMode,
    DddTrajectoryDiversityMode,
    DddTrajectoryFactorizedLpOptimizer,
    DddTrajectoryFactorizedMipReferenceOptimizer,
    DddTrajectoryMasterDualMode,
    DddTrajectoryPricingFormulation,
    DddTrajectoryExactRootColumnGenerationSolver,
    DddTrajectoryExactNoWaitPricingOracle,
    DddTrajectoryExactPricingStatus,
    DddTrajectoryExhaustivePricingOracle,
    DddTrajectoryPassengerDuals,
    DddTrajectoryRootCgStatus,
    DddTrajectoryPassengerLpStatus,
    EanArtifactToDddMovementProblemAdapter,
    build_ddd_trajectory_resource_window_rows,
    ddd_trajectory_pair_has_resource_window_witness,
    enumerate_ddd_trajectory_resource_windows,
    read_ddd_trajectory_root_cg_checkpoint,
    write_ddd_trajectory_root_cg_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanPassengerCandidateBuilder,
    EanPassengerObjective,
    StationWaitingMode,
)


def _physical_problem() -> tuple[object, object, object]:
    artifact = build_three_station_exhaustive_bound_artifact()
    scenario = replace(build_three_station_scenario(), id=artifact.scenario_id)
    movement = EanArtifactToDddMovementProblemAdapter().build(artifact)
    problem = build_initial_ddd_network_problem(movement)
    passenger_build = EanPassengerCandidateBuilder().build(scenario, artifact)
    return problem, artifact, passenger_build


def test_complete_tiny_no_wait_master_certifies_lp_and_integer_gap() -> None:
    pytest.importorskip("gurobipy")
    problem, artifact, passenger_build = _physical_problem()
    built = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )

    assert built.trajectory_count_by_cabin_id == {0: 8, 1: 8, 2: 7}
    assert built.trajectory_count == 23
    assert built.incompatibility_pair_check_count == 176
    assert len(built.master_problem.incompatibility_pairs) == 63
    assert sum(len(option.rides) for option in built.master_problem.options) == 109
    assert built.master_problem.trajectory_columns_complete
    assert built.master_problem.incompatibility_rows_complete

    lp = DddTrajectoryFactorizedLpOptimizer().solve(built.master_problem)
    mip = DddTrajectoryFactorizedMipReferenceOptimizer().solve(built.master_problem)

    assert lp.status is DddTrajectoryPassengerLpStatus.OPTIMAL
    assert mip.status is DddTrajectoryPassengerLpStatus.OPTIMAL
    assert lp.objective_value is not None
    assert mip.objective_value is not None
    assert lp.objective_value <= mip.objective_value + 1e-6
    assert lp.certified_lower_bound == pytest.approx(lp.objective_value)
    assert lp.bound_status is DddTrajectoryBoundStatus.FULL_ROOT_LP_CERTIFIED


def test_complete_reference_refuses_unbounded_pair_enumeration() -> None:
    problem, artifact, passenger_build = _physical_problem()

    with pytest.raises(
        DddExhaustiveTrajectoryLimitError,
        match="incompatibility-pair limit",
    ):
        DddExhaustiveTrajectoryMasterBuilder(max_incompatibility_pair_checks=175).build(
            problem=problem,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=EanPassengerObjective.JOURNEY_TIME,
        )


def test_complete_reference_rejects_waiting_target_domain() -> None:
    problem, artifact, passenger_build = _physical_problem()
    waiting_artifact = replace(
        artifact,
        config=replace(
            artifact.config,
            station_configs=(
                replace(
                    artifact.config.station_configs[0],
                    waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT,
                ),
                *artifact.config.station_configs[1:],
            ),
        ),
    )

    with pytest.raises(ValueError, match="no-wait only"):
        DddExhaustiveTrajectoryMasterBuilder().build(
            problem=problem,
            artifact=waiting_artifact,
            passenger_build=passenger_build,
            objective=EanPassengerObjective.JOURNEY_TIME,
        )


def test_exact_no_wait_pricing_matches_exhaustive_randomized_duals() -> None:
    problem, artifact, passenger_build = _physical_problem()
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    rng = Random(7)
    groups = tuple(exhaustive.master_problem.demand_by_group_id)
    exact_oracle = DddTrajectoryExactNoWaitPricingOracle(time_limit_seconds=10.0)
    legacy_oracle = DddTrajectoryExactNoWaitPricingOracle(
        time_limit_seconds=10.0,
        formulation=DddTrajectoryPricingFormulation.LEGACY_INDICATORS,
    )
    time_expanded_oracle = DddTrajectoryExactNoWaitPricingOracle(
        time_limit_seconds=10.0,
        formulation=DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH,
    )
    reference_oracle = DddTrajectoryExhaustivePricingOracle()

    for trial in range(5):
        duals = DddTrajectoryPassengerDuals(
            cabin_choice_raw_by_cabin_id={
                cabin_id: rng.uniform(-500.0, 500.0)
                for cabin_id in exhaustive.master_problem.cabin_ids
            },
            demand_raw_by_group_id={
                group_id: rng.uniform(-500.0, 0.0) for group_id in groups
            },
            demand_marginal_value_by_group_id={},
            incompatibility_raw_by_pair={},
            ride_activation_raw_by_ride_id={},
            capacity_raw_by_option_segment={},
            fingerprint=f"random-duals-{trial}",
        )
        for cabin_id in exhaustive.master_problem.cabin_ids:
            reference = reference_oracle.solve(
                exhaustive=exhaustive,
                cabin_id=cabin_id,
                duals=duals,
            )
            exact = exact_oracle.solve(
                movement_problem=problem.movement_problem,
                artifact=artifact,
                passenger_build=passenger_build,
                objective=EanPassengerObjective.JOURNEY_TIME,
                cabin_id=cabin_id,
                duals=duals,
            )
            legacy = legacy_oracle.solve(
                movement_problem=problem.movement_problem,
                artifact=artifact,
                passenger_build=passenger_build,
                objective=EanPassengerObjective.JOURNEY_TIME,
                cabin_id=cabin_id,
                duals=duals,
            )
            time_expanded = time_expanded_oracle.solve(
                movement_problem=problem.movement_problem,
                artifact=artifact,
                passenger_build=passenger_build,
                objective=EanPassengerObjective.JOURNEY_TIME,
                cabin_id=cabin_id,
                duals=duals,
            )

            assert exact.status is DddTrajectoryExactPricingStatus.OPTIMAL
            assert exact.exact
            assert exact.certified_reduced_cost_lower_bound == pytest.approx(
                exact.minimum_reduced_cost
            )
            assert exact.minimum_reduced_cost == pytest.approx(
                reference.minimum_reduced_cost,
                abs=1e-6,
            )
            assert exact.minimum_reduced_cost == pytest.approx(
                legacy.minimum_reduced_cost,
                abs=1e-6,
            )
            assert exact.minimum_reduced_cost == pytest.approx(
                time_expanded.minimum_reduced_cost,
                abs=1e-6,
            )
            assert exact.option_id is not None
            option_ids = {
                option.id
                for option in exhaustive.master_problem.options
                if option.cabin_id == cabin_id
            }
            exact_column_reference = reference_oracle.solve(
                exhaustive=exhaustive,
                cabin_id=cabin_id,
                duals=duals,
                excluded_option_ids=frozenset(option_ids - {exact.option_id}),
            )
            assert exact.minimum_reduced_cost == pytest.approx(
                exact_column_reference.minimum_reduced_cost,
                abs=1e-6,
            )
            assert exact.ride_counts_by_candidate_id == (
                exact_column_reference.ride_counts_by_candidate_id
            )


def test_exact_pricing_matches_exhaustive_resource_window_duals() -> None:
    problem, artifact, passenger_build = _physical_problem()
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    windows = enumerate_ddd_trajectory_resource_windows(
        movement_problem=problem.movement_problem,
        trajectories=tuple(exhaustive.reference_trajectory_by_option_id.values()),
    )[:3]
    rows = build_ddd_trajectory_resource_window_rows(
        windows=windows,
        movement_problem=problem.movement_problem,
        trajectory_by_option_id=exhaustive.reference_trajectory_by_option_id,
    )
    exhaustive = replace(
        exhaustive,
        master_problem=replace(
            exhaustive.master_problem,
            resource_window_rows=rows,
        ),
    )
    duals = DddTrajectoryPassengerDuals(
        cabin_choice_raw_by_cabin_id={0: 20.0, 1: -7.0, 2: 11.0},
        demand_raw_by_group_id={
            group_id: -13.0 for group_id in exhaustive.master_problem.demand_by_group_id
        },
        demand_marginal_value_by_group_id={},
        incompatibility_raw_by_pair={},
        ride_activation_raw_by_ride_id={},
        capacity_raw_by_option_segment={},
        fingerprint="resource-window-duals",
        resource_window_raw_by_row_id={
            row.id: -float(index + 1) * 17.0 for index, row in enumerate(rows)
        },
    )

    for cabin_id in exhaustive.master_problem.cabin_ids:
        reference = DddTrajectoryExhaustivePricingOracle().solve(
            exhaustive=exhaustive,
            cabin_id=cabin_id,
            duals=duals,
        )
        exact = DddTrajectoryExactNoWaitPricingOracle(time_limit_seconds=10.0).solve(
            movement_problem=problem.movement_problem,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=EanPassengerObjective.JOURNEY_TIME,
            cabin_id=cabin_id,
            duals=duals,
            resource_window_rows=rows,
        )

        assert exact.exact
        assert exact.minimum_reduced_cost == pytest.approx(
            reference.minimum_reduced_cost,
            abs=1e-6,
        )


def test_all_tiny_pair_conflicts_have_a_resource_window_witness() -> None:
    problem, artifact, passenger_build = _physical_problem()
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )

    for first_id, second_id in exhaustive.master_problem.incompatibility_pairs:
        assert ddd_trajectory_pair_has_resource_window_witness(
            first=exhaustive.reference_trajectory_by_option_id[first_id],
            second=exhaustive.reference_trajectory_by_option_id[second_id],
            movement_problem=problem.movement_problem,
        )


def test_complete_resource_window_master_preserves_integer_optimum() -> None:
    problem, artifact, passenger_build = _physical_problem()
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    windows = enumerate_ddd_trajectory_resource_windows(
        movement_problem=problem.movement_problem,
        trajectories=tuple(exhaustive.reference_trajectory_by_option_id.values()),
    )
    rows = build_ddd_trajectory_resource_window_rows(
        windows=windows,
        movement_problem=problem.movement_problem,
        trajectory_by_option_id=exhaustive.reference_trajectory_by_option_id,
    )
    augmented = replace(exhaustive.master_problem, resource_window_rows=rows)

    pair_lp = DddTrajectoryFactorizedLpOptimizer().solve(exhaustive.master_problem)
    augmented_lp = DddTrajectoryFactorizedLpOptimizer().solve(augmented)
    pair_mip = DddTrajectoryFactorizedMipReferenceOptimizer().solve(
        exhaustive.master_problem
    )
    augmented_mip = DddTrajectoryFactorizedMipReferenceOptimizer().solve(augmented)

    assert augmented_lp.objective_value >= pair_lp.objective_value - 1e-6
    assert augmented_lp.objective_value <= augmented_mip.objective_value + 1e-6
    assert augmented_mip.objective_value == pytest.approx(pair_mip.objective_value)


def test_exact_no_wait_pricing_respects_existing_column_exclusions() -> None:
    problem, artifact, passenger_build = _physical_problem()
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.WAITING_TIME,
    )
    cabin_id = 0
    options = tuple(
        option
        for option in exhaustive.master_problem.options
        if option.cabin_id == cabin_id
    )
    retained = options[-1]
    excluded_ids = frozenset(option.id for option in options[:-1])
    excluded_sequences = frozenset(
        exhaustive.reference_trajectory_by_option_id[option_id].support_signature
        for option_id in excluded_ids
    )
    duals = DddTrajectoryPassengerDuals(
        cabin_choice_raw_by_cabin_id={0: 13.0, 1: 0.0, 2: 0.0},
        demand_raw_by_group_id={
            group_id: -17.0 for group_id in exhaustive.master_problem.demand_by_group_id
        },
        demand_marginal_value_by_group_id={},
        incompatibility_raw_by_pair={},
        ride_activation_raw_by_ride_id={},
        capacity_raw_by_option_segment={},
        fingerprint="exclusion-duals",
    )

    reference = DddTrajectoryExhaustivePricingOracle().solve(
        exhaustive=exhaustive,
        cabin_id=cabin_id,
        duals=duals,
        excluded_option_ids=excluded_ids,
    )
    exact = DddTrajectoryExactNoWaitPricingOracle().solve(
        movement_problem=problem.movement_problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.WAITING_TIME,
        cabin_id=cabin_id,
        duals=duals,
        excluded_route_option_sequences=excluded_sequences,
    )

    assert reference.option_id == retained.id
    assert exact.option_id == retained.id
    assert exact.minimum_reduced_cost == pytest.approx(
        reference.minimum_reduced_cost,
        abs=1e-6,
    )


def test_exact_no_wait_pricing_reports_model_metrics_on_setup_timeout() -> None:
    problem, artifact, passenger_build = _physical_problem()
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    lp = DddTrajectoryFactorizedLpOptimizer().solve(exhaustive.master_problem)
    assert lp.duals is not None

    result = DddTrajectoryExactNoWaitPricingOracle(
        time_limit_seconds=1e-12,
    ).solve(
        movement_problem=problem.movement_problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        cabin_id=0,
        duals=lp.duals,
    )

    assert result.status is DddTrajectoryExactPricingStatus.UNKNOWN
    assert result.model_variable_count > 0
    assert result.model_linear_constraint_count > 0


def test_exact_root_column_generation_matches_complete_physical_master() -> None:
    problem, artifact, passenger_build = _physical_problem()
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    complete_lp = DddTrajectoryFactorizedLpOptimizer().solve(exhaustive.master_problem)
    complete_mip = DddTrajectoryFactorizedMipReferenceOptimizer().solve(
        exhaustive.master_problem
    )

    generated = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=20,
        pricing_time_limit_seconds=10.0,
    ).solve(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    barrier_generated = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=20,
        pricing_time_limit_seconds=10.0,
        master_dual_mode=DddTrajectoryMasterDualMode.BARRIER_NO_CROSSOVER,
    ).solve(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )

    assert generated.status is DddTrajectoryRootCgStatus.OPTIMAL_ROOT_LP
    assert generated.root_lp_certified
    assert generated.certified_lower_bound == pytest.approx(complete_lp.objective_value)
    assert generated.best_upper_bound == pytest.approx(complete_mip.objective_value)
    assert generated.relative_gap == pytest.approx(0.0)
    assert barrier_generated.status is DddTrajectoryRootCgStatus.OPTIMAL_ROOT_LP
    assert barrier_generated.certified_lower_bound == pytest.approx(
        generated.certified_lower_bound
    )
    assert len(generated.iterations) == 2
    assert generated.iterations[0].added_trajectory_count == 3
    assert generated.iterations[-1].added_trajectory_count == 0
    assert generated.iterations[0].proof_pricing_exclusion_count == 3
    assert len(generated.iterations[0].pricing_diagnostics) == 3
    assert all(
        item.model_variable_count > 0
        for item in generated.iterations[0].pricing_diagnostics
    )
    assert all(
        left.global_lower_bound <= right.global_lower_bound + 1e-9
        for left, right in zip(
            generated.iterations,
            generated.iterations[1:],
        )
    )


def test_exact_root_column_generation_checkpoint_roundtrip_and_resume(
    tmp_path,
) -> None:
    problem, artifact, passenger_build = _physical_problem()
    states = []
    partial = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=1,
        pricing_time_limit_seconds=10.0,
    ).solve(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        checkpoint_callback=states.append,
    )

    assert partial.status is DddTrajectoryRootCgStatus.ITERATION_LIMIT
    assert len(states) == 1
    checkpoint_path = tmp_path / "root-cg.checkpoint.json"
    write_ddd_trajectory_root_cg_checkpoint(checkpoint_path, states[0])
    restored = read_ddd_trajectory_root_cg_checkpoint(checkpoint_path)
    assert restored == states[0]

    resumed_states = []
    resumed = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=20,
        pricing_time_limit_seconds=10.0,
    ).solve(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        resume_state=restored,
        checkpoint_callback=resumed_states.append,
    )

    assert resumed.status is DddTrajectoryRootCgStatus.OPTIMAL_ROOT_LP
    assert resumed.root_lp_certified
    assert len(resumed.iterations) == 2
    assert resumed.iterations[0] == partial.iterations[0]
    assert resumed_states[-1].completed_rounds == 2
    assert resumed_states[-1].root_lp_certified
    assert resumed_states[-1].incumbent_ride_values_by_id
    assert resumed.total_seconds >= partial.total_seconds
    assert len(resumed.incumbent_option_ids) == len(problem.movement_problem.starts)

    terminal_resume = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=20,
    ).solve(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        resume_state=resumed_states[-1],
    )
    assert terminal_resume.status is DddTrajectoryRootCgStatus.OPTIMAL_ROOT_LP
    assert terminal_resume.iterations == resumed.iterations


def test_resource_window_root_mode_retains_exact_pair_fallback() -> None:
    problem, artifact, passenger_build = _physical_problem()
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    complete_mip = DddTrajectoryFactorizedMipReferenceOptimizer().solve(
        exhaustive.master_problem
    )

    generated = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=20,
        pricing_time_limit_seconds=10.0,
        conflict_row_mode=(
            DddTrajectoryConflictRowMode.RESOURCE_WINDOWS_WITH_PAIR_FALLBACK
        ),
    ).solve(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )

    assert generated.status is DddTrajectoryRootCgStatus.OPTIMAL_ROOT_LP
    assert generated.root_lp_certified
    assert generated.best_upper_bound == pytest.approx(complete_mip.objective_value)
    assert any(
        iteration.incompatibility_pair_count > 0 for iteration in generated.iterations
    )


def test_extra_diverse_columns_do_not_change_root_certificate() -> None:
    problem, artifact, passenger_build = _physical_problem()
    baseline = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=20,
        pricing_time_limit_seconds=10.0,
    ).solve(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    diverse = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=20,
        pricing_time_limit_seconds=10.0,
        columns_per_cabin_per_round=3,
        diversity_mode=DddTrajectoryDiversityMode.STOP_SKIP,
        minimum_diversity_distance=1,
        extra_column_time_limit_seconds=10.0,
    ).solve(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )

    assert diverse.status is DddTrajectoryRootCgStatus.OPTIMAL_ROOT_LP
    assert diverse.certified_lower_bound == pytest.approx(
        baseline.certified_lower_bound
    )
    assert diverse.best_upper_bound == pytest.approx(baseline.best_upper_bound)
    assert diverse.iterations[0].diverse_added_trajectory_count == 6
    assert diverse.iterations[0].extra_pricing_call_count == 6
