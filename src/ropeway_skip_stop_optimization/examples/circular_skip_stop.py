from __future__ import annotations

from dataclasses import dataclass, replace
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
    EanFleetConfig,
    EanFleetMode,
    RingEanBuildArtifactBuilder,
    StationEanConfig,
    StationWaitingMode,
)


@dataclass(frozen=True)
class CircularSkipStopSpec:
    scenario_id: str
    station_ids: tuple[str, ...]
    label: str
    description: str
    include_skip_routes: bool
    service_station_waiting_mode: StationWaitingMode
    direction: str = "cw"
    service_start_time: time = time(8, 0)
    service_end_time: time = time(8, 20)
    rope_speed_m_per_s: float = 5.0
    platform_speed_m_per_s: float = 0.5
    rope_segment_length_m: float = 150.0
    platform_length_m: float = 10.0
    bypass_length_m: float = 20.0
    cabin_capacity: int = 8
    cabin_length_m: float = 3.0
    min_clearance_m: float = 0.5
    scenario_cabin_count: int = 8
    demand_count_per_od_pair: int = 128

    def validate(self) -> None:
        if len(self.station_ids) < 3:
            raise ValueError("circular skip-stop examples need at least three stations")
        if len(set(self.station_ids)) != len(self.station_ids):
            raise ValueError("circular skip-stop station ids must be unique")
        if not self.direction:
            raise ValueError("circular skip-stop direction must not be empty")
        if self.service_end_time <= self.service_start_time:
            raise ValueError("service_end_time must be after service_start_time")
        if self.scenario_cabin_count <= 0:
            raise ValueError("scenario_cabin_count must be positive")
        if self.demand_count_per_od_pair <= 0:
            raise ValueError("demand_count_per_od_pair must be positive")


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


class FiveStationCircleCwFullNoSkipNoWaitExample(ScenarioExample):
    metadata = ScenarioExampleMetadata(
        id="five_station_circle_cw_full_no_skip_no_wait_v0",
        label="Five station circle cw full cabins no_skip+no_wait",
        description=(
            "Clockwise five-station circular ropeway with all EAN start cabins, skip disabled, "
            "and station waiting disabled."
        ),
        tags=("circle", "cw", "ean-demo", "scaling-demo", "full-cabins", "no-skip", "no-waiting"),
        family_id="five_station_circle",
        family_label="Five station circle",
        variant_id="full_no_skip_no_wait",
        variant_label="Full cabins no_skip+no_wait",
    )

    spec = CircularSkipStopSpec(
        scenario_id=metadata.id,
        station_ids=("A", "B", "C", "D", "E"),
        label=metadata.label,
        description=metadata.description,
        include_skip_routes=False,
        service_station_waiting_mode=StationWaitingMode.NO_WAITING,
    )

    def build_scenario(self) -> Scenario:
        return build_circular_skip_stop_scenario(self.spec)

    def build_discretization_config(self, scenario: Scenario) -> DiscretizationConfig:
        config = DiscretizationConfig()
        config.validate()
        return config

    def build_ean_config(self, scenario: Scenario) -> EanConfig:
        return build_circular_skip_stop_ean_config(
            scenario,
            waiting_mode=self.spec.service_station_waiting_mode,
        )

    def build_ean_artifact_builder(
        self,
        scenario: Scenario,
        config: EanConfig,
    ) -> EanBuildArtifactBuilder:
        switch_cycle = build_circular_skip_stop_ean_ring_switch_order(scenario, direction=self.spec.direction)
        return RingEanBuildArtifactBuilder(
            switch_cycle=switch_cycle,
            start_builder=ContinuousAllStopMaxCabinStartBuilder(switch_cycle=switch_cycle),
        )


