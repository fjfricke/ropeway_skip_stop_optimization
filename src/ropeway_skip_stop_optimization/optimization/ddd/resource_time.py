from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from functools import reduce
from hashlib import sha1
from math import gcd

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddResource,
    DddResourceUsage,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddTimeCell,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    DddTimeTick,
)


@dataclass(frozen=True, order=True)
class DddTickInterval:
    """A nonempty half-open interval in the canonical DDD tick domain."""

    lower_tick: DddTimeTick
    upper_tick: DddTimeTick

    def validate(self) -> None:
        if self.lower_tick >= self.upper_tick:
            raise ValueError("DDD tick interval must have positive width")

    @property
    def last_tick(self) -> DddTimeTick:
        self.validate()
        return self.upper_tick - 1

    @property
    def width_ticks(self) -> int:
        self.validate()
        return self.upper_tick - self.lower_tick

    def contains_tick(self, tick: DddTimeTick) -> bool:
        return self.lower_tick <= tick < self.upper_tick


@dataclass(frozen=True, order=True)
class DddBoundedTickDelay:
    minimum_tick: DddTimeTick = 0
    maximum_tick: DddTimeTick = 0

    def validate(self) -> None:
        if self.minimum_tick < 0:
            raise ValueError("DDD resource timing delay must be nonnegative")
        if self.minimum_tick > self.maximum_tick:
            raise ValueError("DDD resource timing delay bounds are inconsistent")


class DddResourceTimingAssumption(StrEnum):
    NO_WAIT = "no_wait"
    BOUNDED_WAIT_ENVELOPE = "bounded_wait_envelope"


class DddResourceWindowCutMode(StrEnum):
    OFF = "off"
    ENTRY_COUNT = "entry_count"
    ENTRY_AND_ENERGY = "entry_and_energy"


