from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementProblem,
    DddRouteOption,
)


class DddTimeBoundaryError(ValueError):
    pass


def _time_token(value: float) -> str:
    return format(ddd_normalize_time_seconds(value), ".12g").replace(
        "-", "m"
    ).replace(".", "p")


def ddd_normalize_time_seconds(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("DDD time value must be finite")
    return float(format(value, ".12g"))


@dataclass(frozen=True, order=True)
class DddTimeCell:
    state_id: str
    lower_seconds: float
    upper_seconds: float

    def validate(self) -> None:
        if not self.state_id.strip():
            raise ValueError("DDD time cell state_id must be nonempty")
        if not math.isfinite(self.lower_seconds) or not math.isfinite(
            self.upper_seconds
        ):
            raise ValueError("DDD time cell bounds must be finite")
        if ddd_normalize_time_seconds(
            self.lower_seconds
        ) >= ddd_normalize_time_seconds(self.upper_seconds):
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
        normalized_time = ddd_normalize_time_seconds(time_seconds)
        return (
            ddd_normalize_time_seconds(self.lower_seconds)
            <= normalized_time
            < ddd_normalize_time_seconds(self.upper_seconds)
        )


@dataclass(frozen=True)
class DddTimePartition:
    state_id: str
    boundaries_seconds: tuple[float, ...]

    def validate(self) -> None:
        if not self.state_id.strip():
            raise ValueError("DDD time partition state_id must be nonempty")
        if len(self.boundaries_seconds) < 2:
            raise ValueError("DDD time partition needs at least two boundaries")
        if any(not math.isfinite(value) for value in self.boundaries_seconds):
            raise ValueError("DDD time partition boundaries must be finite")
        normalized = tuple(
            ddd_normalize_time_seconds(value) for value in self.boundaries_seconds
        )
        if any(
            left >= right
            for left, right in zip(
                normalized[:-1],
                normalized[1:],
                strict=True,
            )
        ):
            raise ValueError("DDD time partition boundaries must increase strictly")

    @property
    def cells(self) -> tuple[DddTimeCell, ...]:
        self.validate()
        return tuple(
            DddTimeCell(
                self.state_id,
                ddd_normalize_time_seconds(lower),
                ddd_normalize_time_seconds(upper),
            )
            for lower, upper in zip(
                self.boundaries_seconds[:-1],
                self.boundaries_seconds[1:],
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
        normalized_boundary = ddd_normalize_time_seconds(boundary_seconds)
        normalized_existing = tuple(
            ddd_normalize_time_seconds(value) for value in self.boundaries_seconds
        )
        if any(
            math.isclose(
                normalized_boundary,
                existing,
                rel_tol=0.0,
                abs_tol=tolerance_seconds,
            )
            for existing in normalized_existing
        ):
            raise DddTimeBoundaryError(
                f"DDD split boundary already exists at {boundary_seconds}"
            )
        if not (
            normalized_existing[0] + tolerance_seconds
            < normalized_boundary
            < normalized_existing[-1] - tolerance_seconds
        ):
            raise DddTimeBoundaryError(
                f"DDD split boundary {normalized_boundary} lies outside partition interior"
            )
        result = DddTimePartition(
            state_id=self.state_id,
            boundaries_seconds=tuple(
                sorted((*normalized_existing, normalized_boundary))
            ),
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
            + ",".join(format(value, ".12g") for value in partition.boundaries_seconds)
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
            if ddd_normalize_time_seconds(time_seconds)
            < ddd_normalize_time_seconds(self.threshold_seconds)
            else self.at_or_after_cost
        )

    def lower_bound(self, cell: DddTimeCell, *, tolerance_seconds: float) -> float:
        if tolerance_seconds < 0:
            raise ValueError("DDD terminal cost tolerance must be nonnegative")
        if cell.state_id != self.state_id:
            raise ValueError("DDD terminal cost evaluated for another state")
        upper = ddd_normalize_time_seconds(cell.upper_seconds)
        lower = ddd_normalize_time_seconds(cell.lower_seconds)
        threshold = ddd_normalize_time_seconds(self.threshold_seconds)
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

    def validate(self) -> None:
        self.movement_problem.validate()
        self.discretization.validate()
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

    @property
    def id(self) -> str:
        source = self.source_cell_id or "fixed_start"
        return (
            f"partial_arc::v{self.visit_index}::{self.route_option_id}::"
            f"{source}::{self.target_cell.id}"
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
) -> bool:
    duration = ddd_normalize_time_seconds(option.duration_seconds)
    horizon = ddd_normalize_time_seconds(operational_end_seconds)
    if fixed_source_time is not None:
        normalized_source = ddd_normalize_time_seconds(fixed_source_time)
        if normalized_source > horizon:
            return False
        return target_cell.contains(
            ddd_normalize_time_seconds(normalized_source + duration),
            tolerance_seconds=tolerance_seconds,
        )
    if source_cell is None:
        raise ValueError("DDD partial arc needs a source cell or fixed source time")
    if source_cell.contains(
        horizon,
        tolerance_seconds=tolerance_seconds,
    ) and target_cell.contains(
        ddd_normalize_time_seconds(horizon + duration),
        tolerance_seconds=tolerance_seconds,
    ):
        # Route entry at exactly H is active even though the interval below is
        # open at its operational-horizon truncation.
        return True
    source_lower = ddd_normalize_time_seconds(source_cell.lower_seconds)
    source_upper = min(
        ddd_normalize_time_seconds(source_cell.upper_seconds),
        horizon,
    )
    compatible_lower = max(
        source_lower,
        ddd_normalize_time_seconds(target_cell.lower_seconds) - duration,
    )
    compatible_upper = min(
        source_upper,
        ddd_normalize_time_seconds(target_cell.upper_seconds) - duration,
    )
    return ddd_normalize_time_seconds(compatible_lower) < ddd_normalize_time_seconds(
        compatible_upper
    )