class FiveStationCircleCwHalfNoSkipNoWaitExample(FiveStationCircleCwFullNoSkipNoWaitExample):
    metadata = ScenarioExampleMetadata(
        id="five_station_circle_cw_half_no_skip_no_wait_v0",
        label="Five station circle cw half cabins no_skip+no_wait",
        description=(
            "Clockwise five-station circular ropeway with every second EAN start cabin, "
            "skip disabled, and station waiting disabled."
        ),
        tags=("circle", "cw", "ean-demo", "scaling-demo", "half-cabins", "no-skip", "no-waiting"),
        family_id="five_station_circle",
        family_label="Five station circle",
        variant_id="half_no_skip_no_wait",
        variant_label="Half cabins no_skip+no_wait",
    )

    spec = CircularSkipStopSpec(
        scenario_id=metadata.id,
        station_ids=FiveStationCircleCwFullNoSkipNoWaitExample.spec.station_ids,
        label=metadata.label,
        description=metadata.description,
        include_skip_routes=False,
        service_station_waiting_mode=StationWaitingMode.NO_WAITING,
        demand_count_per_od_pair=64,
    )

    def build_ean_artifact_builder(
        self,
        scenario: Scenario,
        config: EanConfig,
    ) -> EanBuildArtifactBuilder:
        switch_cycle = build_circular_skip_stop_ean_ring_switch_order(scenario, direction=self.spec.direction)
        return RingEanBuildArtifactBuilder(
            switch_cycle=switch_cycle,
            start_builder=KeepEverySecondCabinStartBuilder(
                ContinuousAllStopMaxCabinStartBuilder(switch_cycle=switch_cycle),
            ),
        )


class FiveStationCircleCwHalfSkipNoWaitExample(FiveStationCircleCwHalfNoSkipNoWaitExample):
    metadata = ScenarioExampleMetadata(
        id="five_station_circle_cw_half_skip_no_wait_v0",
        label="Five station circle cw half cabins skip+no_wait",
        description=(
            "Clockwise five-station circular ropeway with every second EAN start cabin, "
            "skip enabled, and station waiting disabled."
        ),
        tags=("circle", "cw", "skip-stop", "ean-demo", "scaling-demo", "half-cabins", "no-waiting"),
        family_id="five_station_circle",
        family_label="Five station circle",
        variant_id="half_skip_no_wait",
        variant_label="Half cabins skip+no_wait",
    )

    spec = CircularSkipStopSpec(
        scenario_id=metadata.id,
        station_ids=FiveStationCircleCwFullNoSkipNoWaitExample.spec.station_ids,
        label=metadata.label,
        description=metadata.description,
        include_skip_routes=True,
        service_station_waiting_mode=StationWaitingMode.NO_WAITING,
        demand_count_per_od_pair=64,
    )


class FiveStationCircleCwHalfSkipWaitExample(FiveStationCircleCwHalfNoSkipNoWaitExample):
    metadata = ScenarioExampleMetadata(
        id="five_station_circle_cw_half_skip_wait_v0",
        label="Five station circle cw half cabins skip+wait",
        description=(
            "Clockwise five-station circular ropeway with every second EAN start cabin, "
            "skip enabled, and station waiting enabled."
        ),
        tags=("circle", "cw", "skip-stop", "ean-demo", "scaling-demo", "half-cabins", "waiting"),
        family_id="five_station_circle",
        family_label="Five station circle",
        variant_id="half_skip_wait",
        variant_label="Half cabins skip+wait",
    )

    spec = CircularSkipStopSpec(
        scenario_id=metadata.id,
        station_ids=FiveStationCircleCwFullNoSkipNoWaitExample.spec.station_ids,
        label=metadata.label,
        description=metadata.description,
        include_skip_routes=True,
        service_station_waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT,
        demand_count_per_od_pair=64,
    )


class FiveStationOptimizedInitialPlacementNoSkipNoWaitExample(
    FiveStationCircleCwFullNoSkipNoWaitExample
):
    metadata = ScenarioExampleMetadata(
        id="five_station_optimized_initial_placement_no_skip_no_wait_v0",
        label="Five station optimized initial placement no_skip+no_wait",
        description=(
            "Five-station clockwise ring with optimized initial placement, "
            "explicit fleet limit, no skipping, and no waiting."
        ),
        tags=("circle", "cw", "optimized-initial-placement", "no-skip", "no-waiting"),
        family_id="five_station_circle",
        family_label="Five station circle",
        variant_id="optimized_initial_placement_no_skip_no_wait",
        variant_label="Initial placement no_skip+no_wait",
    )
    spec = CircularSkipStopSpec(
        scenario_id=metadata.id,
        station_ids=FiveStationCircleCwFullNoSkipNoWaitExample.spec.station_ids,
        label=metadata.label,
        description=metadata.description,
        include_skip_routes=False,
        service_station_waiting_mode=StationWaitingMode.NO_WAITING,
    )

    def build_ean_artifact_builder(
        self,
        scenario: Scenario,
        config: EanConfig,
    ) -> EanBuildArtifactBuilder:
        return _optimized_initial_placement_artifact_builder(scenario, self.spec.direction)


