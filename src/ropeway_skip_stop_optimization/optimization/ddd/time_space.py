from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementProblem,
    DddRouteOption,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    DDD_TIME_TICKS_PER_SECOND,
    DddTimeTick,
    ddd_quantize_time_seconds,
    ddd_seconds_to_tick,
    ddd_tick_to_seconds,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddTrajectoryWaitingPolicy,
)


class DddTimeBoundaryError(ValueError):
    pass


def _time_token(value: float) -> str:
    tick = ddd_seconds_to_tick(value)
    return f"m{-tick}" if tick < 0 else str(tick)


def ddd_normalize_time_seconds(value: float) -> float:
    return ddd_quantize_time_seconds(value)


@dataclass(frozen=True, order=True, init=False)
class DddTimeCell:
    state_id: str
    lower_tick: DddTimeTick
    upper_tick: DddTimeTick

    def __init__(
        self,
        state_id: str,
        lower_seconds: float,
        upper_seconds: float,
    ) -> None:
        object.__setattr__(self, "state_id", state_id)
        object.__setattr__(self, "lower_tick", ddd_seconds_to_tick(lower_seconds))
        object.__setattr__(self, "upper_tick", ddd_seconds_to_tick(upper_seconds))

    @classmethod
    def from_ticks(
        cls,
        state_id: str,
        lower_tick: DddTimeTick,
        upper_tick: DddTimeTick,
    ) -> DddTimeCell:
        result = object.__new__(cls)
        object.__setattr__(result, "state_id", state_id)
        object.__setattr__(result, "lower_tick", lower_tick)
        object.__setattr__(result, "upper_tick", upper_tick)
        return result

    @property
    def lower_seconds(self) -> float:
        return ddd_tick_to_seconds(self.lower_tick)

    @property
    def upper_seconds(self) -> float:
        return ddd_tick_to_seconds(self.upper_tick)

    def validate(self) -> None:
        if not self.state_id.strip():
            raise ValueError("DDD time cell state_id must be nonempty")
        if not math.isfinite(self.lower_seconds) or not math.isfinite(
            self.upper_seconds
        ):
            raise ValueError("DDD time cell bounds must be finite")
        if self.lower_tick >= self.upper_tick:
            raise ValueError("DDD time cell must have positive width")

    @property
    def id(self) -> str:
        return (
            f"time_cell::{self.state_id}::"
            f"{_time_token(self.lower_seconds)}::"
            f"{_time_token(self.upper_seconds)}"
        )

    def contains(self, time_seconds: float, *, tolerance_seconds: float) -> bool:
        if tolerance_seconds < 0:
            raise ValueError("DDD time cell tolerance must be nonnegative")
        if not math.isfinite(time_seconds):
            raise ValueError("DDD time cell query must be finite")
        # Membership is exact and half-open. Tolerance is deliberately not
        # applied here because gaps or overlaps could invalidate projection.
        return self.contains_tick(ddd_seconds_to_tick(time_seconds))

    def contains_tick(self, time_tick: DddTimeTick) -> bool:
        return self.lower_tick <= time_tick < self.upper_tick


