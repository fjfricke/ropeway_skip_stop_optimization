from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import time
from enum import Enum

from ropeway_skip_stop_optimization.models import (
    DiscreteArc,
    DiscreteArcKind,
    DiscreteConstraint,
    DiscreteConstraintKind,
    DiscreteConstraintScope,
    DiscreteConstraintStrength,
    DiscreteDemand,
    DiscreteNode,
    DiscreteRoute,
    DiscreteScenario,
    PhysicalNode,
    Scenario,
    SpeedProfile,
    SpeedProfileKind,
    StationRouteKind,
    TrackSegment,
    TrackSegmentKind,
)
from ropeway_skip_stop_optimization.validation import validate_scenario


class RoundingPolicy(Enum):
    CEIL = "ceil"


@dataclass(frozen=True)
class DiscretizationConfig:
    delta_seconds: float = 0.5
    rounding_policy: RoundingPolicy = RoundingPolicy.CEIL

    def validate(self) -> None:
        if self.delta_seconds <= 0:
            raise ValueError("delta_seconds must be positive")
        if self.rounding_policy is not RoundingPolicy.CEIL:
            raise NotImplementedError("only CEIL rounding is implemented in discretizer v0")


@dataclass(frozen=True)
class _SegmentPosition:
    node_id: str
    segment_id: str
    position_m: float


def discretize_scenario(
    scenario: Scenario,
    config: DiscretizationConfig | None = None,
) -> DiscreteScenario:
    config = config or DiscretizationConfig()
    config.validate()
    if scenario.headway_design is not None:
        raise NotImplementedError(
            "the legacy physical-to-discrete model does not support derived "
            "A/B/C headway designs; use the EAN or DDD network model"
        )
    validate_scenario(scenario).raise_for_errors()

    physical_nodes_by_id = {node.id: node for node in scenario.physical_nodes}
    route_id_by_segment_id = _route_id_by_segment_id(scenario)
    segment_node_ids_by_id = {
        segment.id: _segment_node_ids(segment, duration_steps_for_segment(segment, config))
        for segment in scenario.track_segments
    }
    boarding_node_ids, alighting_node_ids = _service_platform_endpoint_node_ids(scenario, segment_node_ids_by_id)

    nodes: list[DiscreteNode] = [
        _discrete_physical_node(node, boarding_node_ids, alighting_node_ids)
        for node in scenario.physical_nodes
    ]
    arcs: list[DiscreteArc] = []

    for segment in scenario.track_segments:
        route_id = route_id_by_segment_id.get(segment.id)
        segment_node_ids = segment_node_ids_by_id[segment.id]
        duration_steps = len(segment_node_ids) - 1

        for index, node_id in enumerate(segment_node_ids[1:-1], start=1):
            nodes.append(
                DiscreteNode(
                    id=node_id,
                    source_segment_id=segment.id,
                    station_id=_segment_station_id(segment, physical_nodes_by_id),
                    resource_id=segment.resource_id,
                    position_m=position_m_at_step(segment, index, duration_steps, config),
                    allows_waiting=False,
                    allows_boarding=node_id in boarding_node_ids,
                    allows_alighting=node_id in alighting_node_ids,
                )
            )

        for step, (from_node_id, to_node_id) in enumerate(zip(segment_node_ids, segment_node_ids[1:]), start=1):
            arcs.append(
                DiscreteArc(
                    id=f"move::{segment.id}::{step}",
                    kind=DiscreteArcKind.MOVE,
                    from_node_id=from_node_id,
                    to_node_id=to_node_id,
                    source_segment_id=segment.id,
                    source_route_id=route_id,
                )
            )

    for node in scenario.physical_nodes:
        if node.allows_waiting:
            discrete_node_id = physical_node_id(node.id)
            arcs.append(
                DiscreteArc(
                    id=f"wait::{discrete_node_id}",
                    kind=DiscreteArcKind.WAIT,
                    from_node_id=discrete_node_id,
                    to_node_id=discrete_node_id,
                )
            )

    discrete = DiscreteScenario(
        id=f"{scenario.id}__dt_{_format_delta(config.delta_seconds)}",
        source_scenario_id=scenario.id,
        delta_seconds=config.delta_seconds,
        horizon_steps=_time_to_step(
            scenario.service_end_time,
            scenario.service_start_time,
            config.delta_seconds,
        ),
        nodes=tuple(nodes),
        arcs=tuple(arcs),
        routes=tuple(_discrete_routes(scenario, arcs)),
        constraints=tuple(_headway_constraints(nodes, scenario, scenario.operating.required_cabin_spacing_m)),
        stations=scenario.stations,
        station_routes=scenario.station_routes,
        cabins=(),
        cabin_initial_states=(),
        demands=tuple(
            DiscreteDemand(
                time_step=_time_to_step(demand.arrival_time, scenario.service_start_time, config.delta_seconds),
                origin=demand.origin,
                destination=demand.destination,
                count=demand.count,
            )
            for demand in scenario.demands
        ),
        cabin_capacity=scenario.operating.cabin_capacity,
        required_cabin_spacing_m=scenario.operating.required_cabin_spacing_m,
    )
    discrete.validate()
    return discrete


