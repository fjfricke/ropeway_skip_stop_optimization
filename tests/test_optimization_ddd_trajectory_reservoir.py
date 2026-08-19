from dataclasses import replace
import math

import pytest

from ropeway_skip_stop_optimization.examples.three_station import (
    ThreeStationOptimizedInitialPlacementExample,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddReservoirBoundaryConfig,
    DddReservoirBoundaryMode,
    DddReservoirDispatchCardinalityMode,
    DddReservoirTrajectoryKind,
    DddReservoirTrajectoryStartDomain,
    DddTrajectoryExactReservoirNoWaitPricingOracle,
    DddTrajectoryExactRootColumnGenerationSolver,
    DddTrajectoryReservoirAnchorPricingOracle,
    DddTrajectoryFactorizedLpOptimizer,
    DddTrajectoryPassengerLpStatus,
    DddTrajectoryProblem,
    DddResourceUsage,
    DddTrajectoryPricingFormulation,
    DddTrajectoryRootCgStatus,
    EanArtifactToDddMovementProblemAdapter,
    build_ddd_reservoir_all_stop_seed,
    build_ddd_reservoir_dispatch_anchors,
    build_ddd_reservoir_neighbor_k_initial_pool,
    build_ddd_reservoir_passenger_candidates,
    build_ddd_reservoir_reference_trajectory,
    build_ddd_stored_reservoir_trajectory,
    build_ddd_trajectory_reference_master,
    ddd_trajectory_column,
    ddd_trajectory_problem_instance_fingerprint,
    ddd_reservoir_covers_horizon,
    read_ddd_trajectory_root_cg_checkpoint,
    validate_ddd_reservoir_solution,
    validate_ddd_reservoir_plan_against_artifact,
    write_ddd_trajectory_root_cg_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanFleetCardinalityMode,
    EanPassengerObjective,
    StationWaitingMode,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)