@dataclass(frozen=True, init=False)
class DddTimePartition:
    state_id: str
    boundaries_ticks: tuple[DddTimeTick, ...]

    def __init__(
        self,
        state_id: str,
        boundaries_seconds: tuple[float, ...],
    ) -> None:
        object.__setattr__(self, "state_id", state_id)
        object.__setattr__(
            self,
            "boundaries_ticks",
            tuple(ddd_seconds_to_tick(value) for value in boundaries_seconds),
        )

    @classmethod
    def from_ticks(
        cls,
        state_id: str,
        boundaries_ticks: tuple[DddTimeTick, ...],
    ) -> DddTimePartition:
        result = object.__new__(cls)
        object.__setattr__(result, "state_id", state_id)
        object.__setattr__(result, "boundaries_ticks", boundaries_ticks)
        return result

    @property
    def boundaries_seconds(self) -> tuple[float, ...]:
        return tuple(
            ddd_tick_to_seconds(value) for value in self.boundaries_ticks
        )

    def validate(self) -> None:
        if not self.state_id.strip():
            raise ValueError("DDD time partition state_id must be nonempty")
        if len(self.boundaries_ticks) < 2:
            raise ValueError("DDD time partition needs at least two boundaries")
        if any(
            left >= right
            for left, right in zip(
                self.boundaries_ticks[:-1],
                self.boundaries_ticks[1:],
                strict=True,
            )
        ):
            raise ValueError("DDD time partition boundaries must increase strictly")

    @property
    def cells(self) -> tuple[DddTimeCell, ...]:
        self.validate()
        return tuple(
            DddTimeCell.from_ticks(
                self.state_id,
                lower,
                upper,
            )
            for lower, upper in zip(
                self.boundaries_ticks[:-1],
                self.boundaries_ticks[1:],
                strict=True,
            )
        )

    def split(
        self,
        boundary_seconds: float,
        *,
        tolerance_seconds: float,
    ) -> DddTimePartition:
        self.validate()
        if tolerance_seconds < 0:
            raise DddTimeBoundaryError("DDD split tolerance must be nonnegative")
        if not math.isfinite(boundary_seconds):
            raise DddTimeBoundaryError("DDD split boundary must be finite")
        boundary_tick = ddd_seconds_to_tick(boundary_seconds)
        existing_ticks = self.boundaries_ticks
        if boundary_tick in existing_ticks:
            raise DddTimeBoundaryError(
                f"DDD split boundary already exists at {boundary_seconds}"
            )
        if not (
            existing_ticks[0] < boundary_tick < existing_ticks[-1]
        ):
            raise DddTimeBoundaryError(
                f"DDD split boundary {boundary_tick} lies outside partition interior"
            )
        result = DddTimePartition.from_ticks(
            self.state_id,
            tuple(sorted((*existing_ticks, boundary_tick))),
        )
        result.validate()
        return result


@dataclass(frozen=True)
class DddTimeDiscretization:
    partitions: tuple[DddTimePartition, ...]

    def validate(self) -> None:
        if not self.partitions:
            raise ValueError("DDD time discretization needs partitions")
        state_ids: set[str] = set()
        for partition in self.partitions:
            partition.validate()
            if partition.state_id in state_ids:
                raise ValueError(
                    f"duplicate DDD time partition state: {partition.state_id}"
                )
            state_ids.add(partition.state_id)

    @property
    def by_state_id(self) -> dict[str, DddTimePartition]:
        return {partition.state_id: partition for partition in self.partitions}

    @property
    def fingerprint(self) -> str:
        return "||".join(
            f"{partition.state_id}:"
            + ",".join(str(value) for value in partition.boundaries_ticks)
            for partition in sorted(self.partitions, key=lambda item: item.state_id)
        )

    def partition(self, state_id: str) -> DddTimePartition:
        try:
            return self.by_state_id[state_id]
        except KeyError as error:
            raise ValueError(f"missing DDD time partition for state {state_id!r}") from error

    def split(
        self,
        *,
        state_id: str,
        boundary_seconds: float,
        tolerance_seconds: float,
    ) -> DddTimeDiscretization:
        replacement = self.partition(state_id).split(
            boundary_seconds,
            tolerance_seconds=tolerance_seconds,
        )
        result = DddTimeDiscretization(
            partitions=tuple(
                replacement if item.state_id == state_id else item
                for item in self.partitions
            )
        )
        result.validate()
        return result


@dataclass(frozen=True, order=True)
class DddWaitingInterval:
    """A nonempty interval of discrete waiting-step indices.

    ``upper_step`` is exclusive.  Keeping the partition in step indices avoids
    tolerance-sensitive floating-point boundaries while still allowing the
    physical tick values to be recovered exactly.
    """

    station_id: str
    lower_step: int
    upper_step: int
    step_tick: DddTimeTick

    def validate(self) -> None:
        if not self.station_id.strip():
            raise ValueError("DDD waiting interval station_id must be nonempty")
        if self.lower_step < 0 or self.lower_step >= self.upper_step:
            raise ValueError("DDD waiting interval step range is invalid")
        if self.step_tick <= 0:
            raise ValueError("DDD waiting interval step tick must be positive")

    @property
    def minimum_wait_tick(self) -> DddTimeTick:
        self.validate()
        return self.lower_step * self.step_tick

    @property
    def maximum_wait_tick(self) -> DddTimeTick:
        self.validate()
        return (self.upper_step - 1) * self.step_tick

    @property
    def is_singleton(self) -> bool:
        return self.upper_step == self.lower_step + 1

    @property
    def id(self) -> str:
        return (
            f"wait_interval::{self.station_id}::{self.lower_step}::"
            f"{self.upper_step}::step::{self.step_tick}"
        )

    def contains_wait_tick(self, wait_tick: DddTimeTick) -> bool:
        if wait_tick < 0 or wait_tick % self.step_tick:
            return False
        step = wait_tick // self.step_tick
        return self.lower_step <= step < self.upper_step


