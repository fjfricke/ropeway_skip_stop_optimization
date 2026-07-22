from __future__ import annotations

from datetime import datetime

from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.models import (
    Scenario,
    StationKind,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanCirculationPatternDefinition,
    EanConfig,
    StationEanConfig,
    StationWaitingMode,
)


def build_three_station_ean_config(
    scenario: Scenario | None = None,
    tail_seconds: float = 0.0,
) -> EanConfig:
    """Build the v0 EAN config.

    Examples keep tail_seconds at 0.0 by default. Callers may supply a
    nonzero certification tail to extend physical movement and headway
    certification without extending passenger service.
    """
    scenario = scenario or build_three_station_scenario()
    scenario.validate()

    config = EanConfig(
        horizon_seconds=_service_duration_seconds(scenario),
        tail_seconds=tail_seconds,
        cabin_capacity=scenario.operating.cabin_capacity,
        station_configs=tuple(
            StationEanConfig(
                station_id=station.id,
                waiting_mode=(
                    StationWaitingMode.END_OF_PLATFORM_WAIT
                    if station.kind is StationKind.SERVICE
                    else StationWaitingMode.NO_WAITING
                ),
            )
            for station in scenario.stations
            if station.kind in {StationKind.SERVICE, StationKind.TERMINAL}
        ),
    )
    config.validate()
    return config


def build_three_station_ean_pattern_definition() -> EanCirculationPatternDefinition:
    return EanCirculationPatternDefinition(
        id="selected_pattern",
        state_node_ids=(
            "M_entry_lr",
            "R_entry_lr",
            "M_entry_rl",
            "L_entry_rl",
        ),
    )


def _service_duration_seconds(scenario: Scenario) -> float:
    start = datetime.combine(datetime.min.date(), scenario.service_start_time)
    end = datetime.combine(datetime.min.date(), scenario.service_end_time)
    return (end - start).total_seconds()
