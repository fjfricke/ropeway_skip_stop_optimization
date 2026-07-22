from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.examples.circular_skip_stop import (
    FiveStationOptimizedInitialPlacementNoSkipNoWaitExample,
    FiveStationOptimizedInitialPlacementSkipNoWaitExample,
    build_five_station_circle_cw_ean_ring_switch_order,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    AllPairsHeadwayPairBuilder,
    EanFleetConfig,
    EanFleetMode,
    EanPeriodicRouteCapacityBoundBuilder,
    EanPeriodicRouteMipStartSeedBuilder,
    EanRouteDecision,
    EanHorizonFormulation,
    network_ean_builder_for_cycle,
    SparseHeadwayPairBuilder,
    StationWaitingMode,
)
from ropeway_skip_stop_optimization.optimization.ean.validation import (
    validate_ean_movement_plan_against_artifact,
)


def test_periodic_route_finds_the_all_skip_rope_certificate() -> None:
    example = FiveStationOptimizedInitialPlacementSkipNoWaitExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    artifact = network_ean_builder_for_cycle(
        state_ids=build_five_station_circle_cw_ean_ring_switch_order(scenario),
        fleet_config=EanFleetConfig(
            mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
            available_fleet_count=1,
        ),
    ).build(scenario, config)

    bound = EanPeriodicRouteCapacityBoundBuilder().build(artifact)

    assert bound.fleet_lower_bound == 242
    assert bound.cycle_seconds == 170.0
    assert bound.bottleneck_headway_seconds == 0.7
    assert {decision.value for decision in bound.decisions_by_switch_id.values()} == {
        "skip"
    }


def test_periodic_route_rejects_cycle_shorter_than_headway() -> None:
    artifact = _artifact(
        FiveStationOptimizedInitialPlacementSkipNoWaitExample(),
        sparse=True,
    )
    artifact = replace(
        artifact,
        headway_checkpoints=tuple(
            replace(checkpoint, headway_seconds=10_000.0)
            for checkpoint in artifact.headway_checkpoints
        ),
    )

    with pytest.raises(ValueError, match="no homogeneous periodic route"):
        EanPeriodicRouteCapacityBoundBuilder().build(artifact)
    assert EanPeriodicRouteCapacityBoundBuilder().build_optional(artifact) is None


def test_periodic_route_validates_cycle_sum_and_artifact_origin() -> None:
    skip_artifact = _artifact(FiveStationOptimizedInitialPlacementSkipNoWaitExample())
    no_skip_artifact = _artifact(
        FiveStationOptimizedInitialPlacementNoSkipNoWaitExample()
    )
    bound = EanPeriodicRouteCapacityBoundBuilder().build(skip_artifact)

    with pytest.raises(ValueError, match="cycle disagrees"):
        replace(bound, cycle_seconds=bound.cycle_seconds + 1.0).validate()
    with pytest.raises(ValueError, match="does not match"):
        bound.validate_for_artifact(no_skip_artifact)
    with pytest.raises(ValueError, match="does not match"):
        EanPeriodicRouteMipStartSeedBuilder().build(
            no_skip_artifact,
            EanHorizonFormulation.EXACT_TIME_ACTIVATION,
            route_bound=bound,
        )


def test_periodic_route_respects_disabled_skip_and_seed_validates() -> None:
    artifact = _artifact(
        FiveStationOptimizedInitialPlacementNoSkipNoWaitExample(),
        fleet_count=8,
    )
    bound = EanPeriodicRouteCapacityBoundBuilder().build(artifact)
    assert set(bound.decisions_by_switch_id.values()) == {EanRouteDecision.STOP}

    seed = EanPeriodicRouteMipStartSeedBuilder().build(
        artifact,
        EanHorizonFormulation.EXACT_TIME_ACTIVATION,
        route_bound=bound,
    )
    validate_ean_movement_plan_against_artifact(
        artifact,
        seed.movement_plan,
        tolerance_seconds=1e-5,
    ).raise_for_errors()


def test_periodic_route_can_select_a_mixed_stop_skip_cycle_deterministically() -> None:
    artifact = _artifact(
        FiveStationOptimizedInitialPlacementSkipNoWaitExample(), sparse=True
    )
    first_switch = artifact.circulation_state_ids[0]
    timings = tuple(
        replace(timing, skip_allowed=False)
        if timing.switch_id == first_switch
        else timing
        for timing in artifact.timings
    )
    checkpoints = tuple(
        replace(
            checkpoint,
            headway_seconds=(
                1.0
                if checkpoint.switch_id == first_switch
                or checkpoint.applies_to_skip
                else 100.0
            ),
        )
        for checkpoint in artifact.headway_checkpoints
    )
    artifact = replace(
        artifact,
        timings=timings,
        headway_checkpoints=checkpoints,
    )
    builder = EanPeriodicRouteCapacityBoundBuilder()

    first = builder.build(artifact)
    second = builder.build(artifact)

    assert first == second
    assert first.decisions_by_switch_id[first_switch] is EanRouteDecision.STOP
    assert set(first.decisions_by_switch_id.values()) == {
        EanRouteDecision.STOP,
        EanRouteDecision.SKIP,
    }


def test_periodic_no_wait_seed_is_valid_with_end_waiting_semantics() -> None:
    example = FiveStationOptimizedInitialPlacementNoSkipNoWaitExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    config = replace(
        config,
        station_configs=tuple(
            replace(
                station_config,
                waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT,
            )
            for station_config in config.station_configs
        ),
    )
    artifact = network_ean_builder_for_cycle(
        state_ids=build_five_station_circle_cw_ean_ring_switch_order(scenario),
        fleet_config=EanFleetConfig(
            mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
            available_fleet_count=8,
        ),
    ).build(scenario, config)
    bound = EanPeriodicRouteCapacityBoundBuilder().build(artifact)
    seed = EanPeriodicRouteMipStartSeedBuilder().build(
        artifact,
        EanHorizonFormulation.EXACT_TIME_ACTIVATION,
        route_bound=bound,
    )

    validate_ean_movement_plan_against_artifact(
        artifact,
        seed.movement_plan,
        tolerance_seconds=1e-5,
    ).raise_for_errors()


def _artifact(example, *, fleet_count: int = 1, sparse: bool = False):
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    return network_ean_builder_for_cycle(
        state_ids=build_five_station_circle_cw_ean_ring_switch_order(scenario),
        fleet_config=EanFleetConfig(
            mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
            available_fleet_count=fleet_count,
        ),
        headway_pair_builder=(
            SparseHeadwayPairBuilder()
            if sparse
            else AllPairsHeadwayPairBuilder()
        ),
    ).build(scenario, config)