def travel_seconds_for_segment(segment: TrackSegment) -> float:
    if segment.speed_profile is None:
        raise ValueError(f"segment {segment.id!r} needs a speed_profile for discretization")
    return travel_seconds(segment.length_m, segment.speed_profile)


def travel_seconds(length_m: float, speed_profile: SpeedProfile) -> float:
    speed_profile.validate()
    if speed_profile.kind is SpeedProfileKind.CONSTANT:
        assert speed_profile.speed_m_per_s is not None
        return length_m / speed_profile.speed_m_per_s

    if speed_profile.kind is SpeedProfileKind.LINEAR:
        assert speed_profile.start_speed_m_per_s is not None
        assert speed_profile.end_speed_m_per_s is not None
        average_speed = (speed_profile.start_speed_m_per_s + speed_profile.end_speed_m_per_s) / 2
        return length_m / average_speed

    raise ValueError(f"unsupported speed profile kind: {speed_profile.kind}")


def duration_steps_for_segment(segment: TrackSegment, config: DiscretizationConfig) -> int:
    return _ceil_steps(travel_seconds_for_segment(segment), config.delta_seconds)


def position_m_at_step(
    segment: TrackSegment,
    step: int,
    duration_steps: int,
    config: DiscretizationConfig,
) -> float:
    if step < 0 or step > duration_steps:
        raise ValueError("step must be between 0 and duration_steps")
    if step == 0:
        return 0.0
    if step == duration_steps:
        return segment.length_m
    if segment.speed_profile is None:
        raise ValueError(f"segment {segment.id!r} needs a speed_profile for discretization")

    total_seconds = travel_seconds_for_segment(segment)
    elapsed_seconds = min(step * config.delta_seconds, total_seconds)
    position_m = _travel_distance_at_time(segment.length_m, segment.speed_profile, elapsed_seconds, total_seconds)
    return min(segment.length_m, max(0.0, position_m))


def physical_node_id(source_physical_node_id: str) -> str:
    return f"pn::{source_physical_node_id}"


def _discrete_physical_node(
    node: PhysicalNode,
    boarding_node_ids: set[str],
    alighting_node_ids: set[str],
) -> DiscreteNode:
    node_id = physical_node_id(node.id)
    return DiscreteNode(
        id=node_id,
        source_physical_node_id=node.id,
        station_id=node.station_id,
        allows_waiting=node.allows_waiting,
        allows_boarding=node_id in boarding_node_ids,
        allows_alighting=node_id in alighting_node_ids,
    )


def _segment_node_ids(segment: TrackSegment, duration_steps: int) -> tuple[str, ...]:
    if duration_steps <= 0:
        raise ValueError("duration_steps must be positive")
    return (
        physical_node_id(segment.from_node_id),
        *(f"seg::{segment.id}::{index}" for index in range(1, duration_steps)),
        physical_node_id(segment.to_node_id),
    )


def _route_id_by_segment_id(scenario: Scenario) -> dict[str, str]:
    route_id_by_segment_id: dict[str, str] = {}
    for route in scenario.station_routes:
        for segment_id in route.segment_ids:
            previous = route_id_by_segment_id.get(segment_id)
            if previous is not None:
                raise ValueError(
                    f"segment {segment_id!r} belongs to multiple station routes: "
                    f"{previous!r} and {route.id!r}"
                )
            route_id_by_segment_id[segment_id] = route.id
    return route_id_by_segment_id


def _service_platform_endpoint_node_ids(
    scenario: Scenario,
    segment_node_ids_by_id: dict[str, tuple[str, ...]],
) -> tuple[set[str], set[str]]:
    segment_by_id = {segment.id: segment for segment in scenario.track_segments}
    boarding_node_ids: set[str] = set()
    alighting_node_ids: set[str] = set()
    for route in scenario.station_routes:
        if route.kind is not StationRouteKind.SERVICE:
            continue
        station_segment_ids = tuple(
            segment_id
            for segment_id in route.segment_ids
            if segment_by_id[segment_id].kind is TrackSegmentKind.STATION
        )
        if not station_segment_ids:
            raise ValueError(f"service route {route.id!r} needs at least one station/platform segment")
        platform_node_ids = _route_node_ids(station_segment_ids, segment_node_ids_by_id)
        if route.allows_alighting:
            alighting_node_ids.add(platform_node_ids[0])
        if route.allows_boarding:
            boarding_node_ids.add(platform_node_ids[-1])
    return boarding_node_ids, alighting_node_ids


