from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from ropeway_skip_stop_optimization.examples.base import ScenarioExample, ScenarioExampleMetadata
from ropeway_skip_stop_optimization.mapping import DiscretizationConfig
from ropeway_skip_stop_optimization.models import (
    Cabin,
    CabinInitialState,
    Demand,
    OperatingParameters,
    PhysicalNode,
    PhysicalNodeKind,
    Scenario,
    SpeedProfile,
    SpeedProfileKind,
    Station,
    StationKind,
    StationRoute,
    StationRouteKind,
    TrackSegment,
    TrackSegmentKind,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    ContinuousAllStopMaxCabinStartBuilder,
    EanCabinStart,
    EanCabinStartBuilder,
    EanBuildArtifactBuilder,
    EanConfig,
    network_ean_builder_for_cycle,
    StationEanConfig,
    StationWaitingMode,
)


@dataclass(frozen=True)
class LinearSkipStopSpec:
    scenario_id: str
    station_ids: tuple[str, ...]
    middle_station_ids: tuple[str, ...]
    label: str
    description: str
    service_start_time: time = time(8, 0)
    service_end_time: time = time(8, 20)
    rope_speed_m_per_s: float = 5.0
    platform_speed_m_per_s: float = 0.5
    rope_segment_length_m: float = 150.0
    terminal_platform_length_m: float = 10.0
    middle_platform_length_m: float = 10.0
    middle_bypass_length_m: float = 20.0
    cabin_capacity: int = 8
    cabin_length_m: float = 3.0
    min_clearance_m: float = 0.5
    scenario_cabin_count: int = 8
    include_skip_routes: bool = True

    def validate(self) -> None:
        if len(self.station_ids) < 3:
            raise ValueError("linear skip-stop examples need at least three stations")
        if self.station_ids[0] in self.middle_station_ids or self.station_ids[-1] in self.middle_station_ids:
            raise ValueError("terminal stations must not be middle skip-stop stations")
        if self.middle_station_ids != self.station_ids[1:-1]:
            raise ValueError("middle_station_ids must match station_ids without terminals")
        if self.service_end_time <= self.service_start_time:
            raise ValueError("service_end_time must be after service_start_time")
        if self.scenario_cabin_count <= 0:
            raise ValueError("scenario_cabin_count must be positive")


@dataclass(frozen=True)
class KeepEverySecondCabinStartBuilder(EanCabinStartBuilder):
    base_builder: EanCabinStartBuilder

    def build(
        self,
        scenario: Scenario,
        config: EanConfig,
        target_switch_ids: frozenset[str],
    ) -> tuple[EanCabinStart, ...]:
        starts = self.base_builder.build(
            scenario=scenario,
            config=config,
            target_switch_ids=target_switch_ids,
        )
        return tuple(start for index, start in enumerate(starts) if index % 2 == 0)


class FiveStationExample(ScenarioExample):
    metadata = ScenarioExampleMetadata(
        id="five_station_v0",
        label="Five station ring half cabins skip+wait",
        description=(
            "Bidirectional five-station ring with every second EAN start cabin, skip enabled, "
            "and middle-station waiting enabled."
        ),
        tags=("ring", "skip-stop", "ean-demo", "scaling-demo", "half-cabins", "waiting"),
        family_id="five_station_ring",
        family_label="Five station ring",
        variant_id="half_cabins_skip_wait",
        variant_label="Half cabins skip+wait",
    )

    spec = LinearSkipStopSpec(
        scenario_id=metadata.id,
        station_ids=("L", "A", "B", "C", "R"),
        middle_station_ids=("A", "B", "C"),
        label=metadata.label,
        description=metadata.description,
    )

    def build_scenario(self) -> Scenario:
        return build_linear_skip_stop_scenario(self.spec)

    def build_discretization_config(self, scenario: Scenario) -> DiscretizationConfig:
        config = DiscretizationConfig()
        config.validate()
        return config

    def build_ean_config(self, scenario: Scenario) -> EanConfig:
        return build_linear_skip_stop_ean_config(scenario)

    def build_ean_artifact_builder(
        self,
        scenario: Scenario,
        config: EanConfig,
    ) -> EanBuildArtifactBuilder:
        switch_cycle = build_linear_skip_stop_ean_ring_switch_order(scenario)
        return network_ean_builder_for_cycle(
            state_ids=switch_cycle,
            start_builder=KeepEverySecondCabinStartBuilder(
                ContinuousAllStopMaxCabinStartBuilder(switch_cycle=switch_cycle),
            ),
        )


