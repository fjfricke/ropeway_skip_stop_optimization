from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.mapping.physical_to_discrete import travel_seconds_for_segment
from ropeway_skip_stop_optimization.models import (
    DefaultBypassStopOnFaultDesign,
    FailSafeDiversionDesign,
    MandatoryServiceStationDesign,
    PhysicalNodeKind,
    Scenario,
    StationRoute,
    StationRouteKind,
    TrackSegment,
    TrackSegmentKind,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanActivationReference,
    EanTimeReference,
    HeadwayCheckpointKind,
)
from ropeway_skip_stop_optimization.optimization.ean.network import (
    EanCirculationPattern,
    EanCirculationPatternDefinition,
    EanMovementEffect,
    EanMovementNetwork,
    EanMovementState,
    EanPassengerBehavior,
    EanResource,
    EanResourceKind,
    EanResourceUsage,
    EanRouteOption,
    compatibility_resource_id,
)


@dataclass(frozen=True)
class PhysicalMovementNetworkBuilder:
    """Derive the canonical EAN network directly from physical scenario data."""

    def build(
        self,
        scenario: Scenario,
        pattern_definition: EanCirculationPatternDefinition | None = None,
    ) -> EanMovementNetwork:
        scenario.validate()
        if pattern_definition is None:
            discovered = self.discover_pattern_definitions(scenario)
            if len(discovered) != 1:
                raise ValueError(
                    "physical network contains multiple circulation patterns; "
                    "select one explicitly"
                )
            pattern_definition = discovered[0]
        pattern_definition.validate()
        nodes_by_id = {node.id: node for node in scenario.physical_nodes}
        segments_by_id = {segment.id: segment for segment in scenario.track_segments}

        for node_id in pattern_definition.state_node_ids:
            node = nodes_by_id.get(node_id)
            if node is None:
                raise ValueError(f"circulation pattern references unknown physical node {node_id!r}")
            if node.kind is not PhysicalNodeKind.ENTRY_SWITCH:
                raise ValueError(f"circulation pattern node {node_id!r} is not an entry switch")

        states = tuple(
            EanMovementState(id=node_id, physical_node_id=node_id)
            for node_id in pattern_definition.state_node_ids
        )
        options: list[EanRouteOption] = []
        option_ids_by_position: list[tuple[str, ...]] = []
        resources: dict[str, EanResource] = {}

        for index, state_id in enumerate(pattern_definition.state_node_ids):
            next_state_id = pattern_definition.state_node_ids[
                (index + 1) % len(pattern_definition.state_node_ids)
            ]
            routes = _routes_from_state(scenario.station_routes, segments_by_id, state_id)
            service_routes = tuple(route for route in routes if route.kind is StationRouteKind.SERVICE)
            skip_routes = tuple(route for route in routes if route.kind is StationRouteKind.SKIP)
            if len(service_routes) != 1 or len(skip_routes) > 1:
                raise _dynamic_routing_error(
                    state_id,
                    f"found {len(service_routes)} service and {len(skip_routes)} skip routes",
                )

            selected_routes = service_routes + skip_routes
            exit_ids = {
                segments_by_id[route.segment_ids[-1]].to_node_id
                for route in selected_routes
            }
            if len(exit_ids) != 1:
                raise _dynamic_routing_error(state_id, "service and skip routes do not reconverge")
            exit_id = next(iter(exit_ids))
            exit_node = nodes_by_id.get(exit_id)
            if exit_node is None or exit_node.kind is not PhysicalNodeKind.EXIT_SWITCH:
                raise ValueError(f"routes from state {state_id!r} must end at an exit switch")

            continuation_segments = tuple(
                segment
                for segment in scenario.track_segments
                if segment.kind is TrackSegmentKind.ROPE
                and segment.from_node_id == exit_id
            )
            if len(continuation_segments) != 1:
                raise _dynamic_routing_error(
                    state_id,
                    f"expected one continuation from {exit_id!r}, found {len(continuation_segments)}",
                )
            continuation = continuation_segments[0]
            if continuation.to_node_id != next_state_id:
                raise _dynamic_routing_error(
                    state_id,
                    f"continuation reaches {continuation.to_node_id!r}, not pattern successor {next_state_id!r}",
                )

            position_option_ids: list[str] = []
            for route in selected_routes:
                route_segments = tuple(segments_by_id[segment_id] for segment_id in route.segment_ids)
                behavior = (
                    EanPassengerBehavior.SERVICE
                    if route.kind is StationRouteKind.SERVICE
                    else EanPassengerBehavior.SKIP
                )
                usages = _resource_usages(
                    state_id=state_id,
                    behavior=behavior,
                    segments=route_segments + (continuation,),
                    resources=resources,
                    service_mechanism=(
                        scenario.headway_design.mechanism_for_exit_switch(exit_id)
                        if scenario.headway_design is not None
                        else None
                    ),
                )
                option_id = f"route_option::{route.id}::to::{next_state_id}"
                options.append(
                    EanRouteOption(
                        id=option_id,
                        from_state_id=state_id,
                        to_state_id=next_state_id,
                        station_id=route.station_id,
                        station_route_id=route.id,
                        passenger_behavior=behavior,
                        movement_effect=EanMovementEffect.CONTINUE,
                        station_segment_ids=route.segment_ids,
                        continuation_segment_ids=(continuation.id,),
                        minimum_seconds=sum(
                            travel_seconds_for_segment(segment)
                            for segment in route_segments + (continuation,)
                        ),
                        maximum_seconds=sum(
                            travel_seconds_for_segment(segment)
                            for segment in route_segments + (continuation,)
                        ),
                        resource_usages=usages,
                    )
                )
                position_option_ids.append(option_id)
            option_ids_by_position.append(tuple(position_option_ids))

        pattern = EanCirculationPattern(
            id=pattern_definition.id,
            state_ids=pattern_definition.state_node_ids,
            route_option_ids_by_position=tuple(option_ids_by_position),
        )
        network = EanMovementNetwork(
            states=states,
            route_options=tuple(options),
            resources=tuple(resources.values()),
            circulation_patterns=(pattern,),
        )
        network.validate()
        return network

    def discover_pattern_definitions(
        self, scenario: Scenario
    ) -> tuple[EanCirculationPatternDefinition, ...]:
        """Detect deterministic physical cycles with stable canonical rotations."""

        scenario.validate()
        entry_ids = {
            node.id
            for node in scenario.physical_nodes
            if node.kind is PhysicalNodeKind.ENTRY_SWITCH
        }
        segments_by_id = {segment.id: segment for segment in scenario.track_segments}
        successor_by_state: dict[str, str] = {}
        for state_id in sorted(entry_ids):
            routes = _routes_from_state(scenario.station_routes, segments_by_id, state_id)
            service_routes = tuple(route for route in routes if route.kind is StationRouteKind.SERVICE)
            skip_routes = tuple(route for route in routes if route.kind is StationRouteKind.SKIP)
            if len(service_routes) != 1 or len(skip_routes) > 1:
                raise _dynamic_routing_error(
                    state_id,
                    f"found {len(service_routes)} service and {len(skip_routes)} skip routes",
                )
            exits = {
                segments_by_id[route.segment_ids[-1]].to_node_id
                for route in service_routes + skip_routes
            }
            if len(exits) != 1:
                raise _dynamic_routing_error(state_id, "service and skip routes do not reconverge")
            exit_id = next(iter(exits))
            continuations = tuple(
                segment
                for segment in scenario.track_segments
                if segment.kind is TrackSegmentKind.ROPE
                and segment.from_node_id == exit_id
            )
            if len(continuations) != 1 or continuations[0].to_node_id not in entry_ids:
                raise _dynamic_routing_error(
                    state_id,
                    f"exit {exit_id!r} does not have one continuation to an entry state",
                )
            successor_by_state[state_id] = continuations[0].to_node_id

        predecessor_counts = {state_id: 0 for state_id in entry_ids}
        for successor in successor_by_state.values():
            predecessor_counts[successor] += 1
        if any(count != 1 for count in predecessor_counts.values()):
            raise ValueError(
                "dynamic routing not yet supported: deterministic circulation needs "
                "exactly one predecessor per entry state"
            )

        unvisited = set(entry_ids)
        cycles: list[tuple[str, ...]] = []
        while unvisited:
            origin = min(unvisited)
            cycle: list[str] = []
            current = origin
            while current not in cycle:
                if current not in unvisited:
                    raise ValueError("deterministic circulation graph contains a non-cycle component")
                cycle.append(current)
                unvisited.remove(current)
                current = successor_by_state[current]
            if current != origin:
                raise ValueError("deterministic circulation graph contains a tail into a cycle")
            cycles.append(tuple(cycle))

        return tuple(
            EanCirculationPatternDefinition(
                id=f"physical_cycle::{index}::{cycle[0]}",
                state_node_ids=cycle,
            )
            for index, cycle in enumerate(sorted(cycles))
        )


