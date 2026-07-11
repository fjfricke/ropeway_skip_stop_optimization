from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, time
from typing import TYPE_CHECKING

from ropeway_skip_stop_optimization.mapping.physical_to_discrete import travel_seconds_for_segment
from ropeway_skip_stop_optimization.models import (
    PhysicalNode,
    PhysicalNodeKind,
    Scenario,
    TrackSegment,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanCabinStart,
    EanCabinStartKind,
    EanConfig,
)

if TYPE_CHECKING:
    from ropeway_skip_stop_optimization.optimization.ean.builders.headway_duration_builder import (
        HeadwayDurations,
    )
    from ropeway_skip_stop_optimization.optimization.ean.models import SkipStopTiming


class EanCabinStartBuilder(ABC):
    @abstractmethod
    def build(
        self,
        scenario: Scenario,
        config: EanConfig,
        target_switch_ids: frozenset[str],
    ) -> tuple[EanCabinStart, ...]:
        """Derive EAN cabin starts from scenario-specific start data."""


@dataclass(frozen=True)
class DeterministicPhysicalNodeToSwitchStartBuilder(EanCabinStartBuilder):
    """Map fixed physical cabin starts to the first reachable EAN switch.

    This builder intentionally rejects any branch before the first target switch.
    It is for starts whose physical path to the first EAN event is already
    deterministic, not for depot insertion or optimized initial positioning.
    """

    def build(
        self,
        scenario: Scenario,
        config: EanConfig,
        target_switch_ids: frozenset[str],
    ) -> tuple[EanCabinStart, ...]:
        scenario.validate()
        config.validate()

        nodes_by_id = {node.id: node for node in scenario.physical_nodes}
        _validate_target_switches(target_switch_ids, nodes_by_id)
        outgoing_segments_by_node = _build_outgoing_segments_by_node(scenario.track_segments)

        cabin_starts: list[EanCabinStart] = []
        for initial_state in sorted(scenario.cabin_initial_states, key=lambda state: state.cabin_id):
            start_node = nodes_by_id[initial_state.node_id]
            path = _find_deterministic_path_to_target_switch(
                start_node_id=initial_state.node_id,
                target_switch_ids=target_switch_ids,
                outgoing_segments_by_node=outgoing_segments_by_node,
            )
            time_seconds = _seconds_since_service_start(scenario.service_start_time, initial_state.available_from)
            time_seconds += path.travel_seconds
            if time_seconds > config.model_end_seconds:
                raise ValueError(
                    f"EAN cabin start for cabin {initial_state.cabin_id!r} is after model_end_seconds"
                )

            cabin_start = EanCabinStart(
                cabin_id=initial_state.cabin_id,
                first_switch_id=path.switch_id,
                kind=_start_kind_for_node(start_node),
                time_seconds=time_seconds,
            )
            cabin_start.validate()
            cabin_starts.append(cabin_start)

        return tuple(cabin_starts)


@dataclass(frozen=True)
class ContinuousAllStopMaxCabinStartBuilder(EanCabinStartBuilder):
    """Place the maximum number of all-stop cabins on a continuous switch ring.

    This builder is for ring examples with a fixed switch order and all cabins
    serving every station. It does not use discrete cells. Cabin starts are
    generated from equal continuous phases around the all-stop cycle and mapped
    to each cabin's next switch arrival at or after t=0.
    """

    switch_cycle: tuple[str, ...]

    def build(
        self,
        scenario: Scenario,
        config: EanConfig,
        target_switch_ids: frozenset[str],
    ) -> tuple[EanCabinStart, ...]:
        from ropeway_skip_stop_optimization.optimization.ean.builders.headway_duration_builder import (
            OperatingSpeedHeadwayDurationBuilder,
        )
        from ropeway_skip_stop_optimization.optimization.ean.builders.timing_builder import (
            PhysicalSkipStopTimingBuilder,
        )

        scenario.validate()
        config.validate()
        _validate_switch_cycle(self.switch_cycle)
        if target_switch_ids != frozenset(self.switch_cycle):
            raise ValueError("continuous all-stop starts must target exactly the configured switch_cycle")

        timings = PhysicalSkipStopTimingBuilder().build(scenario, self.switch_cycle)
        cycle_boundaries = _all_stop_cycle_boundaries(timings, self.switch_cycle)
        cycle_seconds = cycle_boundaries[-1].seconds
        headway_seconds = _max_all_stop_headway_seconds(
            OperatingSpeedHeadwayDurationBuilder().build(scenario, timings),
        )
        cabin_count = max(1, math.floor((cycle_seconds + 1e-9) / headway_seconds))
        phase_spacing_seconds = cycle_seconds / cabin_count

        starts: list[EanCabinStart] = []
        for cabin_id in range(cabin_count):
            phase_seconds = cabin_id * phase_spacing_seconds
            start = _start_for_phase(
                cabin_id=cabin_id,
                phase_seconds=phase_seconds,
                cycle_seconds=cycle_seconds,
                cycle_boundaries=cycle_boundaries,
            )
            start.validate()
            starts.append(start)

        return tuple(starts)


@dataclass(frozen=True)
class _StartPath:
    switch_id: str
    travel_seconds: float


@dataclass(frozen=True)
class _CycleBoundary:
    switch_id: str
    seconds: float


