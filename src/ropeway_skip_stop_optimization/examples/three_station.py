from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import time

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


class ThreeStationExample(ScenarioExample):
    metadata = ScenarioExampleMetadata(
        id="three_station_v0",
        label="Three station ring half cabins skip+wait",
        description=(
            "Bidirectional three-station ropeway with every second EAN start cabin, skip enabled, "
            "and middle-station waiting enabled."
        ),
        tags=("ring", "skip-stop", "discrete-time-demo", "half-cabins", "waiting"),
        family_id="three_station_ring",
        family_label="Three station ring",
        variant_id="half_cabins_skip_wait",
        variant_label="Half cabins skip+wait",
    )

    def build_scenario(self) -> Scenario:
        return build_three_station_scenario()

    def build_discretization_config(self, scenario: Scenario) -> DiscretizationConfig:
        config = DiscretizationConfig()
        config.validate()
        return config

    def build_ean_config(self, scenario: Scenario) -> EanConfig:
        from ropeway_skip_stop_optimization.examples.three_station_ean import build_three_station_ean_config

        return build_three_station_ean_config(scenario)

    def build_ean_artifact_builder(
        self,
        scenario: Scenario,
        config: EanConfig,
    ) -> EanBuildArtifactBuilder:
        from ropeway_skip_stop_optimization.examples.three_station_ean import build_three_station_ean_ring_switch_order

        switch_cycle = build_three_station_ean_ring_switch_order(scenario)
        return RingEanBuildArtifactBuilder(
            switch_cycle=switch_cycle,
            start_builder=KeepEverySecondCabinStartBuilder(
                ContinuousAllStopMaxCabinStartBuilder(switch_cycle=switch_cycle),
            ),
        )


class ThreeStationFullNoSkipNoWaitExample(ThreeStationExample):
    metadata = ScenarioExampleMetadata(
        id="three_station_full_no_skip_no_wait_v0",
        label="Three station ring full cabins no_skip+no_wait",
        description=(
            "Bidirectional three-station ropeway with all EAN start cabins, skip disabled, "
            "and station waiting disabled."
        ),
        tags=("ring", "discrete-time-demo", "full-cabins", "no-skip", "no-waiting"),
        family_id="three_station_ring",
        family_label="Three station ring",
        variant_id="full_cabins_no_skip_no_wait",
        variant_label="Full cabins no_skip+no_wait",
    )

    def build_scenario(self) -> Scenario:
        return build_three_station_no_skip_no_wait_scenario(self.metadata.id)

    def build_ean_config(self, scenario: Scenario) -> EanConfig:
        from ropeway_skip_stop_optimization.examples.three_station_ean import build_three_station_ean_config

        base_config = build_three_station_ean_config(scenario)
        return EanConfig(
            horizon_seconds=base_config.horizon_seconds,
            tail_seconds=base_config.tail_seconds,
            cabin_capacity=base_config.cabin_capacity,
            station_configs=tuple(
                StationEanConfig(station_id=config.station_id, waiting_mode=StationWaitingMode.NO_WAITING)
                for config in base_config.station_configs
            ),
        )

    def build_ean_artifact_builder(
        self,
        scenario: Scenario,
        config: EanConfig,
    ) -> EanBuildArtifactBuilder:
        from ropeway_skip_stop_optimization.examples.three_station_ean import build_three_station_ean_ring_switch_order

        switch_cycle = build_three_station_ean_ring_switch_order(scenario)
        return RingEanBuildArtifactBuilder(
            switch_cycle=switch_cycle,
            start_builder=ContinuousAllStopMaxCabinStartBuilder(switch_cycle=switch_cycle),
        )


class ThreeStationHalfNoSkipNoWaitExample(ThreeStationFullNoSkipNoWaitExample):
    metadata = ScenarioExampleMetadata(
        id="three_station_half_no_skip_no_wait_v0",
        label="Three station ring half cabins no_skip+no_wait",
        description=(
            "Bidirectional three-station ropeway with every second EAN start cabin, skip disabled, "
            "and station waiting disabled."
        ),
        tags=("ring", "discrete-time-demo", "half-cabins", "no-skip", "no-waiting"),
        family_id="three_station_ring",
        family_label="Three station ring",
        variant_id="half_cabins_no_skip_no_wait",
        variant_label="Half cabins no_skip+no_wait",
    )

    def build_ean_artifact_builder(
        self,
        scenario: Scenario,
        config: EanConfig,
    ) -> EanBuildArtifactBuilder:
        from ropeway_skip_stop_optimization.examples.three_station_ean import build_three_station_ean_ring_switch_order

        switch_cycle = build_three_station_ean_ring_switch_order(scenario)
        return RingEanBuildArtifactBuilder(
            switch_cycle=switch_cycle,
            start_builder=KeepEverySecondCabinStartBuilder(
                ContinuousAllStopMaxCabinStartBuilder(switch_cycle=switch_cycle),
            ),
        )


