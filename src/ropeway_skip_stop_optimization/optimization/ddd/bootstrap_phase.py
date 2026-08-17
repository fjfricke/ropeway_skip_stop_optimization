from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_primal import (
    DddCpSatPrimalOracle,
    DddCpSatPrimalResult,
    DddCpSatPrimalStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddNetworkTimeProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.primal_tracking import (
    DddPrimalCandidateOutcome,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddRecoveredSchedule,
)


DddBootstrapCandidateValidator = Callable[
    [tuple[DddRecoveredSchedule, ...]],
    DddReferenceSolution | None,
]
DddBootstrapCandidateConsumer = Callable[
    [tuple[DddRecoveredSchedule, ...], DddReferenceSolution],
    DddPrimalCandidateOutcome,
]
DddBootstrapProgressCallback = Callable[[], None]


@dataclass(frozen=True)
class DddBootstrapPhaseResult:
    oracle_result: DddCpSatPrimalResult | None = None
    objective_value: float | None = None
    exact_infeasible: bool = False
    invalid_candidate: bool = False


@dataclass(frozen=True)
class DddBootstrapPhaseSolver:
    enabled: bool

    def solve(
        self,
        *,
        problem: DddNetworkTimeProblem,
        oracle: DddCpSatPrimalOracle,
        validate_candidate: DddBootstrapCandidateValidator,
        consume_candidate: DddBootstrapCandidateConsumer,
        on_started: DddBootstrapProgressCallback | None = None,
        on_finished: DddBootstrapProgressCallback | None = None,
    ) -> DddBootstrapPhaseResult:
        if not self.enabled:
            return DddBootstrapPhaseResult()

        if on_started is not None:
            on_started()
        oracle_result = oracle.solve(problem)

        if oracle_result.status is DddCpSatPrimalStatus.INFEASIBLE:
            if on_finished is not None:
                on_finished()
            return DddBootstrapPhaseResult(
                oracle_result=oracle_result,
                exact_infeasible=True,
            )

        objective_value: float | None = None
        if oracle_result.status is DddCpSatPrimalStatus.FEASIBLE:
            candidates = (
                oracle_result.candidate_schedules
                if oracle_result.candidate_schedules
                else (oracle_result.schedules,)
            )
            for schedules in candidates:
                solution = validate_candidate(schedules)
                if solution is None:
                    if on_finished is not None:
                        on_finished()
                    return DddBootstrapPhaseResult(
                        oracle_result=oracle_result,
                        objective_value=objective_value,
                        invalid_candidate=True,
                    )
                outcome = consume_candidate(schedules, solution)
                if outcome.improved_incumbent:
                    objective_value = outcome.objective_value

        if on_finished is not None:
            on_finished()
        return DddBootstrapPhaseResult(
            oracle_result=oracle_result,
            objective_value=objective_value,
        )
