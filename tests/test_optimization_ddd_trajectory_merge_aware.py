from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.optimization.ddd import (
    DddFixedStart,
    DddMovementCore,
    DddMovementProblem,
    DddMovementState,
    DddReferenceResourceOccurrence,
    DddReferenceTrajectory,
    DddReferenceVisit,
    DddResource,
    DddResourceUsage,
    DddRouteDecision,
    DddRouteOption,
    DddTrajectoryCompatibleBatchStatus,
    DddTrajectoryCompatibilityBatchOptimizer,
    DddTrajectoryMasterRow,
    DddTrajectoryMasterRowKind,
    DddTrajectoryMasterRowPool,
    DddTrajectoryMasterRowScope,
    DddTrajectoryMergeDomainBuilder,
    DddTrajectoryPricedCandidate,
    DddTrajectoryResourceWindow,
    DddTrajectoryResourceWindowCoefficientOracle,
    build_ddd_trajectory_resource_window_row,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick,
)


def _usage(resource_id: str, *, offset: float = 1.0) -> DddResourceUsage:
    return DddResourceUsage(
        resource_id=resource_id,
        leader_clear_offset_seconds=offset,
        follower_enter_offset_seconds=offset,
    )


def _merge_core() -> DddMovementCore:
    return DddMovementCore(
        scenario_id="merge-aware-test",
        passenger_service_end_seconds=20.0,
        operational_end_seconds=20.0,
        states=(DddMovementState("merge"), DddMovementState("rope")),
        route_options=(
            DddRouteOption(
                id="service",
                from_state_id="merge",
                to_state_id="rope",
                station_id="station",
                decision=DddRouteDecision.STOP,
                duration_seconds=3.0,
                platform_entry_offset_seconds=0.5,
                platform_exit_offset_seconds=1.5,
                exit_switch_offset_seconds=2.0,
                resource_usages=(
                    _usage("platform", offset=1.0),
                    _usage("merge-resource", offset=2.0),
                ),
            ),
            DddRouteOption(
                id="skip",
                from_state_id="merge",
                to_state_id="rope",
                station_id="station",
                decision=DddRouteDecision.SKIP,
                duration_seconds=3.0,
                platform_entry_offset_seconds=None,
                platform_exit_offset_seconds=None,
                exit_switch_offset_seconds=2.0,
                resource_usages=(
                    _usage("skip-lane", offset=1.0),
                    _usage("merge-resource", offset=2.0),
                ),
            ),
            DddRouteOption(
                id="rope",
                from_state_id="rope",
                to_state_id="merge",
                station_id="station",
                decision=DddRouteDecision.SKIP,
                duration_seconds=4.0,
                platform_entry_offset_seconds=None,
                platform_exit_offset_seconds=None,
                exit_switch_offset_seconds=3.0,
                resource_usages=(_usage("rope-resource", offset=1.0),),
            ),
        ),
        resources=tuple(
            DddResource(resource_id, 1.0)
            for resource_id in (
                "merge-resource",
                "platform",
                "rope-resource",
                "skip-lane",
            )
        ),
    )


def test_merge_domain_derives_reconvergence_and_fifo_provenance() -> None:
    domain = DddTrajectoryMergeDomainBuilder().build(_merge_core())

    assert len(domain.families) == 1
    family = domain.families[0]
    assert family.state_id == "merge"
    assert family.target_state_id == "rope"
    assert family.service_only_resource_ids == ("platform",)
    assert family.skip_only_resource_ids == ("skip-lane",)
    assert family.shared_merge_resource_ids == ("merge-resource",)
    assert family.outgoing_common_resource_ids == ("rope-resource",)
    assert family.protected_resource_ids == (
        "merge-resource",
        "rope-resource",
    )
    assert family.provenance.service_fifo
    assert family.provenance.skip_fifo
    assert len(domain.fingerprint) == 64


def test_merge_occurrence_includes_branch_and_immediate_outgoing_resources() -> None:
    domain = DddTrajectoryMergeDomainBuilder().build(_merge_core())
    trajectory = DddReferenceTrajectory(
        cabin_id=0,
        visits=(
            DddReferenceVisit(
                cabin_id=0,
                visit_index=0,
                state_id="merge",
                route_option_id="service",
                decision=DddRouteDecision.STOP,
                switch_time_seconds=0.0,
                next_switch_time_seconds=3.0,
                resource_occurrences=(
                    DddReferenceResourceOccurrence(
                        resource_id="merge-resource",
                        cabin_id=0,
                        visit_index=0,
                        leader_clear_time_seconds=2.0,
                        follower_enter_time_seconds=2.0,
                    ),
                ),
            ),
            DddReferenceVisit(
                cabin_id=0,
                visit_index=1,
                state_id="rope",
                route_option_id="rope",
                decision=DddRouteDecision.SKIP,
                switch_time_seconds=3.0,
                next_switch_time_seconds=7.0,
                resource_occurrences=(
                    DddReferenceResourceOccurrence(
                        resource_id="rope-resource",
                        cabin_id=0,
                        visit_index=1,
                        leader_clear_time_seconds=4.0,
                        follower_enter_time_seconds=4.0,
                    ),
                ),
            ),
        ),
    )

    occurrences = domain.occurrences(trajectory)

    assert len(occurrences) == 1
    assert occurrences[0].protected_resource_ids == (
        "merge-resource",
        "rope-resource",
    )


def test_merge_domain_rejects_non_reconverging_stop_skip_routes() -> None:
    core = _merge_core()
    skip = next(item for item in core.route_options if item.id == "skip")
    changed = replace(skip, to_state_id="merge")
    broken = replace(
        core,
        route_options=tuple(
            changed if item.id == "skip" else item for item in core.route_options
        ),
    )

    with pytest.raises(NotImplementedError, match="non-reconverging"):
        DddTrajectoryMergeDomainBuilder().build(broken)


