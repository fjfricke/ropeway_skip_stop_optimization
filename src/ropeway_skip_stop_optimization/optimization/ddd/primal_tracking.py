from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import math

from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddNetworkTimeProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.primal_evaluation import (
    DddPrimalEvaluationResult,
    DddPrimalEvaluationStatus,
    DddPrimalEvaluationSummary,
    DddPrimalEvaluator,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddRecoveredSchedule,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_slot import (
    DddTrajectoryColumnPool,
    DddTrajectorySlotCandidate,
)


@dataclass
class DddPrimalRoundState:
    status: DddPrimalEvaluationStatus = DddPrimalEvaluationStatus.NOT_RUN
    evaluation_count: int = 0
    evaluation_seconds: float = 0.0
    objective_value: float | None = None
    evaluation: DddPrimalEvaluationResult | None = None
    summaries: list[DddPrimalEvaluationSummary] = field(default_factory=list)
    trajectory_pool_added_option_count: int = 0

    def record_evaluation(
        self,
        evaluation: DddPrimalEvaluationResult,
        *,
        accept_feasible_status: bool,
        record_failure_status: bool,
    ) -> None:
        self.summaries.append(evaluation.summary)
        self.evaluation_count += 1
        self.evaluation_seconds += evaluation.total_seconds
        if (
            accept_feasible_status
            and evaluation.status is DddPrimalEvaluationStatus.FEASIBLE
        ):
            self.status = DddPrimalEvaluationStatus.FEASIBLE
            if evaluation.objective_value is not None and (
                self.objective_value is None
                or evaluation.objective_value < self.objective_value
            ):
                self.objective_value = evaluation.objective_value
                self.evaluation = evaluation
        elif (
            record_failure_status
            and self.status is DddPrimalEvaluationStatus.NOT_RUN
        ):
            self.status = evaluation.status


@dataclass(frozen=True)
class DddPrimalCandidateOutcome:
    objective_value: float | None
    evaluation: DddPrimalEvaluationResult | None
    improved_incumbent: bool


DddPrimalEvaluationCallback = Callable[[DddPrimalRoundState, float | None], None]


@dataclass
class DddPrimalIncumbentTracker:
    evaluator: DddPrimalEvaluator | None
    trajectory_column_pool: DddTrajectoryColumnPool
    trajectory_pool_enabled: bool
    remember_candidates: bool
    upper_bound: float = math.inf
    best_schedules: tuple[DddRecoveredSchedule, ...] = ()
    best_reference: DddReferenceSolution | None = None
    best_evaluation: DddPrimalEvaluationResult | None = None
    _remembered_schedules: dict[
        tuple[tuple[int, tuple[str, ...]], ...],
        tuple[DddRecoveredSchedule, ...],
    ] = field(default_factory=dict)

    @property
    def remembered_schedules(self) -> tuple[tuple[DddRecoveredSchedule, ...], ...]:
        return tuple(self._remembered_schedules.values())

    def consider_candidate(
        self,
        problem: DddNetworkTimeProblem,
        schedules: tuple[DddRecoveredSchedule, ...],
        solution: DddReferenceSolution,
        *,
        round_state: DddPrimalRoundState | None = None,
        on_evaluated: DddPrimalEvaluationCallback | None = None,
        require_movement_plan: bool = True,
        time_limit_seconds: float | None = None,
    ) -> DddPrimalCandidateOutcome:
        self._remember(schedules)
        if time_limit_seconds is not None and time_limit_seconds <= 0:
            raise ValueError("DDD primal-evaluation time limit must be positive")
        evaluator = self.evaluator
        original_time_limit = None
        has_mutable_time_limit = evaluator is not None and hasattr(
            evaluator, "time_limit_seconds"
        )
        if has_mutable_time_limit:
            original_time_limit = getattr(evaluator, "time_limit_seconds")
            effective_time_limit = time_limit_seconds
            if original_time_limit is not None and effective_time_limit is not None:
                effective_time_limit = min(original_time_limit, effective_time_limit)
            elif effective_time_limit is None:
                effective_time_limit = original_time_limit
            setattr(evaluator, "time_limit_seconds", effective_time_limit)
        try:
            evaluation = (
                evaluator.evaluate(problem, solution) if evaluator is not None else None
            )
        finally:
            if has_mutable_time_limit:
                setattr(evaluator, "time_limit_seconds", original_time_limit)
        if evaluation is None:
            objective_value: float | None = sum(
                schedule.objective_value for schedule in schedules
            )
        else:
            objective_value = evaluation.objective_value
            if round_state is not None:
                round_state.record_evaluation(
                    evaluation,
                    accept_feasible_status=True,
                    record_failure_status=True,
                )
                if on_evaluated is not None:
                    on_evaluated(
                        round_state,
                        (
                            min(self.upper_bound, objective_value)
                            if objective_value is not None
                            else _finite_or_none(self.upper_bound)
                        ),
                    )
            if self.trajectory_pool_enabled and evaluation.movement_plan is not None:
                added_count = self.trajectory_column_pool.add_candidate(
                    DddTrajectorySlotCandidate(
                        schedules=schedules,
                        reference_solution=solution,
                        movement_plan=evaluation.movement_plan,
                    )
                )
                if round_state is not None:
                    round_state.trajectory_pool_added_option_count += added_count
            if (
                evaluation.status is not DddPrimalEvaluationStatus.FEASIBLE
                or objective_value is None
            ):
                return DddPrimalCandidateOutcome(
                    objective_value=objective_value,
                    evaluation=evaluation,
                    improved_incumbent=False,
                )
            if require_movement_plan and evaluation.movement_plan is None:
                raise RuntimeError("feasible DDD primal evaluation has no movement plan")

        improved = self._update_incumbent(
            schedules=schedules,
            solution=solution,
            evaluation=evaluation,
            objective_value=objective_value,
        )
        return DddPrimalCandidateOutcome(
            objective_value=objective_value,
            evaluation=evaluation,
            improved_incumbent=improved,
        )

    def record_external_evaluation(
        self,
        *,
        schedules: tuple[DddRecoveredSchedule, ...],
        solution: DddReferenceSolution | None,
        evaluation: DddPrimalEvaluationResult,
        round_state: DddPrimalRoundState,
    ) -> DddPrimalCandidateOutcome:
        eligible = (
            evaluation.status is DddPrimalEvaluationStatus.FEASIBLE
            and evaluation.objective_value is not None
            and solution is not None
        )
        round_state.record_evaluation(
            evaluation,
            accept_feasible_status=eligible,
            record_failure_status=False,
        )
        improved = False
        if eligible:
            improved = self._update_incumbent(
                schedules=schedules,
                solution=solution,
                evaluation=evaluation,
                objective_value=evaluation.objective_value,
            )
        return DddPrimalCandidateOutcome(
            objective_value=evaluation.objective_value,
            evaluation=evaluation,
            improved_incumbent=improved,
        )

    def _remember(self, schedules: tuple[DddRecoveredSchedule, ...]) -> None:
        if not self.remember_candidates:
            return
        fingerprint = tuple(
            sorted(
                (schedule.cabin_id, schedule.route_option_ids)
                for schedule in schedules
            )
        )
        self._remembered_schedules.setdefault(fingerprint, schedules)

    def _update_incumbent(
        self,
        *,
        schedules: tuple[DddRecoveredSchedule, ...],
        solution: DddReferenceSolution,
        evaluation: DddPrimalEvaluationResult | None,
        objective_value: float,
    ) -> bool:
        if objective_value >= self.upper_bound:
            return False
        self.upper_bound = objective_value
        self.best_schedules = schedules
        self.best_reference = solution
        self.best_evaluation = evaluation
        return True


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None