def _case(*, k: int = 1, optional: bool = True):
    example = ThreeStationOptimizedInitialPlacementExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    config = replace(
        config,
        horizon_seconds=60.0,
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
    core = EanArtifactToDddMovementProblemAdapter().build_movement_core(artifact)
    entry_state = artifact.circulation_state_ids[0]
    minimum_duration = min(option.duration_seconds for option in core.route_options)
    maximum_visits = math.ceil(
        (120.0 + core.operational_end_seconds) / minimum_duration
    ) + 3
    problem = DddTrajectoryProblem(
        movement_core=core,
        start_domain=DddReservoirTrajectoryStartDomain(
            cabin_ids=tuple(range(k)),
            boundary=DddReservoirBoundaryConfig(
                id="test_reservoir",
                entry_state_id=entry_state,
            ),
            warmup_seconds=120.0,
            maximum_visit_count=maximum_visits,
            cardinality_mode=(
                DddReservoirDispatchCardinalityMode.OPTIONAL
                if optional
                else DddReservoirDispatchCardinalityMode.EXACT
            ),
        ),
    )
    passenger_build = build_ddd_reservoir_passenger_candidates(
        scenario=scenario,
        problem=problem,
    )
    return problem, artifact, scenario, passenger_build


def test_reservoir_horizon_coverage_includes_exact_tail_boundary() -> None:
    assert not ddd_reservoir_covers_horizon(60.0 - 2e-9, 60.0)
    assert ddd_reservoir_covers_horizon(60.0, 60.0)


def test_neighbor_k_initial_pool_transfers_incumbent_and_covers_new_cabin() -> None:
    source, _, _, _ = _case(k=2)
    target, _, _, _ = _case(k=3)
    source_seed = build_ddd_reservoir_all_stop_seed(source)
    source_incumbent = tuple(
        next(
            trajectory
            for trajectory in source_seed
            if trajectory.cabin_id == cabin_id
            and trajectory.reservoir_state is not None
            and trajectory.reservoir_state.kind
            is DddReservoirTrajectoryKind.DISPATCHED
        )
        for cabin_id in source.cabin_ids
    )

    pool = build_ddd_reservoir_neighbor_k_initial_pool(
        target_problem=target,
        source_domain=source.start_domain,
        source_incumbent_trajectories=source_incumbent,
    )

    assert {item.cabin_id for item in pool} == {0, 1, 2}
    assert all(item in pool for item in source_incumbent)
    assert any(
        item.cabin_id == 2
        and item.reservoir_state is not None
        and item.reservoir_state.kind is DddReservoirTrajectoryKind.STORED
        for item in pool
    )


def test_neighbor_k_initial_pool_rejects_an_incompatible_boundary() -> None:
    source, _, _, _ = _case(k=1)
    target, _, _, _ = _case(k=2)
    target_domain = target.start_domain
    assert isinstance(target_domain, DddReservoirTrajectoryStartDomain)
    incompatible = replace(
        source.start_domain,
        boundary=replace(source.start_domain.boundary, id="another-reservoir"),
    )

    with pytest.raises(ValueError, match="boundary does not match"):
        build_ddd_reservoir_neighbor_k_initial_pool(
            target_problem=target,
            source_domain=incompatible,
            source_incumbent_trajectories=(
                build_ddd_stored_reservoir_trajectory(
                    cabin_id=0,
                    domain=source.start_domain,
                ),
            ),
        )


def _all_stop_route(problem: DddTrajectoryProblem, dispatch_time: float):
    domain = problem.start_domain
    assert isinstance(domain, DddReservoirTrajectoryStartDomain)
    state = domain.boundary.entry_state_id
    time = dispatch_time
    result = []
    for _ in range(domain.maximum_visit_count):
        stop = next(
            option
            for option in problem.movement_core.route_options_by_state_id[state]
            if option.decision.value == "stop"
        )
        result.append(stop.id)
        state = stop.to_state_id
        time += stop.duration_seconds
        if time > problem.movement_core.operational_end_seconds:
            break
    return tuple(result)


def test_stored_reservoir_column_is_physically_empty() -> None:
    problem, _, _, _ = _case()
    domain = problem.start_domain
    assert isinstance(domain, DddReservoirTrajectoryStartDomain)

    trajectory = build_ddd_stored_reservoir_trajectory(
        cabin_id=0,
        domain=domain,
    )
    fleet = validate_ddd_reservoir_solution(problem, (trajectory,))

    assert trajectory.visits == ()
    assert trajectory.resource_occurrences == ()
    assert trajectory.reservoir_state is not None
    assert trajectory.reservoir_state.kind is DddReservoirTrajectoryKind.STORED
    assert fleet.dispatched_fleet_count == 0


def test_reservoir_solution_rejects_two_selected_columns_for_one_cabin() -> None:
    problem, _, _, _ = _case()
    domain = problem.start_domain
    assert isinstance(domain, DddReservoirTrajectoryStartDomain)
    dispatch_time = -91.234567891
    dispatched = build_ddd_reservoir_reference_trajectory(
        problem=problem,
        cabin_id=0,
        dispatch_time_seconds=dispatch_time,
        route_option_ids=_all_stop_route(problem, dispatch_time),
    )
    stored = build_ddd_stored_reservoir_trajectory(cabin_id=0, domain=domain)

    with pytest.raises(ValueError, match="one column per available cabin"):
        validate_ddd_reservoir_solution(problem, (stored, dispatched))


def test_reservoir_trajectory_rejects_a_decision_different_from_its_route() -> None:
    problem, _, _, _ = _case()
    dispatch_time = -91.234567891
    trajectory = build_ddd_reservoir_reference_trajectory(
        problem=problem,
        cabin_id=0,
        dispatch_time_seconds=dispatch_time,
        route_option_ids=_all_stop_route(problem, dispatch_time),
    )
    first = trajectory.visits[0]
    wrong_decision = (
        type(first.decision).SKIP
        if first.decision is type(first.decision).STOP
        else type(first.decision).STOP
    )
    corrupted = replace(
        trajectory,
        visits=(
            replace(first, decision=wrong_decision, quantize_times=False),
            *trajectory.visits[1:],
        ),
    )

    with pytest.raises(ValueError, match="decision does not match"):
        validate_ddd_reservoir_solution(problem, (corrupted,))


def test_reservoir_dispatch_preserves_continuous_time_and_all_stop_warmup() -> None:
    problem, _, _, _ = _case()
    dispatch_time = -91.234567891
    trajectory = build_ddd_reservoir_reference_trajectory(
        problem=problem,
        cabin_id=0,
        dispatch_time_seconds=dispatch_time,
        route_option_ids=_all_stop_route(problem, dispatch_time),
    )

    assert trajectory.visits[0].switch_time_seconds == dispatch_time
    assert all(
        visit.decision.value == "stop"
        for visit in trajectory.visits
        if visit.switch_time_seconds < 0
    )
    assert trajectory.visits[-1].next_switch_time_seconds > (
        problem.movement_core.operational_end_seconds
    )


def test_physical_reservoir_dispatch_creates_explicit_boundary_occurrence() -> None:
    problem, artifact, _, _ = _case()
    domain = problem.start_domain
    assert isinstance(domain, DddReservoirTrajectoryStartDomain)
    first_option = problem.movement_core.route_options_by_state_id[
        domain.boundary.entry_state_id
    ][0]
    resource_id = first_option.resource_usages[0].resource_id
    physical_domain = replace(
        domain,
        boundary=replace(
            domain.boundary,
            boundary_mode=DddReservoirBoundaryMode.PHYSICAL_RESOURCE,
            dispatch_resource_usages=(
                DddResourceUsage(
                    resource_id=resource_id,
                    leader_clear_offset_seconds=0.0,
                    follower_enter_offset_seconds=0.0,
                ),
            ),
        ),
    )
    physical_problem = replace(problem, start_domain=physical_domain)
    dispatch_time = -100.25
    trajectory = build_ddd_reservoir_reference_trajectory(
        problem=physical_problem,
        cabin_id=0,
        dispatch_time_seconds=dispatch_time,
        route_option_ids=_all_stop_route(physical_problem, dispatch_time),
    )

    assert len(trajectory.boundary_resource_occurrences) == 1
    occurrence = trajectory.boundary_resource_occurrences[0]
    assert occurrence.boundary_origin
    assert occurrence.visit_index == -1
    assert occurrence.resource_id == resource_id
    assert occurrence.follower_enter_time_seconds == dispatch_time
    movement_plan, fleet = validate_ddd_reservoir_plan_against_artifact(
        problem=physical_problem,
        artifact=artifact,
        trajectories=(trajectory,),
    )
    assert movement_plan.trajectories
    assert fleet.dispatched_fleet_count == 1


def test_physical_reservoir_boundary_requires_dispatch_resource() -> None:
    problem, _, _, _ = _case()
    domain = problem.start_domain
    assert isinstance(domain, DddReservoirTrajectoryStartDomain)
    invalid = replace(
        problem,
        start_domain=replace(
            domain,
            boundary=replace(
                domain.boundary,
                boundary_mode=DddReservoirBoundaryMode.PHYSICAL_RESOURCE,
            ),
        ),
    )

    with pytest.raises(ValueError, match="requires a dispatch resource"):
        invalid.validate()


def test_reservoir_artifact_validation_rejects_another_movement_core() -> None:
    problem, artifact, _, _ = _case()
    trajectory = build_ddd_reservoir_all_stop_seed(problem)[-1]
    mismatched = replace(
        problem,
        movement_core=replace(problem.movement_core, scenario_id="another_scenario"),
    )

    with pytest.raises(ValueError, match="does not match the supplied EAN artifact"):
        validate_ddd_reservoir_plan_against_artifact(
            problem=mismatched,
            artifact=artifact,
            trajectories=(trajectory,),
        )


def test_reservoir_master_marks_stored_option_and_keeps_dispatch_option() -> None:
    problem, artifact, _, passenger_build = _case()
    domain = problem.start_domain
    assert isinstance(domain, DddReservoirTrajectoryStartDomain)
    stored = build_ddd_stored_reservoir_trajectory(cabin_id=0, domain=domain)
    dispatched = build_ddd_reservoir_reference_trajectory(
        problem=problem,
        cabin_id=0,
        dispatch_time_seconds=-100.0,
        route_option_ids=_all_stop_route(problem, -100.0),
    )

    built = build_ddd_trajectory_reference_master(
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        reference_trajectories=(stored, dispatched),
    )

    assert len(built.master_problem.options) == 2
    assert sum(option.is_stored for option in built.master_problem.options) == 1
    assert next(option for option in built.master_problem.options if option.is_stored).rides == ()


def test_continuous_reservoir_pricing_covers_stored_and_dispatch_domain() -> None:
    problem, artifact, _, passenger_build = _case()
    seed = build_ddd_reservoir_all_stop_seed(problem)
    built = build_ddd_trajectory_reference_master(
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        reference_trajectories=seed,
    )
    lp = DddTrajectoryFactorizedLpOptimizer().solve(built.master_problem)
    assert lp.status is DddTrajectoryPassengerLpStatus.OPTIMAL
    assert lp.duals is not None

    priced = DddTrajectoryExactReservoirNoWaitPricingOracle(
        time_limit_seconds=10.0,
    ).solve(
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        cabin_id=0,
        duals=lp.duals,
    )

    assert priced.required_start_class_count == 1
    assert priced.certified_reduced_cost_lower_bound is not None
    assert priced.reference_trajectory is not None


def test_restricted_compact_reservoir_pricing_is_primal_only() -> None:
    problem, artifact, _, passenger_build = _case()
    seed = build_ddd_reservoir_all_stop_seed(problem)
    built = build_ddd_trajectory_reference_master(
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        reference_trajectories=seed,
    )
    lp = DddTrajectoryFactorizedLpOptimizer().solve(built.master_problem)
    assert lp.duals is not None

    priced = DddTrajectoryExactReservoirNoWaitPricingOracle(
        time_limit_seconds=10.0,
        mip_focus=1,
    ).solve(
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        cabin_id=0,
        duals=lp.duals,
        dispatch_time_bounds_seconds=(-120.0, -110.0),
        certify_complete_domain=False,
        dispatch_only=True,
    )

    assert priced.reference_trajectory is not None
    assert priced.reference_trajectory.reservoir_state is not None
    dispatch_time = priced.reference_trajectory.reservoir_state.dispatch_time_seconds
    assert dispatch_time is not None
    assert -120.0 <= dispatch_time <= -110.0
    assert priced.certified_reduced_cost_lower_bound is None
    assert not priced.exact


def test_time_expanded_anchor_pricing_is_primal_only() -> None:
    problem, artifact, _, passenger_build = _case()
    seed = build_ddd_reservoir_all_stop_seed(problem)
    built = build_ddd_trajectory_reference_master(
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        reference_trajectories=seed,
    )
    lp = DddTrajectoryFactorizedLpOptimizer().solve(built.master_problem)
    assert lp.duals is not None
    domain = problem.start_domain
    assert isinstance(domain, DddReservoirTrajectoryStartDomain)
    anchor = build_ddd_reservoir_dispatch_anchors(domain, anchor_count=5)[1]

    priced = DddTrajectoryReservoirAnchorPricingOracle(
        time_limit_seconds=10.0,
    ).solve(
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        cabin_id=0,
        dispatch_time_seconds=anchor,
        duals=lp.duals,
    )

    assert priced.reference_trajectory is not None
    assert priced.reference_trajectory.reservoir_state is not None
    assert priced.reference_trajectory.reservoir_state.dispatch_time_seconds == anchor
    assert priced.certified_reduced_cost_lower_bound is None
    assert not priced.exact

    skipped = DddTrajectoryReservoirAnchorPricingOracle(
        time_limit_seconds=10.0,
        maximum_time_expanded_arc_count=1,
    ).solve(
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        cabin_id=0,
        dispatch_time_seconds=anchor,
        duals=lp.duals,
    )
    assert skipped.reference_trajectory is None
    assert skipped.certified_reduced_cost_lower_bound is None
    assert "skipped before model build" in (skipped.detail or "")


def test_exact_dispatch_domain_rejects_stored_column() -> None:
    problem, _, _, _ = _case(optional=False)
    domain = problem.start_domain
    assert isinstance(domain, DddReservoirTrajectoryStartDomain)

    with pytest.raises(ValueError, match="no stored column"):
        build_ddd_stored_reservoir_trajectory(cabin_id=0, domain=domain)


def test_root_cg_combines_anchor_incumbent_with_continuous_bound(tmp_path) -> None:
    problem, artifact, _, passenger_build = _case()
    checkpoints = []
    result = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=1,
        pricing_time_limit_seconds=10.0,
        pricing_formulation=DddTrajectoryPricingFormulation.TIGHT_CONVEX_HULL,
        reservoir_primal_pricing_time_limit_seconds=2.0,
        reservoir_dispatch_anchor_count=5,
    ).solve(
        problem=build_initial_ddd_network_problem(
            problem.structural_movement_problem
        ),
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        checkpoint_callback=checkpoints.append,
    )

    assert result.iterations
    iteration = result.iterations[0]
    assert iteration.primal_pricing_call_count == 1
    assert iteration.bounded_start_class_count == 1
    assert iteration.pricing_corrected_lower_bound is not None
    assert iteration.pricing_corrected_lower_bound <= result.best_upper_bound
    checkpoint_path = tmp_path / "reservoir.json"
    write_ddd_trajectory_root_cg_checkpoint(checkpoint_path, checkpoints[-1])
    restored = read_ddd_trajectory_root_cg_checkpoint(checkpoint_path)
    assert restored.reservoir_start_domain == problem.start_domain
    expected_ids = {
        ddd_trajectory_column(
            trajectory,
            instance_fingerprint=ddd_trajectory_problem_instance_fingerprint(
                artifact,
                problem,
            ),
        ).id
        for trajectory in restored.trajectories
    }
    assert set(restored.incumbent_option_ids) <= expected_ids


