from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddAnalyticAllStopInfeasible,
    DddFixedKArcFlowRunConfig,
    build_ddd_fixed_k_arc_flow_problem,
    run_ddd_fixed_k_arc_flow,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddArcFlowResourceInterval,
    DddArcFlowBoundaryInterval,
    DddArcFlowProblemPreparer,
    DddArcFlowPassengerDomainBuilder,
    DddArcFlowPassengerModelBuilder,
    DddCabinTimeExpandedArc,
    DddCabinTimeExpandedNetwork,
    DddCabinTimeExpandedNetworkBuilder,
    DddFixedKArcFlowOptimizer,
    DddFixedKArcFlowSolveConfig,
    DddFixedKArcFlowStatus,
    DddFixedKMovementArcFlowConfig,
    DddFixedKMovementArcFlowOptimizer,
    DddFixedKMovementArcFlowStatus,
    DddMovementArcFlowObjectiveMode,
    DddFixedKOperatingMode,
    DddFixedKStartPolicy,
    DddFixedKTrajectoryProblem,
    DddFixedKPrimalSeedFactory,
    DddTrajectoryWaitingDomain,
    DddTrajectoryWaitingPolicy,
    DddFixedMovementPassengerRecourseOracle,
    DddPassengerRecourseConfig,
    build_ddd_arc_flow_movement_values,
    EanArtifactToDddMovementProblemAdapter,
    build_ddd_arc_flow_resource_cliques,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    CanonicalFixedKRopeCabinStartBuilder,
    EanPassengerCandidateBuilder,
    EanPassengerObjective,
    SparseHeadwayPairBuilder,
    EanPassengerAssignmentDomain,
)


EXAMPLE_ID = "five_station_circle_cw_half_skip_no_wait_v0"
HEADWAY_B_EXAMPLE_ID = "five_station_circle_cw_half_skip_no_wait_headway_b_v0"


def _fixed_problem(cabin_count: int = 1) -> DddFixedKTrajectoryProblem:
    example = get_example(EXAMPLE_ID)
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    artifact = replace(
        example.build_ean_artifact_builder(scenario, config),
        start_builder=CanonicalFixedKRopeCabinStartBuilder(cabin_count),
        headway_pair_builder=SparseHeadwayPairBuilder(),
    ).build(scenario, config)
    trajectory_problem = (
        EanArtifactToDddMovementProblemAdapter().build_trajectory_problem(artifact)
    )
    return DddFixedKTrajectoryProblem(
        trajectory_problem=trajectory_problem,
        artifact=artifact,
        passenger_build=EanPassengerCandidateBuilder().build(scenario, artifact),
        objective=EanPassengerObjective.JOURNEY_TIME,
        operating_mode=DddFixedKOperatingMode.SKIP_STOP,
        start_policy=DddFixedKStartPolicy.CANONICAL_ROPE,
    )


def test_time_expanded_network_is_deterministic_and_covers_horizon() -> None:
    problem = _fixed_problem()
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    start = movement.starts[0]

    first = DddCabinTimeExpandedNetworkBuilder().build(movement, start)
    second = DddCabinTimeExpandedNetworkBuilder().build(movement, start)

    assert first == second
    assert first.arcs
    assert any(arc.option_id is not None for arc in first.arcs)
    assert any(not arc.target_active for arc in first.arcs)
    assert all(
        interval.clear_with_headway_tick > interval.enter_tick
        for arc in first.arcs
        for interval in arc.resource_intervals
    )


def test_time_expanded_network_rejects_waiting_v1() -> None:
    problem = _fixed_problem()
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    station_id = movement.route_options[0].station_id
    with pytest.raises(ValueError, match="no-wait"):
        DddCabinTimeExpandedNetworkBuilder().build(
            movement,
            movement.starts[0],
            waiting_policy=DddTrajectoryWaitingPolicy(
                domain=DddTrajectoryWaitingDomain.BOUNDED_WAIT,
                step_seconds=1.0,
                maximum_wait_seconds_by_station_id=((station_id, 1.0),),
            ),
        )


def test_boundary_interval_prunes_a_conflicting_route_arc() -> None:
    problem = _fixed_problem()
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    start = movement.starts[0]
    baseline = DddCabinTimeExpandedNetworkBuilder().build(movement, start)
    occupied = next(
        interval
        for arc in baseline.arcs
        if arc.source_active
        for interval in arc.resource_intervals
    )
    boundary = DddArcFlowBoundaryInterval(
        resource_id=occupied.resource_id,
        cabin_id=99,
        enter_tick=occupied.enter_tick,
        clear_with_headway_tick=occupied.clear_with_headway_tick,
    )

    pruned = DddCabinTimeExpandedNetworkBuilder().build(
        movement,
        start,
        boundary_intervals=(boundary,),
    )

    assert len(pruned.arcs) < len(baseline.arcs)
    assert all(
        not boundary.overlaps(interval)
        for arc in pruned.arcs
        for interval in arc.resource_intervals
    )