def _routes_from_state(
    routes: tuple[StationRoute, ...],
    segments_by_id: dict[str, TrackSegment],
    state_id: str,
) -> tuple[StationRoute, ...]:
    return tuple(
        route
        for route in routes
        if route.segment_ids and segments_by_id[route.segment_ids[0]].from_node_id == state_id
    )


def _resource_usages(
    *,
    state_id: str,
    behavior: EanPassengerBehavior,
    segments: tuple[TrackSegment, ...],
    resources: dict[str, EanResource],
    service_mechanism: object | None,
) -> tuple[EanResourceUsage, ...]:
    usages: list[EanResourceUsage] = []
    seen_physical_resources: set[str] = set()
    for segment in segments:
        if segment.resource_id is None or segment.resource_id in seen_physical_resources:
            continue
        seen_physical_resources.add(segment.resource_id)
        resource_id = f"physical::{segment.resource_id}"
        resources.setdefault(
            resource_id,
            EanResource(
                id=resource_id,
                kind=EanResourceKind.PHYSICAL,
                physical_resource_id=segment.resource_id,
            ),
        )
        usages.append(
            EanResourceUsage(
                resource_id=resource_id,
                time_reference=EanTimeReference.ENTRY_TIME,
                activation_reference=EanActivationReference.ACTIVE,
            )
        )

    checkpoint_kinds = (
        (HeadwayCheckpointKind.PLATFORM_ENTRY, EanTimeReference.PLATFORM_ENTRY_TIME),
        (HeadwayCheckpointKind.PLATFORM_EXIT, EanTimeReference.PLATFORM_EXIT_TIME),
        (HeadwayCheckpointKind.EXIT_SWITCH, EanTimeReference.EXIT_SWITCH_TIME),
    )
    for kind, time_reference in checkpoint_kinds:
        if behavior is EanPassengerBehavior.SKIP and kind is not HeadwayCheckpointKind.EXIT_SWITCH:
            continue
        resource_id = compatibility_resource_id(kind, state_id)
        resources.setdefault(resource_id, EanResource(id=resource_id, kind=EanResourceKind.COMPATIBILITY))
        usages.append(
            EanResourceUsage(
                resource_id=resource_id,
                time_reference=time_reference,
                activation_reference=(
                    EanActivationReference.SERVE
                    if kind is not HeadwayCheckpointKind.EXIT_SWITCH
                    else EanActivationReference.ACTIVE
                ),
                checkpoint_kind=kind,
            )
        )
    if behavior is EanPassengerBehavior.SERVICE and isinstance(
        service_mechanism,
        DefaultBypassStopOnFaultDesign
        | FailSafeDiversionDesign
        | MandatoryServiceStationDesign,
    ):
        resource_id = f"service_mechanism::{state_id}"
        resources.setdefault(
            resource_id,
            EanResource(
                id=resource_id,
                kind=EanResourceKind.PHYSICAL,
                physical_resource_id=service_mechanism.service_resource_id,
            ),
        )
        usages.append(
            EanResourceUsage(
                resource_id=resource_id,
                time_reference=EanTimeReference.EXIT_SWITCH_TIME,
                activation_reference=EanActivationReference.SERVE,
                checkpoint_kind=HeadwayCheckpointKind.SERVICE_MECHANISM,
            )
        )
    return tuple(usages)


def _dynamic_routing_error(state_id: str, detail: str) -> ValueError:
    return ValueError(f"dynamic routing not yet supported at state {state_id!r}: {detail}")
