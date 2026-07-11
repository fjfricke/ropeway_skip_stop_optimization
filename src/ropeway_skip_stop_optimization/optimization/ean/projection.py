from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ropeway_skip_stop_optimization.models import (
    Scenario,
    StationRoute,
    StationRouteKind,
    TrackSegment,
    TrackSegmentKind,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.models import SkipStopTiming
from ropeway_skip_stop_optimization.optimization.ean.models import StationEanConfig
from ropeway_skip_stop_optimization.optimization.ean.models import StationWaitingMode
from ropeway_skip_stop_optimization.optimization.ean.plan import (
    EanCabinVisit,
    EanMovementPlan,
    EanRouteDecision,
)


class EanPhysicalEventKind(Enum):
    ENTER_SWITCH = "enter_switch"
    ENTER_PLATFORM = "enter_platform"
    ENTER_WAIT = "enter_wait"
    EXIT_WAIT = "exit_wait"
    EXIT_PLATFORM = "exit_platform"
    EXIT_SWITCH = "exit_switch"
    REACH_NEXT_SWITCH = "reach_next_switch"


@dataclass(frozen=True)
class EanPhysicalEvent:
    time_seconds: float
    cabin_id: int
    visit_index: int
    event_kind: EanPhysicalEventKind
    switch_id: str
    station_id: str
    physical_node_id: str
    source_segment_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EanPhysicalReplay:
    scenario_id: str
    horizon_seconds: float
    model_end_seconds: float
    events: tuple[EanPhysicalEvent, ...]


def project_ean_movement_plan_to_physical_replay(
    scenario: Scenario,
    artifact: EanBuildArtifact,
    plan: EanMovementPlan,
    include_events_after_horizon: bool = True,
) -> EanPhysicalReplay:
    scenario.validate()
    artifact.validate()
    plan.validate()

    route_by_switch_id = _projection_routes_by_switch_id(scenario, artifact.switch_cycle)
    station_config_by_id = {station_config.station_id: station_config for station_config in artifact.config.station_configs}
    timing_by_switch_id = {timing.switch_id: timing for timing in artifact.timings}
    event_limit_seconds = artifact.config.model_end_seconds if include_events_after_horizon else artifact.config.horizon_seconds

    events: list[EanPhysicalEvent] = []
    for trajectory in plan.trajectories:
        if trajectory.visits:
            events.extend(
                _initial_context_events(
                    first_visit=trajectory.visits[0],
                    switch_cycle=artifact.switch_cycle,
                    timing_by_switch_id=timing_by_switch_id,
                    route_by_switch_id=route_by_switch_id,
                    station_config_by_id=station_config_by_id,
                )
            )
        for visit in trajectory.visits:
            route = route_by_switch_id[visit.switch_id]
            waiting_mode = station_config_by_id[visit.station_id].waiting_mode
            events.extend(_events_for_visit(visit, route, waiting_mode))

    filtered_events = _with_boundary_context_events(events, event_limit_seconds)
    return EanPhysicalReplay(
        scenario_id=scenario.id,
        horizon_seconds=artifact.config.horizon_seconds,
        model_end_seconds=artifact.config.model_end_seconds,
        events=tuple(sorted(filtered_events, key=_event_sort_key)),
    )


def _with_boundary_context_events(
    events: list[EanPhysicalEvent],
    event_limit_seconds: float,
) -> tuple[EanPhysicalEvent, ...]:
    """Keep visible events plus one post-limit interpolation target per cabin."""
    filtered_events = [event for event in events if event.time_seconds <= event_limit_seconds]
    first_after_limit_by_cabin_id: dict[int, EanPhysicalEvent] = {}
    for event in sorted(events, key=_event_sort_key):
        if event.time_seconds <= event_limit_seconds:
            continue
        first_after_limit_by_cabin_id.setdefault(event.cabin_id, event)
    return tuple((*filtered_events, *first_after_limit_by_cabin_id.values()))


def _initial_context_events(
    first_visit: EanCabinVisit,
    switch_cycle: tuple[str, ...],
    timing_by_switch_id: dict[str, SkipStopTiming],
    route_by_switch_id: dict[str, _ProjectionRoute],
    station_config_by_id: dict[str, StationEanConfig],
) -> tuple[EanPhysicalEvent, ...]:
    if first_visit.switch_time_seconds <= 0:
        return ()

    previous_switch_id = _previous_switch_id(first_visit.switch_id, switch_cycle)
    timing = timing_by_switch_id[previous_switch_id]
    previous_switch_time_seconds = first_visit.switch_time_seconds - _all_stop_switch_to_next_seconds(timing)
    previous_platform_entry_time_seconds = (
        previous_switch_time_seconds + timing.entry_to_platform_entry_seconds
    )
    previous_platform_exit_time_seconds = (
        previous_platform_entry_time_seconds + timing.min_platform_entry_to_platform_exit_seconds
    )
    previous_exit_switch_time_seconds = (
        previous_platform_exit_time_seconds + timing.platform_exit_to_exit_switch_seconds
    )
    context_visit = EanCabinVisit(
        cabin_id=first_visit.cabin_id,
        visit_index=first_visit.visit_index - 1,
        switch_id=previous_switch_id,
        station_id=timing.station_id,
        decision=EanRouteDecision.STOP,
        switch_time_seconds=previous_switch_time_seconds,
        platform_entry_time_seconds=previous_platform_entry_time_seconds,
        platform_exit_time_seconds=previous_platform_exit_time_seconds,
        exit_switch_time_seconds=previous_exit_switch_time_seconds,
        next_switch_time_seconds=first_visit.switch_time_seconds,
        wait_seconds=0.0,
    )
    route = route_by_switch_id[previous_switch_id]
    waiting_mode = station_config_by_id[timing.station_id].waiting_mode
    return _events_for_visit(context_visit, route, waiting_mode)


def _previous_switch_id(switch_id: str, switch_cycle: tuple[str, ...]) -> str:
    index_by_switch_id = {cycle_switch_id: index for index, cycle_switch_id in enumerate(switch_cycle)}
    index = index_by_switch_id.get(switch_id)
    if index is None:
        raise ValueError(f"switch {switch_id!r} is outside switch_cycle")
    return switch_cycle[(index - 1) % len(switch_cycle)]


def _all_stop_switch_to_next_seconds(timing: SkipStopTiming) -> float:
    return (
        timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
        + timing.platform_exit_to_exit_switch_seconds
        + timing.rope_to_next_switch_seconds
    )


@dataclass(frozen=True)
class _ProjectionRoute:
    switch_id: str
    station_id: str
    service_segment_ids: tuple[str, ...]
    skip_segment_ids: tuple[str, ...] | None
    platform_entry_node_id: str
    platform_exit_node_id: str
    exit_switch_node_id: str
    rope_segment_id: str
    next_switch_node_id: str
    service_to_platform_segment_ids: tuple[str, ...]
    station_segment_ids: tuple[str, ...]
    platform_to_exit_segment_ids: tuple[str, ...]


def _events_for_visit(
    visit: EanCabinVisit,
    route: _ProjectionRoute,
    waiting_mode: StationWaitingMode,
) -> tuple[EanPhysicalEvent, ...]:
    if visit.wait_seconds > 0 and waiting_mode is StationWaitingMode.STATION_FIFO_BUFFER:
        raise NotImplementedError(
            "STATION_FIFO_BUFFER wait projection needs station FIFO position traces"
        )

    events = [
        EanPhysicalEvent(
            time_seconds=visit.switch_time_seconds,
            cabin_id=visit.cabin_id,
            visit_index=visit.visit_index,
            event_kind=EanPhysicalEventKind.ENTER_SWITCH,
            switch_id=visit.switch_id,
            station_id=visit.station_id,
            physical_node_id=visit.switch_id,
        )
    ]

    if visit.decision is EanRouteDecision.STOP:
        if visit.platform_entry_time_seconds is None or visit.platform_exit_time_seconds is None:
            raise ValueError("STOP projection needs platform event times")
        minimum_platform_exit_time = visit.platform_exit_time_seconds - visit.wait_seconds
        events.append(
            EanPhysicalEvent(
                time_seconds=visit.platform_entry_time_seconds,
                cabin_id=visit.cabin_id,
                visit_index=visit.visit_index,
                event_kind=EanPhysicalEventKind.ENTER_PLATFORM,
                switch_id=visit.switch_id,
                station_id=visit.station_id,
                physical_node_id=route.platform_entry_node_id,
                source_segment_ids=route.service_to_platform_segment_ids,
            )
        )
        if visit.wait_seconds > 0:
            events.append(
                EanPhysicalEvent(
                    time_seconds=minimum_platform_exit_time,
                    cabin_id=visit.cabin_id,
                    visit_index=visit.visit_index,
                    event_kind=EanPhysicalEventKind.ENTER_WAIT,
                    switch_id=visit.switch_id,
                    station_id=visit.station_id,
                    physical_node_id=route.platform_exit_node_id,
                    source_segment_ids=route.station_segment_ids,
                )
            )
            events.append(
                EanPhysicalEvent(
                    time_seconds=visit.platform_exit_time_seconds,
                    cabin_id=visit.cabin_id,
                    visit_index=visit.visit_index,
                    event_kind=EanPhysicalEventKind.EXIT_WAIT,
                    switch_id=visit.switch_id,
                    station_id=visit.station_id,
                    physical_node_id=route.platform_exit_node_id,
                )
            )
        events.append(
            EanPhysicalEvent(
                time_seconds=visit.platform_exit_time_seconds,
                cabin_id=visit.cabin_id,
                visit_index=visit.visit_index,
                event_kind=EanPhysicalEventKind.EXIT_PLATFORM,
                switch_id=visit.switch_id,
                station_id=visit.station_id,
                physical_node_id=route.platform_exit_node_id,
                source_segment_ids=() if visit.wait_seconds > 0 else route.station_segment_ids,
            )
        )
        events.append(
            EanPhysicalEvent(
                time_seconds=visit.exit_switch_time_seconds,
                cabin_id=visit.cabin_id,
                visit_index=visit.visit_index,
                event_kind=EanPhysicalEventKind.EXIT_SWITCH,
                switch_id=visit.switch_id,
                station_id=visit.station_id,
                physical_node_id=route.exit_switch_node_id,
                source_segment_ids=route.platform_to_exit_segment_ids,
            )
        )
    elif visit.decision is EanRouteDecision.SKIP:
        if route.skip_segment_ids is None:
            raise ValueError(f"SKIP projection needs a physical skip route for switch {visit.switch_id!r}")
        events.append(
            EanPhysicalEvent(
                time_seconds=visit.exit_switch_time_seconds,
                cabin_id=visit.cabin_id,
                visit_index=visit.visit_index,
                event_kind=EanPhysicalEventKind.EXIT_SWITCH,
                switch_id=visit.switch_id,
                station_id=visit.station_id,
                physical_node_id=route.exit_switch_node_id,
                source_segment_ids=route.skip_segment_ids,
            )
        )

    events.append(
        EanPhysicalEvent(
            time_seconds=visit.next_switch_time_seconds,
            cabin_id=visit.cabin_id,
            visit_index=visit.visit_index,
            event_kind=EanPhysicalEventKind.REACH_NEXT_SWITCH,
            switch_id=visit.switch_id,
            station_id=visit.station_id,
            physical_node_id=route.next_switch_node_id,
            source_segment_ids=(route.rope_segment_id,),
        )
    )
    return tuple(events)


def _projection_routes_by_switch_id(
    scenario: Scenario,
    switch_cycle: tuple[str, ...],
) -> dict[str, _ProjectionRoute]:
    segments_by_id = {segment.id: segment for segment in scenario.track_segments}
    routes: dict[str, _ProjectionRoute] = {}
    for index, switch_id in enumerate(switch_cycle):
        next_switch_id = switch_cycle[(index + 1) % len(switch_cycle)]
        service_route = _single_route_from_switch(scenario.station_routes, segments_by_id, switch_id, StationRouteKind.SERVICE)
        skip_route = _optional_route_from_switch(scenario.station_routes, segments_by_id, switch_id, StationRouteKind.SKIP)
        service_segments = tuple(segments_by_id[segment_id] for segment_id in service_route.segment_ids)
        station_segment_indices = tuple(
            segment_index
            for segment_index, segment in enumerate(service_segments)
            if segment.kind is TrackSegmentKind.STATION
        )
        if not station_segment_indices:
            raise ValueError(f"service route {service_route.id!r} needs a station segment for projection")
        first_station_index = station_segment_indices[0]
        last_station_index = station_segment_indices[-1]
        exit_switch_node_id = service_segments[-1].to_node_id
        rope_segment = _single_rope_segment(scenario.track_segments, exit_switch_node_id, next_switch_id)
        routes[switch_id] = _ProjectionRoute(
            switch_id=switch_id,
            station_id=service_route.station_id,
            service_segment_ids=service_route.segment_ids,
            skip_segment_ids=skip_route.segment_ids if skip_route is not None else None,
            platform_entry_node_id=service_segments[first_station_index].from_node_id,
            platform_exit_node_id=service_segments[last_station_index].to_node_id,
            exit_switch_node_id=exit_switch_node_id,
            rope_segment_id=rope_segment.id,
            next_switch_node_id=next_switch_id,
            service_to_platform_segment_ids=tuple(segment.id for segment in service_segments[:first_station_index]),
            station_segment_ids=tuple(segment.id for segment in service_segments[first_station_index : last_station_index + 1]),
            platform_to_exit_segment_ids=tuple(segment.id for segment in service_segments[last_station_index + 1 :]),
        )
    return routes


def _single_route_from_switch(
    routes: tuple[StationRoute, ...],
    segments_by_id: dict[str, TrackSegment],
    switch_id: str,
    route_kind: StationRouteKind,
) -> StationRoute:
    matching_routes = _routes_from_switch(routes, segments_by_id, switch_id, route_kind)
    if len(matching_routes) != 1:
        raise ValueError(f"expected exactly one {route_kind.value} route from switch {switch_id!r}")
    return matching_routes[0]


def _optional_route_from_switch(
    routes: tuple[StationRoute, ...],
    segments_by_id: dict[str, TrackSegment],
    switch_id: str,
    route_kind: StationRouteKind,
) -> StationRoute | None:
    matching_routes = _routes_from_switch(routes, segments_by_id, switch_id, route_kind)
    if len(matching_routes) > 1:
        raise ValueError(f"expected at most one {route_kind.value} route from switch {switch_id!r}")
    return matching_routes[0] if matching_routes else None


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


def _single_rope_segment(
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
        raise ValueError(f"expected exactly one rope segment from {from_node_id!r} to {to_node_id!r}")
    return rope_segments[0]


def _event_sort_key(event: EanPhysicalEvent) -> tuple[float, int, int, str]:
    return (event.time_seconds, event.cabin_id, event.visit_index, event.event_kind.value)
