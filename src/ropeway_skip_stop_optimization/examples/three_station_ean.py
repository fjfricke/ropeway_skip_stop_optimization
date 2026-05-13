from __future__ import annotations

from datetime import datetime

from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.models import (
    PhysicalNodeKind,
    Scenario,
    StationKind,
    StationRoute,
    StationRouteKind,
    TrackSegment,
    TrackSegmentKind,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanConfig,
    StationEanConfig,
    StationWaitingMode,
)


def build_three_station_ean_config(
    scenario: Scenario | None = None,
    tail_seconds: float = 0.0,
) -> EanConfig:
    """Build the v0 EAN config.

    The current baseline treats the passenger horizon as the physical model
    boundary, so example exports keep tail_seconds at 0.0. Nonzero tails are
    left as an explicit caller override until horizon-tail semantics are needed.
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


def build_three_station_ean_ring_switch_order(
    scenario: Scenario | None = None,
) -> tuple[str, ...]:
    scenario = scenario or build_three_station_scenario()
    scenario.validate()

    switch_cycle = (
        "M_entry_lr",
        "R_entry_lr",
        "M_entry_rl",
        "L_entry_rl",
    )
    _validate_switch_cycle_is_physical_ring(scenario, switch_cycle)
    return switch_cycle


def _service_duration_seconds(scenario: Scenario) -> float:
    start = datetime.combine(datetime.min.date(), scenario.service_start_time)
    end = datetime.combine(datetime.min.date(), scenario.service_end_time)
    return (end - start).total_seconds()


def _validate_switch_cycle_is_physical_ring(scenario: Scenario, switch_cycle: tuple[str, ...]) -> None:
    if not switch_cycle:
        raise ValueError("three-station EAN switch cycle must not be empty")

    nodes_by_id = {node.id: node for node in scenario.physical_nodes}
    segments_by_id = {segment.id: segment for segment in scenario.track_segments}

    for index, switch_id in enumerate(switch_cycle):
        next_switch_id = switch_cycle[(index + 1) % len(switch_cycle)]
        switch_node = nodes_by_id.get(switch_id)
        next_switch_node = nodes_by_id.get(next_switch_id)
        if switch_node is None:
            raise ValueError(f"three-station EAN switch cycle references unknown switch {switch_id!r}")
        if next_switch_node is None:
            raise ValueError(f"three-station EAN switch cycle references unknown switch {next_switch_id!r}")
        if switch_node.kind is not PhysicalNodeKind.ENTRY_SWITCH:
            raise ValueError(f"three-station EAN switch {switch_id!r} is not an entry switch")
        if next_switch_node.kind is not PhysicalNodeKind.ENTRY_SWITCH:
            raise ValueError(f"three-station EAN switch {next_switch_id!r} is not an entry switch")

        service_route = _single_service_route_from_switch(scenario.station_routes, segments_by_id, switch_id)
        exit_segment = segments_by_id[service_route.segment_ids[-1]]
        exit_node = nodes_by_id[exit_segment.to_node_id]
        if exit_node.kind is not PhysicalNodeKind.EXIT_SWITCH:
            raise ValueError(
                f"three-station EAN service route {service_route.id!r} does not end at an exit switch"
            )

        rope_segments = [
            segment
            for segment in scenario.track_segments
            if segment.kind is TrackSegmentKind.ROPE
            and segment.from_node_id == exit_node.id
            and segment.to_node_id == next_switch_id
        ]
        if len(rope_segments) != 1:
            raise ValueError(
                "three-station EAN switch cycle is not physically connected: "
                f"{switch_id!r} exits at {exit_node.id!r}, expected one rope segment to {next_switch_id!r}"
            )


def _single_service_route_from_switch(
    station_routes: tuple[StationRoute, ...],
    segments_by_id: dict[str, TrackSegment],
    switch_id: str,
) -> StationRoute:
    routes = [
        route
        for route in station_routes
        if route.kind is StationRouteKind.SERVICE
        and segments_by_id[route.segment_ids[0]].from_node_id == switch_id
    ]
    if len(routes) != 1:
        raise ValueError(
            f"three-station EAN expected exactly one service route from switch {switch_id!r}, found {len(routes)}"
        )
    return routes[0]