class FiveStationOptimizedInitialPlacementSkipNoWaitExample(
    FiveStationCircleCwHalfSkipNoWaitExample
):
    metadata = ScenarioExampleMetadata(
        id="five_station_optimized_initial_placement_skip_no_wait_v0",
        label="Five station optimized initial placement skip+no_wait",
        description=(
            "Five-station clockwise ring with optimized initial placement, "
            "explicit fleet limit, skipping enabled, and no waiting."
        ),
        tags=("circle", "cw", "skip-stop", "optimized-initial-placement", "no-waiting"),
        family_id="five_station_circle",
        family_label="Five station circle",
        variant_id="optimized_initial_placement_skip_no_wait",
        variant_label="Initial placement skip+no_wait",
    )
    spec = CircularSkipStopSpec(
        scenario_id=metadata.id,
        station_ids=FiveStationCircleCwFullNoSkipNoWaitExample.spec.station_ids,
        label=metadata.label,
        description=metadata.description,
        include_skip_routes=True,
        service_station_waiting_mode=StationWaitingMode.NO_WAITING,
    )

    def build_ean_artifact_builder(
        self,
        scenario: Scenario,
        config: EanConfig,
    ) -> EanBuildArtifactBuilder:
        return _optimized_initial_placement_artifact_builder(scenario, self.spec.direction)


class FiveStationOptimizedInitialPlacementDoubleAllStopSkipWaitExample(
    FiveStationCircleCwHalfSkipWaitExample
):
    """Passenger experiment with twice the canonical all-stop fleet available."""

    metadata = ScenarioExampleMetadata(
        id="five_station_optimized_initial_placement_double_all_stop_skip_wait_v0",
        label="Five station OIP 2x all-stop skip+wait",
        description=(
            "Five-station clockwise ring with optimized initial placement, "
            "76 available cabins, skipping enabled, and end-of-platform waiting."
        ),
        tags=(
            "circle",
            "cw",
            "skip-stop",
            "optimized-initial-placement",
            "double-all-stop-fleet",
            "waiting",
        ),
        family_id="five_station_circle",
        family_label="Five station circle",
        variant_id="optimized_initial_placement_double_all_stop_skip_wait",
        variant_label="OIP 76 cabins skip+wait",
    )
    spec = replace(
        FiveStationCircleCwHalfSkipWaitExample.spec,
        scenario_id=metadata.id,
        label=metadata.label,
        description=metadata.description,
    )

    def build_ean_artifact_builder(
        self,
        scenario: Scenario,
        config: EanConfig,
    ) -> EanBuildArtifactBuilder:
        return replace(
            _optimized_initial_placement_artifact_builder(
                scenario,
                self.spec.direction,
            ),
            fleet_config=EanFleetConfig(
                mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
                available_fleet_count=76,
            ),
        )


class FiveStationOptimizedInitialPlacementAllStopSkipWaitExample(
    FiveStationOptimizedInitialPlacementDoubleAllStopSkipWaitExample
):
    """Build-profile reference with the 38-cabin all-stop fleet available."""

    metadata = ScenarioExampleMetadata(
        id="five_station_optimized_initial_placement_all_stop_skip_wait_v0",
        label="Five station OIP all-stop fleet skip+wait",
        description=(
            "Five-station clockwise ring with optimized initial placement, "
            "38 available cabins, skipping enabled, and end-of-platform waiting."
        ),
        tags=(
            "circle",
            "cw",
            "skip-stop",
            "optimized-initial-placement",
            "all-stop-fleet",
            "waiting",
        ),
        family_id="five_station_circle",
        family_label="Five station circle",
        variant_id="optimized_initial_placement_all_stop_skip_wait",
        variant_label="OIP 38 cabins skip+wait",
    )
    spec = replace(
        FiveStationOptimizedInitialPlacementDoubleAllStopSkipWaitExample.spec,
        scenario_id=metadata.id,
        label=metadata.label,
        description=metadata.description,
    )

    def build_ean_artifact_builder(
        self,
        scenario: Scenario,
        config: EanConfig,
    ) -> EanBuildArtifactBuilder:
        return replace(
            _optimized_initial_placement_artifact_builder(
                scenario,
                self.spec.direction,
            ),
            fleet_config=EanFleetConfig(
                mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
                available_fleet_count=38,
            ),
        )


