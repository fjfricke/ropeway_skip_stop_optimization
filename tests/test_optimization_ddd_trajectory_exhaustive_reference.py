from dataclasses import replace
import json
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
    DddTrajectoryCompatibleBatchMode,
    DddTrajectoryCoordinatedPrimalGenerator,
    DddTrajectoryDiversityMode,
    DddTrajectoryFactorizedLpOptimizer,
    DddTrajectoryFactorizedMipReferenceOptimizer,
    DddTrajectoryMasterDualMode,
    DddTrajectoryNeighborhoodPrimalOptimizer,
    DddTrajectoryNeighborhoodSelector,
    DddTrajectoryMergeCorridorPrimalOptimizer,
    DddTrajectoryMergeCorridorSelector,
    DddTrajectoryMergeDomainBuilder,
    DddTrajectoryPricingFormulation,
    DddTrajectoryExactRootColumnGenerationSolver,
    DddTrajectoryExactNoWaitPricingOracle,
    DddTrajectoryExactPricingStatus,
    DddTrajectoryExhaustivePricingOracle,
    DddTrajectoryPassengerDuals,
    DddReferenceSolution,
    DddReferenceTrajectory,
    DddTrajectoryRootCgStatus,
    DddTrajectoryPassengerLpStatus,
    EanArtifactToDddMovementProblemAdapter,
    build_ddd_trajectory_resource_window_rows,
    ddd_trajectory_pair_has_resource_window_witness,
    ddd_trajectory_resource_intervals,
    enumerate_ddd_trajectory_resource_windows,
    find_ddd_reference_conflicts,
    validate_ddd_reference_solution,
    build_ddd_all_stop_seed_trajectories,
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


