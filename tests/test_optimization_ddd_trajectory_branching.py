from __future__ import annotations

from dataclasses import replace

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
    DddExhaustiveTrajectoryMasterBuilder,
    DddFixedTrajectoryStartDomain,
    DddReferenceTrajectory,
    DddReferenceVisit,
    DddRouteDecision,
    DddTrajectoryBranchCandidateEvaluator,
    DddTrajectoryBranchDecision,
    DddTrajectoryBranchDomain,
    DddTrajectoryBranchPredicate,
    DddTrajectoryDiveConfig,
    DddTrajectoryDiveCoordinator,
    DddTrajectoryDiveStatus,
    DddTrajectoryExactNoWaitPricingOracle,
    DddTrajectoryExactRootColumnGenerationSolver,
    DddTrajectoryExhaustivePricingOracle,
    DddTrajectoryFactorizedLpOptimizer,
    DddTrajectoryFactorizedMipReferenceOptimizer,
    DddTrajectoryPassengerDuals,
    DddTrajectoryRootCgResult,
    DddTrajectoryRootCgStatus,
    DddTrajectoryProblem,
    EanArtifactToDddMovementProblemAdapter,
    ddd_trajectory_problem_instance_fingerprint,
    find_ddd_reference_conflicts,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanPassengerCandidateBuilder,
    EanPassengerObjective,
)


def _visit(
    *,
    cabin_id: int,
    visit_index: int,
    decision: DddRouteDecision,
) -> DddReferenceVisit:
    return DddReferenceVisit(
        cabin_id=cabin_id,
        visit_index=visit_index,
        state_id=f"state_{visit_index}",
        route_option_id=f"route_{decision.value}_{visit_index}",
        decision=decision,
        switch_time_seconds=float(visit_index),
        next_switch_time_seconds=float(visit_index + 1),
        resource_occurrences=(),
    )


def _trajectory(
    *decisions: DddRouteDecision,
    cabin_id: int = 0,
) -> DddReferenceTrajectory:
    return DddReferenceTrajectory(
        cabin_id=cabin_id,
        visits=tuple(
            _visit(cabin_id=cabin_id, visit_index=index, decision=decision)
            for index, decision in enumerate(decisions)
        ),
    )


def _physical_problem() -> tuple[object, object, object]:
    artifact = build_three_station_exhaustive_bound_artifact()
    scenario = replace(build_three_station_scenario(), id=artifact.scenario_id)
    movement = EanArtifactToDddMovementProblemAdapter().build(artifact)
    problem = build_initial_ddd_network_problem(movement)
    passenger_build = EanPassengerCandidateBuilder().build(scenario, artifact)
    return problem, artifact, passenger_build


def test_branch_predicate_complement_partitions_missing_visits() -> None:
    predicate = DddTrajectoryBranchPredicate.service_decision(
        cabin_id=0,
        visit_index=1,
        decision=DddRouteDecision.STOP,
    )
    parent = DddTrajectoryBranchDomain()
    left = parent.child(predicate, required=True)
    right = parent.child(predicate, required=False)
    trajectories = (
        _trajectory(DddRouteDecision.STOP),
        _trajectory(DddRouteDecision.STOP, DddRouteDecision.STOP),
        _trajectory(DddRouteDecision.STOP, DddRouteDecision.SKIP),
    )

    left_ids = {id(item) for item in left.filter(trajectories)}
    right_ids = {id(item) for item in right.filter(trajectories)}

    assert left_ids.isdisjoint(right_ids)
    assert left_ids | right_ids == {id(item) for item in trajectories}
    assert len(left_ids) == 1
    assert len(right_ids) == 2


def test_branch_domain_round_trip_is_canonical_and_detects_contradiction() -> None:
    stop = DddTrajectoryBranchPredicate.service_decision(
        cabin_id=1,
        visit_index=2,
        decision=DddRouteDecision.STOP,
    )
    route = DddTrajectoryBranchPredicate.route_option(
        cabin_id=0,
        visit_index=0,
        route_option_id="route_0",
    )
    domain = DddTrajectoryBranchDomain(
        (
            DddTrajectoryBranchDecision(stop, False),
            DddTrajectoryBranchDecision(route, True),
        )
    )

    restored = DddTrajectoryBranchDomain.from_payload(domain.to_payload())

    assert restored == domain
    assert restored.fingerprint == domain.fingerprint
    with pytest.raises(ValueError, match="contradictory"):
        domain.child(stop, required=True)

    malformed = domain.to_payload()
    decisions = malformed["decisions"]
    assert isinstance(decisions, list)
    assert isinstance(decisions[0], dict)
    decisions[0]["required"] = "false"
    with pytest.raises(ValueError, match="required flag"):
        DddTrajectoryBranchDomain.from_payload(malformed)