@dataclass(frozen=True)
class DddTimedResourceUsageWindow:
    """Conservative timing envelope of one resource use on one timed arc.

    The source interval already includes all upstream timing freedom represented
    by the timed arc. Separate delays describe additional timing freedom between
    the arc source event and the follower-enter or leader-clear occurrence. The
    two delay ranges need not be independent in the physical model: using their
    marginal extrema is conservative for mandatory cores and universal conflict
    proofs.
    """

    timed_arc_id: str
    resource_id: str
    source_interval: DddTickInterval
    follower_enter_offset_tick: DddTimeTick
    leader_clear_offset_tick: DddTimeTick
    headway_tick: DddTimeTick
    usage_index: int = 0
    follower_enter_delay: DddBoundedTickDelay = DddBoundedTickDelay()
    leader_clear_delay: DddBoundedTickDelay = DddBoundedTickDelay()
    timing_assumption: DddResourceTimingAssumption = DddResourceTimingAssumption.NO_WAIT

    @classmethod
    def from_usage(
        cls,
        *,
        timed_arc_id: str,
        source_interval: DddTickInterval,
        resource: DddResource,
        usage: DddResourceUsage,
        usage_index: int = 0,
        follower_enter_delay: DddBoundedTickDelay = DddBoundedTickDelay(),
        leader_clear_delay: DddBoundedTickDelay = DddBoundedTickDelay(),
        timing_assumption: DddResourceTimingAssumption = (
            DddResourceTimingAssumption.NO_WAIT
        ),
    ) -> DddTimedResourceUsageWindow:
        if resource.id != usage.resource_id:
            raise ValueError("DDD resource timing usage and resource differ")
        result = cls(
            timed_arc_id=timed_arc_id,
            resource_id=resource.id,
            source_interval=source_interval,
            follower_enter_offset_tick=usage.follower_enter_offset_tick,
            leader_clear_offset_tick=usage.leader_clear_offset_tick,
            headway_tick=usage.separation_after_tick(
                resource.minimum_headway_tick
            ),
            usage_index=usage_index,
            follower_enter_delay=follower_enter_delay,
            leader_clear_delay=leader_clear_delay,
            timing_assumption=timing_assumption,
        )
        result.validate()
        return result

    def validate(self) -> None:
        if not self.timed_arc_id.strip() or not self.resource_id.strip():
            raise ValueError("DDD resource timing ids must be nonempty")
        self.source_interval.validate()
        self.follower_enter_delay.validate()
        self.leader_clear_delay.validate()
        if self.follower_enter_offset_tick < 0:
            raise ValueError("DDD resource enter offset must be nonnegative")
        if self.leader_clear_offset_tick < 0:
            raise ValueError("DDD resource clear offset must be nonnegative")
        if self.headway_tick <= 0:
            raise ValueError("DDD resource headway must be positive")
        if self.usage_index < 0:
            raise ValueError("DDD resource usage index must be nonnegative")
        if not isinstance(self.timing_assumption, DddResourceTimingAssumption):
            raise ValueError("DDD resource timing assumption is invalid")
        if self.timing_assumption is DddResourceTimingAssumption.NO_WAIT and (
            self.follower_enter_delay != DddBoundedTickDelay()
            or self.leader_clear_delay != DddBoundedTickDelay()
        ):
            raise ValueError("DDD no-wait resource timing cannot contain delays")

    @property
    def earliest_follower_enter_tick(self) -> DddTimeTick:
        return (
            self.source_interval.lower_tick
            + self.follower_enter_offset_tick
            + self.follower_enter_delay.minimum_tick
        )

    @property
    def latest_follower_enter_tick(self) -> DddTimeTick:
        return (
            self.source_interval.last_tick
            + self.follower_enter_offset_tick
            + self.follower_enter_delay.maximum_tick
        )

    @property
    def earliest_leader_clear_tick(self) -> DddTimeTick:
        return (
            self.source_interval.lower_tick
            + self.leader_clear_offset_tick
            + self.leader_clear_delay.minimum_tick
        )

    @property
    def minimum_clear_after_enter_tick(self) -> DddTimeTick:
        """Universal lower bound on clear minus entry for one realization."""

        return (
            self.leader_clear_offset_tick
            + self.leader_clear_delay.minimum_tick
            - self.follower_enter_offset_tick
            - self.follower_enter_delay.maximum_tick
        )

    @property
    def minimum_protected_occupancy_tick(self) -> DddTimeTick:
        return self.minimum_clear_after_enter_tick + self.headway_tick

    @property
    def latest_leader_clear_tick(self) -> DddTimeTick:
        return (
            self.source_interval.last_tick
            + self.leader_clear_offset_tick
            + self.leader_clear_delay.maximum_tick
        )

    @property
    def mandatory_occupancy_core(self) -> DddTickInterval | None:
        lower = self.latest_follower_enter_tick
        upper = self.earliest_leader_clear_tick + self.headway_tick
        if lower >= upper:
            return None
        return DddTickInterval(lower, upper)

    @property
    def id(self) -> str:
        return (
            f"{self.timed_arc_id}::resource::{self.resource_id}::"
            f"usage::{self.usage_index}"
        )


class DddAnonymousResourceRowKind(StrEnum):
    MANDATORY_CORE = "mandatory_core"
    UNIVERSAL_CONFLICT = "universal_conflict"
    INTERVAL_CAPACITY = "interval_capacity"
    INTERVAL_ENERGY = "interval_energy"


@dataclass(frozen=True, order=True)
class DddAnonymousResourceRowTerm:
    timed_arc_id: str
    coefficient: int = 1

    def validate(self) -> None:
        if not self.timed_arc_id.strip():
            raise ValueError("DDD anonymous resource row arc id must be nonempty")
        if self.coefficient <= 0:
            raise ValueError("DDD anonymous resource row coefficient must be positive")