def test_exact_resource_window_pricing_includes_fixed_boundary_coefficient() -> None:
    problem, artifact, passenger_build = _physical_problem()
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    cabin_id = 0
    trajectories = exhaustive.reference_trajectory_by_option_id
    cabin_option_ids = {
        option.id
        for option in exhaustive.master_problem.options
        if option.cabin_id == cabin_id
    }
    boundary = next(
        replace(occurrence, cabin_id=cabin_id, boundary_origin=True)
        for trajectory in trajectories.values()
        if trajectory.cabin_id != cabin_id
        for occurrence in trajectory.resource_occurrences
        if 0
        < sum(
            not find_ddd_reference_conflicts(
                (
                    *trajectories[option_id].resource_occurrences,
                    replace(occurrence, cabin_id=cabin_id, boundary_origin=True),
                ),
                problem.movement_problem,
            )
            for option_id in cabin_option_ids
        )
        < len(cabin_option_ids)
    )
    allowed = {
        option_id
        for option_id in cabin_option_ids
        if not find_ddd_reference_conflicts(
            (*trajectories[option_id].resource_occurrences, boundary),
            problem.movement_problem,
        )
    }
    bounded_trajectories = {
        option_id: (
            replace(trajectory, boundary_resource_occurrences=(boundary,))
            if option_id in allowed
            else trajectory
        )
        for option_id, trajectory in trajectories.items()
    }
    boundary_interval = ddd_trajectory_resource_intervals(
        DddReferenceTrajectory(
            cabin_id=cabin_id,
            visits=(),
            boundary_resource_occurrences=(boundary,),
        ),
        problem.movement_problem,
    )[0]
    windows = enumerate_ddd_trajectory_resource_windows(
        movement_problem=problem.movement_problem,
        trajectories=(
            DddReferenceTrajectory(
                cabin_id=cabin_id,
                visits=(),
                boundary_resource_occurrences=(boundary,),
            ),
        ),
    )
    window = next(
        item
        for item in windows
        if item.resource_id == boundary_interval.resource_id
        and item.anchor_tick == boundary_interval.enter_tick
    )
    rows = build_ddd_trajectory_resource_window_rows(
        windows=(window,),
        movement_problem=problem.movement_problem,
        trajectory_by_option_id=bounded_trajectories,
    )
    assert all(
        rows[0].coefficient_by_option_id[option_id] == 1
        for option_id in allowed
    )
    exhaustive = replace(
        exhaustive,
        reference_trajectory_by_option_id=bounded_trajectories,
        master_problem=replace(
            exhaustive.master_problem,
            resource_window_rows=rows,
        ),
    )
    duals = DddTrajectoryPassengerDuals(
        cabin_choice_raw_by_cabin_id={
            item: 0.0 for item in exhaustive.master_problem.cabin_ids
        },
        demand_raw_by_group_id={
            group_id: -17.0
            for group_id in exhaustive.master_problem.demand_by_group_id
        },
        demand_marginal_value_by_group_id={},
        incompatibility_raw_by_pair={},
        ride_activation_raw_by_ride_id={},
        capacity_raw_by_option_segment={},
        fingerprint="boundary-resource-window-pricing-test",
        resource_window_raw_by_row_id={rows[0].id: -23.0},
    )
    reference = DddTrajectoryExhaustivePricingOracle().solve(
        exhaustive=exhaustive,
        cabin_id=cabin_id,
        duals=duals,
        excluded_option_ids=frozenset(cabin_option_ids - allowed),
    )
    exact = DddTrajectoryExactNoWaitPricingOracle(time_limit_seconds=10.0).solve(
        movement_problem=problem.movement_problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        cabin_id=cabin_id,
        duals=duals,
        resource_window_rows=rows,
        boundary_occurrences=(boundary,),
    )

    assert exact.exact
    assert exact.minimum_reduced_cost == pytest.approx(
        reference.minimum_reduced_cost,
        abs=1e-6,
    )
    assert exact.option_id in allowed


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

    final_iteration = resumed_states[-1].iterations[-1]
    corrupt_certified_state = replace(
        resumed_states[-1],
        iterations=(
            *resumed_states[-1].iterations[:-1],
            replace(
                final_iteration,
                exact_pricing_cabin_count=(
                    final_iteration.exact_pricing_cabin_count - 1
                ),
            ),
        ),
    )
    with pytest.raises(ValueError, match="root certificate is inconsistent"):
        DddTrajectoryExactRootColumnGenerationSolver(max_iterations=20).solve(
            problem=problem,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=EanPassengerObjective.JOURNEY_TIME,
            resume_state=corrupt_certified_state,
        )

    legacy_path = tmp_path / "legacy-incomplete-pricing.checkpoint.json"
    write_ddd_trajectory_root_cg_checkpoint(legacy_path, resumed_states[-1])
    legacy_payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    legacy_payload["schema_version"] = 1
    legacy_payload["state"].pop("root_lp_certified")
    legacy_payload["state"]["iterations"][-1]["exact_pricing_cabin_count"] -= 1
    legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

    assert not read_ddd_trajectory_root_cg_checkpoint(
        legacy_path
    ).root_lp_certified


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


def test_compatible_batch_admission_preserves_exact_root_certificate() -> None:
    problem, artifact, passenger_build = _physical_problem()
    baseline = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=20,
        pricing_time_limit_seconds=10.0,
        columns_per_cabin_per_round=3,
    ).solve(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    compatible = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=40,
        pricing_time_limit_seconds=10.0,
        columns_per_cabin_per_round=3,
        compatible_batch_mode=(
            DddTrajectoryCompatibleBatchMode.MAXIMUM_COMPATIBLE
        ),
        compatible_batch_time_limit_seconds=5.0,
    ).solve(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )

    assert baseline.root_lp_certified
    assert compatible.root_lp_certified
    assert compatible.certified_lower_bound == pytest.approx(
        baseline.certified_lower_bound
    )
    assert compatible.best_upper_bound == pytest.approx(baseline.best_upper_bound)
    assert any(
        iteration.compatible_batch_status is not None
        for iteration in compatible.iterations
    )