class ThreeStationOptimizedInitialPlacementExample(ThreeStationExample):
    metadata = ScenarioExampleMetadata(
        id="three_station_optimized_initial_placement_v0",
        label="Three station optimized initial placement",
        description=(
            "Three-station ring with an optimized physical fleet state at "
            "passenger-service start."
        ),
        tags=("ring", "skip-stop", "optimized-initial-placement"),
        family_id="three_station_ring",
        family_label="Three station ring",
        variant_id="optimized_initial_placement",
        variant_label="Optimized initial placement",
    )

    def build_scenario(self) -> Scenario:
        return replace(build_three_station_scenario(), id=self.metadata.id)

    def build_ean_artifact_builder(
        self,
        scenario: Scenario,
        config: EanConfig,
    ) -> EanBuildArtifactBuilder:
        from ropeway_skip_stop_optimization.examples.three_station_ean import (
            build_three_station_ean_ring_switch_order,
        )

        return RingEanBuildArtifactBuilder(
            switch_cycle=build_three_station_ean_ring_switch_order(scenario),
            fleet_config=EanFleetConfig(
                mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
                available_fleet_count=len(scenario.cabins),
            ),
        )


def build_three_station_scenario() -> Scenario:
    rope_speed = 5.0
    platform_speed = 0.5

    stations = (
        Station(id="L", kind=StationKind.TERMINAL, name="Left terminal", route_ids=("L_service_turnaround",)),
        Station(
            id="M",
            kind=StationKind.SERVICE,
            name="Middle station",
            route_ids=("M_service_lr", "M_skip_lr", "M_service_rl", "M_skip_rl"),
        ),
        Station(id="R", kind=StationKind.TERMINAL, name="Right terminal", route_ids=("R_service_turnaround",)),
    )

    physical_nodes = (
        PhysicalNode(id="L_entry_rl", kind=PhysicalNodeKind.ENTRY_SWITCH, station_id="L"),
        PhysicalNode(id="L_platform_entry", kind=PhysicalNodeKind.PLATFORM, station_id="L"),
        PhysicalNode(id="L_platform_exit", kind=PhysicalNodeKind.PLATFORM, station_id="L"),
        PhysicalNode(id="L_exit_lr", kind=PhysicalNodeKind.EXIT_SWITCH, station_id="L"),
        PhysicalNode(id="R_entry_lr", kind=PhysicalNodeKind.ENTRY_SWITCH, station_id="R"),
        PhysicalNode(id="R_platform_entry", kind=PhysicalNodeKind.PLATFORM, station_id="R"),
        PhysicalNode(id="R_platform_exit", kind=PhysicalNodeKind.PLATFORM, station_id="R"),
        PhysicalNode(id="R_exit_rl", kind=PhysicalNodeKind.EXIT_SWITCH, station_id="R"),
        PhysicalNode(id="M_entry_lr", kind=PhysicalNodeKind.ENTRY_SWITCH, station_id="M"),
        PhysicalNode(id="M_service_approach_lr", kind=PhysicalNodeKind.CONNECTOR, station_id="M"),
        PhysicalNode(id="M_platform_entry_lr", kind=PhysicalNodeKind.PLATFORM, station_id="M"),
        PhysicalNode(id="M_platform_exit_lr", kind=PhysicalNodeKind.PLATFORM, station_id="M"),
        PhysicalNode(id="M_service_accelerate_lr", kind=PhysicalNodeKind.CONNECTOR, station_id="M"),
        PhysicalNode(id="M_exit_lr", kind=PhysicalNodeKind.EXIT_SWITCH, station_id="M"),
        PhysicalNode(id="M_entry_rl", kind=PhysicalNodeKind.ENTRY_SWITCH, station_id="M"),
        PhysicalNode(id="M_service_approach_rl", kind=PhysicalNodeKind.CONNECTOR, station_id="M"),
        PhysicalNode(id="M_platform_entry_rl", kind=PhysicalNodeKind.PLATFORM, station_id="M"),
        PhysicalNode(id="M_platform_exit_rl", kind=PhysicalNodeKind.PLATFORM, station_id="M"),
        PhysicalNode(id="M_service_accelerate_rl", kind=PhysicalNodeKind.CONNECTOR, station_id="M"),
        PhysicalNode(id="M_exit_rl", kind=PhysicalNodeKind.EXIT_SWITCH, station_id="M"),
    )

    rope_profile = SpeedProfile(SpeedProfileKind.CONSTANT, speed_m_per_s=rope_speed)
    platform_profile = SpeedProfile(SpeedProfileKind.CONSTANT, speed_m_per_s=platform_speed)
    brake_profile = SpeedProfile(
        SpeedProfileKind.LINEAR,
        start_speed_m_per_s=rope_speed,
        end_speed_m_per_s=platform_speed,
    )
    accelerate_profile = SpeedProfile(
        SpeedProfileKind.LINEAR,
        start_speed_m_per_s=platform_speed,
        end_speed_m_per_s=rope_speed,
    )

    track_segments = (
        *_terminal_station_segments("L", "rl", "lr", platform_profile, brake_profile, accelerate_profile),
        *_terminal_station_segments("R", "lr", "rl", platform_profile, brake_profile, accelerate_profile),
        TrackSegment(
            id="L_exit_lr_to_M_entry_lr",
            kind=TrackSegmentKind.ROPE,
            from_node_id="L_exit_lr",
            to_node_id="M_entry_lr",
            length_m=150.0,
            speed_profile=rope_profile,
            resource_id="rope_lr_1",
        ),
        TrackSegment(
            id="M_exit_lr_to_R_entry_lr",
            kind=TrackSegmentKind.ROPE,
            from_node_id="M_exit_lr",
            to_node_id="R_entry_lr",
            length_m=150.0,
            speed_profile=rope_profile,
            resource_id="rope_lr_2",
        ),
        TrackSegment(
            id="R_exit_rl_to_M_entry_rl",
            kind=TrackSegmentKind.ROPE,
            from_node_id="R_exit_rl",
            to_node_id="M_entry_rl",
            length_m=150.0,
            speed_profile=rope_profile,
            resource_id="rope_rl_1",
        ),
        TrackSegment(
            id="M_exit_rl_to_L_entry_rl",
            kind=TrackSegmentKind.ROPE,
            from_node_id="M_exit_rl",
            to_node_id="L_entry_rl",
            length_m=150.0,
            speed_profile=rope_profile,
            resource_id="rope_rl_2",
        ),
        *(_middle_station_segments("lr", rope_profile, platform_profile, brake_profile, accelerate_profile)),
        *(_middle_station_segments("rl", rope_profile, platform_profile, brake_profile, accelerate_profile)),
    )

    station_routes = (
        StationRoute(
            id="L_service_turnaround",
            station_id="L",
            kind=StationRouteKind.SERVICE,
            segment_ids=("L_turnaround_decelerate", "L_turnaround_platform", "L_turnaround_accelerate"),
            allows_boarding=True,
            allows_alighting=True,
        ),
        StationRoute(
            id="M_service_lr",
            station_id="M",
            kind=StationRouteKind.SERVICE,
            segment_ids=(
                "M_lr_approach_fast",
                "M_lr_brake",
                "M_lr_platform",
                "M_lr_accelerate",
                "M_lr_depart_fast",
            ),
            allows_boarding=True,
            allows_alighting=True,
        ),
        StationRoute(
            id="M_skip_lr",
            station_id="M",
            kind=StationRouteKind.SKIP,
            segment_ids=("M_lr_skip_bypass",),
            allows_boarding=False,
            allows_alighting=False,
        ),
        StationRoute(
            id="M_service_rl",
            station_id="M",
            kind=StationRouteKind.SERVICE,
            segment_ids=(
                "M_rl_approach_fast",
                "M_rl_brake",
                "M_rl_platform",
                "M_rl_accelerate",
                "M_rl_depart_fast",
            ),
            allows_boarding=True,
            allows_alighting=True,
        ),
        StationRoute(
            id="M_skip_rl",
            station_id="M",
            kind=StationRouteKind.SKIP,
            segment_ids=("M_rl_skip_bypass",),
            allows_boarding=False,
            allows_alighting=False,
        ),
        StationRoute(
            id="R_service_turnaround",
            station_id="R",
            kind=StationRouteKind.SERVICE,
            segment_ids=("R_turnaround_decelerate", "R_turnaround_platform", "R_turnaround_accelerate"),
            allows_boarding=True,
            allows_alighting=True,
        ),
    )

    cabins = tuple(Cabin(id=cabin_id) for cabin_id in range(4))
    cabin_initial_states = (
        CabinInitialState(cabin_id=0, node_id="L_platform_exit", available_from=time(8, 0)),
        CabinInitialState(cabin_id=1, node_id="R_platform_exit", available_from=time(8, 0)),
        CabinInitialState(cabin_id=2, node_id="L_platform_exit", available_from=time(8, 2)),
        CabinInitialState(cabin_id=3, node_id="R_platform_exit", available_from=time(8, 2)),
    )

    scenario = Scenario(
        id=ThreeStationExample.metadata.id,
        service_start_time=time(8, 0),
        service_end_time=time(8, 20),
        stations=stations,
        physical_nodes=physical_nodes,
        track_segments=track_segments,
        station_routes=station_routes,
        cabins=cabins,
        cabin_initial_states=cabin_initial_states,
        demands=build_three_station_near_capacity_demands(),
        operating=OperatingParameters(
            rope_speed_m_per_s=rope_speed,
            station_speed_m_per_s=platform_speed,
            cabin_capacity=8,
            cabin_length_m=3.0,
            min_clearance_m=0.5,
        ),
    )
    scenario.validate()
    return scenario