def test_balanced_reference_uses_identical_all_stop_starts_below_capacity() -> None:
    all_stop_config = DddFixedKArcFlowRunConfig(
        example_id=HEADWAY_B_EXAMPLE_ID,
        cabin_count=20,
        operating_mode=DddFixedKOperatingMode.ALL_STOP,
        start_policy=DddFixedKStartPolicy.BALANCED_REFERENCE,
    )
    skip_stop_config = replace(
        all_stop_config,
        operating_mode=DddFixedKOperatingMode.SKIP_STOP,
    )

    _, all_stop = build_ddd_fixed_k_arc_flow_problem(all_stop_config)
    _, skip_stop = build_ddd_fixed_k_arc_flow_problem(skip_stop_config)

    assert all_stop.artifact.cabin_starts == skip_stop.artifact.cabin_starts
    assert not all_stop.boundary_context.resource_occurrences
    assert not skip_stop.boundary_context.resource_occurrences


def test_balanced_reference_certifies_all_stop_above_capacity_analytically() -> None:
    config = DddFixedKArcFlowRunConfig(
        example_id=HEADWAY_B_EXAMPLE_ID,
        cabin_count=39,
        operating_mode=DddFixedKOperatingMode.ALL_STOP,
        start_policy=DddFixedKStartPolicy.BALANCED_REFERENCE,
    )

    with pytest.raises(DddAnalyticAllStopInfeasible) as captured:
        build_ddd_fixed_k_arc_flow_problem(config)

    assert captured.value.maximum_cabin_count == 38


def test_balanced_reference_builds_boundary_safe_skip_stop_snapshot() -> None:
    config = DddFixedKArcFlowRunConfig(
        example_id=HEADWAY_B_EXAMPLE_ID,
        cabin_count=39,
        operating_mode=DddFixedKOperatingMode.SKIP_STOP,
        start_policy=DddFixedKStartPolicy.BALANCED_REFERENCE,
    )

    _, problem = build_ddd_fixed_k_arc_flow_problem(config)

    assert problem.fleet_cardinality == 39
    assert problem.boundary_context.source == "periodic_balanced_reference"
    assert problem.boundary_context.initial_states
    assert problem.boundary_context.resource_occurrences
    problem.validate()


def test_resource_cliques_respect_half_open_boundaries_and_deduplicate() -> None:
    problem = _fixed_problem()
    start = problem.resolved_trajectory_problem.structural_movement_problem.starts[0]
    arcs = (
        DddCabinTimeExpandedArc(
            id="a",
            cabin_id=0,
            visit_index=0,
            source_tick=0,
            source_active=True,
            option_id="route",
            wait_tick=0,
            target_tick=2,
            target_active=False,
            resource_intervals=(DddArcFlowResourceInterval("r", "a", 0, 0, 2),),
        ),
        DddCabinTimeExpandedArc(
            id="b",
            cabin_id=0,
            visit_index=0,
            source_tick=0,
            source_active=True,
            option_id="route",
            wait_tick=0,
            target_tick=2,
            target_active=False,
            resource_intervals=(DddArcFlowResourceInterval("r", "b", 0, 1, 3),),
        ),
        DddCabinTimeExpandedArc(
            id="c",
            cabin_id=0,
            visit_index=0,
            source_tick=0,
            source_active=True,
            option_id="route",
            wait_tick=0,
            target_tick=2,
            target_active=False,
            resource_intervals=(DddArcFlowResourceInterval("r", "c", 0, 3, 4),),
        ),
    )
    network = DddCabinTimeExpandedNetwork(
        cabin_id=0,
        start=replace(start, state_id="unused", time_seconds=0.0, max_visit_count=1),
        state_ids=("unused", "unused"),
        arcs=arcs,
    )

    cliques = build_ddd_arc_flow_resource_cliques((network,))

    assert tuple(clique.coefficients for clique in cliques) == (
        (("a", 1), ("b", 1)),
        (("c", 1),),
    )


def test_full_arc_flow_matches_known_fixed_timetable_passenger_objective() -> None:
    result = DddFixedKArcFlowOptimizer(
        DddFixedKArcFlowSolveConfig(time_limit_seconds=10.0)
    ).solve(_fixed_problem())

    assert result.status is DddFixedKArcFlowStatus.INTEGER_OPTIMAL
    assert result.objective_value == pytest.approx(1_439_868.872376)
    assert result.certified_lower_bound == pytest.approx(result.objective_value)
    assert result.relative_gap == pytest.approx(0.0)
    assert result.solution is not None
    assert result.movement_variable_count > 0
    assert result.passenger_variable_count > 0


