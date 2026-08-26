from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
import math

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceResourceOccurrence,
    DddReferenceTrajectory,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    DddTimeTick,
    ddd_seconds_to_tick,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryWaitingDomain,
)


class DddTrajectoryConflictRowMode(StrEnum):
    PAIR_ONLY = "pair_only"
    RESOURCE_WINDOWS_WITH_PAIR_FALLBACK = "resource_windows_with_pair_fallback"


@dataclass(frozen=True, order=True)
class DddTrajectoryResourceWindow:
    resource_id: str
    anchor_tick: DddTimeTick
    capacity: int = 1
    waiting_domain: DddTrajectoryWaitingDomain = DddTrajectoryWaitingDomain.NO_WAIT
    interval_semantics: str = "follower_enter_to_leader_clear_plus_headway_half_open"

    def validate(self) -> None:
        if not self.resource_id:
            raise ValueError("trajectory resource-window resource ID is required")
        if self.anchor_tick < 0:
            raise ValueError("trajectory resource-window anchor must be nonnegative")
        if self.capacity <= 0:
            raise ValueError("trajectory resource-window capacity must be positive")
        if not isinstance(self.waiting_domain, DddTrajectoryWaitingDomain):
            raise ValueError("trajectory resource-window waiting domain is invalid")
        if not self.interval_semantics:
            raise ValueError("trajectory resource-window semantics are required")

    @property
    def id(self) -> str:
        self.validate()
        payload = (
            self.resource_id,
            self.anchor_tick,
            self.capacity,
            self.waiting_domain.value,
            self.interval_semantics,
        )
        digest = sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
        return f"ddd_resource_window::{digest}"


@dataclass(frozen=True, order=True)
class DddTrajectoryResourceInterval:
    resource_id: str
    cabin_id: int
    visit_index: int
    enter_tick: DddTimeTick
    clear_with_headway_tick: DddTimeTick

    def validate(self) -> None:
        if not self.resource_id:
            raise ValueError("trajectory resource interval ID is required")
        if self.cabin_id < 0 or self.visit_index < 0:
            raise ValueError("trajectory resource interval indices are invalid")
        if self.enter_tick < 0:
            raise ValueError("trajectory resource interval entry must be nonnegative")
        if self.clear_with_headway_tick <= self.enter_tick:
            raise ValueError("trajectory resource interval must be nonempty")

    def contains(self, anchor_tick: DddTimeTick) -> bool:
        return self.enter_tick <= anchor_tick < self.clear_with_headway_tick


@dataclass(frozen=True)
class DddTrajectoryResourceWindowRow:
    window: DddTrajectoryResourceWindow
    coefficients: tuple[tuple[str, int], ...]

    def validate(self) -> None:
        self.window.validate()
        option_ids = tuple(option_id for option_id, _ in self.coefficients)
        if tuple(sorted(set(option_ids))) != option_ids:
            raise ValueError(
                "trajectory resource-window coefficients must have sorted unique IDs"
            )
        if any(
            not option_id or coefficient <= 0
            for option_id, coefficient in self.coefficients
        ):
            raise ValueError("trajectory resource-window coefficients must be positive")

    @property
    def id(self) -> str:
        return self.window.id

    @property
    def coefficient_by_option_id(self) -> dict[str, int]:
        return dict(self.coefficients)


@dataclass(frozen=True)
class DddTrajectoryResourceWindowSeparationResult:
    new_windows: tuple[DddTrajectoryResourceWindow, ...]
    violating_window_count: int
    maximum_violation: float
    positive_interval_count: int


@dataclass(frozen=True)
class DddTrajectoryResourceWindowPricingTerm:
    window: DddTrajectoryResourceWindow
    raw_dual: float

    def validate(self) -> None:
        self.window.validate()
        if not math.isfinite(self.raw_dual) or self.raw_dual > 1e-7:
            raise ValueError("trajectory resource-window dual has an invalid sign")

    @property
    def congestion_penalty(self) -> float:
        self.validate()
        return -self.raw_dual


