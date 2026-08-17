from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import heapq
import math

from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanActivationReference,
    EanTimeReference,
    HeadwayCandidate,
    HeadwayCheckpointDefinition,
    HeadwayCheckpointKind,
)


class EanPassengerBehavior(Enum):
    SERVICE = "service"
    SKIP = "skip"


class EanMovementEffect(Enum):
    """Physical effect of an option; only CONTINUE is solved in stage one."""

    CONTINUE = "continue"
    TURNBACK = "turnback"
    ROPE_TRANSFER = "rope_transfer"
    DEPOT_ENTRY = "depot_entry"
    DEPOT_EXIT = "depot_exit"


class EanResourceKind(Enum):
    PHYSICAL = "physical"
    COMPATIBILITY = "compatibility"


@dataclass(frozen=True)
class EanMovementState:
    id: str
    physical_node_id: str

    def validate(self) -> None:
        _require_id("movement state id", self.id)
        _require_id("movement state physical_node_id", self.physical_node_id)


@dataclass(frozen=True)
class EanResource:
    id: str
    kind: EanResourceKind
    physical_resource_id: str | None = None

    def validate(self) -> None:
        _require_id("EAN resource id", self.id)
        if not isinstance(self.kind, EanResourceKind):
            raise ValueError("EAN resource needs a valid kind")
        if self.kind is EanResourceKind.PHYSICAL:
            _require_id("physical resource id", self.physical_resource_id)
        elif self.physical_resource_id is not None:
            raise ValueError("compatibility resources must not reference a physical resource")


@dataclass(frozen=True)
class EanResourceUsage:
    resource_id: str
    time_reference: EanTimeReference
    activation_reference: EanActivationReference
    checkpoint_kind: HeadwayCheckpointKind | None = None

    def validate(self) -> None:
        _require_id("resource usage resource_id", self.resource_id)
        if not isinstance(self.time_reference, EanTimeReference):
            raise ValueError("resource usage needs a valid time reference")
        if not isinstance(self.activation_reference, EanActivationReference):
            raise ValueError("resource usage needs a valid activation reference")
        if self.checkpoint_kind is not None and not isinstance(
            self.checkpoint_kind, HeadwayCheckpointKind
        ):
            raise ValueError("resource usage needs a valid checkpoint kind")


@dataclass(frozen=True)
class EanRouteOption:
    id: str
    from_state_id: str
    to_state_id: str
    station_id: str
    station_route_id: str
    passenger_behavior: EanPassengerBehavior
    movement_effect: EanMovementEffect
    station_segment_ids: tuple[str, ...]
    continuation_segment_ids: tuple[str, ...]
    minimum_seconds: float
    maximum_seconds: float
    resource_usages: tuple[EanResourceUsage, ...]

    @property
    def segment_ids(self) -> tuple[str, ...]:
        return self.station_segment_ids + self.continuation_segment_ids

    def validate(self) -> None:
        for label, value in (
            ("route option id", self.id),
            ("route option from_state_id", self.from_state_id),
            ("route option to_state_id", self.to_state_id),
            ("route option station_id", self.station_id),
            ("route option station_route_id", self.station_route_id),
        ):
            _require_id(label, value)
        if not self.station_segment_ids or not self.continuation_segment_ids:
            raise ValueError("route options need station and continuation segments")
        if self.minimum_seconds < 0 or self.maximum_seconds < self.minimum_seconds:
            raise ValueError("route option time bounds are inconsistent")
        for usage in self.resource_usages:
            usage.validate()


@dataclass(frozen=True)
class EanCirculationPattern:
    id: str
    state_ids: tuple[str, ...]
    route_option_ids_by_position: tuple[tuple[str, ...], ...]

    def validate(self) -> None:
        _require_id("circulation pattern id", self.id)
        if not self.state_ids or len(set(self.state_ids)) != len(self.state_ids):
            raise ValueError("circulation pattern state ids must be nonempty and unique")
        if len(self.route_option_ids_by_position) != len(self.state_ids):
            raise ValueError("circulation pattern route options must match its positions")
        if any(not option_ids for option_ids in self.route_option_ids_by_position):
            raise ValueError("every circulation pattern position needs a route option")


@dataclass(frozen=True)
class EanCirculationPatternDefinition:
    """Stage-one deterministic pattern input derived from today's switch order."""

    id: str
    state_node_ids: tuple[str, ...]

    def validate(self) -> None:
        _require_id("circulation pattern definition id", self.id)
        if not self.state_node_ids or len(set(self.state_node_ids)) != len(self.state_node_ids):
            raise ValueError("circulation pattern node ids must be nonempty and unique")


