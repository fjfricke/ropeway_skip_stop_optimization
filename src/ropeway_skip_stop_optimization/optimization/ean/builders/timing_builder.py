from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ropeway_skip_stop_optimization.mapping.physical_to_discrete import travel_seconds_for_segment
from ropeway_skip_stop_optimization.models import (
    Scenario,
    TrackSegment,
    TrackSegmentKind,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.ring_topology_builder import (
    PhysicalRingTopologyBuilder,
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
    topology_builder: PhysicalRingTopologyBuilder = PhysicalRingTopologyBuilder()

    def build(
        self,
        scenario: Scenario,
        switch_cycle: tuple[str, ...],
    ) -> tuple[SkipStopTiming, ...]:
        scenario.validate()
        topology = self.topology_builder.build(scenario, switch_cycle)
        segments_by_id = {
            segment.id: segment for segment in scenario.track_segments
        }
        timings: list[SkipStopTiming] = []

        for station_topology in topology.stations:
            service_segments = tuple(
                segments_by_id[segment_id]
                for segment_id in station_topology.service_segment_ids
            )

            station_segment_indices = [
                segment_index
                for segment_index, segment in enumerate(service_segments)
                if segment.kind is TrackSegmentKind.STATION
            ]
            if not station_segment_indices:
                raise ValueError(
                    f"service route {station_topology.service_route_id!r} "
                    "needs at least one station segment"
                )
            if station_segment_indices != list(range(station_segment_indices[0], station_segment_indices[-1] + 1)):
                raise ValueError(
                    f"service route {station_topology.service_route_id!r} "
                    "station segments must be contiguous"
                )

            first_station_segment_index = station_segment_indices[0]
            last_station_segment_index = station_segment_indices[-1]
            entry_to_platform_entry_seconds = _travel_seconds(service_segments[:first_station_segment_index])
            min_platform_entry_to_platform_exit_seconds = _travel_seconds(
                service_segments[first_station_segment_index : last_station_segment_index + 1]
            )
            platform_exit_to_exit_switch_seconds = _travel_seconds(
                service_segments[last_station_segment_index + 1 :]
            )

            skip_allowed = station_topology.skip_route_id is not None
            service_entry_to_exit_seconds = _travel_seconds(service_segments)
            if not skip_allowed:
                skip_entry_to_exit_switch_seconds = service_entry_to_exit_seconds
            else:
                skip_segments = tuple(
                    segments_by_id[segment_id]
                    for segment_id in station_topology.skip_segment_ids
                )
                skip_entry_to_exit_switch_seconds = _travel_seconds(skip_segments)

            rope_to_next_switch_seconds = travel_seconds_for_segment(
                segments_by_id[station_topology.rope_segment_id]
            )

            timing = SkipStopTiming(
                switch_id=station_topology.switch_id,
                station_id=station_topology.station_id,
                entry_to_platform_entry_seconds=entry_to_platform_entry_seconds,
                min_platform_entry_to_platform_exit_seconds=min_platform_entry_to_platform_exit_seconds,
                platform_exit_to_exit_switch_seconds=platform_exit_to_exit_switch_seconds,
                skip_entry_to_exit_switch_seconds=skip_entry_to_exit_switch_seconds,
                rope_to_next_switch_seconds=rope_to_next_switch_seconds,
                skip_allowed=skip_allowed,
                exit_switch_id=station_topology.exit_switch_id,
            )
            timing.validate()
            timings.append(timing)

        return tuple(timings)


def _travel_seconds(segments: tuple[TrackSegment, ...]) -> float:
    if not segments:
        return 0.0
    return sum(travel_seconds_for_segment(segment) for segment in segments)
