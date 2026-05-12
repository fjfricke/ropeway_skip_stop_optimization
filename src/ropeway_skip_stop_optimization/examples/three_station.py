from __future__ import annotations

from datetime import time

from ropeway_skip_stop_optimization.examples.base import ScenarioExample, ScenarioExampleMetadata
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


class ThreeStationExample(ScenarioExample):
    metadata = ScenarioExampleMetadata(
        id="three_station_v0",
        label="Three station ring",
        description="Bidirectional three-station ropeway with terminal turnarounds and a middle skip route.",
        tags=("ring", "skip-stop", "discrete-time-demo"),
    )

    def build_scenario(self) -> Scenario:
        return build_three_station_scenario()


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
        PhysicalNode(id="L_platform_exit", kind=PhysicalNodeKind.PLATFORM, station_id="L", allows_waiting=True),
        PhysicalNode(id="L_exit_lr", kind=PhysicalNodeKind.EXIT_SWITCH, station_id="L"),
        PhysicalNode(id="R_entry_lr", kind=PhysicalNodeKind.ENTRY_SWITCH, station_id="R"),
        PhysicalNode(id="R_platform_entry", kind=PhysicalNodeKind.PLATFORM, station_id="R"),
        PhysicalNode(id="R_platform_exit", kind=PhysicalNodeKind.PLATFORM, station_id="R", allows_waiting=True),
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
            length_m=5.0,
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
            length_m=5.0,
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
            length_m=70.0,
            speed_profile=SpeedProfile(SpeedProfileKind.CONSTANT, speed_m_per_s=5.0),
            resource_id=f"M_skip_{direction}",
        ),
    )