def _optimized_initial_placement_artifact_builder(
    scenario: Scenario,
    direction: str,
) -> RingEanBuildArtifactBuilder:
    return RingEanBuildArtifactBuilder(
        switch_cycle=build_circular_skip_stop_ean_ring_switch_order(
            scenario,
            direction=direction,
        ),
        fleet_config=EanFleetConfig(
            mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
            available_fleet_count=len(scenario.cabins),
        ),
    )


def build_five_station_circle_cw_full_no_skip_no_wait_scenario() -> Scenario:
    return build_circular_skip_stop_scenario(FiveStationCircleCwFullNoSkipNoWaitExample.spec)


def build_five_station_circle_cw_half_no_skip_no_wait_scenario() -> Scenario:
    return build_circular_skip_stop_scenario(FiveStationCircleCwHalfNoSkipNoWaitExample.spec)


def build_five_station_circle_cw_half_skip_no_wait_scenario() -> Scenario:
    return build_circular_skip_stop_scenario(FiveStationCircleCwHalfSkipNoWaitExample.spec)


def build_five_station_circle_cw_half_skip_wait_scenario() -> Scenario:
    return build_circular_skip_stop_scenario(FiveStationCircleCwHalfSkipWaitExample.spec)


def build_five_station_circle_cw_full_no_skip_no_wait_ean_config(
    scenario: Scenario | None = None,
    tail_seconds: float = 0.0,
) -> EanConfig:
    return build_circular_skip_stop_ean_config(
        scenario or build_five_station_circle_cw_full_no_skip_no_wait_scenario(),
        waiting_mode=StationWaitingMode.NO_WAITING,
        tail_seconds=tail_seconds,
    )


def build_five_station_circle_cw_half_no_skip_no_wait_ean_config(
    scenario: Scenario | None = None,
    tail_seconds: float = 0.0,
) -> EanConfig:
    return build_circular_skip_stop_ean_config(
        scenario or build_five_station_circle_cw_half_no_skip_no_wait_scenario(),
        waiting_mode=StationWaitingMode.NO_WAITING,
        tail_seconds=tail_seconds,
    )


def build_five_station_circle_cw_half_skip_no_wait_ean_config(
    scenario: Scenario | None = None,
    tail_seconds: float = 0.0,
) -> EanConfig:
    return build_circular_skip_stop_ean_config(
        scenario or build_five_station_circle_cw_half_skip_no_wait_scenario(),
        waiting_mode=StationWaitingMode.NO_WAITING,
        tail_seconds=tail_seconds,
    )


def build_five_station_circle_cw_half_skip_wait_ean_config(
    scenario: Scenario | None = None,
    tail_seconds: float = 0.0,
) -> EanConfig:
    return build_circular_skip_stop_ean_config(
        scenario or build_five_station_circle_cw_half_skip_wait_scenario(),
        waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT,
        tail_seconds=tail_seconds,
    )


def build_five_station_circle_cw_ean_ring_switch_order(
    scenario: Scenario | None = None,
) -> tuple[str, ...]:
    return build_circular_skip_stop_ean_ring_switch_order(
        scenario or build_five_station_circle_cw_full_no_skip_no_wait_scenario(),
    )