def build_three_station_no_skip_no_wait_scenario(
    scenario_id: str = ThreeStationFullNoSkipNoWaitExample.metadata.id,
) -> Scenario:
    base = build_three_station_scenario()
    skip_route_ids = frozenset({"M_skip_lr", "M_skip_rl"})
    skip_segment_ids = frozenset({"M_lr_skip_bypass", "M_rl_skip_bypass"})
    scenario = Scenario(
        id=scenario_id,
        service_start_time=base.service_start_time,
        service_end_time=base.service_end_time,
        stations=tuple(
            replace(
                station,
                route_ids=tuple(route_id for route_id in station.route_ids if route_id not in skip_route_ids),
            )
            if station.id == "M"
            else station
            for station in base.stations
        ),
        physical_nodes=base.physical_nodes,
        track_segments=tuple(segment for segment in base.track_segments if segment.id not in skip_segment_ids),
        station_routes=tuple(route for route in base.station_routes if route.id not in skip_route_ids),
        cabins=base.cabins,
        cabin_initial_states=base.cabin_initial_states,
        demands=base.demands,
        operating=base.operating,
    )
    scenario.validate()
    return scenario


def build_three_station_near_capacity_demands() -> tuple[Demand, ...]:
    return (
        Demand(arrival_time=time(8, 0), origin="L", destination="M", count=580),
        Demand(arrival_time=time(8, 0), origin="L", destination="R", count=580),
        Demand(arrival_time=time(8, 0), origin="M", destination="L", count=580),
        Demand(arrival_time=time(8, 0), origin="M", destination="R", count=580),
        Demand(arrival_time=time(8, 0), origin="R", destination="L", count=580),
        Demand(arrival_time=time(8, 0), origin="R", destination="M", count=580),
    )


