from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.mapping.physical_to_discrete import travel_seconds_for_segment
from ropeway_skip_stop_optimization.models import Scenario, TrackSegment, TrackSegmentKind
from ropeway_skip_stop_optimization.optimization.ean.models import SkipStopTiming
from ropeway_skip_stop_optimization.optimization.ean.network import (
    EanCirculationPattern,
    EanMovementNetwork,
    EanPassengerBehavior,
    EanRouteOption,
)


@dataclass(frozen=True)
class NetworkSkipStopTimingBuilder:
    """Build compatibility timings from a deterministic circulation pattern."""

    def build(
        self,
        scenario: Scenario,
        network: EanMovementNetwork,
        pattern: EanCirculationPattern,
    ) -> tuple[SkipStopTiming, ...]:
        scenario.validate()
        network.validate()
        segments_by_id = {segment.id: segment for segment in scenario.track_segments}
        options_by_id = {option.id: option for option in network.route_options}
        timings: list[SkipStopTiming] = []

        for state_id, option_ids in zip(
            pattern.state_ids, pattern.route_option_ids_by_position, strict=True
        ):
            position_options = tuple(options_by_id[option_id] for option_id in option_ids)
            service_option = _single_behavior_option(position_options, EanPassengerBehavior.SERVICE)
            skip_options = tuple(
                option
                for option in position_options
                if option.passenger_behavior is EanPassengerBehavior.SKIP
            )
            if len(skip_options) > 1:
                raise ValueError(f"pattern state {state_id!r} has multiple skip options")
            service_segments = tuple(
                segments_by_id[segment_id]
                for segment_id in service_option.station_segment_ids
            )
            station_indices = [
                index
                for index, segment in enumerate(service_segments)
                if segment.kind is TrackSegmentKind.STATION
            ]
            if not station_indices:
                raise ValueError(
                    f"service route {service_option.station_route_id!r} needs a station segment"
                )
            if station_indices != list(range(station_indices[0], station_indices[-1] + 1)):
                raise ValueError(
                    f"service route {service_option.station_route_id!r} station segments must be contiguous"
                )
            first_station = station_indices[0]
            last_station = station_indices[-1]
            continuation_segments = tuple(
                segments_by_id[segment_id]
                for segment_id in service_option.continuation_segment_ids
            )
            if len(continuation_segments) != 1:
                raise ValueError("stage-one network timing requires one continuation segment")
            service_seconds = _travel_seconds(service_segments)
            skip_allowed = bool(skip_options)
            skip_seconds = (
                _travel_seconds(
                    tuple(
                        segments_by_id[segment_id]
                        for segment_id in skip_options[0].station_segment_ids
                    )
                )
                if skip_allowed
                else service_seconds
            )
            timing = SkipStopTiming(
                switch_id=state_id,
                station_id=service_option.station_id,
                entry_to_platform_entry_seconds=_travel_seconds(service_segments[:first_station]),
                min_platform_entry_to_platform_exit_seconds=_travel_seconds(
                    service_segments[first_station : last_station + 1]
                ),
                platform_exit_to_exit_switch_seconds=_travel_seconds(
                    service_segments[last_station + 1 :]
                ),
                skip_entry_to_exit_switch_seconds=skip_seconds,
                rope_to_next_switch_seconds=_travel_seconds(continuation_segments),
                skip_allowed=skip_allowed,
                exit_switch_id=service_segments[-1].to_node_id,
            )
            timing.validate()
            timings.append(timing)
        return tuple(timings)


def _single_behavior_option(
    options: tuple[EanRouteOption, ...], behavior: EanPassengerBehavior
) -> EanRouteOption:
    matches = tuple(option for option in options if option.passenger_behavior is behavior)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {behavior.value} route option, found {len(matches)}")
    return matches[0]


def _travel_seconds(segments: tuple[TrackSegment, ...]) -> float:
    return sum(travel_seconds_for_segment(segment) for segment in segments)