@dataclass(frozen=True)
class DddAnonymousResourceRow:
    id: str
    resource_id: str
    kind: DddAnonymousResourceRowKind
    terms: tuple[DddAnonymousResourceRowTerm, ...]
    right_hand_side: int
    witness_tick: DddTimeTick | None = None
    minimum_violation_tick: DddTimeTick | None = None
    interval_lower_tick: DddTimeTick | None = None
    interval_upper_tick: DddTimeTick | None = None

    def validate(self) -> None:
        if not self.id.strip() or not self.resource_id.strip():
            raise ValueError("DDD anonymous resource row ids must be nonempty")
        if not isinstance(self.kind, DddAnonymousResourceRowKind):
            raise ValueError("DDD anonymous resource row kind is invalid")
        if not self.terms:
            raise ValueError("DDD anonymous resource row needs at least one term")
        if self.right_hand_side < 0:
            raise ValueError("DDD anonymous resource row RHS must be nonnegative")
        arc_ids = [term.timed_arc_id for term in self.terms]
        if arc_ids != sorted(arc_ids) or len(arc_ids) != len(set(arc_ids)):
            raise ValueError(
                "DDD anonymous resource row terms must be sorted and unique"
            )
        for term in self.terms:
            term.validate()
        if self.kind is DddAnonymousResourceRowKind.MANDATORY_CORE:
            if (
                self.witness_tick is None
                or self.minimum_violation_tick is not None
                or self.interval_lower_tick is not None
                or self.interval_upper_tick is not None
            ):
                raise ValueError("DDD mandatory-core row witness is inconsistent")
        elif self.kind is DddAnonymousResourceRowKind.UNIVERSAL_CONFLICT:
            if (
                self.witness_tick is not None
                or self.minimum_violation_tick is None
                or self.minimum_violation_tick <= 0
                or self.interval_lower_tick is not None
                or self.interval_upper_tick is not None
            ):
                raise ValueError("DDD universal-conflict row witness is inconsistent")
        elif (
            self.witness_tick is not None
            or self.minimum_violation_tick is not None
            or self.interval_lower_tick is None
            or self.interval_upper_tick is None
            or self.interval_lower_tick > self.interval_upper_tick
        ):
            raise ValueError("DDD interval-capacity row witness is inconsistent")


@dataclass(frozen=True)
class DddResourceWindowSeparationResult:
    rows: tuple[DddAnonymousResourceRow, ...]
    candidate_window_count: int
    violated_candidate_count: int
    duplicate_candidate_count: int

    @property
    def entry_row_count(self) -> int:
        return sum(
            row.kind is DddAnonymousResourceRowKind.INTERVAL_CAPACITY
            for row in self.rows
        )

    @property
    def energy_row_count(self) -> int:
        return sum(
            row.kind is DddAnonymousResourceRowKind.INTERVAL_ENERGY
            for row in self.rows
        )


@dataclass(frozen=True)
class DddUniversalResourceConflict:
    resource_id: str
    first_timed_arc_id: str
    second_timed_arc_id: str
    first_before_second_maximum_separation_tick: DddTimeTick
    second_before_first_maximum_separation_tick: DddTimeTick
    minimum_violation_tick: DddTimeTick


def ddd_feasible_source_interval(
    *,
    source_cell: DddTimeCell | None,
    fixed_source_tick: DddTimeTick | None,
    target_cell: DddTimeCell,
    duration_tick: DddTimeTick,
    operational_end_tick: DddTimeTick,
    minimum_wait_tick: DddTimeTick = 0,
    maximum_wait_tick: DddTimeTick = 0,
    minimum_source_tick: DddTimeTick | None = None,
) -> DddTickInterval | None:
    """Return every integer source tick represented by one timed movement arc."""

    if duration_tick <= 0:
        raise ValueError("DDD timed resource duration must be positive")
    if minimum_wait_tick < 0 or maximum_wait_tick < minimum_wait_tick:
        raise ValueError("DDD timed resource waiting envelope is invalid")
    if fixed_source_tick is not None:
        if source_cell is not None:
            raise ValueError("DDD timed arc cannot have fixed and cell source")
        if (
            fixed_source_tick > operational_end_tick
            or (
                minimum_source_tick is not None
                and fixed_source_tick < minimum_source_tick
            )
            or fixed_source_tick + duration_tick + maximum_wait_tick
            < target_cell.lower_tick
            or fixed_source_tick + duration_tick + minimum_wait_tick
            >= target_cell.upper_tick
        ):
            return None
        return DddTickInterval(fixed_source_tick, fixed_source_tick + 1)
    if source_cell is None:
        raise ValueError("DDD timed arc needs a fixed or cell source")
    lower = max(
        source_cell.lower_tick,
        target_cell.lower_tick - duration_tick - maximum_wait_tick,
        minimum_source_tick if minimum_source_tick is not None else source_cell.lower_tick,
    )
    upper = min(
        source_cell.upper_tick,
        target_cell.upper_tick - duration_tick - minimum_wait_tick,
        operational_end_tick + 1,
    )
    if lower >= upper:
        return None
    return DddTickInterval(lower, upper)