def _terminal_station_segments(
    station: str,
    entry_direction: str,
    exit_direction: str,
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
            length_m=10.0,
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
    direction: str,
    fast_profile: SpeedProfile,
    platform_profile: SpeedProfile,
    brake_profile: SpeedProfile,
    accelerate_profile: SpeedProfile,
) -> tuple[TrackSegment, ...]:
    entry = f"M_entry_{direction}"
    exit_node = f"M_exit_{direction}"
    return (
        TrackSegment(
            id=f"M_{direction}_approach_fast",
            kind=TrackSegmentKind.CONNECTOR,
            from_node_id=entry,
            to_node_id=f"M_service_approach_{direction}",
            length_m=5.0,
            speed_profile=fast_profile,
            resource_id=f"M_service_{direction}",
        ),
        TrackSegment(
            id=f"M_{direction}_brake",
            kind=TrackSegmentKind.CONNECTOR,
            from_node_id=f"M_service_approach_{direction}",
            to_node_id=f"M_platform_entry_{direction}",
            length_m=3.0,
            speed_profile=brake_profile,
            resource_id=f"M_service_{direction}",
        ),
        TrackSegment(
            id=f"M_{direction}_platform",
            kind=TrackSegmentKind.STATION,
            from_node_id=f"M_platform_entry_{direction}",
            to_node_id=f"M_platform_exit_{direction}",
            length_m=10.0,
            speed_profile=platform_profile,
            resource_id=f"M_service_{direction}",
        ),
        TrackSegment(
            id=f"M_{direction}_accelerate",
            kind=TrackSegmentKind.CONNECTOR,
            from_node_id=f"M_platform_exit_{direction}",
            to_node_id=f"M_service_accelerate_{direction}",
            length_m=3.0,
            speed_profile=accelerate_profile,
            resource_id=f"M_service_{direction}",
        ),
        TrackSegment(
            id=f"M_{direction}_depart_fast",
            kind=TrackSegmentKind.CONNECTOR,
            from_node_id=f"M_service_accelerate_{direction}",
            to_node_id=exit_node,
            length_m=5.0,
            speed_profile=fast_profile,
            resource_id=f"M_service_{direction}",
        ),
        TrackSegment(
            id=f"M_{direction}_skip_bypass",
            kind=TrackSegmentKind.SKIP,
            from_node_id=entry,
            to_node_id=exit_node,
            length_m=20.0,
            speed_profile=SpeedProfile(SpeedProfileKind.CONSTANT, speed_m_per_s=5.0),
            resource_id=f"M_skip_{direction}",
        ),
    )
