from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.examples.three_station import (
    ThreeStationOptimizedInitialPlacementExample,
)
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddOipTrajectoryStart,
    DddOptimizedInitialPlacementDomain,
    EanArtifactToDddMovementProblemAdapter,
    DddTrajectoryExactOipNoWaitPricingOracle,
    DddTrajectoryExactRootColumnGenerationSolver,
    DddTrajectoryPricingFormulation,
    DddTrajectoryRootCgStatus,
    DddTrajectoryFactorizedLpOptimizer,
    DddTrajectoryPassengerLpStatus,
    build_ddd_trajectory_reference_master,
    read_ddd_trajectory_root_cg_checkpoint,
    write_ddd_trajectory_root_cg_checkpoint,
    build_ddd_oip_reference_trajectory,
    build_ean_oip_plan_and_fleet,
    validate_ddd_oip_reference_trajectory,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanFleetCardinalityMode,
    EanFleetMode,
    EanPassengerCandidateBuilder,
    EanPassengerObjective,
    StationWaitingMode,
    validate_ean_initial_boundary_against_artifact,
    validate_ean_movement_plan_against_artifact,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_exact_pricing import (
    _build_relative_time_graph,
    _oip_pricing_start_classes,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_oip import (
    DDD_OIP_HORIZON_TAIL_EPSILON_SECONDS,
    ddd_oip_covers_horizon,
)


def _problem_and_artifact(k: int = 1, horizon_seconds: float | None = None):
    example = ThreeStationOptimizedInitialPlacementExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    config = replace(
        config,
        horizon_seconds=(
            config.horizon_seconds if horizon_seconds is None else horizon_seconds
        ),
        station_configs=tuple(
            replace(item, waiting_mode=StationWaitingMode.NO_WAITING)
            for item in config.station_configs
        ),
    )
    builder = example.build_ean_artifact_builder(scenario, config)
    builder = replace(
        builder,
        fleet_config=replace(
            builder.fleet_config,
            available_fleet_count=k,
            cardinality_mode=EanFleetCardinalityMode.EXACT,
        ),
    )
    artifact = builder.build(scenario, config)
    problem = EanArtifactToDddMovementProblemAdapter().build_trajectory_problem(
        artifact
    )
    return problem, artifact, scenario


def _all_stop_sequence(problem, phase_index: int) -> tuple[str, ...]:
    domain = problem.start_domain
    assert isinstance(domain, DddOptimizedInitialPlacementDomain)
    state = domain.phase_state_ids[phase_index]
    result = []
    for _ in range(domain.maximum_visit_count - phase_index):
        options = problem.movement_core.route_options_by_state_id[state]
        stop = next(option for option in options if option.decision.value == "stop")
        result.append(stop.id)
        state = stop.to_state_id
    return tuple(result)


def test_oip_adapter_builds_exact_continuous_start_domain() -> None:
    problem, _, _ = _problem_and_artifact(k=2)

    assert isinstance(problem.start_domain, DddOptimizedInitialPlacementDomain)
    assert problem.cabin_ids == (0, 1)
    assert problem.start_domain.cardinality == 2
    assert problem.start_domain.phase_state_ids
    with pytest.raises(ValueError, match="no fixed-start problem"):
        _ = problem.fixed_movement_problem


def test_oip_rope_start_preserves_non_tick_offset_and_validates_in_ean() -> None:
    problem, artifact, _ = _problem_and_artifact()
    first_switch = 12.3456789123
    trajectory = build_ddd_oip_reference_trajectory(
        problem=problem,
        artifact=artifact,
        cabin_id=0,
        start=DddOipTrajectoryStart(
            phase_index=1,
            station_start=False,
            first_switch_time_seconds=first_switch,
        ),
        route_option_ids=_all_stop_sequence(problem, 1),
    )

    assert trajectory.visits[0].visit_index == 1
    assert trajectory.visits[0].switch_time_seconds == first_switch
    assert trajectory.initial_state is not None
    assert trajectory.initial_state.kind.value == "rope"
    movement, fleet = build_ean_oip_plan_and_fleet(
        problem=problem,
        artifact=artifact,
        trajectories=(trajectory,),
    )
    validate_ean_movement_plan_against_artifact(artifact, movement).raise_for_errors()
    validate_ean_initial_boundary_against_artifact(
        artifact, movement, fleet
    ).raise_for_errors()


def test_pair_only_master_accepts_negative_preboundary_occurrences() -> None:
    problem, artifact, scenario = _problem_and_artifact()
    trajectory = build_ddd_oip_reference_trajectory(
        problem=problem,
        artifact=artifact,
        cabin_id=0,
        start=DddOipTrajectoryStart(
            phase_index=1,
            station_start=False,
            first_switch_time_seconds=12.3456789123,
        ),
        route_option_ids=_all_stop_sequence(problem, 1),
    )
    built = build_ddd_trajectory_reference_master(
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=EanPassengerCandidateBuilder().build(scenario, artifact),
        objective=EanPassengerObjective.JOURNEY_TIME,
        reference_trajectories=(trajectory,),
    )

    assert len(built.master_problem.options) == 1
    assert built.master_problem.resource_window_rows == ()


def test_oip_station_start_straddles_zero() -> None:
    problem, artifact, _ = _problem_and_artifact()
    option = next(
        option
        for option in problem.movement_core.route_options_by_state_id[
            problem.start_domain.phase_state_ids[0]
        ]
        if option.decision.value == "stop"
    )
    first_switch = -option.exit_switch_offset_seconds / 2.0 - 1.23456789e-7
    trajectory = build_ddd_oip_reference_trajectory(
        problem=problem,
        artifact=artifact,
        cabin_id=0,
        start=DddOipTrajectoryStart(
            phase_index=0,
            station_start=True,
            first_switch_time_seconds=first_switch,
        ),
        route_option_ids=_all_stop_sequence(problem, 0),
    )

    assert trajectory.visits[0].switch_time_seconds == first_switch
    assert trajectory.initial_state is not None
    assert trajectory.initial_state.kind.value == "service_route"


def test_oip_trajectory_rejects_missing_resource_provenance() -> None:
    problem, artifact, _ = _problem_and_artifact()
    trajectory = build_ddd_oip_reference_trajectory(
        problem=problem,
        artifact=artifact,
        cabin_id=0,
        start=DddOipTrajectoryStart(
            phase_index=1,
            station_start=False,
            first_switch_time_seconds=12.3456789123,
        ),
        route_option_ids=_all_stop_sequence(problem, 1),
    )
    first = trajectory.visits[0]
    assert first.resource_occurrences
    corrupted = replace(
        trajectory,
        visits=(replace(first, resource_occurrences=()), *trajectory.visits[1:]),
    )

    with pytest.raises(ValueError, match="resource occurrences are inconsistent"):
        validate_ddd_oip_reference_trajectory(problem, artifact, corrupted)


def test_oip_plan_rejects_two_selected_columns_for_one_cabin() -> None:
    problem, artifact, _ = _problem_and_artifact()
    trajectory = build_ddd_oip_reference_trajectory(
        problem=problem,
        artifact=artifact,
        cabin_id=0,
        start=DddOipTrajectoryStart(
            phase_index=1,
            station_start=False,
            first_switch_time_seconds=12.3456789123,
        ),
        route_option_ids=_all_stop_sequence(problem, 1),
    )

    with pytest.raises(ValueError, match="cover every exact-K cabin"):
        build_ean_oip_plan_and_fleet(
            problem=problem,
            artifact=artifact,
            trajectories=(trajectory, trajectory),
        )


def test_oip_station_history_before_zero_is_not_a_passenger_ride() -> None:
    problem, artifact, scenario = _problem_and_artifact()
    option = next(
        option
        for option in problem.movement_core.route_options_by_state_id[
            problem.start_domain.phase_state_ids[0]
        ]
        if option.decision.value == "stop"
    )
    trajectory = build_ddd_oip_reference_trajectory(
        problem=problem,
        artifact=artifact,
        cabin_id=0,
        start=DddOipTrajectoryStart(
            phase_index=0,
            station_start=True,
            first_switch_time_seconds=-option.exit_switch_offset_seconds,
        ),
        route_option_ids=_all_stop_sequence(problem, 0),
    )
    passenger_build = EanPassengerCandidateBuilder().build(scenario, artifact)
    built = build_ddd_trajectory_reference_master(
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        reference_trajectories=(trajectory,),
    )
    pre_horizon_candidate_ids = {
        candidate.id
        for candidate in passenger_build.ride_candidates
        if candidate.cabin_id == 0 and candidate.board_visit_index == 0
    }

    assert pre_horizon_candidate_ids
    assert all(
        ride.id.rsplit("::", 1)[-1] not in pre_horizon_candidate_ids
        for master_option in built.master_problem.options
        for ride in master_option.rides
    )


def test_relative_oip_graph_contains_only_reachable_durations() -> None:
    problem, artifact, _ = _problem_and_artifact()
    start_class = _oip_pricing_start_classes(
        trajectory_problem=problem,
        artifact=artifact,
    )[0]
    graph = _build_relative_time_graph(
        movement_problem=problem.structural_movement_problem,
        start_class=start_class,
    )
    first_durations = {
        option.duration_tick
        for option in problem.movement_core.route_options_by_state_id[
            start_class.state_id
        ]
    }
    first_layer_elapsed = {
        node.elapsed_tick for node in graph.nodes if node.visit_index == 1
    }

    assert first_layer_elapsed == first_durations
    assert len(graph.nodes) == len(set(graph.nodes))
    assert len(graph.arcs) == len(set(graph.arcs))
    assert len({arc.visit_index for arc in graph.arcs if not arc.continues}) > 1
    assert graph == _build_relative_time_graph(
        movement_problem=problem.structural_movement_problem,
        start_class=start_class,
    )
    if len(first_durations) > 1:
        smallest, largest = min(first_durations), max(first_durations)
        midpoint = (smallest + largest) // 2
        if midpoint not in first_durations:
            assert midpoint not in first_layer_elapsed


def test_oip_horizon_coverage_has_one_continuous_boundary() -> None:
    horizon = 100.0
    epsilon = DDD_OIP_HORIZON_TAIL_EPSILON_SECONDS

    assert not ddd_oip_covers_horizon(horizon + 0.5 * epsilon, horizon)
    assert ddd_oip_covers_horizon(horizon + epsilon, horizon)
    assert ddd_oip_covers_horizon(horizon + 2.0 * epsilon, horizon)


@pytest.mark.parametrize(
    "objective",
    (EanPassengerObjective.JOURNEY_TIME, EanPassengerObjective.WAITING_TIME),
)
@pytest.mark.parametrize(
    "formulation",
    (
        DddTrajectoryPricingFormulation.TIGHT_CONVEX_HULL,
        DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP,
    ),
)
def test_exact_oip_pricing_covers_the_full_continuous_start_domain(
    objective, formulation
) -> None:
    pytest.importorskip("gurobipy")
    problem, artifact, scenario = _problem_and_artifact()
    seed = build_ddd_oip_reference_trajectory(
        problem=problem,
        artifact=artifact,
        cabin_id=0,
        start=DddOipTrajectoryStart(
            phase_index=0,
            station_start=True,
            first_switch_time_seconds=0.0,
        ),
        route_option_ids=_all_stop_sequence(problem, 0),
    )
    passenger_build = EanPassengerCandidateBuilder().build(scenario, artifact)
    master = build_ddd_trajectory_reference_master(
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=objective,
        reference_trajectories=(seed,),
    )
    lp = DddTrajectoryFactorizedLpOptimizer().solve(master.master_problem)
    assert lp.status is DddTrajectoryPassengerLpStatus.OPTIMAL
    assert lp.duals is not None

    priced = DddTrajectoryExactOipNoWaitPricingOracle(
        time_limit_seconds=20.0,
        formulation=formulation,
    ).solve(
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=objective,
        cabin_id=0,
        duals=lp.duals,
    )

    assert priced.reference_trajectory is not None
    assert priced.certified_reduced_cost_lower_bound is not None
    assert (
        priced.certified_reduced_cost_lower_bound <= priced.minimum_reduced_cost + 1e-7
    )
    assert priced.required_start_class_count > 1
    assert priced.priced_start_class_count == priced.required_start_class_count
    assert priced.bounded_start_class_count == priced.required_start_class_count
    if formulation is DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP:
        assert priced.relative_node_count > 0
        assert priced.relative_arc_count > 0
        assert priced.origin_product_count > 0


def test_relative_interval_flow_and_compact_oip_pricing_have_the_same_optimum() -> None:
    pytest.importorskip("gurobipy")
    problem, artifact, scenario = _problem_and_artifact(horizon_seconds=240.0)
    seed = build_ddd_oip_reference_trajectory(
        problem=problem,
        artifact=artifact,
        cabin_id=0,
        start=DddOipTrajectoryStart(
            phase_index=0,
            station_start=True,
            first_switch_time_seconds=0.0,
        ),
        route_option_ids=_all_stop_sequence(problem, 0),
    )
    passenger_build = EanPassengerCandidateBuilder().build(scenario, artifact)
    master = build_ddd_trajectory_reference_master(
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        reference_trajectories=(seed,),
    )
    lp = DddTrajectoryFactorizedLpOptimizer().solve(master.master_problem)
    assert lp.duals is not None
    results = tuple(
        DddTrajectoryExactOipNoWaitPricingOracle(
            time_limit_seconds=20.0,
            formulation=formulation,
        ).solve(
            trajectory_problem=problem,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=EanPassengerObjective.JOURNEY_TIME,
            cabin_id=0,
            duals=lp.duals,
        )
        for formulation in (
            DddTrajectoryPricingFormulation.TIGHT_CONVEX_HULL,
            DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP,
            DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP_FLOW,
        )
    )

    compact, relative_intervals, relative_flow = results
    assert compact.exact and relative_intervals.exact and relative_flow.exact
    for relative in (relative_intervals, relative_flow):
        assert relative.minimum_reduced_cost == pytest.approx(
            compact.minimum_reduced_cost, abs=1e-6
        )
        assert relative.certified_reduced_cost_lower_bound == pytest.approx(
            compact.certified_reduced_cost_lower_bound, abs=1e-6
        )
    assert relative_intervals.model_variable_count < relative_flow.model_variable_count
    assert (
        relative_intervals.model_linear_constraint_count
        < relative_flow.model_linear_constraint_count
    )


@pytest.mark.parametrize(
    "formulation",
    (
        DddTrajectoryPricingFormulation.TIGHT_CONVEX_HULL,
        DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP,
    ),
)
def test_root_column_generation_accepts_exact_k_oip(formulation) -> None:
    pytest.importorskip("gurobipy")
    problem, artifact, scenario = _problem_and_artifact()
    passenger_build = EanPassengerCandidateBuilder().build(scenario, artifact)
    result = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=1,
        pricing_time_limit_seconds=20.0,
        pricing_formulation=formulation,
    ).solve(
        problem=build_initial_ddd_network_problem(problem.structural_movement_problem),
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )

    assert result.status in {
        DddTrajectoryRootCgStatus.ITERATION_LIMIT,
        DddTrajectoryRootCgStatus.OPTIMAL_ROOT_LP,
        DddTrajectoryRootCgStatus.UNKNOWN,
    }
    assert result.best_upper_bound is not None
    assert result.fleet_plan is not None
    assert result.fleet_mode.value == "optimized_initial_placement"
    if formulation is DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP:
        assert result.iterations[0].relative_node_count > 0
        assert result.iterations[0].relative_arc_count > 0