def test_reservoir_dispatch_order_canonicalizes_adjacent_cabins() -> None:
    problem, artifact, _, passenger_build = _case(k=2)
    late_first = build_ddd_reservoir_reference_trajectory(
        problem=problem,
        cabin_id=0,
        dispatch_time_seconds=-80.0,
        route_option_ids=_all_stop_route(problem, -80.0),
    )
    early_second = build_ddd_reservoir_reference_trajectory(
        problem=problem,
        cabin_id=1,
        dispatch_time_seconds=-100.0,
        route_option_ids=_all_stop_route(problem, -100.0),
    )
    built = build_ddd_trajectory_reference_master(
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        reference_trajectories=(late_first, early_second),
    )

    assert len(built.master_problem.incompatibility_pairs) == 1


def test_reservoir_proof_pricing_is_shared_between_equivalent_cabins() -> None:
    problem, artifact, _, passenger_build = _case(k=2)
    result = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=1,
        pricing_time_limit_seconds=10.0,
        pricing_formulation=DddTrajectoryPricingFormulation.TIGHT_CONVEX_HULL,
    ).solve(
        problem=build_initial_ddd_network_problem(
            problem.structural_movement_problem
        ),
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )

    iteration = result.iterations[0]
    assert iteration.proof_pricing_solve_count == 1
    assert iteration.proof_pricing_reused_cabin_count == 1
    assert sum(
        diagnostic.reused_from_cabin_id is not None
        for diagnostic in iteration.pricing_diagnostics
    ) == 1


def test_root_cg_total_time_limit_stops_between_completed_rounds() -> None:
    problem, artifact, _, passenger_build = _case()
    result = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=100,
        total_time_limit_seconds=1e-12,
        pricing_time_limit_seconds=10.0,
        pricing_formulation=DddTrajectoryPricingFormulation.TIGHT_CONVEX_HULL,
    ).solve(
        problem=build_initial_ddd_network_problem(
            problem.structural_movement_problem
        ),
        trajectory_problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )

    assert result.status is DddTrajectoryRootCgStatus.TIME_LIMIT
    assert not result.iterations