@dataclass(frozen=True)
class DddWaitingPartition:
    station_id: str
    maximum_step: int
    step_tick: DddTimeTick
    boundaries_steps: tuple[int, ...]

    def validate(self) -> None:
        if not self.station_id.strip() or self.maximum_step <= 0:
            raise ValueError("DDD waiting partition identity is invalid")
        if self.step_tick <= 0:
            raise ValueError("DDD waiting partition step tick must be positive")
        if (
            len(self.boundaries_steps) < 2
            or self.boundaries_steps[0] != 0
            or self.boundaries_steps[-1] != self.maximum_step + 1
            or any(
                left >= right
                for left, right in zip(
                    self.boundaries_steps[:-1],
                    self.boundaries_steps[1:],
                    strict=True,
                )
            )
        ):
            raise ValueError("DDD waiting partition boundaries are invalid")

    @property
    def intervals(self) -> tuple[DddWaitingInterval, ...]:
        self.validate()
        return tuple(
            DddWaitingInterval(
                station_id=self.station_id,
                lower_step=lower,
                upper_step=upper,
                step_tick=self.step_tick,
            )
            for lower, upper in zip(
                self.boundaries_steps[:-1],
                self.boundaries_steps[1:],
                strict=True,
            )
        )

    def split(self, boundary_step: int) -> DddWaitingPartition:
        self.validate()
        if boundary_step in self.boundaries_steps:
            raise DddTimeBoundaryError(
                f"DDD waiting boundary already exists at step {boundary_step}"
            )
        if not 0 < boundary_step < self.maximum_step + 1:
            raise DddTimeBoundaryError(
                f"DDD waiting boundary {boundary_step} lies outside partition"
            )
        result = DddWaitingPartition(
            station_id=self.station_id,
            maximum_step=self.maximum_step,
            step_tick=self.step_tick,
            boundaries_steps=tuple(
                sorted((*self.boundaries_steps, boundary_step))
            ),
        )
        result.validate()
        return result


@dataclass(frozen=True)
class DddWaitingDiscretization:
    partitions: tuple[DddWaitingPartition, ...] = ()

    def validate(self) -> None:
        station_ids: set[str] = set()
        for partition in self.partitions:
            partition.validate()
            if partition.station_id in station_ids:
                raise ValueError(
                    f"duplicate DDD waiting partition: {partition.station_id}"
                )
            station_ids.add(partition.station_id)

    @property
    def by_station_id(self) -> dict[str, DddWaitingPartition]:
        return {partition.station_id: partition for partition in self.partitions}

    @property
    def fingerprint(self) -> str:
        return "||".join(
            f"{item.station_id}:{item.step_tick}:"
            + ",".join(str(value) for value in item.boundaries_steps)
            for item in sorted(self.partitions, key=lambda value: value.station_id)
        )

    def intervals_for_station(
        self,
        station_id: str,
    ) -> tuple[DddWaitingInterval, ...]:
        partition = self.by_station_id.get(station_id)
        if partition is None:
            return (
                DddWaitingInterval(
                    station_id=station_id,
                    lower_step=0,
                    upper_step=1,
                    step_tick=DDD_TIME_TICKS_PER_SECOND,
                ),
            )
        return partition.intervals

    def split(
        self,
        *,
        station_id: str,
        boundary_step: int,
    ) -> DddWaitingDiscretization:
        partition = self.by_station_id.get(station_id)
        if partition is None:
            raise DddTimeBoundaryError(
                f"missing DDD waiting partition for station {station_id!r}"
            )
        replacement = partition.split(boundary_step)
        result = DddWaitingDiscretization(
            tuple(
                replacement if item.station_id == station_id else item
                for item in self.partitions
            )
        )
        result.validate()
        return result


