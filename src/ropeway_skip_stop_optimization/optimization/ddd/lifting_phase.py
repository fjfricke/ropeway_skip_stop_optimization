from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ddd.network_refinement_model import (
    DddNetworkValidationResult,
    DddNetworkValidationStatus,
    DddTimeSplit,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddEventCellInconsistency,
    DddRecoveredSchedule,
    DddStrictTimeCellLifter,
    DddStrictTimeLiftStatus,
    DddTimeRefinementStalledError,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddPartialTimedPath,
    DddPartialTimeProblem,
    DddTimeDiscretization,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick,
)


DddLiftingCandidateValidator = Callable[
    [tuple[DddRecoveredSchedule, ...]], DddNetworkValidationResult
]
DddLiftingCandidateConsumer = Callable[
    [tuple[DddRecoveredSchedule, ...], DddReferenceSolution], None
]


@dataclass(frozen=True)
class DddLiftingPhaseResult:
    statuses: tuple[DddStrictTimeLiftStatus, ...]
    validation: DddNetworkValidationResult
    time_splits: tuple[DddTimeSplit, ...]
    refined_discretization: DddTimeDiscretization
    stalled_detail: str | None


@dataclass(frozen=True)
class DddLiftingPhaseSolver:
    lifter: DddStrictTimeCellLifter
    max_time_splits: int
    tolerance_seconds: float

    def __post_init__(self) -> None:
        if self.max_time_splits <= 0:
            raise ValueError("DDD lifting max_time_splits must be positive")
        if self.tolerance_seconds < 0:
            raise ValueError("DDD lifting tolerance must be nonnegative")

    def solve(
        self,
        *,
        discretization: DddTimeDiscretization,
        path_problems: tuple[DddPartialTimeProblem, ...],
        paths: tuple[DddPartialTimedPath, ...],
        validate_candidate: DddLiftingCandidateValidator,
        consume_candidate: DddLiftingCandidateConsumer,
    ) -> DddLiftingPhaseResult:
        if len(path_problems) != len(paths):
            raise ValueError("DDD lifting requires one problem per path")

        statuses: list[DddStrictTimeLiftStatus] = []
        schedules: list[DddRecoveredSchedule] = []
        inconsistencies: list[DddEventCellInconsistency] = []
        stalled_detail: str | None = None
        for path_problem, path in zip(path_problems, paths, strict=True):
            try:
                lifted = self.lifter.lift(path_problem, path)
            except DddTimeRefinementStalledError as error:
                if stalled_detail is None:
                    stalled_detail = str(error)
                continue
            statuses.append(lifted.status)
            if lifted.schedule is not None:
                schedules.append(lifted.schedule)
            inconsistencies.extend(lifted.inconsistencies)

        time_splits, refined_discretization = build_ddd_time_split_batch(
            discretization,
            tuple(inconsistencies),
            max_splits=self.max_time_splits,
            tolerance_seconds=self.tolerance_seconds,
        )
        validation = DddNetworkValidationResult.not_run()
        if stalled_detail is not None:
            validation = DddNetworkValidationResult(
                status=DddNetworkValidationStatus.INVALID,
                solution=None,
                detail=stalled_detail,
                conflicts=(),
                cuts=(),
            )
        elif len(schedules) == len(paths):
            schedule_tuple = tuple(schedules)
            validation = validate_candidate(schedule_tuple)
            if validation.solution is not None:
                consume_candidate(schedule_tuple, validation.solution)

        return DddLiftingPhaseResult(
            statuses=tuple(statuses),
            validation=validation,
            time_splits=time_splits,
            refined_discretization=refined_discretization,
            stalled_detail=stalled_detail,
        )


def build_ddd_time_split_batch(
    discretization: DddTimeDiscretization,
    inconsistencies: tuple[DddEventCellInconsistency, ...],
    *,
    max_splits: int,
    tolerance_seconds: float,
) -> tuple[tuple[DddTimeSplit, ...], DddTimeDiscretization]:
    """Apply a deterministic batch of tolerance-safe partition refinements."""
    selected: list[DddTimeSplit] = []
    refined = discretization
    for inconsistency in sorted(
        inconsistencies,
        key=lambda item: (
            item.state_id,
            item.split_boundary_seconds,
            item.selected_cell_id,
            item.exact_source_time_seconds,
            item.failed_target_cell_id,
        ),
    ):
        split = DddTimeSplit(
            state_id=inconsistency.state_id,
            boundary_seconds=inconsistency.split_boundary_seconds,
        )
        if any(
            existing.state_id == split.state_id
            and ddd_seconds_to_tick(existing.boundary_seconds)
            == ddd_seconds_to_tick(split.boundary_seconds)
            for existing in selected
        ):
            continue
        refined = refined.split(
            state_id=split.state_id,
            boundary_seconds=split.boundary_seconds,
            tolerance_seconds=tolerance_seconds,
        )
        selected.append(split)
        if len(selected) >= max_splits:
            break
    return tuple(selected), refined
