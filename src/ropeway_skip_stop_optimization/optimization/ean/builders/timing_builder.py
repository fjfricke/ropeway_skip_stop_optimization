from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ropeway_skip_stop_optimization.mapping.physical_to_discrete import travel_seconds_for_segment
from ropeway_skip_stop_optimization.models import (
    PhysicalNodeKind,
    PhysicalNode,
    Scenario,
    StationRoute,
    StationRouteKind,
    TrackSegment,
    TrackSegmentKind,
)
from ropeway_skip_stop_optimization.optimization.ean.models import SkipStopTiming


class SkipStopTimingBuilder(ABC):
    @abstractmethod
    def build(
        self,
        scenario: Scenario,
        switch_cycle: tuple[str, ...],
    ) -> tuple[SkipStopTiming, ...]:
        """Derive skip/stop timing data from a scenario interpretation."""


@dataclass(frozen=True)
class PhysicalSkipStopTimingBuilder(SkipStopTimingBuilder):
    def build(
        self,
        scenario: Scenario,
        switch_cycle: tuple[str, ...],
    ) -> tuple[SkipStopTiming, ...]:
        scenario.validate()
        _validate_switch_cycle(switch_cycle)

        nodes_by_id = {node.id: node for node in scenario.physical_nodes}
        segments_by_id = {segment.id: segment for segment in scenario.track_segments}
        timings: list[SkipStopTiming] = []
        _validate_switch_nodes(nodes_by_id, switch_cycle)

        for index, switch_id in enumerate(switch_cycle):
            next_switch_id = switch_cycle[(index + 1) % len(switch_cycle)]
            service_route = _single_route_from_switch(
                routes=scenario.station_routes,
                segments_by_id=segments_by_id,
                switch_id=switch_id,
                route_kind=StationRouteKind.SERVICE,
            )
            skip_route = _optional_route_from_switch(
                routes=scenario.station_routes,
                segments_by_id=segments_by_id,
                switch_id=switch_id,
                route_kind=StationRouteKind.SKIP,
            )

            service_segments = tuple(segments_by_id[segment_id] for segment_id in service_route.segment_ids)
            service_exit_node_id = service_segments[-1].to_node_id
            exit_node = nodes_by_id.get(service_exit_node_id)
            if exit_node is None or exit_node.kind is not PhysicalNodeKind.EXIT_SWITCH:
                raise ValueError(f"service route {service_route.id!r} must end at an exit switch")

            station_segment_indices = [
                segment_index
                for segment_index, segment in enumerate(service_segments)
                if segment.kind is TrackSegmentKind.STATION
            ]
            if not station_segment_indices:
                raise ValueError(f"service route {service_route.id!r} needs at least one station segment")
            if station_segment_indices != list(range(station_segment_indices[0], station_segment_indices[-1] + 1)):
                raise ValueError(f"service route {service_route.id!r} station segments must be contiguous")

            first_station_segment_index = station_segment_indices[0]
            last_station_segment_index = station_segment_indices[-1]
            entry_to_platform_entry_seconds = _travel_seconds(service_segments[:first_station_segment_index])
            min_platform_entry_to_platform_exit_seconds = _travel_seconds(
                service_segments[first_station_segment_index : last_station_segment_index + 1]
            )
            platform_exit_to_exit_switch_seconds = _travel_seconds(
                service_segments[last_station_segment_index + 1 :]
            )

            skip_allowed = skip_route is not None
            service_entry_to_exit_seconds = _travel_seconds(service_segments)
            if skip_route is None:
                skip_entry_to_exit_switch_seconds = service_entry_to_exit_seconds
            else:
                skip_segments = tuple(segments_by_id[segment_id] for segment_id in skip_route.segment_ids)
                skip_exit_node_id = skip_segments[-1].to_node_id
                if skip_exit_node_id != service_exit_node_id:
                    raise ValueError(
                        f"skip route {skip_route.id!r} must end at same exit switch as service route "
                        f"{service_route.id!r}"
                    )
                skip_entry_to_exit_switch_seconds = _travel_seconds(skip_segments)

            rope_to_next_switch_seconds = _rope_seconds_to_next_switch(
                scenario.track_segments,
                from_node_id=service_exit_node_id,
                to_node_id=next_switch_id,
            )

            timing = SkipStopTiming(
                switch_id=switch_id,
                station_id=service_route.station_id,
                entry_to_platform_entry_seconds=entry_to_platform_entry_seconds,
                min_platform_entry_to_platform_exit_seconds=min_platform_entry_to_platform_exit_seconds,
                platform_exit_to_exit_switch_seconds=platform_exit_to_exit_switch_seconds,
                skip_entry_to_exit_switch_seconds=skip_entry_to_exit_switch_seconds,
                rope_to_next_switch_seconds=rope_to_next_switch_seconds,
                skip_allowed=skip_allowed,
            )
            timing.validate()
            timings.append(timing)

        return tuple(timings)