@dataclass(frozen=True)
class EanMovementNetwork:
    states: tuple[EanMovementState, ...]
    route_options: tuple[EanRouteOption, ...]
    resources: tuple[EanResource, ...]
    circulation_patterns: tuple[EanCirculationPattern, ...]

    def validate(self) -> None:
        state_ids = _validated_ids("movement state", self.states)
        option_ids = _validated_ids("route option", self.route_options)
        resource_ids = _validated_ids("resource", self.resources)
        pattern_ids = _validated_ids("circulation pattern", self.circulation_patterns)
        options_by_id = {option.id: option for option in self.route_options}
        if not state_ids or not option_ids or not pattern_ids:
            raise ValueError("movement network needs states, route options, and patterns")
        for state in self.states:
            state.validate()
        for option in self.route_options:
            option.validate()
            if not isinstance(option.passenger_behavior, EanPassengerBehavior):
                raise ValueError(f"route option {option.id!r} needs a passenger behavior")
            if not isinstance(option.movement_effect, EanMovementEffect):
                raise ValueError(f"route option {option.id!r} needs a movement effect")
            if option.from_state_id not in state_ids or option.to_state_id not in state_ids:
                raise ValueError(f"route option {option.id!r} references an unknown state")
            unknown_resources = {usage.resource_id for usage in option.resource_usages} - resource_ids
            if unknown_resources:
                raise ValueError(f"route option {option.id!r} references unknown resources: {unknown_resources}")
        for resource in self.resources:
            resource.validate()
        for pattern in self.circulation_patterns:
            pattern.validate()
            if set(pattern.state_ids) - state_ids:
                raise ValueError(f"circulation pattern {pattern.id!r} references unknown states")
            referenced_options = {
                option_id
                for position_options in pattern.route_option_ids_by_position
                for option_id in position_options
            }
            if referenced_options - option_ids:
                raise ValueError(f"circulation pattern {pattern.id!r} references unknown route options")
            for position, position_option_ids in enumerate(
                pattern.route_option_ids_by_position
            ):
                from_state_id = pattern.state_ids[position]
                to_state_id = pattern.state_ids[(position + 1) % len(pattern.state_ids)]
                for option_id in position_option_ids:
                    option = options_by_id[option_id]
                    if (
                        option.from_state_id != from_state_id
                        or option.to_state_id != to_state_id
                    ):
                        raise ValueError(
                            f"circulation pattern {pattern.id!r} assigns route option "
                            f"{option_id!r} to the wrong position"
                        )

    def pattern(self, pattern_id: str) -> EanCirculationPattern:
        matches = tuple(pattern for pattern in self.circulation_patterns if pattern.id == pattern_id)
        if len(matches) != 1:
            raise ValueError(f"movement network has no unique pattern {pattern_id!r}")
        return matches[0]

    def minimum_return_seconds_by_state(self) -> dict[str, float]:
        """Shortest strictly positive movement cycle through every state."""

        self.validate()
        outgoing: dict[str, list[tuple[str, float]]] = {
            state.id: [] for state in self.states
        }
        for option in self.route_options:
            outgoing[option.from_state_id].append(
                (option.to_state_id, option.minimum_seconds)
            )
        result: dict[str, float] = {}
        for origin in outgoing:
            distances: dict[str, float] = {}
            queue: list[tuple[float, str]] = []
            for successor, seconds in outgoing[origin]:
                heapq.heappush(queue, (seconds, successor))
            while queue:
                seconds, state_id = heapq.heappop(queue)
                if state_id == origin:
                    result[origin] = seconds
                    break
                if seconds >= distances.get(state_id, math.inf):
                    continue
                distances[state_id] = seconds
                for successor, edge_seconds in outgoing[state_id]:
                    heapq.heappush(queue, (seconds + edge_seconds, successor))
            if origin not in result:
                result[origin] = math.inf
        return result

    def deterministic_corridors(self) -> tuple[tuple[str, ...], ...]:
        """Return current non-branching circulation corridors deterministically."""

        self.validate()
        return tuple(pattern.state_ids for pattern in self.circulation_patterns)


@dataclass(frozen=True)
class EanResourceConflictIndex:
    """Route-option and current candidate conflicts grouped by resource."""

    route_option_ids_by_resource_id: tuple[tuple[str, tuple[str, ...]], ...]
    candidate_ids_by_resource_id: tuple[tuple[str, tuple[str, ...]], ...]

    @property
    def complete_headway_pair_count(self) -> int:
        return sum(
            len(candidate_ids) * (len(candidate_ids) - 1) // 2
            for _, candidate_ids in self.candidate_ids_by_resource_id
        )

    @classmethod
    def build(
        cls,
        network: EanMovementNetwork,
        checkpoints: tuple[HeadwayCheckpointDefinition, ...],
        candidates: tuple[HeadwayCandidate, ...],
    ) -> EanResourceConflictIndex:
        network.validate()
        checkpoint_ids = {checkpoint.id for checkpoint in checkpoints}
        network_resource_ids = {resource.id for resource in network.resources}
        missing = checkpoint_ids - network_resource_ids
        if missing:
            raise ValueError(f"network is missing resources for checkpoints: {missing}")
        route_options_by_resource: dict[str, list[str]] = {
            resource.id: [] for resource in network.resources
        }
        for option in network.route_options:
            for resource_id in dict.fromkeys(
                usage.resource_id for usage in option.resource_usages
            ):
                route_options_by_resource[resource_id].append(option.id)

        grouped: dict[str, list[str]] = {checkpoint.id: [] for checkpoint in checkpoints}
        for candidate in candidates:
            if candidate.checkpoint_id not in grouped:
                raise ValueError(f"candidate references unknown checkpoint {candidate.checkpoint_id!r}")
            grouped[candidate.checkpoint_id].append(candidate.id)
        return cls(
            route_option_ids_by_resource_id=tuple(
                (resource_id, tuple(option_ids))
                for resource_id, option_ids in route_options_by_resource.items()
            ),
            candidate_ids_by_resource_id=tuple(
                (resource_id, tuple(candidate_ids))
                for resource_id, candidate_ids in grouped.items()
            )
        )


def compatibility_resource_id(kind: HeadwayCheckpointKind, state_id: str) -> str:
    return f"{kind.value}::{state_id}"


def _validated_ids(label: str, values: tuple[object, ...]) -> set[str]:
    ids = [getattr(value, "id") for value in values]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate {label} ids")
    return set(ids)


def _require_id(label: str, value: str | None) -> None:
    if value is None or not value.strip():
        raise ValueError(f"{label} must be nonempty")
