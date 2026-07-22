from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.models import (
    PhysicalNode,
    PhysicalNodeKind,
    Scenario,
    StationRoute,
    StationRouteKind,
    TrackSegment,
    TrackSegmentKind,
)


@dataclass(frozen=True)
class RingStationTopology:
    switch_id: str
    next_switch_id: str
    station_id: str
    exit_switch_id: str
    service_route_id: str
    service_segment_ids: tuple[str, ...]
    skip_route_id: str | None
    skip_segment_ids: tuple[str, ...]
    rope_segment_id: str


@dataclass(frozen=True)
class RingPhysicalTopology:
    switch_cycle: tuple[str, ...]
    stations: tuple[RingStationTopology, ...]


@dataclass(frozen=True)
class PhysicalRingTopologyBuilder:
    """Resolve the physical paths used by a directed EAN ring."""

    def build(
        self,
        scenario: Scenario,
        switch_cycle: tuple[str, ...],
    ) -> RingPhysicalTopology:
        scenario.validate()
        _validate_switch_cycle(switch_cycle)

        nodes_by_id = {node.id: node for node in scenario.physical_nodes}
        segments_by_id = {
            segment.id: segment for segment in scenario.track_segments
        }
        _validate_switch_nodes(nodes_by_id, switch_cycle)

        stations: list[RingStationTopology] = []
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
            service_segments = tuple(
                segments_by_id[segment_id]
                for segment_id in service_route.segment_ids
            )
            service_exit_node_id = service_segments[-1].to_node_id
            exit_node = nodes_by_id.get(service_exit_node_id)
            if (
                exit_node is None
                or exit_node.kind is not PhysicalNodeKind.EXIT_SWITCH
            ):
                raise ValueError(
                    f"service route {service_route.id!r} must end at an exit switch"
                )

            skip_segment_ids: tuple[str, ...] = ()
            if skip_route is not None:
                skip_segments = tuple(
                    segments_by_id[segment_id]
                    for segment_id in skip_route.segment_ids
                )
                if skip_segments[-1].to_node_id != service_exit_node_id:
                    raise ValueError(
                        f"skip route {skip_route.id!r} must end at same exit switch as "
                        f"service route {service_route.id!r}"
                    )
                skip_segment_ids = skip_route.segment_ids

            rope_segment = _rope_segment_to_next_switch(
                scenario.track_segments,
                from_node_id=service_exit_node_id,
                to_node_id=next_switch_id,
            )
            stations.append(
                RingStationTopology(
                    switch_id=switch_id,
                    next_switch_id=next_switch_id,
                    station_id=service_route.station_id,
                    exit_switch_id=service_exit_node_id,
                    service_route_id=service_route.id,
                    service_segment_ids=service_route.segment_ids,
                    skip_route_id=(
                        skip_route.id if skip_route is not None else None
                    ),
                    skip_segment_ids=skip_segment_ids,
                    rope_segment_id=rope_segment.id,
                )
            )

        return RingPhysicalTopology(
            switch_cycle=switch_cycle,
            stations=tuple(stations),
        )


def _single_route_from_switch(
    routes: tuple[StationRoute, ...],
    segments_by_id: dict[str, TrackSegment],
    switch_id: str,
    route_kind: StationRouteKind,
) -> StationRoute:
    matched_routes = _routes_from_switch(
        routes,
        segments_by_id,
        switch_id,
        route_kind,
    )
    if len(matched_routes) != 1:
        raise ValueError(
            f"expected exactly one {route_kind.value} route from switch "
            f"{switch_id!r}, found {len(matched_routes)}"
        )
    return matched_routes[0]


def _optional_route_from_switch(
    routes: tuple[StationRoute, ...],
    segments_by_id: dict[str, TrackSegment],
    switch_id: str,
    route_kind: StationRouteKind,
) -> StationRoute | None:
    matched_routes = _routes_from_switch(
        routes,
        segments_by_id,
        switch_id,
        route_kind,
    )
    if len(matched_routes) > 1:
        raise ValueError(
            f"expected at most one {route_kind.value} route from switch "
            f"{switch_id!r}, found {len(matched_routes)}"
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


def _rope_segment_to_next_switch(
    segments: tuple[TrackSegment, ...],
    from_node_id: str,
    to_node_id: str,
) -> TrackSegment:
    rope_segments = tuple(
        segment
        for segment in segments
        if segment.kind is TrackSegmentKind.ROPE
        and segment.from_node_id == from_node_id
        and segment.to_node_id == to_node_id
    )
    if len(rope_segments) != 1:
        raise ValueError(
            f"expected exactly one rope segment from {from_node_id!r} to next "
            f"switch {to_node_id!r}, found {len(rope_segments)}"
        )
    return rope_segments[0]


def _validate_switch_cycle(switch_cycle: tuple[str, ...]) -> None:
    if not switch_cycle:
        raise ValueError("switch_cycle must not be empty")
    seen: set[str] = set()
    duplicates: set[str] = set()
    for switch_id in switch_cycle:
        if not switch_id:
            raise ValueError("switch_cycle ids must be nonempty")
        if switch_id in seen:
            duplicates.add(switch_id)
        seen.add(switch_id)
    if duplicates:
        raise ValueError(f"duplicate switch_cycle ids: {duplicates}")


def _validate_switch_nodes(
    nodes_by_id: dict[str, PhysicalNode],
    switch_cycle: tuple[str, ...],
) -> None:
    for switch_id in switch_cycle:
        node = nodes_by_id.get(switch_id)
        if node is None:
            raise ValueError(
                f"switch_cycle references unknown physical node {switch_id!r}"
            )
        if node.kind is not PhysicalNodeKind.ENTRY_SWITCH:
            raise ValueError(
                f"switch_cycle node {switch_id!r} is not an entry switch"
            )