@dataclass(frozen=True)
class DddRouteOptionCost:
    route_option_id: str
    cost: float

    def validate(self) -> None:
        if not self.route_option_id.strip():
            raise ValueError("DDD route option cost id must be nonempty")
        if not math.isfinite(self.cost):
            raise ValueError("DDD route option cost must be finite")


@dataclass(frozen=True)
class DddTerminalThresholdCost:
    state_id: str
    threshold_seconds: float
    before_cost: float
    at_or_after_cost: float

    def validate(self) -> None:
        if not self.state_id.strip():
            raise ValueError("DDD terminal cost state_id must be nonempty")
        if not all(
            math.isfinite(value)
            for value in (
                self.threshold_seconds,
                self.before_cost,
                self.at_or_after_cost,
            )
        ):
            raise ValueError("DDD terminal threshold cost values must be finite")

    def exact_value(self, time_seconds: float, *, tolerance_seconds: float) -> float:
        if tolerance_seconds < 0:
            raise ValueError("DDD terminal cost tolerance must be nonnegative")
        return (
            self.before_cost
            if ddd_seconds_to_tick(time_seconds)
            < ddd_seconds_to_tick(self.threshold_seconds)
            else self.at_or_after_cost
        )

    def lower_bound(self, cell: DddTimeCell, *, tolerance_seconds: float) -> float:
        if tolerance_seconds < 0:
            raise ValueError("DDD terminal cost tolerance must be nonnegative")
        if cell.state_id != self.state_id:
            raise ValueError("DDD terminal cost evaluated for another state")
        upper = cell.upper_tick
        lower = cell.lower_tick
        threshold = ddd_seconds_to_tick(self.threshold_seconds)
        if upper <= threshold:
            return self.before_cost
        if lower >= threshold:
            return self.at_or_after_cost
        return min(self.before_cost, self.at_or_after_cost)


@dataclass(frozen=True)
class DddTimeSpaceObjective:
    route_option_costs: tuple[DddRouteOptionCost, ...]
    terminal_cost: DddTerminalThresholdCost

    def validate(self, problem: DddMovementProblem, terminal_state_id: str) -> None:
        self.terminal_cost.validate()
        if self.terminal_cost.state_id != terminal_state_id:
            raise ValueError("DDD terminal objective and terminal state differ")
        known_option_ids = {option.id for option in problem.route_options}
        cost_ids: set[str] = set()
        for item in self.route_option_costs:
            item.validate()
            if item.route_option_id in cost_ids:
                raise ValueError(
                    f"duplicate DDD route option cost: {item.route_option_id}"
                )
            if item.route_option_id not in known_option_ids:
                raise ValueError(
                    f"DDD objective references unknown route: {item.route_option_id}"
                )
            cost_ids.add(item.route_option_id)
        if cost_ids != known_option_ids:
            raise ValueError("DDD objective must price every route option explicitly")

    @property
    def route_cost_by_option_id(self) -> dict[str, float]:
        return {item.route_option_id: item.cost for item in self.route_option_costs}

    def exact_value(
        self,
        route_option_ids: tuple[str, ...],
        terminal_time_seconds: float,
        *,
        tolerance_seconds: float,
    ) -> float:
        return sum(
            self.route_cost_by_option_id[option_id]
            for option_id in route_option_ids
        ) + self.terminal_cost.exact_value(
            terminal_time_seconds,
            tolerance_seconds=tolerance_seconds,
        )

    def lower_bound(
        self,
        route_option_ids: tuple[str, ...],
        terminal_cell: DddTimeCell,
        *,
        tolerance_seconds: float,
    ) -> float:
        return sum(
            self.route_cost_by_option_id[option_id]
            for option_id in route_option_ids
        ) + self.terminal_cost.lower_bound(
            terminal_cell,
            tolerance_seconds=tolerance_seconds,
        )