def find_ddd_universal_resource_conflict(
    first: DddTimedResourceUsageWindow,
    second: DddTimedResourceUsageWindow,
) -> DddUniversalResourceConflict | None:
    """Prove that neither temporal ordering can satisfy the resource headway."""

    first.validate()
    second.validate()
    if first.resource_id != second.resource_id:
        raise ValueError("DDD universal conflict needs one shared resource")
    first_before_second = (
        second.latest_follower_enter_tick - first.earliest_leader_clear_tick
    )
    second_before_first = (
        first.latest_follower_enter_tick - second.earliest_leader_clear_tick
    )
    first_before_second_violation = first.headway_tick - first_before_second
    second_before_first_violation = second.headway_tick - second_before_first
    if first_before_second_violation <= 0 or second_before_first_violation <= 0:
        return None
    minimum_violation = min(
        first_before_second_violation,
        second_before_first_violation,
    )
    return DddUniversalResourceConflict(
        resource_id=first.resource_id,
        first_timed_arc_id=first.timed_arc_id,
        second_timed_arc_id=second.timed_arc_id,
        first_before_second_maximum_separation_tick=first_before_second,
        second_before_first_maximum_separation_tick=second_before_first,
        minimum_violation_tick=minimum_violation,
    )


def build_ddd_mandatory_resource_rows(
    windows: tuple[DddTimedResourceUsageWindow, ...],
) -> tuple[DddAnonymousResourceRow, ...]:
    """Enumerate maximal mandatory-core cliques by a deterministic sweep."""

    windows_by_resource: dict[str, list[DddTimedResourceUsageWindow]] = {}
    for window in windows:
        window.validate()
        if window.mandatory_occupancy_core is not None:
            windows_by_resource.setdefault(window.resource_id, []).append(window)

    rows: list[DddAnonymousResourceRow] = []
    for resource_id, resource_windows in sorted(windows_by_resource.items()):
        starts_by_tick: dict[int, list[DddTimedResourceUsageWindow]] = {}
        ends_by_tick: dict[int, list[DddTimedResourceUsageWindow]] = {}
        for window in resource_windows:
            core = window.mandatory_occupancy_core
            if core is None:
                continue
            starts_by_tick.setdefault(core.lower_tick, []).append(window)
            ends_by_tick.setdefault(core.upper_tick, []).append(window)

        active_arc_multiplicity: Counter[str] = Counter()
        additions_since_last_candidate = False
        for tick in sorted(set(starts_by_tick) | set(ends_by_tick)):
            ending = ends_by_tick.get(tick, ())
            if ending and additions_since_last_candidate:
                terms = tuple(
                    DddAnonymousResourceRowTerm(arc_id, coefficient)
                    for arc_id, coefficient in sorted(active_arc_multiplicity.items())
                    if coefficient
                )
                if terms:
                    row = DddAnonymousResourceRow(
                        id=(f"resource_core::{resource_id}::tick::{tick - 1}"),
                        resource_id=resource_id,
                        kind=DddAnonymousResourceRowKind.MANDATORY_CORE,
                        terms=terms,
                        right_hand_side=1,
                        witness_tick=tick - 1,
                    )
                    row.validate()
                    rows.append(row)
                additions_since_last_candidate = False

            for window in ending:
                active_arc_multiplicity[window.timed_arc_id] -= 1
                if active_arc_multiplicity[window.timed_arc_id] == 0:
                    del active_arc_multiplicity[window.timed_arc_id]
            starting = starts_by_tick.get(tick, ())
            for window in starting:
                active_arc_multiplicity[window.timed_arc_id] += 1
            if starting:
                additions_since_last_candidate = True

    return tuple(rows)


def build_ddd_universal_resource_row(
    first: DddTimedResourceUsageWindow,
    second: DddTimedResourceUsageWindow,
) -> DddAnonymousResourceRow | None:
    """Turn a proved universal pair conflict into an anonymous master row."""

    conflict = find_ddd_universal_resource_conflict(first, second)
    if conflict is None:
        return None
    usage_ids = tuple(sorted((first.id, second.id)))
    if first.timed_arc_id != second.timed_arc_id:
        terms = tuple(
            DddAnonymousResourceRowTerm(arc_id)
            for arc_id in sorted((first.timed_arc_id, second.timed_arc_id))
        )
        right_hand_side = 1
    elif first.id == second.id:
        terms = (DddAnonymousResourceRowTerm(first.timed_arc_id),)
        right_hand_side = 1
    else:
        # One selected timed arc would contain both incompatible occurrences.
        terms = (DddAnonymousResourceRowTerm(first.timed_arc_id),)
        right_hand_side = 0
    row = DddAnonymousResourceRow(
        id=(f"resource_universal::{first.resource_id}::{usage_ids[0]}::{usage_ids[1]}"),
        resource_id=first.resource_id,
        kind=DddAnonymousResourceRowKind.UNIVERSAL_CONFLICT,
        terms=terms,
        right_hand_side=right_hand_side,
        minimum_violation_tick=conflict.minimum_violation_tick,
    )
    row.validate()
    return row


