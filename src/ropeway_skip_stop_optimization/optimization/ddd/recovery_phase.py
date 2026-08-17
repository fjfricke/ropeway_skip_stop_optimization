from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

from ropeway_skip_stop_optimization.optimization.ddd.network_refinement_model import (
    DddNetworkValidationResult,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddCellFreeSupportRecovery,
    DddPrimalRecoveryStatus,
    DddRecoveredSchedule,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddPartialTimedPath,
    DddPartialTimeProblem,
)


DddRecoveryCandidateValidator = Callable[
    [tuple[DddRecoveredSchedule, ...]], DddNetworkValidationResult
]
DddRecoveryCandidateConsumer = Callable[
    [tuple[DddRecoveredSchedule, ...], DddReferenceSolution], None
]


@dataclass(frozen=True)
class DddRecoveryPhaseResult:
    schedules: tuple[DddRecoveredSchedule, ...]
    feasible: bool
    objective_value: float | None
    validation: DddNetworkValidationResult
    seconds: float


@dataclass(frozen=True)
class DddRecoveryPhaseSolver:
    recovery: DddCellFreeSupportRecovery

    def solve(
        self,
        *,
        path_problems: tuple[DddPartialTimeProblem, ...],
        paths: tuple[DddPartialTimedPath, ...],
        validate_candidate: DddRecoveryCandidateValidator,
        consume_candidate: DddRecoveryCandidateConsumer,
    ) -> DddRecoveryPhaseResult:
        if len(path_problems) != len(paths):
            raise ValueError("DDD recovery requires one problem per path")

        started = perf_counter()
        schedules: list[DddRecoveredSchedule] = []
        for path_problem, path in zip(path_problems, paths, strict=True):
            recovered = self.recovery.recover(path_problem, path)
            if (
                recovered.status is not DddPrimalRecoveryStatus.FEASIBLE
                or recovered.schedule is None
            ):
                return DddRecoveryPhaseResult(
                    schedules=tuple(schedules),
                    feasible=False,
                    objective_value=None,
                    validation=DddNetworkValidationResult.not_run(),
                    seconds=perf_counter() - started,
                )
            schedules.append(recovered.schedule)

        schedule_tuple = tuple(schedules)
        validation = validate_candidate(schedule_tuple)
        if validation.solution is None:
            return DddRecoveryPhaseResult(
                schedules=schedule_tuple,
                feasible=False,
                objective_value=None,
                validation=validation,
                seconds=perf_counter() - started,
            )

        objective_value = sum(schedule.objective_value for schedule in schedule_tuple)
        consume_candidate(schedule_tuple, validation.solution)
        return DddRecoveryPhaseResult(
            schedules=schedule_tuple,
            feasible=True,
            objective_value=objective_value,
            validation=validation,
            seconds=perf_counter() - started,
        )