def _single_route_from_switch(
    routes: tuple[StationRoute, ...],
    segments_by_id: dict[str, TrackSegment],
    switch_id: str,
    route_kind: StationRouteKind,
) -> StationRoute:
    matched_routes = _routes_from_switch(routes, segments_by_id, switch_id, route_kind)
    if len(matched_routes) != 1:
        raise ValueError(
            f"expected exactly one {route_kind.value} route from switch {switch_id!r}, found {len(matched_routes)}"
        )
    return matched_routes[0]


def _optional_route_from_switch(
    routes: tuple[StationRoute, ...],
    segments_by_id: dict[str, TrackSegment],
    switch_id: str,
    route_kind: StationRouteKind,
) -> StationRoute | None:
    matched_routes = _routes_from_switch(routes, segments_by_id, switch_id, route_kind)
    if len(matched_routes) > 1:
        raise ValueError(
            f"expected at most one {route_kind.value} route from switch {switch_id!r}, found {len(matched_routes)}"
        )
    return matched_routes[0] if matched_routes else None


def _routes_from_switch(
    routes: tuple[StationRoute, ...],
    segments_by_id: dict[str, TrackSegment],
    switch_id: str,
    route_kind: StationRouteKind,
) -> tuple[StationRoute, ...]:
    return tuple(
        route
        for route in routes
        if route.kind is route_kind
        and route.segment_ids
        and segments_by_id[route.segment_ids[0]].from_node_id == switch_id
    )


def _rope_seconds_to_next_switch(
    segments: tuple[TrackSegment, ...],
    from_node_id: str,
    to_node_id: str,
) -> float:
    rope_segments = tuple(
        segment
        for segment in segments
        if segment.kind is TrackSegmentKind.ROPE
        and segment.from_node_id == from_node_id
        and segment.to_node_id == to_node_id
    )
    if len(rope_segments) != 1:
        raise ValueError(
            f"expected exactly one rope segment from {from_node_id!r} to next switch {to_node_id!r}, "
            f"found {len(rope_segments)}"
        )
    return travel_seconds_for_segment(rope_segments[0])


def _travel_seconds(segments: tuple[TrackSegment, ...]) -> float:
    if not segments:
        return 0.0
    return sum(travel_seconds_for_segment(segment) for segment in segments)


def _validate_switch_cycle(switch_cycle: tuple[str, ...]) -> None:
    if not switch_cycle:
        raise ValueError("switch_cycle must not be empty")
    seen = set()
    duplicates = set()
    for switch_id in switch_cycle:
        if not switch_id:
            raise ValueError("switch_cycle ids must be nonempty")
        if switch_id in seen:
            duplicates.add(switch_id)
        seen.add(switch_id)
    if duplicates:
        raise ValueError(f"duplicate switch_cycle ids: {duplicates}")


def _validate_switch_nodes(nodes_by_id: dict[str, PhysicalNode], switch_cycle: tuple[str, ...]) -> None:
    for switch_id in switch_cycle:
        node = nodes_by_id.get(switch_id)
        if node is None:
            raise ValueError(f"switch_cycle references unknown physical node {switch_id!r}")
        if node.kind is not PhysicalNodeKind.ENTRY_SWITCH:
            raise ValueError(f"switch_cycle node {switch_id!r} is not an entry switch")
