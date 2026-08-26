from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_primal import (
    DddCpSatPrimalOracle,
    DddCpSatPrimalStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddNetworkTimeProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceResourceOccurrence,
    DddReferenceSolution,
    DddReferenceTrajectory,
    ddd_reference_solution_from_recovered_schedules,
    validate_ddd_reference_solution,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_root_column_generation import (
    build_ddd_all_stop_seed_trajectories,
)


class DddFixedKSeedStatus(StrEnum):
    FEASIBLE = "feasible"
    MOVEMENT_INFEASIBLE = "movement_infeasible"
    UNKNOWN_NO_FEASIBLE_SEED = "unknown_no_feasible_seed"
    INTERNAL_VALIDATION_ERROR = "internal_validation_error"


class DddFixedKSeedKind(StrEnum):
    ALL_STOP = "all_stop"
    CP_SAT = "cp_sat"


DddFixedKSeedEvaluator = Callable[[DddReferenceSolution], float | None]


@dataclass(frozen=True)
class DddFixedKSeedResult:
    status: DddFixedKSeedStatus
    trajectories: tuple[DddReferenceTrajectory, ...] = ()
    kind: DddFixedKSeedKind | None = None
    passenger_objective: float | None = None
    cp_sat_seconds: float = 0.0
    detail: str | None = None
    cp_sat_solver_status_name: str | None = None
    cp_sat_conflict_count: int = 0
    cp_sat_branch_count: int = 0
    cp_sat_search_complete: bool = False
    cp_sat_response_stats: str | None = None


@dataclass(frozen=True)
class DddFixedKSeedCoordinator:
    cp_sat_time_limit_seconds: float
    cp_sat_num_workers: int = 1
    cp_sat_max_candidate_count: int = 3
    cp_sat_oracle: DddCpSatPrimalOracle | None = None

    def solve(
        self,
        problem: DddNetworkTimeProblem,
        *,
        evaluate: DddFixedKSeedEvaluator | None = None,
        boundary_occurrences: tuple[DddReferenceResourceOccurrence, ...] = (),
    ) -> DddFixedKSeedResult:
        movement = problem.movement_problem
        try:
            all_stop = build_ddd_all_stop_seed_trajectories(movement)
            solution = _with_boundary_occurrences(all_stop, boundary_occurrences)
            validate_ddd_reference_solution(movement, solution)
        except ValueError:
            pass
        else:
            return DddFixedKSeedResult(
                status=DddFixedKSeedStatus.FEASIBLE,
                trajectories=solution.trajectories,
                kind=DddFixedKSeedKind.ALL_STOP,
                passenger_objective=evaluate(solution)
                if evaluate is not None
                else None,
            )

        oracle = self.cp_sat_oracle or DddCpSatPrimalOracle(
            time_limit_seconds=self.cp_sat_time_limit_seconds,
            num_workers=self.cp_sat_num_workers,
            max_candidate_count=self.cp_sat_max_candidate_count,
        )
        cp_result = (
            oracle.solve(problem, boundary_occurrences=boundary_occurrences)
            if boundary_occurrences
            else oracle.solve(problem)
        )
        if cp_result.status is DddCpSatPrimalStatus.INFEASIBLE:
            return DddFixedKSeedResult(
                status=DddFixedKSeedStatus.MOVEMENT_INFEASIBLE,
                cp_sat_seconds=cp_result.wall_seconds,
                detail="complete CP-SAT movement model is infeasible",
                cp_sat_solver_status_name=cp_result.solver_status_name,
                cp_sat_conflict_count=cp_result.conflict_count,
                cp_sat_branch_count=cp_result.branch_count,
                cp_sat_search_complete=cp_result.search_complete,
                cp_sat_response_stats=cp_result.solver_response_stats,
            )
        if cp_result.status is not DddCpSatPrimalStatus.FEASIBLE:
            return DddFixedKSeedResult(
                status=DddFixedKSeedStatus.UNKNOWN_NO_FEASIBLE_SEED,
                cp_sat_seconds=cp_result.wall_seconds,
                detail=f"CP-SAT seed search ended with {cp_result.status.value}",
                cp_sat_solver_status_name=cp_result.solver_status_name,
                cp_sat_conflict_count=cp_result.conflict_count,
                cp_sat_branch_count=cp_result.branch_count,
                cp_sat_search_complete=cp_result.search_complete,
                cp_sat_response_stats=cp_result.solver_response_stats,
            )
        candidates = (
            cp_result.candidate_schedules
            if cp_result.candidate_schedules
            else (cp_result.schedules,)
        )
        validated: list[tuple[float | None, DddReferenceSolution]] = []
        try:
            for schedules in candidates:
                solution = ddd_reference_solution_from_recovered_schedules(
                    movement,
                    schedules,
                )
                if boundary_occurrences:
                    solution = _with_boundary_occurrences(
                        solution.trajectories,
                        boundary_occurrences,
                    )
                    validate_ddd_reference_solution(movement, solution)
                objective = evaluate(solution) if evaluate is not None else None
                validated.append((objective, solution))
        except ValueError as error:
            return DddFixedKSeedResult(
                status=DddFixedKSeedStatus.INTERNAL_VALIDATION_ERROR,
                cp_sat_seconds=cp_result.wall_seconds,
                detail=str(error),
                cp_sat_solver_status_name=cp_result.solver_status_name,
                cp_sat_conflict_count=cp_result.conflict_count,
                cp_sat_branch_count=cp_result.branch_count,
                cp_sat_search_complete=cp_result.search_complete,
                cp_sat_response_stats=cp_result.solver_response_stats,
            )
        if not validated:
            return DddFixedKSeedResult(
                status=DddFixedKSeedStatus.UNKNOWN_NO_FEASIBLE_SEED,
                cp_sat_seconds=cp_result.wall_seconds,
                detail="CP-SAT returned no complete candidate schedule",
                cp_sat_solver_status_name=cp_result.solver_status_name,
                cp_sat_conflict_count=cp_result.conflict_count,
                cp_sat_branch_count=cp_result.branch_count,
                cp_sat_search_complete=cp_result.search_complete,
                cp_sat_response_stats=cp_result.solver_response_stats,
            )
        best_objective, best_solution = min(
            validated,
            key=lambda item: (
                float("inf") if item[0] is None else item[0],
                tuple(
                    trajectory.support_signature for trajectory in item[1].trajectories
                ),
            ),
        )
        return DddFixedKSeedResult(
            status=DddFixedKSeedStatus.FEASIBLE,
            trajectories=best_solution.trajectories,
            kind=DddFixedKSeedKind.CP_SAT,
            passenger_objective=best_objective,
            cp_sat_seconds=cp_result.wall_seconds,
            cp_sat_solver_status_name=cp_result.solver_status_name,
            cp_sat_conflict_count=cp_result.conflict_count,
            cp_sat_branch_count=cp_result.branch_count,
            cp_sat_search_complete=cp_result.search_complete,
            cp_sat_response_stats=cp_result.solver_response_stats,
        )


def _with_boundary_occurrences(
    trajectories: tuple[DddReferenceTrajectory, ...],
    occurrences: tuple[DddReferenceResourceOccurrence, ...],
) -> DddReferenceSolution:
    by_cabin: dict[int, list[DddReferenceResourceOccurrence]] = {}
    for occurrence in occurrences:
        by_cabin.setdefault(occurrence.cabin_id, []).append(occurrence)
    return DddReferenceSolution(
        tuple(
            DddReferenceTrajectory(
                cabin_id=trajectory.cabin_id,
                visits=trajectory.visits,
                initial_state=trajectory.initial_state,
                boundary_resource_occurrences=tuple(
                    by_cabin.get(trajectory.cabin_id, ())
                ),
                reservoir_state=trajectory.reservoir_state,
            )
            for trajectory in trajectories
        )
    )