def test_branch_candidate_evaluator_prefers_balanced_stop_split() -> None:
    trajectories = {
        "a": _trajectory(DddRouteDecision.STOP, DddRouteDecision.STOP),
        "b": _trajectory(DddRouteDecision.SKIP, DddRouteDecision.STOP),
        "c": _trajectory(DddRouteDecision.SKIP, DddRouteDecision.SKIP),
    }

    candidates = DddTrajectoryBranchCandidateEvaluator().evaluate(
        trajectory_by_option_id=trajectories,
        option_values_by_id={"a": 0.49, "b": 0.20, "c": 0.31},
    )

    assert candidates
    assert candidates[0].predicate.visit_index == 0
    assert candidates[0].true_mass == pytest.approx(0.49)
    assert candidates[0].false_mass == pytest.approx(0.51)
    assert not candidates[0].preferred_required


def test_exact_pricing_respects_both_service_branch_children() -> None:
    pytest.importorskip("gurobipy")
    problem, artifact, passenger_build = _physical_problem()
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    cabin_id = 0
    predicate = DddTrajectoryBranchPredicate.service_decision(
        cabin_id=cabin_id,
        visit_index=0,
        decision=DddRouteDecision.STOP,
    )
    duals = DddTrajectoryPassengerDuals(
        cabin_choice_raw_by_cabin_id={
            item: 0.0 for item in exhaustive.master_problem.cabin_ids
        },
        demand_raw_by_group_id={
            group_id: -17.0 for group_id in exhaustive.master_problem.demand_by_group_id
        },
        demand_marginal_value_by_group_id={},
        incompatibility_raw_by_pair={},
        ride_activation_raw_by_ride_id={},
        capacity_raw_by_option_segment={},
        fingerprint="branch-pricing-test",
    )
    option_ids = {
        option.id
        for option in exhaustive.master_problem.options
        if option.cabin_id == cabin_id
    }

    for required in (False, True):
        domain = DddTrajectoryBranchDomain().child(predicate, required=required)
        allowed = {
            option_id
            for option_id in option_ids
            if domain.allows(exhaustive.reference_trajectory_by_option_id[option_id])
        }
        assert allowed
        reference = DddTrajectoryExhaustivePricingOracle().solve(
            exhaustive=exhaustive,
            cabin_id=cabin_id,
            duals=duals,
            excluded_option_ids=frozenset(option_ids - allowed),
        )
        exact = DddTrajectoryExactNoWaitPricingOracle(time_limit_seconds=10.0).solve(
            movement_problem=problem.movement_problem,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=EanPassengerObjective.JOURNEY_TIME,
            cabin_id=cabin_id,
            duals=duals,
            branch_domain=domain,
        )

        assert exact.exact
        assert exact.minimum_reduced_cost == pytest.approx(
            reference.minimum_reduced_cost,
            abs=1e-6,
        )
        assert exact.reference_trajectory is not None
        assert domain.allows(exact.reference_trajectory)


def test_exact_pricing_respects_fixed_boundary_occurrences() -> None:
    pytest.importorskip("gurobipy")
    problem, artifact, passenger_build = _physical_problem()
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    cabin_id = 0
    cabin_options = {
        option.id
        for option in exhaustive.master_problem.options
        if option.cabin_id == cabin_id
    }
    trajectories = exhaustive.reference_trajectory_by_option_id
    boundary = next(
        replace(occurrence, boundary_origin=True)
        for trajectory in trajectories.values()
        if trajectory.cabin_id != cabin_id
        for occurrence in trajectory.resource_occurrences
        if 0
        < sum(
            not find_ddd_reference_conflicts(
                (
                    *trajectories[option_id].resource_occurrences,
                    replace(occurrence, boundary_origin=True),
                ),
                problem.movement_problem,
            )
            for option_id in cabin_options
        )
        < len(cabin_options)
    )
    allowed = {
        option_id
        for option_id in cabin_options
        if not find_ddd_reference_conflicts(
            (*trajectories[option_id].resource_occurrences, boundary),
            problem.movement_problem,
        )
    }
    duals = DddTrajectoryPassengerDuals(
        cabin_choice_raw_by_cabin_id={
            item: 0.0 for item in exhaustive.master_problem.cabin_ids
        },
        demand_raw_by_group_id={
            group_id: -17.0 for group_id in exhaustive.master_problem.demand_by_group_id
        },
        demand_marginal_value_by_group_id={},
        incompatibility_raw_by_pair={},
        ride_activation_raw_by_ride_id={},
        capacity_raw_by_option_segment={},
        fingerprint="boundary-pricing-test",
    )
    reference = DddTrajectoryExhaustivePricingOracle().solve(
        exhaustive=exhaustive,
        cabin_id=cabin_id,
        duals=duals,
        excluded_option_ids=frozenset(cabin_options - allowed),
    )
    exact = DddTrajectoryExactNoWaitPricingOracle(time_limit_seconds=10.0).solve(
        movement_problem=problem.movement_problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        cabin_id=cabin_id,
        duals=duals,
        boundary_occurrences=(boundary,),
    )

    assert exact.exact
    assert exact.minimum_reduced_cost == pytest.approx(
        reference.minimum_reduced_cost,
        abs=1e-6,
    )
    assert exact.option_id in allowed
    assert exact.reference_trajectory is not None
    assert not find_ddd_reference_conflicts(
        (*exact.reference_trajectory.resource_occurrences, boundary),
        problem.movement_problem,
    )