def _all_stop_cycle_boundaries(
    timings: tuple["SkipStopTiming", ...],
    switch_cycle: tuple[str, ...],
) -> tuple[_CycleBoundary, ...]:
    timings_by_switch_id = {timing.switch_id: timing for timing in timings}
    boundaries = [_CycleBoundary(switch_id=switch_cycle[0], seconds=0.0)]
    elapsed = 0.0
    for index, switch_id in enumerate(switch_cycle):
        timing = timings_by_switch_id[switch_id]
        elapsed += _all_stop_switch_to_next_seconds(timing)
        next_switch_id = switch_cycle[(index + 1) % len(switch_cycle)]
        boundaries.append(_CycleBoundary(switch_id=next_switch_id, seconds=elapsed))
    if elapsed <= 0:
        raise ValueError("continuous all-stop cycle duration must be positive")
    return tuple(boundaries)


def _all_stop_switch_to_next_seconds(timing: "SkipStopTiming") -> float:
    timing.validate()
    return (
        timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
        + timing.platform_exit_to_exit_switch_seconds
        + timing.rope_to_next_switch_seconds
    )


def _max_all_stop_headway_seconds(headway_durations: "HeadwayDurations") -> float:
    headway_durations.validate()
    headways = (
        *headway_durations.station_headway_seconds_by_station_id.values(),
        *headway_durations.exit_switch_headway_seconds_by_switch_id.values(),
    )
    return max(headways)


def _start_for_phase(
    cabin_id: int,
    phase_seconds: float,
    cycle_seconds: float,
    cycle_boundaries: tuple[_CycleBoundary, ...],
) -> EanCabinStart:
    tolerance_seconds = 1e-9
    normalized_phase_seconds = phase_seconds % cycle_seconds
    for boundary in cycle_boundaries[:-1]:
        if abs(normalized_phase_seconds - boundary.seconds) <= tolerance_seconds:
            return EanCabinStart(
                cabin_id=cabin_id,
                first_switch_id=boundary.switch_id,
                kind=EanCabinStartKind.FIXED,
                time_seconds=0.0,
            )
    for boundary in cycle_boundaries[1:]:
        if normalized_phase_seconds < boundary.seconds - tolerance_seconds:
            return EanCabinStart(
                cabin_id=cabin_id,
                first_switch_id=boundary.switch_id,
                kind=EanCabinStartKind.FIXED,
                time_seconds=boundary.seconds - normalized_phase_seconds,
            )

    first_boundary = cycle_boundaries[0]
    return EanCabinStart(
        cabin_id=cabin_id,
        first_switch_id=first_boundary.switch_id,
        kind=EanCabinStartKind.FIXED,
        time_seconds=cycle_seconds - normalized_phase_seconds,
    )


def _find_deterministic_path_to_target_switch(
    start_node_id: str,
    target_switch_ids: frozenset[str],
    outgoing_segments_by_node: dict[str, tuple[TrackSegment, ...]],
) -> _StartPath:
    current_node_id = start_node_id
    travel_seconds = 0.0
    visited_node_ids: set[str] = set()

    while True:
        if current_node_id in target_switch_ids:
            return _StartPath(switch_id=current_node_id, travel_seconds=travel_seconds)
        if current_node_id in visited_node_ids:
            raise ValueError(f"cycle before first EAN target switch from start node {start_node_id!r}")
        visited_node_ids.add(current_node_id)

        outgoing_segments = outgoing_segments_by_node.get(current_node_id, ())
        if not outgoing_segments:
            raise ValueError(f"no path from start node {start_node_id!r} to an EAN target switch")
        if len(outgoing_segments) > 1:
            raise ValueError(
                f"ambiguous path from start node {start_node_id!r}: node {current_node_id!r} "
                f"has {len(outgoing_segments)} outgoing segments before the first EAN target switch"
            )

        segment = outgoing_segments[0]
        travel_seconds += travel_seconds_for_segment(segment)
        current_node_id = segment.to_node_id


def _build_outgoing_segments_by_node(
    segments: tuple[TrackSegment, ...],
) -> dict[str, tuple[TrackSegment, ...]]:
    outgoing: dict[str, list[TrackSegment]] = {}
    for segment in segments:
        outgoing.setdefault(segment.from_node_id, []).append(segment)
    return {node_id: tuple(node_segments) for node_id, node_segments in outgoing.items()}


def _start_kind_for_node(node: PhysicalNode) -> EanCabinStartKind:
    if node.allows_waiting or node.kind in {PhysicalNodeKind.DEPOT, PhysicalNodeKind.HOLD}:
        return EanCabinStartKind.EARLIEST
    return EanCabinStartKind.FIXED


def _validate_target_switches(
    target_switch_ids: frozenset[str],
    nodes_by_id: dict[str, PhysicalNode],
) -> None:
    if not target_switch_ids:
        raise ValueError("EAN cabin start builder needs at least one target switch")
    for switch_id in sorted(target_switch_ids):
        if not switch_id:
            raise ValueError("EAN target switch ids must be nonempty")
        node = nodes_by_id.get(switch_id)
        if node is None:
            raise ValueError(f"EAN target switch references unknown physical node {switch_id!r}")
        if node.kind is not PhysicalNodeKind.ENTRY_SWITCH:
            raise ValueError(f"EAN target switch {switch_id!r} is not an entry switch")


def _seconds_since_service_start(service_start_time: time, value: time) -> float:
    start = datetime.combine(datetime.min.date(), service_start_time)
    target = datetime.combine(datetime.min.date(), value)
    return (target - start).total_seconds()


def _validate_switch_cycle(switch_cycle: tuple[str, ...]) -> None:
    if not switch_cycle:
        raise ValueError("continuous all-stop start builder needs a nonempty switch_cycle")
    seen: set[str] = set()
    duplicates: set[str] = set()
    for switch_id in switch_cycle:
        if not switch_id:
            raise ValueError("continuous all-stop switch ids must be nonempty")
        if switch_id in seen:
            duplicates.add(switch_id)
        seen.add(switch_id)
    if duplicates:
        raise ValueError(f"duplicate continuous all-stop switch ids: {duplicates}")