class FiveStationNoWaitExample(FiveStationExample):
    metadata = ScenarioExampleMetadata(
        id="five_station_no_wait_v0",
        label="Five station ring full cabins skip+no_wait",
        description=(
            "Bidirectional five-station ring with all EAN start cabins, skip enabled, and station waiting disabled."
        ),
        tags=("ring", "skip-stop", "ean-demo", "scaling-demo", "full-cabins", "no-waiting"),
        family_id="five_station_ring",
        family_label="Five station ring",
        variant_id="full_cabins_skip_no_wait",
        variant_label="Full cabins skip+no_wait",
    )

    spec = LinearSkipStopSpec(
        scenario_id=metadata.id,
        station_ids=FiveStationExample.spec.station_ids,
        middle_station_ids=FiveStationExample.spec.middle_station_ids,
        label=metadata.label,
        description=metadata.description,
    )

    def build_ean_config(self, scenario: Scenario) -> EanConfig:
        return build_linear_skip_stop_ean_config(
            scenario,
            service_station_waiting_mode=StationWaitingMode.NO_WAITING,
        )

    def build_ean_artifact_builder(
        self,
        scenario: Scenario,
        config: EanConfig,
    ) -> EanBuildArtifactBuilder:
        switch_cycle = build_linear_skip_stop_ean_ring_switch_order(scenario)
        return network_ean_builder_for_cycle(
            state_ids=switch_cycle,
            start_builder=ContinuousAllStopMaxCabinStartBuilder(switch_cycle=switch_cycle),
        )


class FiveStationHalfNoSkipNoWaitExample(FiveStationExample):
    metadata = ScenarioExampleMetadata(
        id="five_station_half_no_skip_no_wait_v0",
        label="Five station ring half cabins no_skip+no_wait",
        description=(
            "Bidirectional five-station ring with every second EAN start cabin, skip disabled, "
            "and station waiting disabled."
        ),
        tags=("ring", "ean-demo", "scaling-demo", "half-cabins", "no-skip", "no-waiting"),
        family_id="five_station_ring",
        family_label="Five station ring",
        variant_id="half_cabins_no_skip_no_wait",
        variant_label="Half cabins no_skip+no_wait",
    )

    spec = LinearSkipStopSpec(
        scenario_id=metadata.id,
        station_ids=FiveStationExample.spec.station_ids,
        middle_station_ids=FiveStationExample.spec.middle_station_ids,
        label=metadata.label,
        description=metadata.description,
        include_skip_routes=False,
    )

    def build_ean_config(self, scenario: Scenario) -> EanConfig:
        return build_linear_skip_stop_ean_config(
            scenario,
            service_station_waiting_mode=StationWaitingMode.NO_WAITING,
        )


def build_five_station_scenario() -> Scenario:
    return build_linear_skip_stop_scenario(FiveStationExample.spec)


def build_five_station_ean_config(
    scenario: Scenario | None = None,
    tail_seconds: float = 0.0,
) -> EanConfig:
    return build_linear_skip_stop_ean_config(scenario or build_five_station_scenario(), tail_seconds=tail_seconds)


def build_five_station_ean_ring_switch_order(
    scenario: Scenario | None = None,
) -> tuple[str, ...]:
    return build_linear_skip_stop_ean_ring_switch_order(scenario or build_five_station_scenario())


def build_five_station_no_wait_scenario() -> Scenario:
    return build_linear_skip_stop_scenario(FiveStationNoWaitExample.spec)


def build_five_station_no_wait_ean_config(
    scenario: Scenario | None = None,
    tail_seconds: float = 0.0,
) -> EanConfig:
    return build_linear_skip_stop_ean_config(
        scenario or build_five_station_no_wait_scenario(),
        tail_seconds=tail_seconds,
        service_station_waiting_mode=StationWaitingMode.NO_WAITING,
    )


