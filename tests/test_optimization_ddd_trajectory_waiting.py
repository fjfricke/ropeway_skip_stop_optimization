from dataclasses import replace
import math

import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.examples.three_station import (
    ThreeStationExample,
    ThreeStationOptimizedInitialPlacementExample,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddReservoirBoundaryConfig,
    DddReservoirDispatchCardinalityMode,
    DddReservoirPrimalPricingMode,
    DddReservoirTrajectoryStartDomain,
    DddTrajectoryExactNoWaitPricingOracle,
    DddTrajectoryExactReservoirNoWaitPricingOracle,
    DddTrajectoryExactRootColumnGenerationSolver,
    DddTrajectoryConflictRowMode,
    DddTrajectoryPassengerDuals,
    DddTrajectoryPricingFormulation,
    DddTrajectoryProblem,
    DddTrajectoryWaitingDomain,
    EanArtifactToDddMovementProblemAdapter,
    build_ddd_reservoir_passenger_candidates,
    build_ddd_reservoir_reference_trajectory,
    ddd_trajectory_problem_instance_fingerprint,
    read_ddd_trajectory_root_cg_checkpoint,
    write_ddd_trajectory_root_cg_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanFleetCardinalityMode,
    EanPassengerCandidateBuilder,
    EanPassengerObjective,
    StationWaitingMode,
)


def _fixed_waiting_case(*, waiting_step_seconds: float = 1.0):
    example = ThreeStationExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    config = replace(
        config,
        horizon_seconds=180.0,
        station_configs=tuple(
            replace(station, max_wait_seconds=10.0)
            if station.waiting_mode is StationWaitingMode.END_OF_PLATFORM_WAIT
            else station
            for station in config.station_configs
        ),
    )
    artifact = example.build_ean_artifact_builder(scenario, config).build(
        scenario,
        config,
    )
    adapter = EanArtifactToDddMovementProblemAdapter(
        waiting_step_seconds=waiting_step_seconds
    )
    return scenario, artifact, adapter.build_trajectory_problem(artifact)


def _reservoir_waiting_case():
    example = ThreeStationOptimizedInitialPlacementExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    config = replace(
        config,
        horizon_seconds=180.0,
        station_configs=tuple(
            replace(station, max_wait_seconds=10.0)
            if station.waiting_mode is StationWaitingMode.END_OF_PLATFORM_WAIT
            else station
            for station in config.station_configs
        ),
    )
    builder = example.build_ean_artifact_builder(scenario, config)
    builder = replace(
        builder,
        fleet_config=replace(
            builder.fleet_config,
            available_fleet_count=1,
            cardinality_mode=EanFleetCardinalityMode.EXACT,
        ),
    )
    artifact = builder.build(scenario, config)
    adapter = EanArtifactToDddMovementProblemAdapter()
    core = adapter.build_movement_core(artifact)
    minimum_duration = min(option.duration_seconds for option in core.route_options)
    problem = DddTrajectoryProblem(
        movement_core=core,
        start_domain=DddReservoirTrajectoryStartDomain(
            cabin_ids=(0,),
            boundary=DddReservoirBoundaryConfig(
                id="test_reservoir",
                entry_state_id=artifact.circulation_state_ids[0],
            ),
            warmup_seconds=60.0,
            maximum_visit_count=math.ceil(
                (60.0 + core.operational_end_seconds) / minimum_duration
            )
            + 3,
            cardinality_mode=DddReservoirDispatchCardinalityMode.OPTIONAL,
        ),
        waiting_policy=adapter.build_waiting_policy(artifact, core=core),
    )
    passenger_build = build_ddd_reservoir_passenger_candidates(
        scenario=scenario,
        problem=problem,
    )
    return scenario, artifact, problem, passenger_build


def _force_wait_duals(problem, passenger_build):
    return DddTrajectoryPassengerDuals(
        cabin_choice_raw_by_cabin_id={cabin_id: 0.0 for cabin_id in problem.cabin_ids},
        demand_raw_by_group_id={
            group.id: 10_000.0 for group in passenger_build.demand_groups
        },
        demand_marginal_value_by_group_id={},
        incompatibility_raw_by_pair={},
        ride_activation_raw_by_ride_id={},
        capacity_raw_by_option_segment={},
        fingerprint="force-bounded-wait",
    )


def test_adapter_requires_an_explicit_wait_limit() -> None:
    example = ThreeStationExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    artifact = example.build_ean_artifact_builder(scenario, config).build(
        scenario,
        config,
    )

    with pytest.raises(ValueError, match="explicit max_wait_seconds"):
        EanArtifactToDddMovementProblemAdapter().build_trajectory_problem(artifact)


def test_legacy_movement_adapter_cannot_drop_the_waiting_policy() -> None:
    _, artifact, _ = _fixed_waiting_case()

    with pytest.raises(ValueError, match="build_trajectory_problem"):
        EanArtifactToDddMovementProblemAdapter().build(artifact)