@dataclass(frozen=True)
class DddTrajectoryResourceWindowIndex:
    intervals_by_option_id: dict[str, tuple[DddTrajectoryResourceInterval, ...]]

    @classmethod
    def build(
        cls,
        *,
        movement_problem: DddMovementProblem,
        trajectory_by_option_id: dict[str, DddReferenceTrajectory],
    ) -> DddTrajectoryResourceWindowIndex:
        return cls(
            intervals_by_option_id={
                option_id: ddd_trajectory_resource_intervals(
                    trajectory,
                    movement_problem,
                )
                for option_id, trajectory in sorted(trajectory_by_option_id.items())
            }
        )

    def build_row(
        self,
        window: DddTrajectoryResourceWindow,
    ) -> DddTrajectoryResourceWindowRow:
        window.validate()
        coefficients = []
        for option_id, intervals in self.intervals_by_option_id.items():
            coefficient = sum(
                interval.resource_id == window.resource_id
                and interval.contains(window.anchor_tick)
                for interval in intervals
            )
            if coefficient > 1 and window.capacity == 1:
                raise ValueError(
                    "a locally valid trajectory occupies a capacity-one resource "
                    "window more than once"
                )
            if coefficient:
                coefficients.append((option_id, coefficient))
        row = DddTrajectoryResourceWindowRow(
            window=window,
            coefficients=tuple(coefficients),
        )
        row.validate()
        return row

    def build_rows(
        self,
        windows: tuple[DddTrajectoryResourceWindow, ...],
    ) -> tuple[DddTrajectoryResourceWindowRow, ...]:
        normalized = tuple(sorted(set(windows)))
        if normalized != windows:
            raise ValueError("trajectory resource windows must be sorted and unique")
        return tuple(
            sorted(
                (self.build_row(window) for window in windows), key=lambda row: row.id
            )
        )


def ddd_trajectory_resource_interval(
    occurrence: DddReferenceResourceOccurrence,
    movement_problem: DddMovementProblem,
) -> DddTrajectoryResourceInterval:
    interval = _ddd_trajectory_resource_interval_or_none(
        occurrence,
        movement_problem,
    )
    if interval is None:
        raise ValueError(
            "trajectory resource occurrence has no protected-interval representation"
        )
    return interval


def _ddd_trajectory_resource_interval_or_none(
    occurrence: DddReferenceResourceOccurrence,
    movement_problem: DddMovementProblem,
) -> DddTrajectoryResourceInterval | None:
    resource = movement_problem.resources_by_id.get(occurrence.resource_id)
    if resource is None:
        raise ValueError("trajectory occurrence references an unknown resource")
    raw_enter_tick = ddd_seconds_to_tick(occurrence.follower_enter_time_seconds)
    if raw_enter_tick < 0 and not occurrence.boundary_origin:
        raise ValueError(
            "non-boundary trajectory resource interval entry must be nonnegative"
        )
    # A retained boundary occurrence may have entered the resource before the
    # optimization horizon and still protect it after t=0. Resource-window
    # rows live on the modeled horizon, so intersect that fixed interval with
    # [0, +inf) instead of discarding its remaining occupancy.
    enter_tick = max(0, raw_enter_tick)
    clear_with_headway_tick = (
        ddd_seconds_to_tick(occurrence.leader_clear_time_seconds)
        + occurrence.separation_after_tick(resource)
    )
    if clear_with_headway_tick <= enter_tick:
        return None
    interval = DddTrajectoryResourceInterval(
        resource_id=occurrence.resource_id,
        cabin_id=occurrence.cabin_id,
        visit_index=occurrence.visit_index,
        enter_tick=enter_tick,
        clear_with_headway_tick=clear_with_headway_tick,
    )
    interval.validate()
    return interval


def ddd_trajectory_resource_intervals(
    trajectory: DddReferenceTrajectory,
    movement_problem: DddMovementProblem,
) -> tuple[DddTrajectoryResourceInterval, ...]:
    possible_intervals = (
        _ddd_trajectory_resource_interval_or_none(occurrence, movement_problem)
        for occurrence in trajectory.resource_occurrences
    )
    intervals = tuple(
        sorted(interval for interval in possible_intervals if interval is not None)
    )
    for interval in intervals:
        interval.validate()
    return intervals


def build_ddd_trajectory_resource_window_row(
    *,
    window: DddTrajectoryResourceWindow,
    movement_problem: DddMovementProblem,
    trajectory_by_option_id: dict[str, DddReferenceTrajectory],
) -> DddTrajectoryResourceWindowRow:
    window.validate()
    if window.resource_id not in movement_problem.resources_by_id:
        raise ValueError("trajectory resource window references an unknown resource")
    return DddTrajectoryResourceWindowIndex.build(
        movement_problem=movement_problem,
        trajectory_by_option_id=trajectory_by_option_id,
    ).build_row(window)