def build_five_station_half_no_skip_no_wait_scenario() -> Scenario:
    return build_linear_skip_stop_scenario(FiveStationHalfNoSkipNoWaitExample.spec)


def build_five_station_half_no_skip_no_wait_ean_config(
    scenario: Scenario | None = None,
    tail_seconds: float = 0.0,
) -> EanConfig:
    return build_linear_skip_stop_ean_config(
        scenario or build_five_station_half_no_skip_no_wait_scenario(),
        tail_seconds=tail_seconds,
        service_station_waiting_mode=StationWaitingMode.NO_WAITING,
    )


def build_linear_skip_stop_scenario(spec: LinearSkipStopSpec) -> Scenario:
    spec.validate()

    rope_profile = SpeedProfile(SpeedProfileKind.CONSTANT, speed_m_per_s=spec.rope_speed_m_per_s)
    platform_profile = SpeedProfile(SpeedProfileKind.CONSTANT, speed_m_per_s=spec.platform_speed_m_per_s)
    brake_profile = SpeedProfile(
        SpeedProfileKind.LINEAR,
        start_speed_m_per_s=spec.rope_speed_m_per_s,
        end_speed_m_per_s=spec.platform_speed_m_per_s,
    )
    accelerate_profile = SpeedProfile(
        SpeedProfileKind.LINEAR,
        start_speed_m_per_s=spec.platform_speed_m_per_s,
        end_speed_m_per_s=spec.rope_speed_m_per_s,
    )

    left_terminal = spec.station_ids[0]
    right_terminal = spec.station_ids[-1]
    middle_station_ids = spec.station_ids[1:-1]

    stations = (
        Station(
            id=left_terminal,
            kind=StationKind.TERMINAL,
            name=f"{left_terminal} terminal",
            route_ids=(f"{left_terminal}_service_turnaround",),
        ),
        *(
            Station(
                id=station_id,
                kind=StationKind.SERVICE,
                name=f"{station_id} station",
                route_ids=_middle_station_route_ids(station_id, include_skip_routes=spec.include_skip_routes),
            )
            for station_id in middle_station_ids
        ),
        Station(
            id=right_terminal,
            kind=StationKind.TERMINAL,
            name=f"{right_terminal} terminal",
            route_ids=(f"{right_terminal}_service_turnaround",),
        ),
    )

    physical_nodes = (
        *_terminal_nodes(left_terminal, entry_direction="rl", exit_direction="lr"),
        *_terminal_nodes(right_terminal, entry_direction="lr", exit_direction="rl"),
        *(
            node
            for station_id in middle_station_ids
            for node in _middle_station_nodes(station_id)
        ),
    )

    track_segments = (
        *_terminal_station_segments(
            left_terminal,
            entry_direction="rl",
            exit_direction="lr",
            platform_length_m=spec.terminal_platform_length_m,
            platform_profile=platform_profile,
            brake_profile=brake_profile,
            accelerate_profile=accelerate_profile,
        ),
        *_terminal_station_segments(
            right_terminal,
            entry_direction="lr",
            exit_direction="rl",
            platform_length_m=spec.terminal_platform_length_m,
            platform_profile=platform_profile,
            brake_profile=brake_profile,
            accelerate_profile=accelerate_profile,
        ),
        *_rope_segments(
            station_ids=spec.station_ids,
            length_m=spec.rope_segment_length_m,
            rope_profile=rope_profile,
        ),
        *(
            segment
            for station_id in middle_station_ids
            for segment in (
                *_middle_station_segments(
                    station_id,
                    "lr",
                    fast_profile=rope_profile,
                    platform_profile=platform_profile,
                    brake_profile=brake_profile,
                    accelerate_profile=accelerate_profile,
                    platform_length_m=spec.middle_platform_length_m,
                    bypass_length_m=spec.middle_bypass_length_m,
                ),
                *_middle_station_segments(
                    station_id,
                    "rl",
                    fast_profile=rope_profile,
                    platform_profile=platform_profile,
                    brake_profile=brake_profile,
                    accelerate_profile=accelerate_profile,
                    platform_length_m=spec.middle_platform_length_m,
                    bypass_length_m=spec.middle_bypass_length_m,
                ),
            )
        ),
    )

    station_routes = (
        _terminal_route(left_terminal),
        *(
            route
            for station_id in middle_station_ids
            for route in _middle_station_routes(station_id, include_skip_routes=spec.include_skip_routes)
        ),
        _terminal_route(right_terminal),
    )

    cabins = tuple(Cabin(id=cabin_id) for cabin_id in range(spec.scenario_cabin_count))
    cabin_initial_states = _linear_skip_stop_initial_states(
        cabin_count=spec.scenario_cabin_count,
        left_terminal=left_terminal,
        right_terminal=right_terminal,
        service_start_time=spec.service_start_time,
    )

    scenario = Scenario(
        id=spec.scenario_id,
        service_start_time=spec.service_start_time,
        service_end_time=spec.service_end_time,
        stations=stations,
        physical_nodes=physical_nodes,
        track_segments=track_segments,
        station_routes=station_routes,
        cabins=cabins,
        cabin_initial_states=cabin_initial_states,
        demands=build_five_station_demo_demands()
        if spec.station_ids == FiveStationExample.spec.station_ids
        else (),
        operating=OperatingParameters(
            rope_speed_m_per_s=spec.rope_speed_m_per_s,
            station_speed_m_per_s=spec.platform_speed_m_per_s,
            cabin_capacity=spec.cabin_capacity,
            cabin_length_m=spec.cabin_length_m,
            min_clearance_m=spec.min_clearance_m,
        ),
    )
    scenario.validate()
    return scenario