def test_bounded_waiting_rejects_incomplete_pricing_and_conflict_domains() -> None:
    scenario, artifact, fixed_problem = _fixed_waiting_case()
    network_problem = build_initial_ddd_network_problem(
        fixed_problem.fixed_movement_problem
    )
    passenger_build = EanPassengerCandidateBuilder().build(scenario, artifact)

    with pytest.raises(ValueError, match="time_expanded_path"):
        DddTrajectoryExactRootColumnGenerationSolver(
            max_iterations=1,
            pricing_formulation=DddTrajectoryPricingFormulation.TIGHT_CONVEX_HULL,
        ).solve(
            problem=network_problem,
            trajectory_problem=fixed_problem,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=EanPassengerObjective.JOURNEY_TIME,
        )
    with pytest.raises(ValueError, match="pair_only"):
        DddTrajectoryExactRootColumnGenerationSolver(
            max_iterations=1,
            pricing_formulation=DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH,
            conflict_row_mode=(
                DddTrajectoryConflictRowMode.RESOURCE_WINDOWS_WITH_PAIR_FALLBACK
            ),
        ).solve(
            problem=network_problem,
            trajectory_problem=fixed_problem,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=EanPassengerObjective.JOURNEY_TIME,
        )


def test_bounded_wait_reservoir_rejects_absolute_dispatch_anchors() -> None:
    _, artifact, problem, passenger_build = _reservoir_waiting_case()

    with pytest.raises(ValueError, match="does not support time-expanded anchors"):
        DddTrajectoryExactRootColumnGenerationSolver(
            max_iterations=1,
            pricing_formulation=DddTrajectoryPricingFormulation.TIGHT_CONVEX_HULL,
            reservoir_primal_pricing_mode=(
                DddReservoirPrimalPricingMode.TIME_EXPANDED_ANCHORS
            ),
        ).solve(
            problem=build_initial_ddd_network_problem(
                problem.structural_movement_problem
            ),
            trajectory_problem=problem,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=EanPassengerObjective.JOURNEY_TIME,
        )


def test_fixed_time_expanded_pricing_uses_the_smallest_feasible_wait() -> None:
    pytest.importorskip("gurobipy")
    scenario, artifact, problem = _fixed_waiting_case()
    passenger_build = EanPassengerCandidateBuilder().build(scenario, artifact)
    passenger_build = replace(
        passenger_build,
        demand_groups=tuple(
            replace(group, release_time_seconds=27.0)
            if group.origin_station_id == "M"
            else group
            for group in passenger_build.demand_groups
        ),
    )

    result = DddTrajectoryExactNoWaitPricingOracle(
        time_limit_seconds=10.0,
        formulation=DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH,
    ).solve(
        movement_problem=problem.fixed_movement_problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        cabin_id=0,
        duals=_force_wait_duals(problem, passenger_build),
        waiting_policy=problem.waiting_policy,
    )

    assert result.reference_trajectory is not None
    first = result.reference_trajectory.visits[0]
    first_option = next(
        option
        for option in problem.movement_core.route_options
        if option.id == first.route_option_id
    )
    assert first.wait_seconds == pytest.approx(5.0)
    assert first.next_switch_time_seconds == pytest.approx(
        first.switch_time_seconds
        + first_option.duration_seconds
        + 5.0
    )
    assert any(
        usage.leader_clear_wait_coefficient == 1
        and usage.follower_enter_wait_coefficient == 0
        for option in problem.movement_core.route_options
        for usage in option.resource_usages
    )


def test_fixed_pricing_honors_a_nondefault_waiting_grid() -> None:
    pytest.importorskip("gurobipy")
    scenario, artifact, problem = _fixed_waiting_case(waiting_step_seconds=0.5)
    passenger_build = EanPassengerCandidateBuilder().build(scenario, artifact)
    passenger_build = replace(
        passenger_build,
        demand_groups=tuple(
            replace(group, release_time_seconds=27.5)
            if group.origin_station_id == "M"
            else group
            for group in passenger_build.demand_groups
        ),
    )

    result = DddTrajectoryExactNoWaitPricingOracle(
        time_limit_seconds=10.0,
        formulation=DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH,
    ).solve(
        movement_problem=problem.fixed_movement_problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        cabin_id=0,
        duals=_force_wait_duals(problem, passenger_build),
        waiting_policy=problem.waiting_policy,
        instance_fingerprint=ddd_trajectory_problem_instance_fingerprint(
            artifact,
            problem,
        ),
    )

    assert result.reference_trajectory is not None
    assert result.reference_trajectory.visits[0].wait_seconds == pytest.approx(5.5)
    assert any(
        usage.leader_clear_wait_coefficient
        == usage.follower_enter_wait_coefficient
        == 1
        for option in problem.movement_core.route_options
        for usage in option.resource_usages
    )