def build_circular_skip_stop_scenario(spec: CircularSkipStopSpec) -> Scenario:
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

    stations = tuple(
        Station(
            id=station_id,
            kind=StationKind.SERVICE,
            name=f"{station_id} station",
            route_ids=_station_route_ids(
                station_id,
                direction=spec.direction,
                include_skip_routes=spec.include_skip_routes,
            ),
        )
        for station_id in spec.station_ids
    )

    physical_nodes = tuple(
        node
        for station_id in spec.station_ids
        for node in _station_nodes(station_id, spec.direction)
    )
    track_segments = (
        *(
            segment
            for station_id in spec.station_ids
            for segment in _station_segments(
                station_id,
                spec.direction,
                fast_profile=rope_profile,
                platform_profile=platform_profile,
                brake_profile=brake_profile,
                accelerate_profile=accelerate_profile,
                platform_length_m=spec.platform_length_m,
                bypass_length_m=spec.bypass_length_m,
            )
        ),
        *_rope_segments(
            station_ids=spec.station_ids,
            direction=spec.direction,
            length_m=spec.rope_segment_length_m,
            rope_profile=rope_profile,
        ),
    )
    station_routes = tuple(
        route
        for station_id in spec.station_ids
        for route in _station_routes(
            station_id,
            direction=spec.direction,
            include_skip_routes=spec.include_skip_routes,
        )
    )

    cabins = tuple(Cabin(id=cabin_id) for cabin_id in range(spec.scenario_cabin_count))
    scenario = Scenario(
        id=spec.scenario_id,
        service_start_time=spec.service_start_time,
        service_end_time=spec.service_end_time,
        stations=stations,
        physical_nodes=physical_nodes,
        track_segments=track_segments,
        station_routes=station_routes,
        cabins=cabins,
        cabin_initial_states=_initial_states(
            cabin_count=spec.scenario_cabin_count,
            station_ids=spec.station_ids,
            direction=spec.direction,
            service_start_time=spec.service_start_time,
        ),
        demands=_all_od_demands(
            station_ids=spec.station_ids,
            arrival_time=spec.service_start_time,
            count=spec.demand_count_per_od_pair,
        ),
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


def build_circular_skip_stop_ean_config(
    scenario: Scenario,
    waiting_mode: StationWaitingMode,
    tail_seconds: float = 0.0,
) -> EanConfig:
    scenario.validate()
    config = EanConfig(
        horizon_seconds=_service_duration_seconds(scenario),
        tail_seconds=tail_seconds,
        cabin_capacity=scenario.operating.cabin_capacity,
        station_configs=tuple(
            StationEanConfig(station_id=station.id, waiting_mode=waiting_mode)
            for station in scenario.stations
            if station.kind is StationKind.SERVICE
        ),
    )
    config.validate()
    return config


def build_circular_skip_stop_ean_ring_switch_order(
    scenario: Scenario,
    direction: str = "cw",
) -> tuple[str, ...]:
    scenario.validate()
    switch_cycle = tuple(f"{station.id}_entry_{direction}" for station in scenario.stations if station.kind is StationKind.SERVICE)
    _validate_switch_cycle_is_physical_ring(scenario, switch_cycle)
    return switch_cycle


def _station_nodes(station: str, direction: str) -> tuple[PhysicalNode, ...]:
    return (
        PhysicalNode(id=f"{station}_entry_{direction}", kind=PhysicalNodeKind.ENTRY_SWITCH, station_id=station),
        PhysicalNode(id=f"{station}_service_approach_{direction}", kind=PhysicalNodeKind.CONNECTOR, station_id=station),
        PhysicalNode(id=f"{station}_platform_entry_{direction}", kind=PhysicalNodeKind.PLATFORM, station_id=station),
        PhysicalNode(id=f"{station}_platform_exit_{direction}", kind=PhysicalNodeKind.PLATFORM, station_id=station),
        PhysicalNode(id=f"{station}_service_accelerate_{direction}", kind=PhysicalNodeKind.CONNECTOR, station_id=station),
        PhysicalNode(id=f"{station}_exit_{direction}", kind=PhysicalNodeKind.EXIT_SWITCH, station_id=station),
    )


def _station_segments(
    station: str,
    direction: str,
    fast_profile: SpeedProfile,
    platform_profile: SpeedProfile,
    brake_profile: SpeedProfile,
    accelerate_profile: SpeedProfile,
    platform_length_m: float,
    bypass_length_m: float,
) -> tuple[TrackSegment, ...]:
    return (
        TrackSegment(
            id=f"{station}_{direction}_approach_fast",
            kind=TrackSegmentKind.CONNECTOR,
            from_node_id=f"{station}_entry_{direction}",
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
            to_node_id=f"{station}_exit_{direction}",
            length_m=5.0,
            speed_profile=fast_profile,
            resource_id=f"{station}_service_{direction}",
        ),
        TrackSegment(
            id=f"{station}_{direction}_skip_bypass",
            kind=TrackSegmentKind.SKIP,
            from_node_id=f"{station}_entry_{direction}",
            to_node_id=f"{station}_exit_{direction}",
            length_m=bypass_length_m,
            speed_profile=fast_profile,
            resource_id=f"{station}_skip_{direction}",
        ),
    )


def _rope_segments(
    station_ids: tuple[str, ...],
    direction: str,
    length_m: float,
    rope_profile: SpeedProfile,
) -> tuple[TrackSegment, ...]:
    segments: list[TrackSegment] = []
    for index, station_id in enumerate(station_ids):
        next_station_id = station_ids[(index + 1) % len(station_ids)]
        segments.append(
            TrackSegment(
                id=f"{station_id}_exit_{direction}_to_{next_station_id}_entry_{direction}",
                kind=TrackSegmentKind.ROPE,
                from_node_id=f"{station_id}_exit_{direction}",
                to_node_id=f"{next_station_id}_entry_{direction}",
                length_m=length_m,
                speed_profile=rope_profile,
                resource_id=f"rope_{direction}_{index + 1}",
            )
        )
    return tuple(segments)


def _station_route_ids(station: str, direction: str, include_skip_routes: bool) -> tuple[str, ...]:
    if include_skip_routes:
        return (f"{station}_service_{direction}", f"{station}_skip_{direction}")
    return (f"{station}_service_{direction}",)


def _station_routes(station: str, direction: str, include_skip_routes: bool) -> tuple[StationRoute, ...]:
    routes = [_station_service_route(station, direction)]
    if include_skip_routes:
        routes.append(_station_skip_route(station, direction))
    return tuple(routes)


def _station_service_route(station: str, direction: str) -> StationRoute:
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


def _station_skip_route(station: str, direction: str) -> StationRoute:
    return StationRoute(
        id=f"{station}_skip_{direction}",
        station_id=station,
        kind=StationRouteKind.SKIP,
        segment_ids=(f"{station}_{direction}_skip_bypass",),
        allows_boarding=False,
        allows_alighting=False,
    )


def _initial_states(
    cabin_count: int,
    station_ids: tuple[str, ...],
    direction: str,
    service_start_time: time,
) -> tuple[CabinInitialState, ...]:
    states: list[CabinInitialState] = []
    for cabin_id in range(cabin_count):
        station_id = station_ids[cabin_id % len(station_ids)]
        states.append(
            CabinInitialState(
                cabin_id=cabin_id,
                node_id=f"{station_id}_exit_{direction}",
                available_from=_add_seconds_to_time(service_start_time, 8 * cabin_id),
            )
        )
    return tuple(states)


def _all_od_demands(station_ids: tuple[str, ...], arrival_time: time, count: int) -> tuple[Demand, ...]:
    return tuple(
        Demand(arrival_time=arrival_time, origin=origin, destination=destination, count=count)
        for origin in station_ids
        for destination in station_ids
        if origin != destination
    )


def _service_duration_seconds(scenario: Scenario) -> float:
    start = datetime.combine(datetime.min.date(), scenario.service_start_time)
    end = datetime.combine(datetime.min.date(), scenario.service_end_time)
    return (end - start).total_seconds()


def _add_seconds_to_time(value: time, seconds: int) -> time:
    return (datetime.combine(datetime.min.date(), value) + timedelta(seconds=seconds)).time()


def _validate_switch_cycle_is_physical_ring(scenario: Scenario, switch_cycle: tuple[str, ...]) -> None:
    if not switch_cycle:
        raise ValueError("circular skip-stop EAN switch cycle must not be empty")

    nodes_by_id = {node.id: node for node in scenario.physical_nodes}
    segments_by_id = {segment.id: segment for segment in scenario.track_segments}

    for index, switch_id in enumerate(switch_cycle):
        next_switch_id = switch_cycle[(index + 1) % len(switch_cycle)]
        switch_node = nodes_by_id.get(switch_id)
        next_switch_node = nodes_by_id.get(next_switch_id)
        if switch_node is None:
            raise ValueError(f"circular skip-stop EAN switch cycle references unknown switch {switch_id!r}")
        if next_switch_node is None:
            raise ValueError(f"circular skip-stop EAN switch cycle references unknown switch {next_switch_id!r}")
        if switch_node.kind is not PhysicalNodeKind.ENTRY_SWITCH:
            raise ValueError(f"circular skip-stop EAN switch {switch_id!r} is not an entry switch")
        if next_switch_node.kind is not PhysicalNodeKind.ENTRY_SWITCH:
            raise ValueError(f"circular skip-stop EAN switch {next_switch_id!r} is not an entry switch")

        service_route = _single_service_route_from_switch(scenario.station_routes, segments_by_id, switch_id)
        exit_segment = segments_by_id[service_route.segment_ids[-1]]
        exit_node = nodes_by_id[exit_segment.to_node_id]
        if exit_node.kind is not PhysicalNodeKind.EXIT_SWITCH:
            raise ValueError(
                f"circular skip-stop EAN service route {service_route.id!r} does not end at an exit switch"
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
                "circular skip-stop EAN switch cycle is not physically connected: "
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