def test_boundary_occurrences_change_root_instance_fingerprint() -> None:
    problem, artifact, passenger_build = _physical_problem()
    trajectory_problem = DddTrajectoryProblem(
        movement_core=problem.movement_problem.core,
        start_domain=DddFixedTrajectoryStartDomain(problem.movement_problem.starts),
    )
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    occurrence = next(
        item
        for candidate in exhaustive.reference_trajectory_by_option_id.values()
        for item in candidate.resource_occurrences
    )
    boundary = replace(occurrence, boundary_origin=True)

    plain = ddd_trajectory_problem_instance_fingerprint(
        artifact,
        trajectory_problem,
    )
    bounded = ddd_trajectory_problem_instance_fingerprint(
        artifact,
        trajectory_problem,
        boundary_occurrences=(boundary,),
    )

    assert bounded != plain


def test_exact_node_column_generation_certifies_service_branch() -> None:
    pytest.importorskip("gurobipy")
    problem, artifact, passenger_build = _physical_problem()
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    predicate = DddTrajectoryBranchPredicate.service_decision(
        cabin_id=0,
        visit_index=0,
        decision=DddRouteDecision.STOP,
    )
    domain = DddTrajectoryBranchDomain().child(predicate, required=True)
    initial = domain.filter(
        tuple(exhaustive.reference_trajectory_by_option_id.values())
    )

    result = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=2,
        pricing_time_limit_seconds=10.0,
        certified_fixed_k_mode=True,
    ).solve(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        initial_trajectories=initial,
        branch_domain=domain,
    )

    assert result.root_lp_certified
    assert result.certificate_valid
    assert result.iterations[-1].added_trajectory_count == 0
    assert all(domain.allows(item) for item in result.trajectories)


def test_dive_coordinator_keeps_integral_root_certificate() -> None:
    pytest.importorskip("gurobipy")
    problem, artifact, passenger_build = _physical_problem()
    exhaustive = DddExhaustiveTrajectoryMasterBuilder().build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )
    lp = DddTrajectoryFactorizedLpOptimizer().solve(exhaustive.master_problem)
    mip = DddTrajectoryFactorizedMipReferenceOptimizer().solve(
        exhaustive.master_problem
    )
    assert lp.objective_value is not None
    assert mip.objective_value is not None
    trajectory_problem = DddTrajectoryProblem(
        movement_core=problem.movement_problem.core,
        start_domain=DddFixedTrajectoryStartDomain(problem.movement_problem.starts),
    )
    root = DddTrajectoryRootCgResult(
        status=DddTrajectoryRootCgStatus.INTEGER_OPTIMAL,
        certified_lower_bound=lp.objective_value,
        best_upper_bound=mip.objective_value,
        relative_gap=0.0,
        root_lp_certified=True,
        iterations=(),
        trajectories=tuple(exhaustive.reference_trajectory_by_option_id.values()),
        incumbent_option_ids=tuple(
            sorted(
                option_id
                for option_id, value in mip.option_values_by_id.items()
                if value >= 0.5
            )
        ),
        incumbent_ride_values_by_id=mip.ride_values_by_id,
        total_seconds=0.0,
        instance_fingerprint=ddd_trajectory_problem_instance_fingerprint(
            artifact,
            trajectory_problem,
        ),
    )

    result = DddTrajectoryDiveCoordinator(
        DddTrajectoryDiveConfig(
            maximum_depth=2,
            maximum_dives=1,
            total_time_limit_seconds=10.0,
            node_time_limit_seconds=5.0,
        )
    ).solve(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        root_result=root,
    )

    assert result.status is DddTrajectoryDiveStatus.NO_FRACTIONAL_BRANCH
    assert result.certified_root_lower_bound == pytest.approx(lp.objective_value)
    assert result.best_validated_upper_bound == pytest.approx(mip.objective_value)
    assert not result.steps