def _route_node_ids(
    segment_ids: tuple[str, ...],
    segment_node_ids_by_id: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    node_ids: list[str] = []
    for segment_id in segment_ids:
        segment_node_ids = segment_node_ids_by_id[segment_id]
        if not node_ids:
            node_ids.extend(segment_node_ids)
            continue
        if node_ids[-1] != segment_node_ids[0]:
            raise ValueError(f"station route is disconnected before segment {segment_id!r}")
        node_ids.extend(segment_node_ids[1:])
    if not node_ids:
        raise ValueError("station route needs at least one node")
    return tuple(node_ids)


def _segment_station_id(
    segment: TrackSegment,
    physical_nodes_by_id: dict[str, PhysicalNode],
) -> str | None:
    from_station = physical_nodes_by_id[segment.from_node_id].station_id
    to_station = physical_nodes_by_id[segment.to_node_id].station_id
    if from_station == to_station:
        return from_station
    return from_station or to_station


def _discrete_routes(scenario: Scenario, arcs: list[DiscreteArc]) -> list[DiscreteRoute]:
    move_arcs_by_segment_id: dict[str, list[DiscreteArc]] = {}
    for arc in arcs:
        if arc.kind is DiscreteArcKind.MOVE:
            assert arc.source_segment_id is not None
            move_arcs_by_segment_id.setdefault(arc.source_segment_id, []).append(arc)

    for segment_arcs in move_arcs_by_segment_id.values():
        segment_arcs.sort(key=lambda arc: int(arc.id.rsplit("::", 1)[1]))

    return [
        DiscreteRoute(
            id=route.id,
            source_route_id=route.id,
            arc_ids=tuple(
                arc.id
                for segment_id in route.segment_ids
                for arc in move_arcs_by_segment_id[segment_id]
            ),
        )
        for route in scenario.station_routes
    ]


def _headway_constraints(
    nodes: list[DiscreteNode],
    scenario: Scenario,
    required_cabin_spacing_m: float,
) -> list[DiscreteConstraint]:
    segment_by_id = {segment.id: segment for segment in scenario.track_segments}
    route_id_by_segment_id = _route_id_by_segment_id(scenario)
    successors_by_segment_id = _successors_by_segment_id(scenario.track_segments)
    positions_by_segment_id = _positions_by_segment_id(nodes, scenario)
    constraints: list[DiscreteConstraint] = []
    seen_pairs: set[tuple[str, str]] = set()

    def add_constraint(
        node_a_id: str,
        node_b_id: str,
        *,
        scope: DiscreteConstraintScope,
        source_segment_ids: tuple[str, ...],
    ) -> None:
        if node_a_id == node_b_id:
            return
        pair = tuple(sorted((node_a_id, node_b_id)))
        if pair in seen_pairs:
            return
        seen_pairs.add(pair)
        unique_segment_ids = tuple(dict.fromkeys(source_segment_ids))
        resource_ids = {
            segment_by_id[segment_id].resource_id
            for segment_id in unique_segment_ids
            if segment_by_id[segment_id].resource_id is not None
        }
        route_ids = tuple(
            route_id
            for route_id in (route_id_by_segment_id.get(segment_id) for segment_id in unique_segment_ids)
            if route_id is not None
        )
        constraints.append(
            DiscreteConstraint(
                id=f"constraint::headway::{scope.value}::{pair[0]}::{pair[1]}",
                kind=DiscreteConstraintKind.HEADWAY,
                scope=scope,
                strength=DiscreteConstraintStrength.HARD,
                node_ids=pair,
                resource_id=next(iter(resource_ids)) if len(resource_ids) == 1 else None,
                source_segment_ids=unique_segment_ids,
                source_route_ids=route_ids,
            )
        )

    for segment_positions in positions_by_segment_id.values():
        for left_index, left_position in enumerate(segment_positions):
            for right_position in segment_positions[left_index + 1:]:
                if right_position.position_m - left_position.position_m >= required_cabin_spacing_m:
                    break
                add_constraint(
                    left_position.node_id,
                    right_position.node_id,
                    scope=DiscreteConstraintScope.SAME_SEGMENT,
                    source_segment_ids=(left_position.segment_id,),
                )

    def walk_successors(
        source_position: _SegmentPosition,
        successor_segment_id: str,
        accumulated_distance_m: float,
        visited_segment_ids: frozenset[str],
    ) -> None:
        if successor_segment_id in visited_segment_ids:
            return

        successor = segment_by_id[successor_segment_id]
        successor_positions = positions_by_segment_id.get(successor_segment_id, ())
        for target_position in successor_positions:
            distance_m = accumulated_distance_m + target_position.position_m
            if distance_m >= required_cabin_spacing_m:
                break
            add_constraint(
                source_position.node_id,
                target_position.node_id,
                scope=DiscreteConstraintScope.CROSS_SEGMENT,
                source_segment_ids=(source_position.segment_id, target_position.segment_id),
            )

        next_accumulated_distance_m = accumulated_distance_m + successor.length_m
        if next_accumulated_distance_m >= required_cabin_spacing_m:
            return

        next_visited = visited_segment_ids | frozenset((successor_segment_id,))
        for next_successor_segment_id in successors_by_segment_id.get(successor_segment_id, ()):
            walk_successors(source_position, next_successor_segment_id, next_accumulated_distance_m, next_visited)

    for segment_id, segment_positions in positions_by_segment_id.items():
        segment = segment_by_id[segment_id]
        for source_position in segment_positions:
            remaining_distance_m = segment.length_m - source_position.position_m
            if remaining_distance_m >= required_cabin_spacing_m:
                continue
            for successor_segment_id in successors_by_segment_id.get(segment_id, ()):
                walk_successors(
                    source_position,
                    successor_segment_id,
                    remaining_distance_m,
                    frozenset((segment_id,)),
                )

    return constraints


def _positions_by_segment_id(
    nodes: list[DiscreteNode],
    scenario: Scenario,
) -> dict[str, tuple[_SegmentPosition, ...]]:
    positions_by_segment_id: dict[str, list[_SegmentPosition]] = {}

    for node in nodes:
        if node.source_segment_id is not None and node.position_m is not None:
            positions_by_segment_id.setdefault(node.source_segment_id, []).append(
                _SegmentPosition(
                    node_id=node.id,
                    segment_id=node.source_segment_id,
                    position_m=node.position_m,
                )
            )

    for segment in scenario.track_segments:
        positions_by_segment_id.setdefault(segment.id, []).extend(
            (
                _SegmentPosition(
                    node_id=physical_node_id(segment.from_node_id),
                    segment_id=segment.id,
                    position_m=0.0,
                ),
                _SegmentPosition(
                    node_id=physical_node_id(segment.to_node_id),
                    segment_id=segment.id,
                    position_m=segment.length_m,
                ),
            )
        )

    return {
        segment_id: tuple(sorted(segment_positions, key=lambda position: position.position_m))
        for segment_id, segment_positions in positions_by_segment_id.items()
    }


def _successors_by_segment_id(segments: tuple[TrackSegment, ...]) -> dict[str, tuple[str, ...]]:
    successors: dict[str, tuple[str, ...]] = {}
    segments_by_from_node_id: dict[str, list[TrackSegment]] = {}
    for segment in segments:
        segments_by_from_node_id.setdefault(segment.from_node_id, []).append(segment)

    for segment in segments:
        successors[segment.id] = tuple(
            successor.id
            for successor in segments_by_from_node_id.get(segment.to_node_id, ())
        )
    return successors


def _time_to_step(value: time, start: time, delta_seconds: float) -> int:
    raw_seconds = _seconds_since_midnight(value) - _seconds_since_midnight(start)
    raw_step = raw_seconds / delta_seconds
    step = round(raw_step)
    if not math.isclose(raw_step, step, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"time {value.isoformat()} is not representable with delta_seconds={delta_seconds}")
    return step


def _seconds_since_midnight(value: time) -> float:
    return value.hour * 3600 + value.minute * 60 + value.second + value.microsecond / 1_000_000


def _ceil_steps(seconds: float, delta_seconds: float) -> int:
    return max(1, math.ceil(seconds / delta_seconds - 1e-12))


def _travel_distance_at_time(
    length_m: float,
    speed_profile: SpeedProfile,
    elapsed_seconds: float,
    total_seconds: float,
) -> float:
    if speed_profile.kind is SpeedProfileKind.CONSTANT:
        assert speed_profile.speed_m_per_s is not None
        return speed_profile.speed_m_per_s * elapsed_seconds

    if speed_profile.kind is SpeedProfileKind.LINEAR:
        assert speed_profile.start_speed_m_per_s is not None
        assert speed_profile.end_speed_m_per_s is not None
        acceleration_m_per_s2 = (
            speed_profile.end_speed_m_per_s - speed_profile.start_speed_m_per_s
        ) / total_seconds
        return speed_profile.start_speed_m_per_s * elapsed_seconds + 0.5 * acceleration_m_per_s2 * elapsed_seconds**2

    raise ValueError(f"unsupported speed profile kind: {speed_profile.kind}")


def _format_delta(delta_seconds: float) -> str:
    return str(delta_seconds).replace(".", "p")
