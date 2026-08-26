from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, time
from typing import TYPE_CHECKING

from ropeway_skip_stop_optimization.mapping.physical_to_discrete import travel_seconds_for_segment
from ropeway_skip_stop_optimization.models import (
    DerivedHeadwayPolicy,
    DerivedSpatialRole,
    HeadwayRouteBehavior,
    PhysicalNode,
    PhysicalNodeKind,
    Scenario,
    TrackSegment,
    TrackSegmentKind,
    SpeedProfileKind,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanCabinStart,
    EanCabinStartKind,
    EanConfig,
)
from ropeway_skip_stop_optimization.optimization.ean.network import (
    EanCirculationPattern,
    EanMovementNetwork,
)

if TYPE_CHECKING:
    from ropeway_skip_stop_optimization.optimization.ean.artifact import (
        EanBuildArtifact,
    )
    from ropeway_skip_stop_optimization.optimization.ean.models import SkipStopTiming


class EanCabinStartBuilder(ABC):
    @abstractmethod
    def build(
        self,
        scenario: Scenario,
        config: EanConfig,
        network: EanMovementNetwork,
        pattern: EanCirculationPattern,
        headway_policy: DerivedHeadwayPolicy | None = None,
    ) -> tuple[EanCabinStart, ...]:
        """Derive EAN cabin starts from scenario-specific start data."""


@dataclass(frozen=True)
class ExplicitEanCabinStartBuilder(EanCabinStartBuilder):
    """Reuse an already validated physical snapshot as fixed EAN starts."""

    starts: tuple[EanCabinStart, ...]

    def build(
        self,
        scenario: Scenario,
        config: EanConfig,
        network: EanMovementNetwork,
        pattern: EanCirculationPattern,
        headway_policy: DerivedHeadwayPolicy | None = None,
    ) -> tuple[EanCabinStart, ...]:
        del scenario, config, headway_policy
        _validate_selected_pattern(network, pattern)
        state_ids = set(pattern.state_ids)
        if not self.starts:
            raise ValueError("explicit EAN starts must not be empty")
        if tuple(start.cabin_id for start in self.starts) != tuple(
            range(len(self.starts))
        ):
            raise ValueError("explicit EAN starts need canonical cabin IDs")
        for start in self.starts:
            start.validate()
            if start.first_switch_id not in state_ids:
                raise ValueError("explicit EAN start references another pattern")
            if start.kind is not EanCabinStartKind.FIXED:
                raise ValueError("explicit EAN starts must be fixed")
        return self.starts


@dataclass(frozen=True)
class EanAllStopStartCapacityAnalysis:
    """Exact no-wait capacity of one deterministic all-stop circulation."""

    cycle_seconds: float
    limiting_headway_seconds: float
    maximum_cabin_count: int
    limiting_resource_ids: tuple[str, ...]

    @property
    def throughput_cabins_per_second(self) -> float:
        return 1.0 / self.limiting_headway_seconds

    def minimum_slack_seconds(self, cabin_count: int) -> float:
        if cabin_count <= 0:
            raise ValueError("all-stop slack needs a positive cabin count")
        return self.cycle_seconds / cabin_count - self.limiting_headway_seconds

    def validate(self) -> None:
        if self.cycle_seconds <= 0 or self.limiting_headway_seconds <= 0:
            raise ValueError("all-stop capacity times must be positive")
        if self.maximum_cabin_count != max(
            1,
            math.floor(
                (self.cycle_seconds + 1e-9) / self.limiting_headway_seconds
            ),
        ):
            raise ValueError("all-stop maximum cabin count is inconsistent")
        if not self.limiting_resource_ids:
            raise ValueError("all-stop capacity needs a limiting resource")


