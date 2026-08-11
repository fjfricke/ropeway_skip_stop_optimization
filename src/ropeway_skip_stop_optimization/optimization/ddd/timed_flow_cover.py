from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256

from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import DddTimeTick


class DddTimedFlowTimingScope(StrEnum):
    """Physical timing semantics under which a timed-flow proof is valid."""

    NO_WAIT = "no_wait"


@dataclass(frozen=True)
class DddTimedFlowRegion:
    """Stable timed movement region represented by one or more refined arcs.

    ``origin_timed_arc_id`` is diagnostic provenance only.  The remaining
    fields define the region.  After a DDD time split, the flow of the region
    is the sum of every child arc whose source and target cells are contained
    in these original half-open intervals.
    """

    visit_index: int
    route_option_id: str
    source_lower_tick: DddTimeTick
    source_upper_tick: DddTimeTick
    target_lower_tick: DddTimeTick
    target_upper_tick: DddTimeTick
    cabin_id: int | None = None
    resource_ids: tuple[str, ...] = ()
    timing_scope: DddTimedFlowTimingScope = DddTimedFlowTimingScope.NO_WAIT
    origin_timed_arc_id: str = field(default="", compare=False, hash=False)

    def validate(self) -> None:
        if self.visit_index < 0:
            raise ValueError("DDD timed-flow visit index must be nonnegative")
        if not self.route_option_id.strip():
            raise ValueError("DDD timed-flow route option id must be nonempty")
        if self.source_lower_tick >= self.source_upper_tick:
            raise ValueError("DDD timed-flow source interval must be nonempty")
        if self.target_lower_tick >= self.target_upper_tick:
            raise ValueError("DDD timed-flow target interval must be nonempty")
        if self.cabin_id is not None and self.cabin_id < 0:
            raise ValueError("DDD timed-flow cabin id must be nonnegative")
        if tuple(sorted(set(self.resource_ids))) != self.resource_ids:
            raise ValueError("DDD timed-flow resource ids must be sorted and unique")
        if not isinstance(self.timing_scope, DddTimedFlowTimingScope):
            raise ValueError("DDD timed-flow timing scope is invalid")

    @property
    def key(self) -> tuple[object, ...]:
        return (
            self.visit_index,
            self.route_option_id,
            -1 if self.cabin_id is None else self.cabin_id,
            self.source_lower_tick,
            self.source_upper_tick,
            self.target_lower_tick,
            self.target_upper_tick,
            self.timing_scope.value,
            self.resource_ids,
        )

    @property
    def id(self) -> str:
        payload = "|".join(str(item) for item in self.key)
        return f"timed_flow_region::{sha256(payload.encode()).hexdigest()[:20]}"


@dataclass(frozen=True)
class DddTimedArcFlowCount:
    region: DddTimedFlowRegion
    count: int

    def validate(self) -> None:
        self.region.validate()
        if self.count <= 0:
            raise ValueError("DDD timed-flow support stores positive counts only")

    @property
    def sort_key(self) -> tuple[object, ...]:
        return (*self.region.key, self.count)


@dataclass(frozen=True)
class DddCpSatTimedFlowSupport:
    """Positive timed-arc flows selected by one anonymous DDD master solution."""

    arc_flows: tuple[DddTimedArcFlowCount, ...]

    def validate(self) -> None:
        if not self.arc_flows:
            raise ValueError("DDD timed-flow support must not be empty")
        region_ids: set[str] = set()
        previous_key: tuple[object, ...] | None = None
        for item in self.arc_flows:
            item.validate()
            if item.region.id in region_ids:
                raise ValueError(f"duplicate DDD timed-flow region: {item.region.id}")
            if previous_key is not None and item.sort_key < previous_key:
                raise ValueError("DDD timed-flow support must be sorted")
            region_ids.add(item.region.id)
            previous_key = item.sort_key


@dataclass(frozen=True)
class DddTimedFlowThresholdLiteral:
    """Predicate stating that at least ``minimum_flow`` uses one timed region."""

    region: DddTimedFlowRegion
    minimum_flow: int

    def validate(self) -> None:
        self.region.validate()
        if self.minimum_flow <= 0:
            raise ValueError("DDD timed-flow threshold must be positive")

    @property
    def sort_key(self) -> tuple[object, ...]:
        return (*self.region.key, self.minimum_flow)

    @property
    def id(self) -> str:
        return f"{self.region.id}::ge::{self.minimum_flow}"


@dataclass(frozen=True)
class DddTimedFlowCoverCut:
    """CP-certified cover: not every timed-flow threshold can hold together."""

    id: str
    literals: tuple[DddTimedFlowThresholdLiteral, ...]

    def validate(self) -> None:
        if not self.id.strip() or not self.literals:
            raise ValueError("DDD timed-flow cover needs an id and literals")
        literal_ids: set[str] = set()
        previous_key: tuple[object, ...] | None = None
        for literal in self.literals:
            literal.validate()
            if literal.id in literal_ids:
                raise ValueError(f"duplicate DDD timed-flow literal: {literal.id}")
            if previous_key is not None and literal.sort_key < previous_key:
                raise ValueError("DDD timed-flow cover literals must be sorted")
            literal_ids.add(literal.id)
            previous_key = literal.sort_key

    @classmethod
    def from_core(
        cls,
        literals: tuple[DddTimedFlowThresholdLiteral, ...],
    ) -> DddTimedFlowCoverCut:
        by_id = {literal.id: literal for literal in literals}
        canonical = tuple(sorted(by_id.values(), key=lambda item: item.sort_key))
        if not canonical:
            raise ValueError("empty CP-SAT core cannot create a timed-flow cover")
        payload = "|".join(literal.id for literal in canonical)
        result = cls(
            id=f"timed_flow_cover::{sha256(payload.encode()).hexdigest()[:20]}",
            literals=canonical,
        )
        result.validate()
        return result

    @property
    def resource_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    resource_id
                    for literal in self.literals
                    for resource_id in literal.region.resource_ids
                }
            )
        )