def test_merge_aware_resource_rows_preserve_tiny_integer_result() -> None:
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
    merge_aware = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=30,
        pricing_time_limit_seconds=10.0,
        conflict_row_mode=DddTrajectoryConflictRowMode.MERGE_AWARE_RESOURCE_WINDOWS,
    ).solve(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )

    assert merge_aware.root_lp_certified
    assert merge_aware.certified_lower_bound == pytest.approx(
        baseline.certified_lower_bound
    )
    assert merge_aware.best_upper_bound == pytest.approx(baseline.best_upper_bound)


def test_coordinated_primal_returns_complete_validated_schedule_batches() -> None:
    problem, artifact, passenger_build = _physical_problem()
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    lp = DddTrajectoryFactorizedLpOptimizer().solve(exhaustive.master_problem)

    generated = DddTrajectoryCoordinatedPrimalGenerator(
        time_limit_seconds=10.0,
        num_workers=1,
        max_candidate_count=2,
        maximum_preference_count=12,
    ).generate(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        lp_result=lp,
        waiting_policy=EanArtifactToDddMovementProblemAdapter().build_waiting_policy(
            artifact,
            core=problem.movement_problem.core,
        ),
    )

    assert generated.trajectory_batches
    assert len(generated.trajectory_batches) == 2
    assert generated.preference_count == 12
    for batch in generated.trajectory_batches:
        validate_ddd_reference_solution(
            problem.movement_problem,
            DddReferenceSolution(batch),
        )

    repeated = DddTrajectoryCoordinatedPrimalGenerator(
        time_limit_seconds=2.0,
        num_workers=1,
        max_candidate_count=1,
        maximum_preference_count=12,
    ).generate(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        lp_result=lp,
        waiting_policy=EanArtifactToDddMovementProblemAdapter().build_waiting_policy(
            artifact,
            core=problem.movement_problem.core,
        ),
        hint_trajectories=generated.trajectory_batches[0],
        excluded_schedules=(generated.schedule_batches[0],),
        exclude_hint_schedule=True,
    )
    assert repeated.solver_status_name


def test_coordinated_primal_does_not_change_the_root_certificate() -> None:
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
    coordinated = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=20,
        pricing_time_limit_seconds=10.0,
        coordinated_primal_time_limit_seconds=5.0,
        coordinated_primal_workers=1,
        coordinated_primal_candidate_count=2,
    ).solve(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )

    assert coordinated.root_lp_certified
    assert coordinated.certified_lower_bound == pytest.approx(
        baseline.certified_lower_bound
    )
    assert coordinated.best_upper_bound == pytest.approx(baseline.best_upper_bound)
    assert any(
        iteration.primal_pricing_call_count > 0
        for iteration in coordinated.iterations
    )


def test_fractional_cabin_neighborhood_is_deterministic_and_partitions_fleet() -> None:
    problem, artifact, passenger_build = _physical_problem()
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    lp = DddTrajectoryFactorizedLpOptimizer().solve(exhaustive.master_problem)
    incumbent = build_ddd_all_stop_seed_trajectories(problem.movement_problem)
    incumbent_ids = tuple(
        option.id
        for option in exhaustive.master_problem.options
        for trajectory in incumbent
        if option.cabin_id == trajectory.cabin_id
        and exhaustive.reference_trajectory_by_option_id[option.id]
        == trajectory
    )
    selector = DddTrajectoryNeighborhoodSelector(cabin_counts=(2,))

    first = selector.select(
        cabin_ids=(0, 1, 2),
        lp_result=lp,
        trajectory_by_option_id=exhaustive.reference_trajectory_by_option_id,
        incumbent_option_ids=incumbent_ids,
        neighborhood_index=1,
    )
    second = selector.select(
        cabin_ids=(0, 1, 2),
        lp_result=lp,
        trajectory_by_option_id=exhaustive.reference_trajectory_by_option_id,
        incumbent_option_ids=incumbent_ids,
        neighborhood_index=1,
    )

    assert first == second
    assert len(first.released_cabin_ids) == 2
    assert len(first.fixed_cabin_ids) == 1
    first.validate((0, 1, 2))


