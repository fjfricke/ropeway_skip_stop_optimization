from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_primal import (
    DddCpSatPrimalOracle,
    DddCpSatPrimalStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddNetworkTimeProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.primal_evaluation import (
    DddPrimalEvaluator,
    DddPrimalPoolEvaluationResult,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddRecoveredSchedule,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddPartialTimedPath,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_passenger_lp import (
    DddTrajectoryPassengerLpResult,
    DddTrajectoryPassengerLpStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_slot import (
    DddTrajectoryColumnPool,
    DddTrajectorySlotPoolResult,
)


DddTrajectoryCandidateValidator = Callable[
    [tuple[DddRecoveredSchedule, ...]], DddReferenceSolution | None
]
DddTrajectoryCandidateConsumer = Callable[
    [tuple[DddRecoveredSchedule, ...], DddReferenceSolution], None
]
DddTrajectoryPoolEvaluationConsumer = Callable[
    [DddPrimalPoolEvaluationResult], None
]
DddTrajectoryProgressCallback = Callable[[], None]
DddTrajectoryCandidateProgressCallback = Callable[[int, float], None]
DddBestSchedulesProvider = Callable[[], tuple[DddRecoveredSchedule, ...]]


@dataclass(frozen=True)
class DddTrajectoryPhaseResult:
    pool_result: DddTrajectorySlotPoolResult | None
    pool_lp_result: DddTrajectoryPassengerLpResult | None
    pool_fingerprint: str | None
    pool_solved_this_round: bool
    pricing_status: DddCpSatPrimalStatus = DddCpSatPrimalStatus.NOT_RUN
    pricing_preference_count: int = 0
    pricing_candidate_count: int = 0
    pricing_objective_value: float | None = None
    pricing_objective_bound: float | None = None
    pricing_signal_fingerprint: str | None = None
    pricing_seconds: float = 0.0
    invalid_candidate: bool = False


@dataclass(frozen=True)
class DddTrajectoryPhaseSolver:
    pool_enabled: bool
    pricing_enabled: bool
    pricing_interval: int

    def __post_init__(self) -> None:
        if self.pricing_interval <= 0:
            raise ValueError("DDD trajectory pricing interval must be positive")
        if self.pricing_enabled and not self.pool_enabled:
            raise ValueError("DDD trajectory pricing requires the trajectory pool")

    def solve(
        self,
        *,
        round_index: int,
        problem: DddNetworkTimeProblem,
        paths: tuple[DddPartialTimedPath, ...],
        column_pool: DddTrajectoryColumnPool,
        evaluator: DddPrimalEvaluator | None,
        pricing_oracle: DddCpSatPrimalOracle,
        previous_pool_result: DddTrajectorySlotPoolResult | None,
        previous_pool_lp_result: DddTrajectoryPassengerLpResult | None,
        previous_pool_fingerprint: str | None,
        best_schedules: DddBestSchedulesProvider,
        validate_candidate: DddTrajectoryCandidateValidator,
        consume_candidate: DddTrajectoryCandidateConsumer,
        consume_pool_evaluation: DddTrajectoryPoolEvaluationConsumer,
        on_pool_started: DddTrajectoryProgressCallback | None = None,
        on_pool_finished: DddTrajectoryProgressCallback | None = None,
        on_candidate_found: DddTrajectoryCandidateProgressCallback | None = None,
    ) -> DddTrajectoryPhaseResult:
        if round_index <= 0:
            raise ValueError("DDD trajectory phase round index must be positive")
        if self.pricing_enabled and evaluator is None:
            raise ValueError("DDD trajectory pricing requires a primal evaluator")

        pool_result = previous_pool_result
        pool_lp_result = previous_pool_lp_result
        pool_fingerprint = previous_pool_fingerprint
        pool_solved_this_round = False

        def evaluate_pool() -> None:
            nonlocal pool_fingerprint
            nonlocal pool_lp_result
            nonlocal pool_result
            nonlocal pool_solved_this_round

            assert evaluator is not None
            if on_pool_started is not None:
                on_pool_started()
            pool_evaluation = evaluator.evaluate_trajectory_pool(problem, column_pool)
            pool_result = pool_evaluation.pool_result
            pool_lp_result = pool_evaluation.lp_result
            pool_solved_this_round = True
            pool_fingerprint = column_pool.fingerprint
            consume_pool_evaluation(pool_evaluation)
            if on_pool_finished is not None:
                on_pool_finished()

        if (
            self.pool_enabled
            and evaluator is not None
            and column_pool.has_recombination_choice
            and column_pool.fingerprint != pool_fingerprint
        ):
            evaluate_pool()

        pricing_status = DddCpSatPrimalStatus.NOT_RUN
        pricing_preference_count = 0
        pricing_candidate_count = 0
        pricing_objective_value: float | None = None
        pricing_objective_bound: float | None = None
        pricing_signal_fingerprint: str | None = None
        pricing_seconds = 0.0
        if (
            self.pricing_enabled
            and pool_lp_result is not None
            and pool_lp_result.status is DddTrajectoryPassengerLpStatus.OPTIMAL
            and pool_lp_result.duals is not None
            and (round_index - 1) % self.pricing_interval == 0
        ):
            assert evaluator is not None
            pricing_signal_builder = getattr(
                evaluator,
                "build_trajectory_pricing_signal",
                None,
            )
            if pricing_signal_builder is None:
                raise ValueError(
                    "trajectory pricing evaluator has no pricing signal builder"
                )
            pricing_signal = pricing_signal_builder(problem, pool_lp_result)
            pricing_preference_count = len(pricing_signal.preferences)
            pricing_signal_fingerprint = pricing_signal.fingerprint
            option_count_before_pricing = column_pool.column_count
            pricing_started = perf_counter()
            pricing_result = pricing_oracle.solve(
                problem,
                hint_paths=paths,
                hint_schedules=best_schedules(),
                excluded_schedules=tuple(
                    candidate.schedules for candidate in column_pool.candidates
                ),
                passenger_ride_preferences=pricing_signal.preferences,
                candidate_callback=on_candidate_found,
            )
            pricing_status = pricing_result.status
            pricing_candidate_count = len(pricing_result.candidate_schedules)
            pricing_objective_value = pricing_result.passenger_pricing_objective_value
            pricing_objective_bound = pricing_result.passenger_pricing_objective_bound
            pricing_seconds = perf_counter() - pricing_started
            if pricing_result.status is DddCpSatPrimalStatus.FEASIBLE:
                pricing_candidates = (
                    pricing_result.candidate_schedules
                    if pricing_result.candidate_schedules
                    else (pricing_result.schedules,)
                )
                for candidate_schedules in pricing_candidates:
                    solution = validate_candidate(candidate_schedules)
                    if solution is None:
                        return DddTrajectoryPhaseResult(
                            pool_result=pool_result,
                            pool_lp_result=pool_lp_result,
                            pool_fingerprint=pool_fingerprint,
                            pool_solved_this_round=pool_solved_this_round,
                            pricing_status=pricing_status,
                            pricing_preference_count=pricing_preference_count,
                            pricing_candidate_count=pricing_candidate_count,
                            pricing_objective_value=pricing_objective_value,
                            pricing_objective_bound=pricing_objective_bound,
                            pricing_signal_fingerprint=(
                                pricing_signal_fingerprint
                            ),
                            pricing_seconds=pricing_seconds,
                            invalid_candidate=True,
                        )
                    consume_candidate(candidate_schedules, solution)
            if column_pool.column_count > option_count_before_pricing:
                evaluate_pool()

        return DddTrajectoryPhaseResult(
            pool_result=pool_result,
            pool_lp_result=pool_lp_result,
            pool_fingerprint=pool_fingerprint,
            pool_solved_this_round=pool_solved_this_round,
            pricing_status=pricing_status,
            pricing_preference_count=pricing_preference_count,
            pricing_candidate_count=pricing_candidate_count,
            pricing_objective_value=pricing_objective_value,
            pricing_objective_bound=pricing_objective_bound,
            pricing_signal_fingerprint=pricing_signal_fingerprint,
            pricing_seconds=pricing_seconds,
        )