def test_complete_primal_seed_supplies_validated_upper_bound_and_passengers() -> None:
    problem = _fixed_problem()
    scenario = get_example(EXAMPLE_ID).build_scenario()
    movement = DddFixedKMovementArcFlowOptimizer(
        DddFixedKMovementArcFlowConfig(time_limit_seconds=10.0)
    ).solve(problem)
    assert movement.solution is not None
    network_problem = build_initial_ddd_network_problem(
        problem.resolved_trajectory_problem.structural_movement_problem
    )
    seed = DddFixedKPrimalSeedFactory(
        scenario=scenario,
        problem=problem,
        network_problem=network_problem,
        passenger_time_limit_seconds=10.0,
    ).build(movement.solution.trajectories, provenance="test")

    result = DddFixedKArcFlowOptimizer(
        DddFixedKArcFlowSolveConfig(time_limit_seconds=10.0)
    ).solve(problem, primal_seed=seed)

    seed.validate(problem)
    assert seed.ride_counts_by_candidate_id
    assert result.status is DddFixedKArcFlowStatus.INTEGER_OPTIMAL
    assert result.primal_seed_objective_value == pytest.approx(seed.objective_value)
    assert result.validated_upper_bound is not None
    assert result.validated_upper_bound <= seed.objective_value + 1e-5
    assert result.solution is not None
    assert result.time_to_first_incumbent_seconds == pytest.approx(0.0)


def test_shared_arc_flow_preparation_supports_movement_only_solve() -> None:
    problem = _fixed_problem()
    prepared = DddArcFlowProblemPreparer().build(problem)

    result = DddFixedKMovementArcFlowOptimizer(
        DddFixedKMovementArcFlowConfig(time_limit_seconds=10.0)
    ).solve_prepared(prepared)

    prepared.validate()
    assert result.status is DddFixedKMovementArcFlowStatus.FEASIBLE
    assert result.solution is not None
    assert result.movement_variable_count == len(prepared.arcs)
    assert result.resource_row_count > 0


def test_fixed_movement_passenger_lp_ip_diagnostic_is_exact_on_tiny_case() -> None:
    problem = _fixed_problem()
    scenario = get_example(EXAMPLE_ID).build_scenario()
    movement = DddFixedKMovementArcFlowOptimizer(
        DddFixedKMovementArcFlowConfig(time_limit_seconds=10.0)
    ).solve(problem)
    assert movement.solution is not None

    comparison = DddFixedMovementPassengerRecourseOracle(
        scenario=scenario,
        problem=problem,
        config=DddPassengerRecourseConfig(time_limit_seconds=10.0),
    ).compare_lp_and_integer(movement.solution)

    assert comparison.lp.optimal
    assert comparison.integer.optimal
    assert comparison.gap_is_exact
    assert comparison.absolute_gap == pytest.approx(0.0)
    assert comparison.lp.objective_value == pytest.approx(
        comparison.integer.objective_value
    )


def test_normalized_passenger_domain_and_recourse_match_monolithic_tiny_case() -> None:
    problem = _fixed_problem()
    prepared = DddArcFlowProblemPreparer().build(problem)
    domain = DddArcFlowPassengerDomainBuilder().build(prepared)
    movement = DddFixedKMovementArcFlowOptimizer(
        DddFixedKMovementArcFlowConfig(time_limit_seconds=10.0)
    ).solve_prepared(prepared)
    assert movement.solution is not None
    movement_values = build_ddd_arc_flow_movement_values(
        prepared,
        movement.solution,
    )
    builder = DddArcFlowPassengerModelBuilder()
    lp_model = builder.build_recourse(
        domain=domain,
        assignment_domain=EanPassengerAssignmentDomain.LP_RELAXATION,
    )
    integer_model = builder.build_recourse(
        domain=domain,
        assignment_domain=EanPassengerAssignmentDomain.INTEGER,
    )

    lp = lp_model.evaluate(movement_values)
    integer = integer_model.evaluate(movement_values)
    independent = DddFixedMovementPassengerRecourseOracle(
        scenario=get_example(EXAMPLE_ID).build_scenario(),
        problem=problem,
        config=DddPassengerRecourseConfig(time_limit_seconds=10.0),
    ).compare_lp_and_integer(movement.solution)

    domain.validate(prepared)
    assert lp.optimal
    assert integer.optimal
    assert lp.objective_value == pytest.approx(integer.objective_value)
    assert integer.objective_value == pytest.approx(
        independent.integer.objective_value
    )
    assert lp.objective_value == pytest.approx(independent.lp.objective_value)
    assert lp.benders_cut is not None
    assert lp.benders_cut.evaluate(movement_values) == pytest.approx(
        lp.objective_value
    )
    assert all(value <= 1e-8 for _, value in lp.benders_cut.coefficients)


