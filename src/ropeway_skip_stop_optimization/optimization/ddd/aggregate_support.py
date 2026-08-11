from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddPartialTimedPath,
)


@dataclass(frozen=True, order=True)
class DddAggregateRouteCount:
    """One route-option multiplicity in an anonymous visit layer."""

    visit_index: int
    route_option_id: str
    count: int

    def validate(self) -> None:
        if self.visit_index < 0:
            raise ValueError("DDD aggregate route visit index must be nonnegative")
        if not self.route_option_id.strip():
            raise ValueError("DDD aggregate route option id must not be empty")
        if self.count < 0:
            raise ValueError("DDD aggregate route count must be nonnegative")


@dataclass(frozen=True)
class DddCpSatFixedSupport:
    """Cabin-independent route multiplicities selected by the DDD master.

    Only positive counts are stored.  The CP-SAT oracle completes the support
    with zero counts for every route option that is structurally available in
    a visit layer.  Fixing that complete count vector preserves the master's
    Stop/Skip decisions while leaving the assignment to physical cabin ids to
    CP-SAT.
    """

    route_counts: tuple[DddAggregateRouteCount, ...]

    def validate(self) -> None:
        keys: set[tuple[int, str]] = set()
        for item in self.route_counts:
            item.validate()
            if item.count <= 0:
                raise ValueError("DDD fixed support stores positive route counts only")
            key = (item.visit_index, item.route_option_id)
            if key in keys:
                raise ValueError(f"duplicate DDD aggregate route count: {key}")
            keys.add(key)

    @classmethod
    def from_paths(
        cls,
        paths: tuple[DddPartialTimedPath, ...],
    ) -> DddCpSatFixedSupport:
        counts: dict[tuple[int, str], int] = {}
        cabin_ids: set[int] = set()
        for path in paths:
            if path.cabin_id in cabin_ids:
                raise ValueError(
                    f"duplicate DDD fixed-support path cabin: {path.cabin_id}"
                )
            cabin_ids.add(path.cabin_id)
            for arc in path.arcs:
                key = (arc.visit_index, arc.route_option_id)
                counts[key] = counts.get(key, 0) + 1
        result = cls(
            tuple(
                DddAggregateRouteCount(visit_index, route_option_id, count)
                for (visit_index, route_option_id), count in sorted(counts.items())
            )
        )
        result.validate()
        return result

    @property
    def count_by_key(self) -> dict[tuple[int, str], int]:
        return {
            (item.visit_index, item.route_option_id): item.count
            for item in self.route_counts
        }


@dataclass(frozen=True, order=True)
class DddAggregateRouteCountLiteral:
    """Equality literal ``route_count[visit, option] == count``."""

    visit_index: int
    route_option_id: str
    count: int

    def validate(self) -> None:
        DddAggregateRouteCount(
            self.visit_index,
            self.route_option_id,
            self.count,
        ).validate()


@dataclass(frozen=True)
class DddAggregateSupportCut:
    """Logic-based no-good over an infeasible aggregate route-count core."""

    id: str
    literals: tuple[DddAggregateRouteCountLiteral, ...]

    def validate(self) -> None:
        if not self.id.strip() or not self.literals:
            raise ValueError("DDD aggregate support cut needs an id and literals")
        keys: set[tuple[int, str]] = set()
        for literal in self.literals:
            literal.validate()
            key = (literal.visit_index, literal.route_option_id)
            if key in keys:
                raise ValueError(f"duplicate DDD aggregate support literal: {key}")
            keys.add(key)

    @classmethod
    def from_core(
        cls,
        literals: tuple[DddAggregateRouteCountLiteral, ...],
    ) -> DddAggregateSupportCut:
        canonical = tuple(sorted(set(literals)))
        if not canonical:
            raise ValueError("empty CP-SAT core cannot create an aggregate cut")
        payload = "|".join(
            f"{item.visit_index}:{item.route_option_id}:{item.count}"
            for item in canonical
        )
        result = cls(
            id=f"aggregate_support::{sha256(payload.encode()).hexdigest()[:20]}",
            literals=canonical,
        )
        result.validate()
        return result


@dataclass(frozen=True)
class DddAggregateSupportDistanceCut:
    """Exclude an L1 ball around one aggregate route-count vector."""

    id: str
    center: tuple[DddAggregateRouteCountLiteral, ...]
    minimum_distance: int

    def validate(self) -> None:
        if not self.id.strip() or not self.center:
            raise ValueError("DDD aggregate distance cut needs an id and center")
        if self.minimum_distance <= 0:
            raise ValueError("DDD aggregate distance must be positive")
        keys: set[tuple[int, str]] = set()
        for literal in self.center:
            literal.validate()
            key = (literal.visit_index, literal.route_option_id)
            if key in keys:
                raise ValueError(f"duplicate DDD aggregate distance coordinate: {key}")
            keys.add(key)

    @classmethod
    def from_center(
        cls,
        center: tuple[DddAggregateRouteCountLiteral, ...],
        *,
        minimum_distance: int,
    ) -> DddAggregateSupportDistanceCut:
        canonical = tuple(sorted(set(center)))
        if not canonical:
            raise ValueError("empty center cannot create an aggregate distance cut")
        payload = "|".join(
            f"{item.visit_index}:{item.route_option_id}:{item.count}"
            for item in canonical
        )
        payload = f"{payload}|distance:{minimum_distance}"
        result = cls(
            id=f"aggregate_distance::{sha256(payload.encode()).hexdigest()[:20]}",
            center=canonical,
            minimum_distance=minimum_distance,
        )
        result.validate()
        return result