def build_ddd_trajectory_resource_window_rows(
    *,
    windows: tuple[DddTrajectoryResourceWindow, ...],
    movement_problem: DddMovementProblem,
    trajectory_by_option_id: dict[str, DddReferenceTrajectory],
) -> tuple[DddTrajectoryResourceWindowRow, ...]:
    return DddTrajectoryResourceWindowIndex.build(
        movement_problem=movement_problem,
        trajectory_by_option_id=trajectory_by_option_id,
    ).build_rows(windows)


def enumerate_ddd_trajectory_resource_windows(
    *,
    movement_problem: DddMovementProblem,
    trajectories: tuple[DddReferenceTrajectory, ...],
    waiting_domain: DddTrajectoryWaitingDomain = DddTrajectoryWaitingDomain.NO_WAIT,
) -> tuple[DddTrajectoryResourceWindow, ...]:
    windows = {
        DddTrajectoryResourceWindow(
            resource_id=interval.resource_id,
            anchor_tick=interval.enter_tick,
            capacity=1,
            waiting_domain=waiting_domain,
        )
        for trajectory in trajectories
        for interval in ddd_trajectory_resource_intervals(
            trajectory,
            movement_problem,
        )
    }
    return tuple(sorted(windows))


def separate_ddd_trajectory_resource_windows(
    *,
    movement_problem: DddMovementProblem,
    trajectory_by_option_id: dict[str, DddReferenceTrajectory],
    option_values_by_id: dict[str, float],
    existing_windows: tuple[DddTrajectoryResourceWindow, ...] = (),
    tolerance: float = 1e-9,
    waiting_domain: DddTrajectoryWaitingDomain = DddTrajectoryWaitingDomain.NO_WAIT,
) -> DddTrajectoryResourceWindowSeparationResult:
    if tolerance < 0 or not math.isfinite(tolerance):
        raise ValueError("trajectory resource-window tolerance is invalid")
    unknown = set(option_values_by_id) - set(trajectory_by_option_id)
    if unknown:
        raise ValueError("trajectory resource-window values contain unknown options")
    existing = set(existing_windows)
    by_resource: dict[str, list[tuple[DddTrajectoryResourceInterval, float]]] = {}
    positive_interval_count = 0
    for option_id, value in sorted(option_values_by_id.items()):
        if not math.isfinite(value) or value < -tolerance:
            raise ValueError("trajectory resource-window master value is invalid")
        if value <= tolerance:
            continue
        for interval in ddd_trajectory_resource_intervals(
            trajectory_by_option_id[option_id], movement_problem
        ):
            by_resource.setdefault(interval.resource_id, []).append((interval, value))
            positive_interval_count += 1

    new_windows: list[DddTrajectoryResourceWindow] = []
    violating_window_count = 0
    maximum_violation = 0.0
    for resource_id, weighted_intervals in sorted(by_resource.items()):
        events: dict[DddTimeTick, list[float]] = {}
        for interval, value in weighted_intervals:
            entry_exit = events.setdefault(interval.enter_tick, [0.0, 0.0])
            entry_exit[1] += value
            entry_exit = events.setdefault(interval.clear_with_headway_tick, [0.0, 0.0])
            entry_exit[0] += value
        load = 0.0
        previously_violating = False
        for tick, (exit_weight, entry_weight) in sorted(events.items()):
            load -= exit_weight
            load += entry_weight
            violation = load - 1.0
            is_violating = violation > tolerance
            if is_violating:
                maximum_violation = max(maximum_violation, violation)
                if not previously_violating:
                    violating_window_count += 1
                    window = DddTrajectoryResourceWindow(
                        resource_id=resource_id,
                        anchor_tick=tick,
                        capacity=1,
                        waiting_domain=waiting_domain,
                    )
                    if window not in existing:
                        new_windows.append(window)
                        existing.add(window)
            previously_violating = is_violating
    return DddTrajectoryResourceWindowSeparationResult(
        new_windows=tuple(sorted(new_windows)),
        violating_window_count=violating_window_count,
        maximum_violation=maximum_violation,
        positive_interval_count=positive_interval_count,
    )


def ddd_trajectory_pair_has_resource_window_witness(
    *,
    first: DddReferenceTrajectory,
    second: DddReferenceTrajectory,
    movement_problem: DddMovementProblem,
) -> bool:
    for first_interval in ddd_trajectory_resource_intervals(first, movement_problem):
        for second_interval in ddd_trajectory_resource_intervals(
            second, movement_problem
        ):
            if first_interval.resource_id != second_interval.resource_id:
                continue
            anchor = max(first_interval.enter_tick, second_interval.enter_tick)
            if first_interval.contains(anchor) and second_interval.contains(anchor):
                return True
    return False
