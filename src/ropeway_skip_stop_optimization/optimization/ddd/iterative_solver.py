from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ropeway_skip_stop_optimization.optimization.ddd.lifting import (
    DddExactLiftStatus,
    DddExactSupportLifter,
    DddRefinementReason,
)
from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
)
from ropeway_skip_stop_optimization.optimization.ddd.support_master import (
    DddSupportConflictCut,
    DddSupportMaster,
    DddSupportMasterStatus,
    DddSupportObjective,
)


class DddIterativeStatus(StrEnum):
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    ITERATION_LIMIT = "iteration_limit"


@dataclass(frozen=True)
class DddIterationRecord:
    round_index: int
    master_status: DddSupportMasterStatus
    selected_support_fingerprint: str | None
    master_objective_value: float | None
    conflict_count: int
    added_cut_ids: tuple[str, ...]
    refinement_reason: DddRefinementReason | None


@dataclass(frozen=True)
class DddIterativeResult:
    status: DddIterativeStatus
    solution: DddReferenceSolution | None
    objective_value: float | None
    cuts: tuple[DddSupportConflictCut, ...]
    iterations: tuple[DddIterationRecord, ...]
    candidate_support_count: int
    final_lift_complete: bool


@dataclass(frozen=True)
class DddDelayedConflictSolver:
    max_iterations: int = 100
    max_new_cuts_per_iteration: int = 10_000
    max_candidate_supports: int = 1_000_000
    tolerance_seconds: float = 1e-9

    def solve(
        self,
        problem: DddMovementProblem,
        *,
        objective: DddSupportObjective | None = None,
    ) -> DddIterativeResult:
        if self.max_iterations <= 0:
            raise ValueError("DDD max_iterations must be positive")
        if self.max_new_cuts_per_iteration <= 0:
            raise ValueError("DDD max_new_cuts_per_iteration must be positive")
        master = DddSupportMaster(
            problem,
            max_candidate_supports=self.max_candidate_supports,
        )
        lifter = DddExactSupportLifter(tolerance_seconds=self.tolerance_seconds)
        cuts: list[DddSupportConflictCut] = []
        cut_ids: set[str] = set()
        iterations: list[DddIterationRecord] = []

        for round_index in range(1, self.max_iterations + 1):
            master_result = master.solve(
                objective=objective,
                cuts=tuple(cuts),
            )
            if master_result.status is DddSupportMasterStatus.INFEASIBLE:
                iterations.append(
                    DddIterationRecord(
                        round_index=round_index,
                        master_status=master_result.status,
                        selected_support_fingerprint=None,
                        master_objective_value=None,
                        conflict_count=0,
                        added_cut_ids=(),
                        refinement_reason=None,
                    )
                )
                return DddIterativeResult(
                    status=DddIterativeStatus.INFEASIBLE,
                    solution=None,
                    objective_value=None,
                    cuts=tuple(cuts),
                    iterations=tuple(iterations),
                    candidate_support_count=master.candidate_support_count,
                    final_lift_complete=True,
                )

            selection = master_result.selection
            if selection is None:
                raise RuntimeError("optimal DDD support master returned no selection")
            lift = lifter.lift(problem, selection)
            if lift.status is DddExactLiftStatus.FEASIBLE:
                if lift.solution is None:
                    raise RuntimeError("feasible DDD lift returned no solution")
                iterations.append(
                    DddIterationRecord(
                        round_index=round_index,
                        master_status=master_result.status,
                        selected_support_fingerprint=selection.support_fingerprint,
                        master_objective_value=master_result.objective_value,
                        conflict_count=0,
                        added_cut_ids=(),
                        refinement_reason=None,
                    )
                )
                return DddIterativeResult(
                    status=DddIterativeStatus.FEASIBLE,
                    solution=lift.solution,
                    objective_value=master_result.objective_value,
                    cuts=tuple(cuts),
                    iterations=tuple(iterations),
                    candidate_support_count=master.candidate_support_count,
                    final_lift_complete=True,
                )

            new_cuts = tuple(
                cut
                for cut in lift.cuts
                if cut.id not in cut_ids
            )[: self.max_new_cuts_per_iteration]
            if not new_cuts:
                raise RuntimeError(
                    "DDD lift repeated a resource conflict without producing a new cut"
                )
            cuts.extend(new_cuts)
            cut_ids.update(cut.id for cut in new_cuts)
            iterations.append(
                DddIterationRecord(
                    round_index=round_index,
                    master_status=master_result.status,
                    selected_support_fingerprint=selection.support_fingerprint,
                    master_objective_value=master_result.objective_value,
                    conflict_count=len(lift.conflicts),
                    added_cut_ids=tuple(cut.id for cut in new_cuts),
                    refinement_reason=lift.refinement_reason,
                )
            )

        return DddIterativeResult(
            status=DddIterativeStatus.ITERATION_LIMIT,
            solution=None,
            objective_value=None,
            cuts=tuple(cuts),
            iterations=tuple(iterations),
            candidate_support_count=master.candidate_support_count,
            final_lift_complete=False,
        )