def find_ddd_violated_interval_capacity_rows(
    windows: tuple[DddTimedResourceUsageWindow, ...],
    *,
    arc_flow_by_id: dict[str, int],
    max_rows: int = 10_000,
) -> tuple[DddAnonymousResourceRow, ...]:
    """Separate entry-count Hall inequalities from one selected integer flow.

    Every counted occurrence has its complete follower-entry window contained
    in the closed interval ``[A, B]``. At headway ``h``, no exact schedule can
    place more than ``1 + floor((B-A)/h)`` such entries in that interval.
    """

    return separate_ddd_resource_window_rows(
        windows,
        arc_flow_by_id=arc_flow_by_id,
        mode=DddResourceWindowCutMode.ENTRY_COUNT,
        max_rows=max_rows,
    ).rows


def separate_ddd_resource_window_rows(
    windows: tuple[DddTimedResourceUsageWindow, ...],
    *,
    arc_flow_by_id: dict[str, int],
    mode: DddResourceWindowCutMode,
    max_rows: int = 100,
) -> DddResourceWindowSeparationResult:
    """Separate proof-safe entry-count and protected-interval energy rows."""

    if not isinstance(mode, DddResourceWindowCutMode):
        raise ValueError("DDD resource-window cut mode is invalid")
    if max_rows <= 0:
        raise ValueError("DDD resource-window row limit must be positive")
    if mode is DddResourceWindowCutMode.OFF:
        return DddResourceWindowSeparationResult((), 0, 0, 0)

    selected_by_resource: dict[str, list[DddTimedResourceUsageWindow]] = {}
    headway_by_resource: dict[str, int] = {}
    for window in windows:
        window.validate()
        flow = arc_flow_by_id.get(window.timed_arc_id, 0)
        if flow < 0:
            raise ValueError("DDD anonymous resource flow must be nonnegative")
        if not flow:
            continue
        known_headway = headway_by_resource.get(window.resource_id)
        headway_by_resource[window.resource_id] = (
            window.headway_tick
            if known_headway is None
            else min(known_headway, window.headway_tick)
        )
        selected_by_resource.setdefault(window.resource_id, []).append(window)

    candidates: list[tuple[int, int, int, DddAnonymousResourceRow]] = []
    candidate_window_count = 0
    violated_candidate_count = 0
    for resource_id, resource_windows in sorted(selected_by_resource.items()):
        headway_tick = headway_by_resource[resource_id]
        lower_candidates = sorted(
            {window.earliest_follower_enter_tick for window in resource_windows}
        )
        upper_candidates = sorted(
            {window.latest_follower_enter_tick for window in resource_windows}
        )
        for lower_tick in lower_candidates:
            eligible = tuple(
                window
                for window in resource_windows
                if window.earliest_follower_enter_tick >= lower_tick
            )
            for upper_tick in upper_candidates:
                if upper_tick < lower_tick:
                    continue
                candidate_window_count += 1
                contained = tuple(
                    window
                    for window in eligible
                    if window.latest_follower_enter_tick <= upper_tick
                    and window.minimum_clear_after_enter_tick >= 0
                )
                if not contained:
                    continue
                multiplicity = Counter(window.timed_arc_id for window in contained)
                selected_count = sum(
                    coefficient * arc_flow_by_id[arc_id]
                    for arc_id, coefficient in multiplicity.items()
                )
                capacity = 1 + (upper_tick - lower_tick) // headway_tick
                violation = selected_count - capacity
                if violation <= 0:
                    continue
                violated_candidate_count += 1
                terms = tuple(
                    DddAnonymousResourceRowTerm(arc_id, coefficient)
                    for arc_id, coefficient in sorted(multiplicity.items())
                )
                signature = "||".join(
                    f"{term.timed_arc_id}:{term.coefficient}" for term in terms
                )
                digest = sha1(signature.encode("utf-8")).hexdigest()[:16]
                row = DddAnonymousResourceRow(
                    id=(
                        f"resource_interval::{resource_id}::{lower_tick}::"
                        f"{upper_tick}::{digest}"
                    ),
                    resource_id=resource_id,
                    kind=DddAnonymousResourceRowKind.INTERVAL_CAPACITY,
                    terms=terms,
                    right_hand_side=capacity,
                    interval_lower_tick=lower_tick,
                    interval_upper_tick=upper_tick,
                )
                row.validate()
                candidates.append(
                    (violation, upper_tick - lower_tick, lower_tick, row)
                )

        if mode is not DddResourceWindowCutMode.ENTRY_AND_ENERGY:
            continue
        energy_lower_candidates = sorted(
            {window.earliest_follower_enter_tick for window in resource_windows}
        )
        energy_upper_candidates = sorted(
            {
                window.latest_leader_clear_tick + window.headway_tick
                for window in resource_windows
            }
        )
        for lower_tick in energy_lower_candidates:
            eligible = tuple(
                window
                for window in resource_windows
                if window.earliest_follower_enter_tick >= lower_tick
            )
            for upper_tick in energy_upper_candidates:
                if upper_tick <= lower_tick:
                    continue
                candidate_window_count += 1
                contained = tuple(
                    window
                    for window in eligible
                    if window.latest_leader_clear_tick + window.headway_tick
                    <= upper_tick
                )
                coefficient_by_arc: Counter[str] = Counter()
                for window in contained:
                    minimum_work = window.minimum_protected_occupancy_tick
                    if minimum_work > 0:
                        coefficient_by_arc[window.timed_arc_id] += minimum_work
                if not coefficient_by_arc:
                    continue
                capacity = upper_tick - lower_tick
                divisor = reduce(gcd, coefficient_by_arc.values())
                normalized_coefficients = {
                    arc_id: coefficient // divisor
                    for arc_id, coefficient in coefficient_by_arc.items()
                }
                normalized_capacity = capacity // divisor
                selected_work = sum(
                    coefficient * arc_flow_by_id[arc_id]
                    for arc_id, coefficient in normalized_coefficients.items()
                )
                violation = selected_work - normalized_capacity
                if violation <= 0:
                    continue
                violated_candidate_count += 1
                terms = tuple(
                    DddAnonymousResourceRowTerm(arc_id, coefficient)
                    for arc_id, coefficient in sorted(normalized_coefficients.items())
                )
                signature = "||".join(
                    f"{term.timed_arc_id}:{term.coefficient}" for term in terms
                )
                digest = sha1(signature.encode("utf-8")).hexdigest()[:16]
                row = DddAnonymousResourceRow(
                    id=(
                        f"resource_energy::{resource_id}::{lower_tick}::"
                        f"{upper_tick}::{digest}"
                    ),
                    resource_id=resource_id,
                    kind=DddAnonymousResourceRowKind.INTERVAL_ENERGY,
                    terms=terms,
                    right_hand_side=normalized_capacity,
                    interval_lower_tick=lower_tick,
                    interval_upper_tick=upper_tick,
                )
                row.validate()
                candidates.append(
                    (violation, upper_tick - lower_tick, lower_tick, row)
                )

    strongest_by_lhs: dict[
        tuple[str, DddAnonymousResourceRowKind, tuple[DddAnonymousResourceRowTerm, ...]],
        tuple[int, int, int, DddAnonymousResourceRow],
    ] = {}
    for candidate in candidates:
        row = candidate[3]
        key = (row.resource_id, row.kind, row.terms)
        incumbent = strongest_by_lhs.get(key)
        if incumbent is None or row.right_hand_side < incumbent[3].right_hand_side:
            strongest_by_lhs[key] = candidate
        elif (
            row.right_hand_side == incumbent[3].right_hand_side
            and row.id < incumbent[3].id
        ):
            strongest_by_lhs[key] = candidate
    selected = tuple(
        item[3]
        for item in sorted(
            strongest_by_lhs.values(),
            key=lambda item: (
                -(item[0] / max(1, item[3].right_hand_side)),
                -item[0],
                item[1],
                item[2],
                item[3].id,
            ),
        )[:max_rows]
    )
    return DddResourceWindowSeparationResult(
        rows=selected,
        candidate_window_count=candidate_window_count,
        violated_candidate_count=violated_candidate_count,
        duplicate_candidate_count=len(candidates) - len(strongest_by_lhs),
    )