def build_five_station_demo_demands() -> tuple[Demand, ...]:
    station_ids = FiveStationExample.spec.station_ids
    demand_count_per_od_pair = 160
    return tuple(
        Demand(arrival_time=time(8, 0), origin=origin, destination=destination, count=demand_count_per_od_pair)
        for origin in station_ids
        for destination in station_ids
        if origin != destination
    )


def build_linear_skip_stop_ean_config(
    scenario: Scenario,
    tail_seconds: float = 0.0,
    service_station_waiting_mode: StationWaitingMode = StationWaitingMode.END_OF_PLATFORM_WAIT,
) -> EanConfig:
    scenario.validate()
    config = EanConfig(
        horizon_seconds=_service_duration_seconds(scenario),
        tail_seconds=tail_seconds,
        cabin_capacity=scenario.operating.cabin_capacity,
        station_configs=tuple(
            StationEanConfig(
                station_id=station.id,
                waiting_mode=(
                    service_station_waiting_mode
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


def build_linear_skip_stop_ean_ring_switch_order(scenario: Scenario) -> tuple[str, ...]:
    scenario.validate()
    service_station_ids = tuple(station.id for station in scenario.stations if station.kind is StationKind.SERVICE)
    terminal_station_ids = tuple(station.id for station in scenario.stations if station.kind is StationKind.TERMINAL)
    if len(terminal_station_ids) != 2:
        raise ValueError("linear skip-stop ring order requires exactly two terminal stations")
    left_terminal, right_terminal = terminal_station_ids
    switch_cycle = (
        *(f"{station_id}_entry_lr" for station_id in service_station_ids),
        f"{right_terminal}_entry_lr",
        *(f"{station_id}_entry_rl" for station_id in reversed(service_station_ids)),
        f"{left_terminal}_entry_rl",
    )
    _validate_switch_cycle_is_physical_ring(scenario, switch_cycle)
    return switch_cycle


def _terminal_nodes(
    station: str,
    entry_direction: str,
    exit_direction: str,
) -> tuple[PhysicalNode, ...]:
    return (
        PhysicalNode(id=f"{station}_entry_{entry_direction}", kind=PhysicalNodeKind.ENTRY_SWITCH, station_id=station),
        PhysicalNode(id=f"{station}_platform_entry", kind=PhysicalNodeKind.PLATFORM, station_id=station),
        PhysicalNode(
            id=f"{station}_platform_exit",
            kind=PhysicalNodeKind.PLATFORM,
            station_id=station,
        ),
        PhysicalNode(id=f"{station}_exit_{exit_direction}", kind=PhysicalNodeKind.EXIT_SWITCH, station_id=station),
    )


def _middle_station_nodes(station: str) -> tuple[PhysicalNode, ...]:
    return (
        *_middle_station_direction_nodes(station, "lr"),
        *_middle_station_direction_nodes(station, "rl"),
    )


def _middle_station_direction_nodes(station: str, direction: str) -> tuple[PhysicalNode, ...]:
    return (
        PhysicalNode(id=f"{station}_entry_{direction}", kind=PhysicalNodeKind.ENTRY_SWITCH, station_id=station),
        PhysicalNode(id=f"{station}_service_approach_{direction}", kind=PhysicalNodeKind.CONNECTOR, station_id=station),
        PhysicalNode(id=f"{station}_platform_entry_{direction}", kind=PhysicalNodeKind.PLATFORM, station_id=station),
        PhysicalNode(id=f"{station}_platform_exit_{direction}", kind=PhysicalNodeKind.PLATFORM, station_id=station),
        PhysicalNode(id=f"{station}_service_accelerate_{direction}", kind=PhysicalNodeKind.CONNECTOR, station_id=station),
        PhysicalNode(id=f"{station}_exit_{direction}", kind=PhysicalNodeKind.EXIT_SWITCH, station_id=station),
    )


def _terminal_station_segments(
    station: str,
    entry_direction: str,
    exit_direction: str,
    platform_length_m: float,
    platform_profile: SpeedProfile,
    brake_profile: SpeedProfile,
    accelerate_profile: SpeedProfile,
) -> tuple[TrackSegment, ...]:
    entry = f"{station}_entry_{entry_direction}"
    platform_entry = f"{station}_platform_entry"
    platform_exit = f"{station}_platform_exit"
    exit_node = f"{station}_exit_{exit_direction}"
    resource_id = f"{station}_service_turnaround"

    return (
        TrackSegment(
            id=f"{station}_turnaround_decelerate",
            kind=TrackSegmentKind.CONNECTOR,
            from_node_id=entry,
            to_node_id=platform_entry,
            length_m=3.0,
            speed_profile=brake_profile,
            resource_id=resource_id,
        ),
        TrackSegment(
            id=f"{station}_turnaround_platform",
            kind=TrackSegmentKind.STATION,
            from_node_id=platform_entry,
            to_node_id=platform_exit,
            length_m=platform_length_m,
            speed_profile=platform_profile,
            resource_id=resource_id,
        ),
        TrackSegment(
            id=f"{station}_turnaround_accelerate",
            kind=TrackSegmentKind.CONNECTOR,
            from_node_id=platform_exit,
            to_node_id=exit_node,
            length_m=3.0,
            speed_profile=accelerate_profile,
            resource_id=resource_id,
        ),
    )


def _middle_station_segments(
    station: str,
    direction: str,
    fast_profile: SpeedProfile,
    platform_profile: SpeedProfile,
    brake_profile: SpeedProfile,
    accelerate_profile: SpeedProfile,
    platform_length_m: float,
    bypass_length_m: float,
) -> tuple[TrackSegment, ...]:
    entry = f"{station}_entry_{direction}"
    exit_node = f"{station}_exit_{direction}"
    return (
        TrackSegment(
            id=f"{station}_{direction}_approach_fast",
            kind=TrackSegmentKind.CONNECTOR,
            from_node_id=entry,
            to_node_id=f"{station}_service_approach_{direction}",
            length_m=5.0,
            speed_profile=fast_profile,
            resource_id=f"{station}_service_{direction}",
        ),
        TrackSegment(
            id=f"{station}_{direction}_brake",
            kind=TrackSegmentKind.CONNECTOR,
            from_node_id=f"{station}_service_approach_{direction}",
            to_node_id=f"{station}_platform_entry_{direction}",
            length_m=3.0,
            speed_profile=brake_profile,
            resource_id=f"{station}_service_{direction}",
        ),
        TrackSegment(
            id=f"{station}_{direction}_platform",
            kind=TrackSegmentKind.STATION,
            from_node_id=f"{station}_platform_entry_{direction}",
            to_node_id=f"{station}_platform_exit_{direction}",
            length_m=platform_length_m,
            speed_profile=platform_profile,
            resource_id=f"{station}_service_{direction}",
        ),
        TrackSegment(
            id=f"{station}_{direction}_accelerate",
            kind=TrackSegmentKind.CONNECTOR,
            from_node_id=f"{station}_platform_exit_{direction}",
            to_node_id=f"{station}_service_accelerate_{direction}",
            length_m=3.0,
            speed_profile=accelerate_profile,
            resource_id=f"{station}_service_{direction}",
        ),
        TrackSegment(
            id=f"{station}_{direction}_depart_fast",
            kind=TrackSegmentKind.CONNECTOR,
            from_node_id=f"{station}_service_accelerate_{direction}",
            to_node_id=exit_node,
            length_m=5.0,
            speed_profile=fast_profile,
            resource_id=f"{station}_service_{direction}",
        ),
        TrackSegment(
            id=f"{station}_{direction}_skip_bypass",
            kind=TrackSegmentKind.SKIP,
            from_node_id=entry,
            to_node_id=exit_node,
            length_m=bypass_length_m,
            speed_profile=fast_profile,
            resource_id=f"{station}_skip_{direction}",
        ),
    )


def _rope_segments(
    station_ids: tuple[str, ...],
    length_m: float,
    rope_profile: SpeedProfile,
) -> tuple[TrackSegment, ...]:
    segments: list[TrackSegment] = []
    for index, (left_station_id, right_station_id) in enumerate(zip(station_ids, station_ids[1:]), start=1):
        segments.append(
            TrackSegment(
                id=f"{left_station_id}_exit_lr_to_{right_station_id}_entry_lr",
                kind=TrackSegmentKind.ROPE,
                from_node_id=f"{left_station_id}_exit_lr",
                to_node_id=f"{right_station_id}_entry_lr",
                length_m=length_m,
                speed_profile=rope_profile,
                resource_id=f"rope_lr_{index}",
            )
        )
    for index, (right_station_id, left_station_id) in enumerate(
        zip(reversed(station_ids), reversed(station_ids[:-1])),
        start=1,
    ):
        segments.append(
            TrackSegment(
                id=f"{right_station_id}_exit_rl_to_{left_station_id}_entry_rl",
                kind=TrackSegmentKind.ROPE,
                from_node_id=f"{right_station_id}_exit_rl",
                to_node_id=f"{left_station_id}_entry_rl",
                length_m=length_m,
                speed_profile=rope_profile,
                resource_id=f"rope_rl_{index}",
            )
        )
    return tuple(segments)


def _terminal_route(station: str) -> StationRoute:
    return StationRoute(
        id=f"{station}_service_turnaround",
        station_id=station,
        kind=StationRouteKind.SERVICE,
        segment_ids=(
            f"{station}_turnaround_decelerate",
            f"{station}_turnaround_platform",
            f"{station}_turnaround_accelerate",
        ),
        allows_boarding=True,
        allows_alighting=True,
    )


def _middle_station_route_ids(station: str, include_skip_routes: bool) -> tuple[str, ...]:
    if include_skip_routes:
        return (
            f"{station}_service_lr",
            f"{station}_skip_lr",
            f"{station}_service_rl",
            f"{station}_skip_rl",
        )
    return (f"{station}_service_lr", f"{station}_service_rl")


def _middle_station_routes(station: str, include_skip_routes: bool) -> tuple[StationRoute, ...]:
    routes = [
        _middle_station_service_route(station, "lr"),
        _middle_station_service_route(station, "rl"),
    ]
    if include_skip_routes:
        routes.insert(1, _middle_station_skip_route(station, "lr"))
        routes.append(_middle_station_skip_route(station, "rl"))
    return tuple(routes)


def _middle_station_service_route(station: str, direction: str) -> StationRoute:
    return StationRoute(
        id=f"{station}_service_{direction}",
        station_id=station,
        kind=StationRouteKind.SERVICE,
        segment_ids=(
            f"{station}_{direction}_approach_fast",
            f"{station}_{direction}_brake",
            f"{station}_{direction}_platform",
            f"{station}_{direction}_accelerate",
            f"{station}_{direction}_depart_fast",
        ),
        allows_boarding=True,
        allows_alighting=True,
    )


def _middle_station_skip_route(station: str, direction: str) -> StationRoute:
    return StationRoute(
        id=f"{station}_skip_{direction}",
        station_id=station,
        kind=StationRouteKind.SKIP,
        segment_ids=(f"{station}_{direction}_skip_bypass",),
        allows_boarding=False,
        allows_alighting=False,
    )


def _linear_skip_stop_initial_states(
    cabin_count: int,
    left_terminal: str,
    right_terminal: str,
    service_start_time: time,
) -> tuple[CabinInitialState, ...]:
    states: list[CabinInitialState] = []
    for cabin_id in range(cabin_count):
        node_id = f"{left_terminal}_platform_exit" if cabin_id % 2 == 0 else f"{right_terminal}_platform_exit"
        side_index = cabin_id // 2
        side_offset_seconds = 0 if cabin_id % 2 == 0 else 4
        states.append(
            CabinInitialState(
                cabin_id=cabin_id,
                node_id=node_id,
                available_from=_add_seconds_to_time(service_start_time, side_offset_seconds + 8 * side_index),
            )
        )
    return tuple(states)


def _service_duration_seconds(scenario: Scenario) -> float:
    start = datetime.combine(datetime.min.date(), scenario.service_start_time)
    end = datetime.combine(datetime.min.date(), scenario.service_end_time)
    return (end - start).total_seconds()


def _add_seconds_to_time(value: time, seconds: int) -> time:
    return (datetime.combine(datetime.min.date(), value) + timedelta(seconds=seconds)).time()


def _validate_switch_cycle_is_physical_ring(scenario: Scenario, switch_cycle: tuple[str, ...]) -> None:
    if not switch_cycle:
        raise ValueError("linear skip-stop EAN switch cycle must not be empty")

    nodes_by_id = {node.id: node for node in scenario.physical_nodes}
    segments_by_id = {segment.id: segment for segment in scenario.track_segments}

    for index, switch_id in enumerate(switch_cycle):
        next_switch_id = switch_cycle[(index + 1) % len(switch_cycle)]
        switch_node = nodes_by_id.get(switch_id)
        next_switch_node = nodes_by_id.get(next_switch_id)
        if switch_node is None:
            raise ValueError(f"linear skip-stop EAN switch cycle references unknown switch {switch_id!r}")
        if next_switch_node is None:
            raise ValueError(f"linear skip-stop EAN switch cycle references unknown switch {next_switch_id!r}")
        if switch_node.kind is not PhysicalNodeKind.ENTRY_SWITCH:
            raise ValueError(f"linear skip-stop EAN switch {switch_id!r} is not an entry switch")
        if next_switch_node.kind is not PhysicalNodeKind.ENTRY_SWITCH:
            raise ValueError(f"linear skip-stop EAN switch {next_switch_id!r} is not an entry switch")

        service_route = _single_service_route_from_switch(scenario.station_routes, segments_by_id, switch_id)
        exit_segment = segments_by_id[service_route.segment_ids[-1]]
        exit_node = nodes_by_id[exit_segment.to_node_id]
        if exit_node.kind is not PhysicalNodeKind.EXIT_SWITCH:
            raise ValueError(
                f"linear skip-stop EAN service route {service_route.id!r} does not end at an exit switch"
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
                "linear skip-stop EAN switch cycle is not physically connected: "
                f"{switch_id!r} exits at {exit_node.id!r}, expected one rope segment to {next_switch_id!r}"
            )


def _single_service_route_from_switch(
    routes: tuple[StationRoute, ...],
    segments_by_id: dict[str, TrackSegment],
    switch_id: str,
) -> StationRoute:
    matching_routes = [
        route
        for route in routes
        if route.kind is StationRouteKind.SERVICE
        and route.segment_ids
        and segments_by_id[route.segment_ids[0]].from_node_id == switch_id
    ]
    if len(matching_routes) != 1:
        raise ValueError(f"expected exactly one service route from switch {switch_id!r}, found {len(matching_routes)}")
    return matching_routes[0]