@dataclass(frozen=True)
class DddPartialTimeProblem:
    movement_problem: DddMovementProblem
    terminal_state_id: str
    discretization: DddTimeDiscretization
    objective: DddTimeSpaceObjective
    waiting_policy: DddTrajectoryWaitingPolicy = DddTrajectoryWaitingPolicy()

    def validate(self) -> None:
        self.movement_problem.validate()
        self.discretization.validate()
        self.waiting_policy.validate(self.movement_problem.core)
        if len(self.movement_problem.starts) != 1:
            raise ValueError("Phase-0 partial time problem requires exactly one start")
        if self.movement_problem.resources:
            raise ValueError("Phase-0 partial time problem does not yet support resources")
        state_ids = {state.id for state in self.movement_problem.states}
        if self.terminal_state_id not in state_ids:
            raise ValueError("DDD partial time problem terminal state is unknown")
        target_state_ids = {
            option.to_state_id for option in self.movement_problem.route_options
        }
        missing_partitions = target_state_ids - set(self.discretization.by_state_id)
        if missing_partitions:
            raise ValueError(
                f"DDD target states lack time partitions: {missing_partitions}"
            )
        self.objective.validate(self.movement_problem, self.terminal_state_id)

    def with_discretization(
        self, discretization: DddTimeDiscretization
    ) -> DddPartialTimeProblem:
        result = DddPartialTimeProblem(
            movement_problem=self.movement_problem,
            terminal_state_id=self.terminal_state_id,
            discretization=discretization,
            objective=self.objective,
            waiting_policy=self.waiting_policy,
        )
        result.validate()
        return result


@dataclass(frozen=True)
class DddPartialTimedArc:
    visit_index: int
    route_option_id: str
    from_state_id: str
    to_state_id: str
    source_cell_id: str | None
    target_cell: DddTimeCell
    waiting_interval: DddWaitingInterval | None = None

    @property
    def id(self) -> str:
        source = self.source_cell_id or "fixed_start"
        base = (
            f"partial_arc::v{self.visit_index}::{self.route_option_id}::"
            f"{source}::{self.target_cell.id}"
        )
        if self.waiting_interval is None or (
            self.waiting_interval.minimum_wait_tick == 0
            and self.waiting_interval.maximum_wait_tick == 0
        ):
            return base
        return f"{base}::{self.waiting_interval.id}"

    @property
    def minimum_wait_tick(self) -> DddTimeTick:
        return (
            0
            if self.waiting_interval is None
            else self.waiting_interval.minimum_wait_tick
        )

    @property
    def maximum_wait_tick(self) -> DddTimeTick:
        return (
            0
            if self.waiting_interval is None
            else self.waiting_interval.maximum_wait_tick
        )


@dataclass(frozen=True)
class DddPartialTimedPath:
    cabin_id: int
    arcs: tuple[DddPartialTimedArc, ...]

    @property
    def route_option_ids(self) -> tuple[str, ...]:
        return tuple(arc.route_option_id for arc in self.arcs)

    @property
    def terminal_cell(self) -> DddTimeCell:
        if not self.arcs:
            raise ValueError("DDD partial path has no terminal arc")
        return self.arcs[-1].target_cell

    @property
    def fingerprint(self) -> str:
        return "||".join(arc.id for arc in self.arcs)


class DddPartialTimeMasterStatus(StrEnum):
    OPTIMAL = "optimal"
    INFEASIBLE = "infeasible"


@dataclass(frozen=True)
class DddPartialTimeMasterResult:
    status: DddPartialTimeMasterStatus
    path: DddPartialTimedPath | None
    objective_lower_bound: float | None
    candidate_path_count: int


