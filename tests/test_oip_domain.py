from __future__ import annotations

import pytest
from dataclasses import replace

from ropeway_skip_stop_optimization.examples.three_station import (
    ThreeStationOptimizedInitialPlacementExample,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanFleetCardinalityMode,
    StationWaitingMode,
)
from ropeway_skip_stop_optimization.optimization.oip import (
    OipOperation,
    OipTimeGrid,
    prepare_oip_domain,
    shift_scenario_for_oip_warmup,
)


def test_oip_grid_rounds_physical_minima_up_and_deadlines_down() -> None:
    grid = OipTimeGrid(ticks_per_second=1_000)

    assert grid.lower_tick(1.0001) == 1_001
    assert grid.upper_tick(1.0009) == 1_000
    assert grid.seconds(1_001) == pytest.approx(1.001)


def test_oip_grid_keeps_signed_event_bounds_directional() -> None:
    grid = OipTimeGrid(ticks_per_second=1_000)

    assert grid.signed_lower_tick(-0.0001) == 0
    assert grid.signed_upper_tick(-0.0001) == -1


def test_oip_warmup_moves_only_the_time_origin() -> None:
    scenario = ThreeStationOptimizedInitialPlacementExample().build_scenario()
    shifted = shift_scenario_for_oip_warmup(scenario, 300)

    assert shifted.service_start_time < scenario.service_start_time
    assert shifted.service_end_time == scenario.service_end_time
    assert shifted.demands == scenario.demands


def test_all_stop_and_skip_stop_share_a_comparison_fingerprint() -> None:
    example = ThreeStationOptimizedInitialPlacementExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    config = replace(
        config,
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
            available_fleet_count=1,
            cardinality_mode=EanFleetCardinalityMode.EXACT,
        ),
    )
    artifact = builder.build(scenario, config)
    all_stop = prepare_oip_domain(
        scenario=scenario,
        artifact=artifact,
        operation=OipOperation.ALL_STOP,
        fixed_k=1,
    )
    skip_stop = prepare_oip_domain(
        scenario=scenario,
        artifact=artifact,
        operation=OipOperation.SKIP_STOP,
        fixed_k=1,
    )

    assert all_stop.fingerprint != skip_stop.fingerprint
    assert all_stop.comparison_fingerprint == skip_stop.comparison_fingerprint
    assert all(
        pair.headway_seconds * all_stop.grid.ticks_per_second
        == pytest.approx(round(pair.headway_seconds * all_stop.grid.ticks_per_second))
        for pair in all_stop.artifact.headway_pairs
    )


def test_oip_rejects_positive_waiting_without_a_finite_cap() -> None:
    example = ThreeStationOptimizedInitialPlacementExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    builder = example.build_ean_artifact_builder(scenario, config)
    artifact = builder.build(scenario, config)

    if all(
        item.waiting_mode is StationWaitingMode.NO_WAITING
        for item in artifact.config.station_configs
    ):
        pytest.skip("example itself has no positive-waiting contract")
    with pytest.raises(ValueError, match="positive finite cap"):
        prepare_oip_domain(scenario=scenario, artifact=artifact)