def test_oip_rejects_absolute_time_expanded_pricing() -> None:
    problem, artifact, scenario = _problem_and_artifact()
    with pytest.raises(ValueError, match="supports tight_convex_hull"):
        DddTrajectoryExactRootColumnGenerationSolver(max_iterations=1).solve(
            problem=build_initial_ddd_network_problem(
                problem.structural_movement_problem
            ),
            trajectory_problem=problem,
            artifact=artifact,
            passenger_build=EanPassengerCandidateBuilder().build(scenario, artifact),
            objective=EanPassengerObjective.JOURNEY_TIME,
        )


def test_two_cabin_oip_round_exports_nontrivial_certified_bound() -> None:
    pytest.importorskip("gurobipy")
    problem, artifact, scenario = _problem_and_artifact(k=2)
    result = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=1,
        pricing_time_limit_seconds=10.0,
        pricing_formulation=DddTrajectoryPricingFormulation.TIGHT_CONVEX_HULL,
    ).solve(
        problem=build_initial_ddd_network_problem(problem.structural_movement_problem),
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=EanPassengerCandidateBuilder().build(scenario, artifact),
        objective=EanPassengerObjective.JOURNEY_TIME,
    )

    assert result.certified_lower_bound > 0.0
    assert result.best_upper_bound is not None
    assert result.certified_lower_bound <= result.best_upper_bound + 1e-6
    assert result.full_start_domain_priced
    iteration = result.iterations[0]
    assert iteration.proof_pricing_solve_count == 1
    assert iteration.proof_pricing_reused_cabin_count == 1
    assert iteration.priced_start_class_count == iteration.required_start_class_count
    assert iteration.bounded_start_class_count == iteration.required_start_class_count
    assert iteration.primal_pricing_call_count == 0
    assert (
        sum(
            item.reused_from_cabin_id is not None
            for item in iteration.pricing_diagnostics
        )
        == 1
    )