def analyze_all_stop_start_capacity(
    artifact: "EanBuildArtifact",
) -> EanAllStopStartCapacityAnalysis:
    """Analyze the all-stop cycle represented by a built network artifact."""

    artifact.validate()
    policy = artifact.headway_policy
    if policy is None:
        raise ValueError("all-stop capacity analysis requires headway provenance")
    timing_by_switch_id = {item.switch_id: item for item in artifact.timings}
    cycle_seconds = sum(
        _all_stop_switch_to_next_seconds(timing_by_switch_id[switch_id])
        for switch_id in artifact.circulation_state_ids
    )
    service = HeadwayRouteBehavior.SERVICE
    values = tuple(
        (
            resource.id,
            policy.rule(resource.rule_id).required_seconds(service, service),
        )
        for resource in policy.resource_requirements
        if resource.applies_to_service
    )
    if not values:
        raise ValueError("all-stop capacity analysis found no service resource")
    limiting = max(value for _, value in values)
    result = EanAllStopStartCapacityAnalysis(
        cycle_seconds=cycle_seconds,
        limiting_headway_seconds=limiting,
        maximum_cabin_count=max(
            1,
            math.floor((cycle_seconds + 1e-9) / limiting),
        ),
        limiting_resource_ids=tuple(
            sorted(
                resource_id
                for resource_id, value in values
                if math.isclose(value, limiting, rel_tol=0.0, abs_tol=1e-9)
            )
        ),
    )
    result.validate()
    return result


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
        network: EanMovementNetwork,
        pattern: EanCirculationPattern,
        headway_policy: DerivedHeadwayPolicy | None = None,
    ) -> tuple[EanCabinStart, ...]:
        del headway_policy
        scenario.validate()
        config.validate()
        _validate_selected_pattern(network, pattern)
        target_switch_ids = frozenset(pattern.state_ids)

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
class EvenlySpacedAllStopCabinStartBuilder(EanCabinStartBuilder):
    """Place a fixed number of evenly spaced cabins on an all-stop pattern."""

    cabin_count: int

    def build(
        self,
        scenario: Scenario,
        config: EanConfig,
        network: EanMovementNetwork,
        pattern: EanCirculationPattern,
        headway_policy: DerivedHeadwayPolicy | None = None,
    ) -> tuple[EanCabinStart, ...]:
        cycle_boundaries, cycle_seconds, maximum_cabin_count = (
            _continuous_all_stop_start_parameters(
                scenario=scenario,
                config=config,
                network=network,
                pattern=pattern,
                headway_policy=headway_policy,
            )
        )
        if self.cabin_count <= 0:
            raise ValueError("evenly spaced all-stop cabin_count must be positive")
        if self.cabin_count > maximum_cabin_count:
            raise ValueError(
                "evenly spaced all-stop cabin_count exceeds the circulation "
                f"capacity: {self.cabin_count} > {maximum_cabin_count}"
            )
        return _evenly_spaced_all_stop_starts(
            cabin_count=self.cabin_count,
            cycle_seconds=cycle_seconds,
            cycle_boundaries=cycle_boundaries,
        )


@dataclass(frozen=True)
class EanCanonicalRopeStartSlot:
    """One physically packed cabin position on a common interstation rope."""

    pattern_position: int
    segment_id: str
    first_switch_id: str
    remaining_seconds: float


