from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from time import perf_counter

import gurobipy as gp
from gurobipy import GRB

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceTrajectory,
    find_ddd_reference_conflicts,
)


class DddTrajectoryCompatibleBatchStatus(StrEnum):
    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    EMPTY = "empty"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DddTrajectoryPricedCandidate:
    option_id: str
    cabin_id: int
    reduced_cost: float
    trajectory: DddReferenceTrajectory
    provenance: str = "proof_pricing"

    def validate(self) -> None:
        if not self.option_id or not self.provenance:
            raise ValueError("priced trajectory candidate identifiers are required")
        if self.cabin_id < 0 or self.trajectory.cabin_id != self.cabin_id:
            raise ValueError("priced trajectory candidate cabin is inconsistent")
        if not math.isfinite(self.reduced_cost):
            raise ValueError("priced trajectory reduced cost must be finite")


@dataclass(frozen=True, slots=True)
class DddTrajectoryCompatibilityBatchResult:
    status: DddTrajectoryCompatibleBatchStatus
    selected_option_ids: tuple[str, ...]
    selected_cabin_ids: tuple[int, ...]
    selected_reduced_cost: float
    candidate_count: int
    conflict_pair_count: int
    same_cabin_pair_count: int
    model_variable_count: int
    model_constraint_count: int
    solve_seconds: float
    detail: str | None = None

    def validate(self) -> None:
        if not isinstance(self.status, DddTrajectoryCompatibleBatchStatus):
            raise ValueError("trajectory compatibility batch status is invalid")
        if tuple(sorted(set(self.selected_option_ids))) != self.selected_option_ids:
            raise ValueError("selected trajectory options must be sorted and unique")
        if tuple(sorted(set(self.selected_cabin_ids))) != self.selected_cabin_ids:
            raise ValueError("selected trajectory cabins must be sorted and unique")
        if len(self.selected_option_ids) != len(self.selected_cabin_ids):
            raise ValueError("trajectory batch must select at most one option per cabin")
        if not math.isfinite(self.selected_reduced_cost):
            raise ValueError("trajectory batch reduced cost must be finite")
        if min(
            self.candidate_count,
            self.conflict_pair_count,
            self.same_cabin_pair_count,
            self.model_variable_count,
            self.model_constraint_count,
        ) < 0:
            raise ValueError("trajectory compatibility batch metrics are invalid")
        if self.solve_seconds < 0 or not math.isfinite(self.solve_seconds):
            raise ValueError("trajectory compatibility batch time is invalid")


@dataclass(frozen=True, slots=True)
class DddTrajectoryCompatibilityBatchOptimizer:
    """Select a deterministic compatible subset of priced negative columns.

    This is a column-discovery accelerator.  Its status or objective never
    certifies omitted-column nonnegativity.
    """

    time_limit_seconds: float = 10.0
    output_flag: bool = False
    tolerance: float = 1e-7

    def solve(
        self,
        *,
        movement_problem: DddMovementProblem,
        candidates: tuple[DddTrajectoryPricedCandidate, ...],
    ) -> DddTrajectoryCompatibilityBatchResult:
        started = perf_counter()
        movement_problem.validate()
        if self.time_limit_seconds <= 0 or not math.isfinite(
            self.time_limit_seconds
        ):
            raise ValueError("trajectory compatibility time limit must be positive")
        if self.tolerance < 0 or not math.isfinite(self.tolerance):
            raise ValueError("trajectory compatibility tolerance is invalid")
        normalized = tuple(sorted(candidates, key=lambda item: item.option_id))
        for candidate in normalized:
            candidate.validate()
        option_ids = tuple(item.option_id for item in normalized)
        if len(set(option_ids)) != len(option_ids):
            raise ValueError("trajectory compatibility candidates must be unique")
        if not normalized:
            return self._empty(started)

        conflict_pairs: list[tuple[str, str]] = []
        same_cabin_pairs: list[tuple[str, str]] = []
        for first_index, first in enumerate(normalized):
            for second in normalized[first_index + 1 :]:
                pair = (first.option_id, second.option_id)
                if first.cabin_id == second.cabin_id:
                    same_cabin_pairs.append(pair)
                    continue
                conflicts = find_ddd_reference_conflicts(
                    (
                        *first.trajectory.resource_occurrences,
                        *second.trajectory.resource_occurrences,
                    ),
                    movement_problem,
                )
                if conflicts:
                    conflict_pairs.append(pair)

        model = gp.Model("ddd_trajectory_compatible_batch")
        model.Params.OutputFlag = int(self.output_flag)
        model.Params.Threads = 1
        model.Params.Seed = 0
        model.Params.TimeLimit = self.time_limit_seconds
        model.ModelSense = GRB.MINIMIZE
        selected = {
            candidate.option_id: model.addVar(
                vtype=GRB.BINARY,
                obj=(
                    candidate.reduced_cost
                    + self.tolerance
                    * 1e-3
                    * (index + 1)
                    / max(1, len(normalized))
                ),
                name=f"select[{index}]",
            )
            for index, candidate in enumerate(normalized)
        }
        for cabin_id in sorted({item.cabin_id for item in normalized}):
            model.addConstr(
                gp.quicksum(
                    selected[item.option_id]
                    for item in normalized
                    if item.cabin_id == cabin_id
                )
                <= 1,
                name=f"cabin[{cabin_id}]",
            )
        for index, (first_id, second_id) in enumerate(conflict_pairs):
            model.addConstr(
                selected[first_id] + selected[second_id] <= 1,
                name=f"conflict[{index}]",
            )
        model.addConstr(
            gp.quicksum(selected.values()) >= 1,
            name="nonempty_batch",
        )
        model.optimize()
        selected_candidates = tuple(
            candidate
            for candidate in normalized
            if int(model.SolCount) > 0 and selected[candidate.option_id].X > 0.5
        )
        if model.Status == GRB.OPTIMAL:
            status = DddTrajectoryCompatibleBatchStatus.OPTIMAL
        elif selected_candidates:
            status = DddTrajectoryCompatibleBatchStatus.FEASIBLE
        else:
            status = DddTrajectoryCompatibleBatchStatus.UNKNOWN
        result = DddTrajectoryCompatibilityBatchResult(
            status=status,
            selected_option_ids=tuple(
                sorted(item.option_id for item in selected_candidates)
            ),
            selected_cabin_ids=tuple(
                sorted(item.cabin_id for item in selected_candidates)
            ),
            selected_reduced_cost=sum(
                item.reduced_cost for item in selected_candidates
            ),
            candidate_count=len(normalized),
            conflict_pair_count=len(conflict_pairs),
            same_cabin_pair_count=len(same_cabin_pairs),
            model_variable_count=int(model.NumVars),
            model_constraint_count=int(model.NumConstrs),
            solve_seconds=perf_counter() - started,
            detail=(
                None
                if selected_candidates
                else f"compatibility solver status {int(model.Status)}"
            ),
        )
        result.validate()
        return result

    @staticmethod
    def _empty(started: float) -> DddTrajectoryCompatibilityBatchResult:
        result = DddTrajectoryCompatibilityBatchResult(
            status=DddTrajectoryCompatibleBatchStatus.EMPTY,
            selected_option_ids=(),
            selected_cabin_ids=(),
            selected_reduced_cost=0.0,
            candidate_count=0,
            conflict_pair_count=0,
            same_cabin_pair_count=0,
            model_variable_count=0,
            model_constraint_count=0,
            solve_seconds=perf_counter() - started,
        )
        result.validate()
        return result
