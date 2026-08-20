from dataclasses import replace
from itertools import product
from types import SimpleNamespace

import pytest

import ropeway_skip_stop_optimization.optimization.ddd.trajectory_slot as trajectory_slot

from ropeway_skip_stop_optimization.optimization.ddd import (
    DddRecoveredSchedule,
    DddReferenceSolution,
    DddReferenceTrajectory,
    DddReferenceVisit,
    DddRouteDecision,
    DddTrajectoryBoundStatus,
    DddTrajectoryColumnPool,
    DddTrajectoryPricingCertificate,
    DddTrajectoryReducedCost,
    DddTrajectorySlotCandidate,
    DddTrajectoryWaitingDomain,
    ddd_trajectory_column,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanHorizonFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import (
    EanCabinTrajectory,
    EanMovementPlan,
)


def _certificate(
    *,
    rmp: float,
    reduced_costs: tuple[DddTrajectoryReducedCost, ...],
    row_complete: bool = False,
    pricing_domain: DddTrajectoryWaitingDomain = DddTrajectoryWaitingDomain.NO_WAIT,
    target_domain: DddTrajectoryWaitingDomain = DddTrajectoryWaitingDomain.NO_WAIT,
) -> DddTrajectoryPricingCertificate:
    return DddTrajectoryPricingCertificate(
        restricted_master_lp_value=rmp,
        expected_cabin_ids=tuple(range(len(reduced_costs))),
        reduced_costs=reduced_costs,
        instance_fingerprint="instance",
        objective_fingerprint="objective",
        master_fingerprint="master",
        dual_fingerprint="dual",
        row_pool_fingerprint="rows",
        pricing_waiting_domain=pricing_domain,
        target_waiting_domain=target_domain,
        row_separation_complete=row_complete,
    )


def test_exact_reduced_cost_correction_matches_exhaustive_independent_master() -> None:
    full_costs = ((3.0, 7.0), (2.0, 5.0, 11.0), (13.0, 17.0))
    exact_optimum = sum(min(costs) for costs in full_costs)

    for selected_indices in product(*(range(len(costs)) for costs in full_costs)):
        selected_costs = tuple(
            full_costs[cabin_id][index]
            for cabin_id, index in enumerate(selected_indices)
        )
        certificate = _certificate(
            rmp=sum(selected_costs),
            reduced_costs=tuple(
                DddTrajectoryReducedCost(
                    cabin_id=cabin_id,
                    minimum_reduced_cost=min(full_costs[cabin_id]) - selected_cost,
                    exact=True,
                )
                for cabin_id, selected_cost in enumerate(selected_costs)
            ),
        )

        assert certificate.certified_lower_bound == pytest.approx(exact_optimum)
        assert (
            certificate.bound_status
            is DddTrajectoryBoundStatus.TRAJECTORY_RELAXATION_BOUND
        )


def test_restricted_or_heuristic_pricing_never_claims_a_lower_bound() -> None:
    certificate = _certificate(
        rmp=100.0,
        reduced_costs=(
            DddTrajectoryReducedCost(0, -20.0, exact=True),
            DddTrajectoryReducedCost(1, -10.0, exact=False),
        ),
    )

    assert certificate.certified_lower_bound is None
    assert certificate.bound_status is DddTrajectoryBoundStatus.PRIMAL_POOL_ONLY


def test_inexact_pricing_solver_bounds_certify_safe_correction() -> None:
    certificate = _certificate(
        rmp=100.0,
        reduced_costs=(
            DddTrajectoryReducedCost(
                0,
                0.0,
                exact=False,
                certified_lower_bound=-20.0,
            ),
            DddTrajectoryReducedCost(
                1,
                0.0,
                exact=False,
                certified_lower_bound=5.0,
            ),
        ),
    )

    assert not certificate.pricing_complete
    assert certificate.pricing_bound_complete
    assert certificate.certified_lower_bound == pytest.approx(80.0)
    assert (
        certificate.bound_status is DddTrajectoryBoundStatus.TRAJECTORY_RELAXATION_BOUND
    )


def test_nonnegative_solver_bounds_certify_root_convergence_without_exact_pricing() -> None:
    certificate = _certificate(
        rmp=100.0,
        reduced_costs=(
            DddTrajectoryReducedCost(
                0,
                4.0,
                exact=False,
                certified_lower_bound=0.0,
            ),
            DddTrajectoryReducedCost(
                1,
                2.0,
                exact=False,
                certified_lower_bound=1.0,
            ),
        ),
        row_complete=True,
    )

    assert certificate.convergence_certified
    assert certificate.certified_lower_bound == pytest.approx(100.0)
    assert certificate.bound_status is DddTrajectoryBoundStatus.FULL_ROOT_LP_CERTIFIED


def test_no_wait_pricing_does_not_certify_waiting_enabled_target() -> None:
    certificate = _certificate(
        rmp=100.0,
        reduced_costs=(DddTrajectoryReducedCost(0, 0.0, exact=True),),
        row_complete=True,
        target_domain=DddTrajectoryWaitingDomain.BOUNDED_WAIT,
    )

    assert certificate.certified_lower_bound is None
    assert certificate.bound_status is DddTrajectoryBoundStatus.PRIMAL_POOL_ONLY


def test_complete_pricing_and_rows_certify_full_root_lp() -> None:
    certificate = _certificate(
        rmp=100.0,
        reduced_costs=(
            DddTrajectoryReducedCost(0, -5e-10, exact=True),
            DddTrajectoryReducedCost(1, 0.0, exact=True),
        ),
        row_complete=True,
    )

    assert certificate.certified_lower_bound == pytest.approx(99.9999999995)
    assert certificate.bound_status is DddTrajectoryBoundStatus.FULL_ROOT_LP_CERTIFIED


@pytest.mark.parametrize(
    "reduced_costs, message",
    (
        (
            (
                DddTrajectoryReducedCost(0, 0.0, exact=True),
                DddTrajectoryReducedCost(0, 0.0, exact=True),
            ),
            "duplicate",
        ),
        ((DddTrajectoryReducedCost(1, 0.0, exact=True),), "expected cabins"),
    ),
)
def test_pricing_certificate_rejects_invalid_cabin_coverage(
    reduced_costs: tuple[DddTrajectoryReducedCost, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        DddTrajectoryPricingCertificate(
            restricted_master_lp_value=1.0,
            expected_cabin_ids=(0,),
            reduced_costs=reduced_costs,
            instance_fingerprint="instance",
            objective_fingerprint="objective",
            master_fingerprint="master",
            dual_fingerprint="dual",
            row_pool_fingerprint="rows",
            pricing_waiting_domain=DddTrajectoryWaitingDomain.NO_WAIT,
            target_waiting_domain=DddTrajectoryWaitingDomain.NO_WAIT,
        )


def test_pricing_certificate_requires_master_and_dual_provenance() -> None:
    with pytest.raises(ValueError, match="fingerprints are required"):
        DddTrajectoryPricingCertificate(
            restricted_master_lp_value=1.0,
            expected_cabin_ids=(0,),
            reduced_costs=(DddTrajectoryReducedCost(0, 0.0, exact=True),),
            instance_fingerprint="instance",
            objective_fingerprint="objective",
            master_fingerprint="",
            dual_fingerprint="dual",
            row_pool_fingerprint="rows",
            pricing_waiting_domain=DddTrajectoryWaitingDomain.NO_WAIT,
            target_waiting_domain=DddTrajectoryWaitingDomain.NO_WAIT,
        )


def test_trajectory_column_id_is_deterministic_and_uses_exact_event_ticks() -> None:
    visit = DddReferenceVisit(
        cabin_id=3,
        visit_index=0,
        state_id="station_a",
        route_option_id="station_a::skip",
        decision=DddRouteDecision.SKIP,
        switch_time_seconds=1.0,
        next_switch_time_seconds=4.0,
        resource_occurrences=(),
    )
    trajectory = DddReferenceTrajectory(cabin_id=3, visits=(visit,))
    same = DddReferenceTrajectory(cabin_id=3, visits=(visit,))
    shifted = DddReferenceTrajectory(
        cabin_id=3,
        visits=(
            DddReferenceVisit(
                cabin_id=3,
                visit_index=0,
                state_id="station_a",
                route_option_id="station_a::skip",
                decision=DddRouteDecision.SKIP,
                switch_time_seconds=2.0,
                next_switch_time_seconds=5.0,
                resource_occurrences=(),
            ),
        ),
    )

    assert ddd_trajectory_column(trajectory).id == ddd_trajectory_column(same).id
    assert ddd_trajectory_column(trajectory).id != ddd_trajectory_column(shifted).id


def _pool_candidate(first_time: float) -> DddTrajectorySlotCandidate:
    trajectories = tuple(
        DddReferenceTrajectory(
            cabin_id=cabin_id,
            visits=(
                DddReferenceVisit(
                    cabin_id=cabin_id,
                    visit_index=0,
                    state_id="station_a",
                    route_option_id="station_a::skip",
                    decision=DddRouteDecision.SKIP,
                    switch_time_seconds=(first_time if cabin_id == 0 else 3.0),
                    next_switch_time_seconds=(
                        first_time + 2.0 if cabin_id == 0 else 5.0
                    ),
                    resource_occurrences=(),
                ),
            ),
        )
        for cabin_id in range(2)
    )
    return DddTrajectorySlotCandidate(
        schedules=tuple(
            DddRecoveredSchedule(
                cabin_id=cabin_id,
                route_option_ids=(),
                events=(),
                objective_value=0.0,
            )
            for cabin_id in range(2)
        ),
        reference_solution=DddReferenceSolution(trajectories=trajectories),
        movement_plan=EanMovementPlan(
            scenario_id="test",
            horizon_seconds=10.0,
            model_end_seconds=12.0,
            trajectories=tuple(
                EanCabinTrajectory(cabin_id=cabin_id, visits=())
                for cabin_id in range(2)
            ),
            horizon_formulation=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
        ),
    )


def test_column_pool_is_append_only_deduplicated_and_order_independent() -> None:
    first = _pool_candidate(1.0)
    second = _pool_candidate(2.0)
    forward = DddTrajectoryColumnPool()
    reverse = DddTrajectoryColumnPool()

    assert forward.add_candidate(first) == 2
    assert forward.add_candidate(first) == 0
    assert forward.add_candidate(second) == 1
    assert forward.column_count == 3
    assert forward.candidate_count == 2
    assert forward.has_recombination_choice

    reverse.add_candidate(second)
    reverse.add_candidate(first)
    assert reverse.fingerprint == forward.fingerprint
    assert tuple(item.id for item in reverse.columns) == tuple(
        item.id for item in forward.columns
    )


def test_column_identity_ignores_recovery_objective_metadata() -> None:
    candidate = _pool_candidate(1.0)
    rescored = replace(
        candidate,
        schedules=tuple(
            replace(schedule, objective_value=123.0) for schedule in candidate.schedules
        ),
    )
    pool = DddTrajectoryColumnPool()

    assert pool.add_candidate(candidate) == 2
    assert pool.add_candidate(rescored) == 0
    assert pool.column_count == 2


def test_column_pool_ids_are_scoped_to_the_physical_instance() -> None:
    candidate = _pool_candidate(1.0)
    other_instance = replace(
        candidate,
        movement_plan=replace(candidate.movement_plan, scenario_id="other"),
    )
    first = DddTrajectoryColumnPool()
    second = DddTrajectoryColumnPool()
    first.add_candidate(candidate)
    second.add_candidate(other_instance)

    assert {item.id for item in first.columns}.isdisjoint(
        item.id for item in second.columns
    )


def test_column_pool_caches_ride_generation_per_new_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = DddTrajectoryColumnPool()
    pool.add_candidate(_pool_candidate(1.0))
    calls: list[int] = []

    def fake_rides(**kwargs: object) -> tuple[object, ...]:
        del kwargs
        calls.append(1)
        return ()

    monkeypatch.setattr(trajectory_slot, "build_ean_fixed_movement_rides", fake_rides)
    passenger_build = object()
    trajectory_slot._build_trajectory_options(
        column_pool=pool,
        passenger_build=passenger_build,
        horizon_seconds=10.0,
    )
    trajectory_slot._build_trajectory_options(
        column_pool=pool,
        passenger_build=passenger_build,
        horizon_seconds=10.0,
    )
    assert len(calls) == 2

    pool.add_candidate(_pool_candidate(2.0))
    trajectory_slot._build_trajectory_options(
        column_pool=pool,
        passenger_build=passenger_build,
        horizon_seconds=10.0,
    )
    assert len(calls) == 3


def test_column_pool_validates_only_new_candidates_per_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = DddTrajectoryColumnPool()
    pool.add_candidate(_pool_candidate(1.0))
    reference_calls: list[int] = []
    movement_calls: list[int] = []

    monkeypatch.setattr(
        trajectory_slot,
        "validate_ddd_reference_solution",
        lambda *args, **kwargs: reference_calls.append(1),
    )

    class Validation:
        def raise_for_errors(self) -> None:
            movement_calls.append(1)

    monkeypatch.setattr(
        trajectory_slot,
        "validate_ean_movement_plan_against_artifact",
        lambda *args, **kwargs: Validation(),
    )
    problem = SimpleNamespace(
        movement_problem=SimpleNamespace(
            scenario_id="test",
            starts=tuple(SimpleNamespace(cabin_id=index) for index in range(2)),
        ),
        validate=lambda: None,
    )
    artifact = SimpleNamespace(scenario_id="test", validate=lambda: None)

    pool.validate_against(problem=problem, artifact=artifact, tolerance_seconds=1e-6)
    pool.validate_against(problem=problem, artifact=artifact, tolerance_seconds=1e-6)
    assert len(reference_calls) == 1
    assert len(movement_calls) == 1

    pool.add_candidate(_pool_candidate(2.0))
    pool.validate_against(problem=problem, artifact=artifact, tolerance_seconds=1e-6)
    assert len(reference_calls) == 2
    assert len(movement_calls) == 2