@dataclass(frozen=True)
class DddPartialTimeMaster:
    tolerance_seconds: float = 1e-9
    max_candidate_paths: int = 100_000

    def solve(self, problem: DddPartialTimeProblem) -> DddPartialTimeMasterResult:
        problem.validate()
        if self.tolerance_seconds < 0:
            raise ValueError("DDD partial master tolerance must be nonnegative")
        if self.max_candidate_paths <= 0:
            raise ValueError("DDD partial master path limit must be positive")
        movement = problem.movement_problem
        start = movement.starts[0]
        options_by_state = movement.route_options_by_state_id
        paths: list[DddPartialTimedPath] = []

        def extend(
            *,
            state_id: str,
            source_cell: DddTimeCell | None,
            fixed_source_time: float | None,
            arcs: tuple[DddPartialTimedArc, ...],
        ) -> None:
            if state_id == problem.terminal_state_id:
                if not arcs:
                    raise ValueError("DDD terminal path must contain movement")
                if len(paths) >= self.max_candidate_paths:
                    raise ValueError("DDD partial master path limit exceeded")
                paths.append(DddPartialTimedPath(start.cabin_id, arcs))
                return
            if len(arcs) >= start.max_visit_count:
                return
            for option in options_by_state.get(state_id, ()):
                for target_cell in problem.discretization.partition(
                    option.to_state_id
                ).cells:
                    if not ddd_partial_arc_is_compatible(
                        source_cell=source_cell,
                        fixed_source_time=fixed_source_time,
                        target_cell=target_cell,
                        option=option,
                        operational_end_seconds=movement.operational_end_seconds,
                        tolerance_seconds=self.tolerance_seconds,
                    ):
                        continue
                    arc = DddPartialTimedArc(
                        visit_index=len(arcs),
                        route_option_id=option.id,
                        from_state_id=option.from_state_id,
                        to_state_id=option.to_state_id,
                        source_cell_id=(source_cell.id if source_cell else None),
                        target_cell=target_cell,
                    )
                    extend(
                        state_id=option.to_state_id,
                        source_cell=target_cell,
                        fixed_source_time=None,
                        arcs=(*arcs, arc),
                    )

        extend(
            state_id=start.state_id,
            source_cell=None,
            fixed_source_time=start.time_seconds,
            arcs=(),
        )
        if not paths:
            return DddPartialTimeMasterResult(
                status=DddPartialTimeMasterStatus.INFEASIBLE,
                path=None,
                objective_lower_bound=None,
                candidate_path_count=0,
            )
        ranked = sorted(
            (
                problem.objective.lower_bound(
                    path.route_option_ids,
                    path.terminal_cell,
                    tolerance_seconds=self.tolerance_seconds,
                ),
                path.fingerprint,
                path,
            )
            for path in paths
        )
        best_value, _, best_path = ranked[0]
        return DddPartialTimeMasterResult(
            status=DddPartialTimeMasterStatus.OPTIMAL,
            path=best_path,
            objective_lower_bound=best_value,
            candidate_path_count=len(paths),
        )


def ddd_partial_arc_is_compatible(
    *,
    source_cell: DddTimeCell | None,
    fixed_source_time: float | None,
    target_cell: DddTimeCell,
    option: DddRouteOption,
    operational_end_seconds: float,
    tolerance_seconds: float,
    minimum_wait_tick: DddTimeTick = 0,
    maximum_wait_tick: DddTimeTick = 0,
    wait_step_tick: DddTimeTick = 1,
) -> bool:
    if (
        minimum_wait_tick < 0
        or maximum_wait_tick < minimum_wait_tick
        or wait_step_tick <= 0
        or minimum_wait_tick % wait_step_tick
        or maximum_wait_tick % wait_step_tick
    ):
        raise ValueError("DDD partial arc waiting interval is invalid")
    horizon = ddd_seconds_to_tick(operational_end_seconds)
    if fixed_source_time is not None:
        source_lower = source_upper = ddd_seconds_to_tick(fixed_source_time)
        if source_lower > horizon:
            return False
    else:
        if source_cell is None:
            raise ValueError(
                "DDD partial arc needs a source cell or fixed source time"
            )
        source_lower = source_cell.lower_tick
        source_upper = min(source_cell.upper_tick - 1, horizon)
        if source_lower > source_upper:
            return False

    # There is a source tick s and a grid wait w iff
    #   target.lower <= s + duration + w <= target.upper - 1.
    # Eliminating s yields one closed interval for w.  Testing whether that
    # interval contains a grid multiple is constant-time; no waiting values
    # are enumerated even when the physical cap is large.
    feasible_wait_lower = max(
        minimum_wait_tick,
        target_cell.lower_tick - option.duration_tick - source_upper,
    )
    feasible_wait_upper = min(
        maximum_wait_tick,
        target_cell.upper_tick - 1 - option.duration_tick - source_lower,
    )
    first_grid_wait = (
        -(-feasible_wait_lower // wait_step_tick) * wait_step_tick
    )
    return first_grid_wait <= feasible_wait_upper