def _simple_problem() -> DddMovementProblem:
    core = DddMovementCore(
        scenario_id="batch-test",
        passenger_service_end_seconds=10.0,
        operational_end_seconds=10.0,
        states=(DddMovementState("s"),),
        route_options=(
            DddRouteOption(
                id="loop",
                from_state_id="s",
                to_state_id="s",
                station_id="station",
                decision=DddRouteDecision.SKIP,
                duration_seconds=11.0,
                platform_entry_offset_seconds=None,
                platform_exit_offset_seconds=None,
                exit_switch_offset_seconds=10.0,
                resource_usages=(),
            ),
        ),
        resources=(DddResource("resource", 1.0),),
    )
    return DddMovementProblem(
        scenario_id=core.scenario_id,
        passenger_service_end_seconds=core.passenger_service_end_seconds,
        operational_end_seconds=core.operational_end_seconds,
        states=core.states,
        starts=tuple(DddFixedStart(cabin_id, "s", 0.0, 1) for cabin_id in range(3)),
        route_options=core.route_options,
        resources=core.resources,
    )


def _trajectory(
    cabin_id: int,
    *,
    enter_seconds: float,
    clear_seconds: float | None = None,
) -> DddReferenceTrajectory:
    clear_seconds = enter_seconds if clear_seconds is None else clear_seconds
    occurrence = DddReferenceResourceOccurrence(
        resource_id="resource",
        cabin_id=cabin_id,
        visit_index=0,
        leader_clear_time_seconds=clear_seconds,
        follower_enter_time_seconds=enter_seconds,
    )
    return DddReferenceTrajectory(
        cabin_id=cabin_id,
        visits=(
            DddReferenceVisit(
                cabin_id=cabin_id,
                visit_index=0,
                state_id="s",
                route_option_id="loop",
                decision=DddRouteDecision.SKIP,
                switch_time_seconds=0.0,
                next_switch_time_seconds=11.0,
                resource_occurrences=(occurrence,),
            ),
        ),
    )


def test_resource_window_row_has_universal_future_column_oracle() -> None:
    problem = _simple_problem()
    first = _trajectory(0, enter_seconds=1.0)
    second = _trajectory(1, enter_seconds=1.5)
    window = DddTrajectoryResourceWindow(
        "resource",
        ddd_seconds_to_tick(1.5),
    )
    row = build_ddd_trajectory_resource_window_row(
        window=window,
        movement_problem=problem,
        trajectory_by_option_id={"first": first},
    )
    oracle = DddTrajectoryResourceWindowCoefficientOracle(
        movement_problem=problem,
        windows=(window,),
    )

    assert row.scope is DddTrajectoryMasterRowScope.UNIVERSAL
    assert row.master_row.kind is DddTrajectoryMasterRowKind.RESOURCE_WINDOW
    assert row.coefficient_by_option_id == {"first": 1}
    assert oracle.coefficient(row.id, second) == 1.0


def test_master_row_pool_rejects_same_id_with_different_payload() -> None:
    pool = DddTrajectoryMasterRowPool()
    row = DddTrajectoryMasterRow(
        id="row",
        kind=DddTrajectoryMasterRowKind.MERGE_WINDOW,
        scope=DddTrajectoryMasterRowScope.UNIVERSAL,
        right_hand_side=1.0,
        coefficients=(("a", 1.0),),
    )

    assert pool.add(row)
    assert not pool.add(row)
    assert pool.certifying_rows == (row,)
    with pytest.raises(ValueError, match="inconsistent"):
        pool.add(replace(row, right_hand_side=2.0))


def test_compatible_batch_prefers_jointly_usable_negative_columns() -> None:
    problem = _simple_problem()
    conflicting = _trajectory(0, enter_seconds=0.0)
    also_conflicting = _trajectory(1, enter_seconds=0.5)
    compatible = _trajectory(1, enter_seconds=2.0)
    third = _trajectory(2, enter_seconds=4.0)
    candidates = (
        DddTrajectoryPricedCandidate("a", 0, -10.0, conflicting),
        DddTrajectoryPricedCandidate("b", 1, -9.0, also_conflicting),
        DddTrajectoryPricedCandidate("c", 1, -8.0, compatible),
        DddTrajectoryPricedCandidate("d", 2, -2.0, third),
    )

    result = DddTrajectoryCompatibilityBatchOptimizer().solve(
        movement_problem=problem,
        candidates=candidates,
    )

    assert result.status is DddTrajectoryCompatibleBatchStatus.OPTIMAL
    assert result.selected_option_ids == ("a", "c", "d")
    assert result.selected_cabin_ids == (0, 1, 2)
    assert result.selected_reduced_cost == pytest.approx(-20.0)
    assert result.conflict_pair_count == 1
    assert result.same_cabin_pair_count == 1


def test_compatible_batch_is_deterministic_under_permuted_input() -> None:
    problem = _simple_problem()
    candidates = (
        DddTrajectoryPricedCandidate("a", 0, -1.0, _trajectory(0, enter_seconds=0.0)),
        DddTrajectoryPricedCandidate("b", 1, -1.0, _trajectory(1, enter_seconds=2.0)),
    )
    optimizer = DddTrajectoryCompatibilityBatchOptimizer()

    first = optimizer.solve(movement_problem=problem, candidates=candidates)
    second = optimizer.solve(
        movement_problem=problem,
        candidates=tuple(reversed(candidates)),
    )

    assert first.selected_option_ids == second.selected_option_ids == ("a", "b")
    assert first.selected_reduced_cost == pytest.approx(second.selected_reduced_cost)