def test_merge_corridor_is_deterministic_and_releases_many_cabins_locally() -> None:
    problem, artifact, passenger_build = _physical_problem()
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    lp = DddTrajectoryFactorizedLpOptimizer().solve(exhaustive.master_problem)
    incumbent = build_ddd_all_stop_seed_trajectories(problem.movement_problem)
    selector = DddTrajectoryMergeCorridorSelector(
        window_widths_seconds=(10_000.0,),
        upstream_visit_count=0,
        downstream_visit_count=0,
        minimum_occurrence_count=2,
    )
    domain = DddTrajectoryMergeDomainBuilder().build(
        problem.movement_problem.core
    )

    first = selector.select(
        merge_domain=domain,
        lp_result=lp,
        trajectory_by_option_id=exhaustive.reference_trajectory_by_option_id,
        incumbent_trajectories=incumbent,
        neighborhood_index=1,
    )
    second = selector.select(
        merge_domain=domain,
        lp_result=lp,
        trajectory_by_option_id=exhaustive.reference_trajectory_by_option_id,
        incumbent_trajectories=incumbent,
        neighborhood_index=1,
    )

    assert first == second
    assert len(first.released_cabin_ids) > 1
    assert first.merge_occurrence_count >= 2
    assert first.fixed_route_decisions
    first.validate(incumbent)


def test_merge_corridor_primal_preserves_every_fixed_route_decision() -> None:
    problem, artifact, passenger_build = _physical_problem()
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    lp = DddTrajectoryFactorizedLpOptimizer().solve(exhaustive.master_problem)
    incumbent = build_ddd_all_stop_seed_trajectories(problem.movement_problem)
    corridor = DddTrajectoryMergeCorridorSelector(
        window_widths_seconds=(10_000.0,),
        upstream_visit_count=0,
        downstream_visit_count=0,
        minimum_occurrence_count=2,
    ).select(
        merge_domain=DddTrajectoryMergeDomainBuilder().build(
            problem.movement_problem.core
        ),
        lp_result=lp,
        trajectory_by_option_id=exhaustive.reference_trajectory_by_option_id,
        incumbent_trajectories=incumbent,
        neighborhood_index=1,
    )

    result = DddTrajectoryMergeCorridorPrimalOptimizer(
        time_limit_seconds=10.0,
        num_workers=1,
        maximum_preference_count=12,
    ).optimize(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        lp_result=lp,
        waiting_policy=EanArtifactToDddMovementProblemAdapter().build_waiting_policy(
            artifact,
            core=problem.movement_problem.core,
        ),
        incumbent_trajectories=incumbent,
        corridor=corridor,
    )

    assert result.coordinated.trajectory_batches
    candidate = {
        (trajectory.cabin_id, visit.visit_index): visit.route_option_id
        for trajectory in result.coordinated.trajectory_batches[0]
        for visit in trajectory.visits
    }
    assert all(
        candidate[item.cabin_id, item.visit_index] == item.route_option_id
        for item in corridor.fixed_route_decisions
    )