def test_reservoir_compact_pricing_keeps_dispatch_continuous_and_wait_discrete() -> None:
    pytest.importorskip("gurobipy")
    _, artifact, problem, passenger_build = _reservoir_waiting_case()
    passenger_build = replace(
        passenger_build,
        demand_groups=tuple(
            replace(group, release_time_seconds=25.0)
            if group.origin_station_id == "M"
            else group
            for group in passenger_build.demand_groups
        ),
    )

    result = DddTrajectoryExactReservoirNoWaitPricingOracle(
        time_limit_seconds=10.0,
    ).solve(
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        cabin_id=0,
        duals=_force_wait_duals(problem, passenger_build),
        dispatch_time_bounds_seconds=(-1.0, -0.9),
        certify_complete_domain=False,
        dispatch_only=True,
    )

    assert result.reference_trajectory is not None
    assert result.reference_trajectory.reservoir_state is not None
    dispatch = result.reference_trajectory.reservoir_state.dispatch_time_seconds
    assert dispatch is not None
    assert -1.0 - 1e-9 <= dispatch <= -0.9 + 1e-9
    assert result.reference_trajectory.visits[0].wait_seconds in {
        float(value) for value in range(1, 11)
    }


def test_reservoir_waiting_filters_resources_at_the_actual_horizon_time() -> None:
    _, _, problem, _ = _reservoir_waiting_case()
    domain = problem.start_domain
    state_id = domain.boundary.entry_state_id
    switch_time = -1.0
    route_ids = []
    waits = []
    for _ in range(domain.maximum_visit_count):
        stop = next(
            option
            for option in problem.movement_core.route_options_by_state_id[state_id]
            if option.decision.value == "stop"
        )
        maximum = problem.waiting_policy.maximum_wait_seconds(stop.station_id)
        wait = (
            maximum
            if maximum > 0
            and switch_time + stop.platform_exit_offset_seconds >= 0.0
            else 0.0
        )
        route_ids.append(stop.id)
        waits.append(wait)
        switch_time += stop.duration_seconds + wait
        state_id = stop.to_state_id
        if switch_time >= problem.movement_core.operational_end_seconds:
            break

    trajectory = build_ddd_reservoir_reference_trajectory(
        problem=problem,
        cabin_id=0,
        dispatch_time_seconds=-1.0,
        route_option_ids=tuple(route_ids),
        wait_seconds_by_visit=tuple(waits),
    )

    assert any(visit.wait_seconds == 10.0 for visit in trajectory.visits)
    assert trajectory.visits[-1].resource_occurrences == ()


def test_reservoir_cannot_wait_before_reaching_the_service_boundary() -> None:
    _, _, problem, _ = _reservoir_waiting_case()
    domain = problem.start_domain
    first_stop = next(
        option
        for option in problem.movement_core.route_options_by_state_id[
            domain.boundary.entry_state_id
        ]
        if option.decision.value == "stop"
    )

    with pytest.raises(ValueError, match="warm-up visits cannot wait"):
        build_ddd_reservoir_reference_trajectory(
            problem=problem,
            cabin_id=0,
            dispatch_time_seconds=-30.0,
            route_option_ids=(first_stop.id,),
            wait_seconds_by_visit=(1.0,),
        )


def test_waiting_policy_changes_fingerprint_and_survives_checkpoint(
    tmp_path,
) -> None:
    pytest.importorskip("gurobipy")
    scenario, artifact, problem = _fixed_waiting_case()
    no_wait_problem = replace(
        problem,
        waiting_policy=type(problem.waiting_policy)(),
    )
    assert ddd_trajectory_problem_instance_fingerprint(
        artifact, problem
    ) != ddd_trajectory_problem_instance_fingerprint(artifact, no_wait_problem)

    states = []
    result = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=2,
        pricing_time_limit_seconds=10.0,
        pricing_formulation=DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH,
    ).solve(
        problem=build_initial_ddd_network_problem(problem.fixed_movement_problem),
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=EanPassengerCandidateBuilder().build(scenario, artifact),
        objective=EanPassengerObjective.JOURNEY_TIME,
        checkpoint_callback=states.append,
    )

    assert states[-1].waiting_policy == problem.waiting_policy
    assert states[-1].waiting_policy.domain is DddTrajectoryWaitingDomain.BOUNDED_WAIT
    assert result.root_lp_certified
    assert result.iterations[-1].added_trajectory_count == 0
    assert result.iterations[-1].proof_pricing_exclusion_count > 0
    path = tmp_path / "bounded-wait.checkpoint.json"
    write_ddd_trajectory_root_cg_checkpoint(path, states[-1])
    restored = read_ddd_trajectory_root_cg_checkpoint(path)
    assert restored.waiting_policy == problem.waiting_policy