def test_oip_checkpoint_v2_preserves_continuous_initial_state(tmp_path) -> None:
    pytest.importorskip("gurobipy")
    problem, artifact, scenario = _problem_and_artifact()
    states = []
    DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=1,
        pricing_time_limit_seconds=20.0,
        pricing_formulation=DddTrajectoryPricingFormulation.TIGHT_CONVEX_HULL,
    ).solve(
        problem=build_initial_ddd_network_problem(problem.structural_movement_problem),
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=EanPassengerCandidateBuilder().build(scenario, artifact),
        objective=EanPassengerObjective.JOURNEY_TIME,
        checkpoint_callback=states.append,
    )
    assert states
    path = tmp_path / "oip-v2.json"
    write_ddd_trajectory_root_cg_checkpoint(path, states[-1])
    restored = read_ddd_trajectory_root_cg_checkpoint(path)

    assert restored == states[-1]
    assert restored.fleet_mode.value == "optimized_initial_placement"
    assert all(item.initial_state is not None for item in restored.trajectories)


def test_architecture_b_rope_boundary_uses_previous_leader_behavior() -> None:
    example = get_example("five_station_circle_cw_full_skip_no_wait_headway_b_v0")
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    builder = example.build_ean_artifact_builder(scenario, config)
    builder = replace(
        builder,
        fleet_config=replace(
            builder.fleet_config,
            mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
            available_fleet_count=1,
            cardinality_mode=EanFleetCardinalityMode.EXACT,
        ),
    )
    artifact = builder.build(scenario, config)
    problem = EanArtifactToDddMovementProblemAdapter().build_trajectory_problem(
        artifact
    )
    phase = 1
    rope_classes = tuple(
        item
        for item in _oip_pricing_start_classes(
            trajectory_problem=problem,
            artifact=artifact,
        )
        if item.phase_index == phase and not item.station_start
    )
    assert {item.previous_service for item in rope_classes} == {False, True}
    assert _build_relative_time_graph(
        movement_problem=problem.structural_movement_problem,
        start_class=rope_classes[0],
    ) == _build_relative_time_graph(
        movement_problem=problem.structural_movement_problem,
        start_class=rope_classes[1],
    )
    previous_state = problem.start_domain.phase_state_ids[phase - 1]
    rope_seconds = next(
        item.rope_to_next_switch_seconds
        for item in artifact.timings
        if item.switch_id == previous_state
    )
    trajectories = tuple(
        build_ddd_oip_reference_trajectory(
            problem=problem,
            artifact=artifact,
            cabin_id=0,
            start=DddOipTrajectoryStart(
                phase_index=phase,
                station_start=False,
                first_switch_time_seconds=rope_seconds / 2.0,
                previous_service=previous_service,
            ),
            route_option_ids=_all_stop_sequence(problem, phase),
        )
        for previous_service in (False, True)
    )

    bypass, service = trajectories
    assert bypass.initial_state.previous_service is False
    assert service.initial_state.previous_service is True
    assert (
        bypass.boundary_resource_occurrences[0].separation_after_seconds
        < service.boundary_resource_occurrences[0].separation_after_seconds
    )
    assert len(service.boundary_resource_occurrences) > len(
        bypass.boundary_resource_occurrences
    )