@dataclass(frozen=True)
class CanonicalFixedKRopeCabinStartBuilder(EanCabinStartBuilder):
    """Build mode-independent Fixed-K starts on common rope continuations.

    The construction is deliberately conservative: cabins are placed only on
    physical rope segments traversed by every option at a pattern position.
    It therefore does not rely on an executable all-stop circulation and can
    define the same initial state above the all-stop capacity.
    """

    cabin_count: int

    def build(
        self,
        scenario: Scenario,
        config: EanConfig,
        network: EanMovementNetwork,
        pattern: EanCirculationPattern,
        headway_policy: DerivedHeadwayPolicy | None = None,
    ) -> tuple[EanCabinStart, ...]:
        del config
        if self.cabin_count <= 0:
            raise ValueError("canonical fixed-K cabin_count must be positive")
        if headway_policy is None:
            raise ValueError("canonical fixed-K starts require a headway policy")
        slots = self.slots(
            scenario=scenario,
            network=network,
            pattern=pattern,
            headway_policy=headway_policy,
        )
        if self.cabin_count > len(slots):
            raise ValueError(
                "canonical fixed-K cabin_count exceeds conservative rope-slot "
                f"capacity: {self.cabin_count} > {len(slots)}"
            )
        selected = tuple(
            slots[(index * len(slots)) // self.cabin_count]
            for index in range(self.cabin_count)
        )
        starts = tuple(
            EanCabinStart(
                cabin_id=cabin_id,
                first_switch_id=slot.first_switch_id,
                kind=EanCabinStartKind.FIXED,
                time_seconds=slot.remaining_seconds,
            )
            for cabin_id, slot in enumerate(selected)
        )
        for start in starts:
            start.validate()
        return starts

    @classmethod
    def canonical_start_slot_capacity(
        cls,
        *,
        scenario: Scenario,
        network: EanMovementNetwork,
        pattern: EanCirculationPattern,
        headway_policy: DerivedHeadwayPolicy,
    ) -> int:
        """Return this constructor's conservative capacity, not a global bound."""

        return len(
            cls.slots(
                scenario=scenario,
                network=network,
                pattern=pattern,
                headway_policy=headway_policy,
            )
        )

    @staticmethod
    def slots(
        *,
        scenario: Scenario,
        network: EanMovementNetwork,
        pattern: EanCirculationPattern,
        headway_policy: DerivedHeadwayPolicy,
    ) -> tuple[EanCanonicalRopeStartSlot, ...]:
        scenario.validate()
        network.validate()
        pattern.validate()
        headway_policy.validate()
        segments_by_id = {segment.id: segment for segment in scenario.track_segments}
        options_by_id = {option.id: option for option in network.route_options}
        state_by_physical_node_id = {
            state.physical_node_id: state.id for state in network.states
        }
        incoming_count_by_state_id: dict[str, int] = {}
        for segment in scenario.track_segments:
            state_id = state_by_physical_node_id.get(segment.to_node_id)
            if segment.kind is TrackSegmentKind.ROPE and state_id is not None:
                incoming_count_by_state_id[state_id] = (
                    incoming_count_by_state_id.get(state_id, 0) + 1
                )
        ambiguous = tuple(
            sorted(
                state_id
                for state_id in pattern.state_ids
                if incoming_count_by_state_id.get(state_id, 0) != 1
            )
        )
        if ambiguous:
            raise ValueError(
                "canonical fixed-K rope starts do not yet support movement states "
                f"with non-unique incoming ropes: {ambiguous}"
            )

        spacing_m = headway_policy.spatial_spacing(DerivedSpatialRole.ROPE)
        slots: list[EanCanonicalRopeStartSlot] = []
        for position, option_ids in enumerate(pattern.route_option_ids_by_position):
            continuation_paths = tuple(
                options_by_id[option_id].continuation_segment_ids
                for option_id in option_ids
            )
            if any(path != continuation_paths[0] for path in continuation_paths[1:]):
                raise ValueError(
                    "canonical fixed-K starts require identical continuation paths "
                    f"at pattern position {position}"
                )
            path = continuation_paths[0]
            downstream_seconds = 0.0
            target_state_id = pattern.state_ids[(position + 1) % len(pattern.state_ids)]
            segment_slots: list[EanCanonicalRopeStartSlot] = []
            for segment_id in reversed(path):
                segment = segments_by_id[segment_id]
                if segment.kind is not TrackSegmentKind.ROPE:
                    downstream_seconds += travel_seconds_for_segment(segment)
                    continue
                profile = segment.speed_profile
                if (
                    profile is None
                    or profile.kind is not SpeedProfileKind.CONSTANT
                    or profile.speed_m_per_s is None
                ):
                    raise ValueError(
                        "canonical fixed-K rope starts currently require constant "
                        f"rope speed: {segment.id!r}"
                    )
                capacity = math.floor(
                    (segment.length_m + scenario.operating.min_clearance_m)
                    / spacing_m
                    + 1e-12
                )
                for slot_index in range(capacity):
                    center_distance_m = (
                        0.5 * scenario.operating.cabin_length_m
                        + slot_index * spacing_m
                    )
                    if center_distance_m > (
                        segment.length_m
                        - 0.5 * scenario.operating.cabin_length_m
                        + 1e-9
                    ):
                        continue
                    segment_slots.append(
                        EanCanonicalRopeStartSlot(
                            pattern_position=position,
                            segment_id=segment.id,
                            first_switch_id=target_state_id,
                            remaining_seconds=(
                                downstream_seconds
                                + center_distance_m / profile.speed_m_per_s
                            ),
                        )
                    )
                downstream_seconds += travel_seconds_for_segment(segment)
            slots.extend(reversed(segment_slots))
        return tuple(
            sorted(
                slots,
                key=lambda item: (
                    item.pattern_position,
                    -item.remaining_seconds,
                    item.segment_id,
                ),
            )
        )


@dataclass(frozen=True)
class ContinuousAllStopMaxCabinStartBuilder(EanCabinStartBuilder):
    """Place the maximum number of cabins on a continuous all-stop pattern.

    This builder is for deterministic circulation patterns with all cabins
    serving every station. It does not use discrete cells. Cabin starts are
    generated from equal continuous phases around the all-stop cycle and mapped
    to each cabin's next switch arrival at or after t=0.
    """

    def build(
        self,
        scenario: Scenario,
        config: EanConfig,
        network: EanMovementNetwork,
        pattern: EanCirculationPattern,
        headway_policy: DerivedHeadwayPolicy | None = None,
    ) -> tuple[EanCabinStart, ...]:
        cycle_boundaries, cycle_seconds, cabin_count = (
            _continuous_all_stop_start_parameters(
                scenario=scenario,
                config=config,
                network=network,
                pattern=pattern,
                headway_policy=headway_policy,
            )
        )
        return _evenly_spaced_all_stop_starts(
            cabin_count=cabin_count,
            cycle_seconds=cycle_seconds,
            cycle_boundaries=cycle_boundaries,
        )


def _continuous_all_stop_start_parameters(
    *,
    scenario: Scenario,
    config: EanConfig,
    network: EanMovementNetwork,
    pattern: EanCirculationPattern,
    headway_policy: DerivedHeadwayPolicy | None,
) -> tuple[tuple[_CycleBoundary, ...], float, int]:
    from ropeway_skip_stop_optimization.optimization.ean.builders.network_timing_builder import (
        NetworkSkipStopTimingBuilder,
    )
    from ropeway_skip_stop_optimization.optimization.headway_policy import (
        PhysicalHeadwayPolicyBuilder,
    )
    scenario.validate()
    config.validate()
    _validate_selected_pattern(network, pattern)
    timings = NetworkSkipStopTimingBuilder().build(
        scenario,
        network,
        pattern,
    )
    cycle_boundaries = _all_stop_cycle_boundaries(timings, pattern.state_ids)
    cycle_seconds = cycle_boundaries[-1].seconds
    policy = headway_policy or PhysicalHeadwayPolicyBuilder().build(
        scenario,
        network,
        timings,
        pattern,
    )
    headway_seconds = _max_all_stop_headway_seconds(policy)
    maximum_cabin_count = max(
        1,
        math.floor((cycle_seconds + 1e-9) / headway_seconds),
    )
    return cycle_boundaries, cycle_seconds, maximum_cabin_count


def _evenly_spaced_all_stop_starts(
    *,
    cabin_count: int,
    cycle_seconds: float,
    cycle_boundaries: tuple[_CycleBoundary, ...],
) -> tuple[EanCabinStart, ...]:
    phase_spacing_seconds = cycle_seconds / cabin_count
    starts: list[EanCabinStart] = []
    for cabin_id in range(cabin_count):
        start = _start_for_phase(
            cabin_id=cabin_id,
            phase_seconds=cabin_id * phase_spacing_seconds,
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
    state_ids: tuple[str, ...],
) -> tuple[_CycleBoundary, ...]:
    timings_by_switch_id = {timing.switch_id: timing for timing in timings}
    boundaries = [_CycleBoundary(switch_id=state_ids[0], seconds=0.0)]
    elapsed = 0.0
    for index, switch_id in enumerate(state_ids):
        timing = timings_by_switch_id[switch_id]
        elapsed += _all_stop_switch_to_next_seconds(timing)
        next_switch_id = state_ids[(index + 1) % len(state_ids)]
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


def _max_all_stop_headway_seconds(policy: DerivedHeadwayPolicy) -> float:
    policy.validate()
    service = HeadwayRouteBehavior.SERVICE
    return max(
        policy.rule(resource.rule_id).required_seconds(service, service)
        for resource in policy.resource_requirements
        if resource.applies_to_service
    )


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


def _validate_selected_pattern(
    network: EanMovementNetwork,
    pattern: EanCirculationPattern,
) -> None:
    network.validate()
    pattern.validate()
    if network.pattern(pattern.id) != pattern:
        raise ValueError("selected circulation pattern does not match the movement network")