def test_neighborhood_primal_preserves_fixed_cabin_route() -> None:
    problem, artifact, passenger_build = _physical_problem()
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    lp = DddTrajectoryFactorizedLpOptimizer().solve(exhaustive.master_problem)
    incumbent = build_ddd_all_stop_seed_trajectories(problem.movement_problem)
    incumbent_ids = tuple(
        option.id
        for option in exhaustive.master_problem.options
        for trajectory in incumbent
        if option.cabin_id == trajectory.cabin_id
        and exhaustive.reference_trajectory_by_option_id[option.id]
        == trajectory
    )
    neighborhood = DddTrajectoryNeighborhoodSelector(cabin_counts=(2,)).select(
        cabin_ids=(0, 1, 2),
        lp_result=lp,
        trajectory_by_option_id=exhaustive.reference_trajectory_by_option_id,
        incumbent_option_ids=incumbent_ids,
        neighborhood_index=1,
    )

    result = DddTrajectoryNeighborhoodPrimalOptimizer(
        time_limit_seconds=10.0,
        num_workers=1,
        max_candidate_count=1,
        maximum_preference_count=12,
    ).optimize(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        lp_result=lp,
        waiting_policy=EanArtifactToDddMovementProblemAdapter().build_waiting_policy(
            artifact,
            core=problem.movement_problem.core,
        ),
        incumbent_trajectories=incumbent,
        neighborhood=neighborhood,
    )

    assert result.coordinated.trajectory_batches
    candidate_by_cabin = {
        trajectory.cabin_id: trajectory
        for trajectory in result.coordinated.trajectory_batches[0]
    }
    incumbent_by_cabin = {
        trajectory.cabin_id: trajectory for trajectory in incumbent
    }
    for cabin_id in neighborhood.fixed_cabin_ids:
        assert candidate_by_cabin[cabin_id].support_signature == (
            incumbent_by_cabin[cabin_id].support_signature
        )
    validate_ddd_reference_solution(
        problem.movement_problem,
        DddReferenceSolution(result.coordinated.trajectory_batches[0]),
    )


def test_neighborhood_primal_preserves_root_certificate_and_forces_mip() -> None:
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
    neighborhood = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=20,
        pricing_time_limit_seconds=10.0,
        restricted_mip_interval=100,
        neighborhood_primal_time_limit_seconds=5.0,
        neighborhood_primal_interval=100,
        neighborhood_primal_cabin_counts=(2,),
        neighborhood_primal_workers=1,
        neighborhood_primal_candidate_count=1,
        neighborhood_primal_maximum_preference_count=12,
    ).solve(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )

    assert neighborhood.root_lp_certified
    assert neighborhood.certified_lower_bound == pytest.approx(
        baseline.certified_lower_bound
    )
    lns_iterations = [
        iteration
        for iteration in neighborhood.iterations
        if iteration.neighborhood_primal_status is not None
    ]
    assert lns_iterations
    assert lns_iterations[0].neighborhood_primal_released_cabin_count == 2
    if lns_iterations[0].neighborhood_primal_candidate_count:
        assert lns_iterations[0].primal_package_upper_bound is not None
        assert lns_iterations[0].primal_package_solution_count > 0
        following = neighborhood.iterations[
            neighborhood.iterations.index(lns_iterations[0]) + 1
        ]
        assert following.restricted_mip_ran


def test_merge_corridor_primal_preserves_root_certificate_and_forces_mip() -> None:
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
    corridor_result = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=20,
        pricing_time_limit_seconds=10.0,
        restricted_mip_interval=100,
        merge_corridor_primal_time_limit_seconds=5.0,
        merge_corridor_primal_interval=100,
        merge_corridor_window_widths_seconds=(10_000.0,),
        merge_corridor_upstream_visit_count=0,
        merge_corridor_downstream_visit_count=0,
        merge_corridor_minimum_occurrence_count=2,
        merge_corridor_primal_workers=1,
        merge_corridor_primal_candidate_count=1,
        merge_corridor_primal_maximum_preference_count=12,
    ).solve(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )

    assert corridor_result.root_lp_certified
    assert corridor_result.certified_lower_bound == pytest.approx(
        baseline.certified_lower_bound
    )
    corridor_iterations = [
        iteration
        for iteration in corridor_result.iterations
        if iteration.merge_corridor_primal_status is not None
    ]
    assert corridor_iterations
    first = corridor_iterations[0]
    assert first.merge_corridor_released_cabin_count > 1
    assert first.merge_corridor_released_decision_count > 0
    assert first.merge_corridor_fixed_decision_count > 0
    if first.merge_corridor_primal_candidate_count:
        assert first.primal_package_upper_bound is not None
        following = corridor_result.iterations[
            corridor_result.iterations.index(first) + 1
        ]
        assert following.restricted_mip_ran
