from __future__ import annotations

from collections.abc import Iterable

from ropeway_skip_stop_optimization.models import (
    PhysicalNodeKind,
    Scenario,
    SpeedProfile,
    SpeedProfileKind,
    StationKind,
    StationRoute,
    StationRouteKind,
    TrackSegment,
)
from ropeway_skip_stop_optimization.validation.result import ValidationIssue, ValidationSeverity


def validate_scenario_rules(scenario: Scenario) -> tuple[ValidationIssue, ...]:
    return (
        *_validate_service_stations_have_service_routes(scenario),
        *_validate_terminal_routes(scenario),
        *_validate_skip_routes_are_service_alternatives(scenario),
        *_validate_segment_speed_continuity(scenario),
    )


def _validate_service_stations_have_service_routes(scenario: Scenario) -> Iterable[ValidationIssue]:
    routes_by_station = _routes_by_station(scenario)

    for station in scenario.stations:
        if station.kind not in {StationKind.SERVICE, StationKind.TERMINAL}:
            continue

        routes = routes_by_station.get(station.id, ())
        if not any(route.kind is StationRouteKind.SERVICE for route in routes):
            yield _issue(
                "passenger_station_without_service_route",
                f"passenger station {station.id!r} needs at least one service route",
                "station",
                station.id,
            )


def _validate_terminal_routes(scenario: Scenario) -> Iterable[ValidationIssue]:
    routes_by_station = _routes_by_station(scenario)
    segments_by_id = {segment.id: segment for segment in scenario.track_segments}
    nodes_by_id = {node.id: node for node in scenario.physical_nodes}

    for station in scenario.stations:
        if station.kind is not StationKind.TERMINAL:
            continue

        routes = routes_by_station.get(station.id, ())
        service_routes = [route for route in routes if route.kind is StationRouteKind.SERVICE]
        skip_routes = [route for route in routes if route.kind is StationRouteKind.SKIP]

        if skip_routes:
            yield _issue(
                "terminal_has_skip_route",
                f"terminal station {station.id!r} must not define skip routes",
                "station",
                station.id,
            )

        if len(service_routes) != 1:
            yield _issue(
                "terminal_service_route_count",
                f"terminal station {station.id!r} must define exactly one service turnaround route",
                "station",
                station.id,
            )
            continue

        route = service_routes[0]
        endpoints = _route_endpoints(route, segments_by_id)
        if endpoints is None:
            continue
        start_node = nodes_by_id.get(endpoints[0])
        end_node = nodes_by_id.get(endpoints[1])

        if start_node is None or end_node is None:
            continue
        if start_node.station_id != station.id or end_node.station_id != station.id:
            yield _issue(
                "terminal_route_crosses_station_boundary",
                f"terminal route {route.id!r} must start and end inside station {station.id!r}",
                "route",
                route.id,
            )
        if start_node.kind is not PhysicalNodeKind.ENTRY_SWITCH:
            yield _issue(
                "terminal_route_start_not_entry",
                f"terminal route {route.id!r} must start at an entry switch",
                "route",
                route.id,
            )
        if end_node.kind is not PhysicalNodeKind.EXIT_SWITCH:
            yield _issue(
                "terminal_route_end_not_exit",
                f"terminal route {route.id!r} must end at an exit switch",
                "route",
                route.id,
            )


def _validate_skip_routes_are_service_alternatives(scenario: Scenario) -> Iterable[ValidationIssue]:
    routes_by_station = _routes_by_station(scenario)
    segments_by_id = {segment.id: segment for segment in scenario.track_segments}

    for station in scenario.stations:
        routes = routes_by_station.get(station.id, ())
        service_endpoints = {
            endpoints
            for route in routes
            if route.kind is StationRouteKind.SERVICE
            for endpoints in [_route_endpoints(route, segments_by_id)]
            if endpoints is not None
        }

        for route in routes:
            if route.kind is not StationRouteKind.SKIP:
                continue
            endpoints = _route_endpoints(route, segments_by_id)
            if endpoints is None:
                continue
            if endpoints not in service_endpoints:
                yield _issue(
                    "skip_without_matching_service_route",
                    f"skip route {route.id!r} must have a service route with the same entry and exit nodes",
                    "route",
                    route.id,
                )


def _validate_segment_speed_continuity(scenario: Scenario) -> Iterable[ValidationIssue]:
    incoming_by_node_id: dict[str, list[TrackSegment]] = {}
    outgoing_by_node_id: dict[str, list[TrackSegment]] = {}
    for segment in scenario.track_segments:
        incoming_by_node_id.setdefault(segment.to_node_id, []).append(segment)
        outgoing_by_node_id.setdefault(segment.from_node_id, []).append(segment)

    for node in scenario.physical_nodes:
        incoming_segments = incoming_by_node_id.get(node.id, ())
        outgoing_segments = outgoing_by_node_id.get(node.id, ())
        for incoming_segment in incoming_segments:
            incoming_speed = _segment_end_speed(incoming_segment)
            if incoming_speed is None:
                continue
            for outgoing_segment in outgoing_segments:
                outgoing_speed = _segment_start_speed(outgoing_segment)
                if outgoing_speed is None:
                    continue
                if _speeds_match(incoming_speed, outgoing_speed):
                    continue
                yield _issue(
                    "node_speed_discontinuity",
                    (
                        f"node {node.id!r} has a sudden speed change from "
                        f"{incoming_speed:g} m/s at the end of segment {incoming_segment.id!r} "
                        f"to {outgoing_speed:g} m/s at the start of segment {outgoing_segment.id!r}; "
                        "model braking or acceleration as an explicit segment"
                    ),
                    "node",
                    node.id,
                )


def _segment_start_speed(segment: TrackSegment) -> float | None:
    if segment.speed_profile is None:
        return None
    return _profile_start_speed(segment.speed_profile)


def _segment_end_speed(segment: TrackSegment) -> float | None:
    if segment.speed_profile is None:
        return None
    return _profile_end_speed(segment.speed_profile)


def _profile_start_speed(profile: SpeedProfile) -> float:
    if profile.kind is SpeedProfileKind.CONSTANT:
        assert profile.speed_m_per_s is not None
        return profile.speed_m_per_s
    assert profile.start_speed_m_per_s is not None
    return profile.start_speed_m_per_s


def _profile_end_speed(profile: SpeedProfile) -> float:
    if profile.kind is SpeedProfileKind.CONSTANT:
        assert profile.speed_m_per_s is not None
        return profile.speed_m_per_s
    assert profile.end_speed_m_per_s is not None
    return profile.end_speed_m_per_s


def _speeds_match(left: float, right: float) -> bool:
    return abs(left - right) <= 1e-9


def _routes_by_station(scenario: Scenario) -> dict[str, tuple[StationRoute, ...]]:
    grouped: dict[str, list[StationRoute]] = {}
    for route in scenario.station_routes:
        grouped.setdefault(route.station_id, []).append(route)
    return {station_id: tuple(routes) for station_id, routes in grouped.items()}


def _route_endpoints(route: StationRoute, segments_by_id: dict[str, TrackSegment]) -> tuple[str, str] | None:
    first = segments_by_id.get(route.segment_ids[0])
    last = segments_by_id.get(route.segment_ids[-1])
    if first is None or last is None:
        return None
    return first.from_node_id, last.to_node_id


def _issue(code: str, message: str, entity_type: str, entity_id: str) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity=ValidationSeverity.ERROR,
        message=message,
        entity_type=entity_type,
        entity_id=entity_id,
    )