def test_passenger_dual_cuts_are_valid_across_diverse_tiny_movements() -> None:
    problem = _fixed_problem()
    prepared = DddArcFlowProblemPreparer().build(problem)
    domain = DddArcFlowPassengerDomainBuilder().build(prepared)
    recourse = DddArcFlowPassengerModelBuilder().build_recourse(
        domain=domain,
        assignment_domain=EanPassengerAssignmentDomain.LP_RELAXATION,
    )
    vectors = []
    for seed in range(3):
        movement = DddFixedKMovementArcFlowOptimizer(
            DddFixedKMovementArcFlowConfig(
                time_limit_seconds=2.0,
                seed=seed,
                objective_mode=(
                    DddMovementArcFlowObjectiveMode.DETERMINISTIC_DIVERSIFICATION
                ),
            )
        ).solve_prepared(prepared)
        assert movement.solution is not None
        vectors.append(
            build_ddd_arc_flow_movement_values(prepared, movement.solution)
        )
    evaluations = tuple(recourse.evaluate(vector) for vector in vectors)

    for source in evaluations:
        assert source.benders_cut is not None
        for vector, target in zip(vectors, evaluations, strict=True):
            assert target.objective_value is not None
            assert source.benders_cut.evaluate(vector) <= (
                target.objective_value + 1e-5
            )
    assert recourse.evaluation_count == 3


def test_arc_flow_progress_heartbeats_cover_non_mip_phases() -> None:
    samples = []

    result = DddFixedKArcFlowOptimizer(
        DddFixedKArcFlowSolveConfig(
            time_limit_seconds=10.0,
            progress_interval_seconds=0.01,
        )
    ).solve(_fixed_problem(), progress_hook=samples.append)

    assert result.status is DddFixedKArcFlowStatus.INTEGER_OPTIMAL
    assert len(samples) >= 2
    assert samples[0].phase == "network_build"
    assert all(sample.certified_lower_bound >= 0 for sample in samples)
    assert all(sample.remaining_seconds >= 0 for sample in samples)
    assert samples[-1].phase == "solve_complete"
    assert samples[-1].certified_lower_bound == pytest.approx(
        result.certified_lower_bound
    )
    assert samples[-1].solver_incumbent == pytest.approx(result.objective_value)


def test_incompatible_imported_bound_is_rejected_as_certificate_error() -> None:
    result = DddFixedKArcFlowOptimizer(
        DddFixedKArcFlowSolveConfig(time_limit_seconds=10.0)
    ).solve(_fixed_problem(), root_cg_lower_bound=2_000_000.0)

    assert result.status is DddFixedKArcFlowStatus.INTERNAL_CERTIFICATE_ERROR
    assert result.validated_upper_bound is None
    assert result.solution is None


@pytest.mark.parametrize(
    "objective",
    (EanPassengerObjective.JOURNEY_TIME, EanPassengerObjective.WAITING_TIME),
)
def test_arc_flow_application_independently_reproduces_passenger_objective(
    objective: EanPassengerObjective,
) -> None:
    result = run_ddd_fixed_k_arc_flow(
        DddFixedKArcFlowRunConfig(
            example_id=EXAMPLE_ID,
            cabin_count=1,
            operating_mode=DddFixedKOperatingMode.ALL_STOP,
            objective=objective,
            total_time_limit_seconds=10.0,
            cp_seed_time_limit_seconds=1.0,
        )
    )

    assert result.solve_result.status is DddFixedKArcFlowStatus.INTEGER_OPTIMAL
    assert result.independent_validation_status == "feasible"
    assert result.independent_validation_objective == pytest.approx(
        result.solve_result.objective_value
    )
    assert result.to_payload()["problem_fingerprint"] == result.problem.fingerprint


@pytest.mark.parametrize(
    "changes",
    (
        {"solver_threads": 0},
        {"mip_gap": -0.1},
        {"mip_gap": 1.1},
        {"mip_focus": 4},
        {"seed": -1},
    ),
)
def test_arc_flow_run_config_rejects_invalid_solver_controls(
    changes: dict[str, object],
) -> None:
    config = replace(
        DddFixedKArcFlowRunConfig(
            example_id=EXAMPLE_ID,
            cabin_count=1,
            operating_mode=DddFixedKOperatingMode.ALL_STOP,
        ),
        **changes,
    )

    with pytest.raises(ValueError, match="arc-flow"):
        config.validate()
