from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import product
import math

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
    DddReferenceTrajectory,
    DddReferenceTrajectoryGenerator,
)


@dataclass(frozen=True, order=True)
class DddSupportLiteral:
    cabin_id: int
    visit_index: int
    route_option_id: str

    def validate(self) -> None:
        if self.cabin_id < 0:
            raise ValueError("DDD support literal cabin_id must be nonnegative")
        if self.visit_index < 0:
            raise ValueError("DDD support literal visit_index must be nonnegative")
        if not self.route_option_id.strip():
            raise ValueError("DDD support literal route_option_id must be nonempty")


@dataclass(frozen=True)
class DddSupportCost:
    literal: DddSupportLiteral
    cost: float

    def validate(self) -> None:
        self.literal.validate()
        if not math.isfinite(self.cost):
            raise ValueError("DDD support cost must be finite")


@dataclass(frozen=True)
class DddSupportObjective:
    costs: tuple[DddSupportCost, ...] = ()
    default_cost: float = 0.0

    def validate(self) -> None:
        if not math.isfinite(self.default_cost):
            raise ValueError("DDD default support cost must be finite")
        literals: set[DddSupportLiteral] = set()
        for item in self.costs:
            item.validate()
            if item.literal in literals:
                raise ValueError(f"duplicate DDD support cost: {item.literal}")
            literals.add(item.literal)

    def value(self, selection: DddSupportSelection) -> float:
        self.validate()
        cost_by_literal = {item.literal: item.cost for item in self.costs}
        return sum(
            cost_by_literal.get(literal, self.default_cost)
            for literal in selection.literals
        )


@dataclass(frozen=True)
class DddSupportConflictCut:
    id: str
    literals: tuple[DddSupportLiteral, ...]
    resource_id: str
    violation_seconds: float
    provenance: str = "exact_fixed_start_no_wait_prefix"

    def validate(self) -> None:
        if not self.id.strip():
            raise ValueError("DDD support conflict cut id must be nonempty")
        if not self.resource_id.strip():
            raise ValueError("DDD support conflict cut resource_id must be nonempty")
        if not math.isfinite(self.violation_seconds) or self.violation_seconds <= 0:
            raise ValueError("DDD support conflict violation must be finite and positive")
        if not self.literals:
            raise ValueError("DDD support conflict cut needs at least one literal")
        if (
            len(self.literals) < 2
            and self.provenance != "exact_cp_sat_no_wait_cabin_path_core"
        ):
            raise ValueError("DDD resource-prefix conflict cut needs two literals")
        if len(set(self.literals)) != len(self.literals):
            raise ValueError("DDD support conflict cut literals must be unique")
        for literal in self.literals:
            literal.validate()

    @property
    def right_hand_side(self) -> int:
        return len(self.literals) - 1

    def excludes(self, selection: DddSupportSelection) -> bool:
        selected = set(selection.literals)
        return all(literal in selected for literal in self.literals)


@dataclass(frozen=True)
class DddSupportSelection:
    trajectories: tuple[DddReferenceTrajectory, ...]

    @property
    def literals(self) -> tuple[DddSupportLiteral, ...]:
        return tuple(
            DddSupportLiteral(
                cabin_id=trajectory.cabin_id,
                visit_index=visit.visit_index,
                route_option_id=visit.route_option_id,
            )
            for trajectory in self.trajectories
            for visit in trajectory.visits
        )

    @property
    def support_fingerprint(self) -> str:
        return self.as_reference_solution().support_fingerprint

    def as_reference_solution(self) -> DddReferenceSolution:
        return DddReferenceSolution(trajectories=self.trajectories)


class DddSupportMasterStatus(StrEnum):
    OPTIMAL = "optimal"
    INFEASIBLE = "infeasible"


@dataclass(frozen=True)
class DddSupportMasterResult:
    status: DddSupportMasterStatus
    selection: DddSupportSelection | None
    objective_value: float | None
    candidate_support_count: int
    cut_rejected_support_count: int


class DddSupportMaster:
    """Exact tiny master over complete individual cabin trajectories.

    It intentionally ignores cross-cabin resource conflicts except for supplied
    conflict cuts. Enumeration is a Phase-0 reference implementation of the
    later binary trajectory-column master, not a production-scale algorithm.
    """

    def __init__(
        self,
        problem: DddMovementProblem,
        *,
        trajectory_generator: DddReferenceTrajectoryGenerator | None = None,
        max_candidate_supports: int = 1_000_000,
    ) -> None:
        problem.validate()
        if max_candidate_supports <= 0:
            raise ValueError("max_candidate_supports must be positive")
        generated = (trajectory_generator or DddReferenceTrajectoryGenerator()).generate(
            problem
        )
        self._problem = problem
        self._starts = tuple(sorted(problem.starts, key=lambda item: item.cabin_id))
        self._trajectories_by_cabin_id = generated.by_cabin_id
        self._max_candidate_supports = max_candidate_supports
        self._known_literals = frozenset(
            DddSupportLiteral(
                cabin_id=trajectory.cabin_id,
                visit_index=visit.visit_index,
                route_option_id=visit.route_option_id,
            )
            for trajectories in generated.by_cabin_id.values()
            for trajectory in trajectories
            for visit in trajectory.visits
        )

    @property
    def candidate_support_count(self) -> int:
        count = 1
        for start in self._starts:
            count *= len(self._trajectories_by_cabin_id[start.cabin_id])
        return count

    def solve(
        self,
        *,
        objective: DddSupportObjective | None = None,
        cuts: tuple[DddSupportConflictCut, ...] = (),
    ) -> DddSupportMasterResult:
        active_objective = objective or DddSupportObjective()
        active_objective.validate()
        unknown_objective_literals = {
            item.literal for item in active_objective.costs
        } - self._known_literals
        if unknown_objective_literals:
            raise ValueError(
                "DDD support objective references unknown literals: "
                f"{sorted(unknown_objective_literals)}"
            )
        cut_ids: set[str] = set()
        for cut in cuts:
            cut.validate()
            if cut.id in cut_ids:
                raise ValueError(f"duplicate DDD support conflict cut id: {cut.id}")
            cut_ids.add(cut.id)
            unknown_cut_literals = set(cut.literals) - self._known_literals
            if unknown_cut_literals:
                raise ValueError(
                    "DDD support conflict cut references unknown literals: "
                    f"{sorted(unknown_cut_literals)}"
                )

        support_count = self.candidate_support_count
        if support_count > self._max_candidate_supports:
            raise ValueError(
                "DDD support master candidate limit exceeded: "
                f"{support_count} > {self._max_candidate_supports}"
            )
        if support_count == 0:
            return DddSupportMasterResult(
                status=DddSupportMasterStatus.INFEASIBLE,
                selection=None,
                objective_value=None,
                candidate_support_count=0,
                cut_rejected_support_count=0,
            )

        best: DddSupportSelection | None = None
        best_key: tuple[float, str] | None = None
        rejected_count = 0
        trajectory_groups = tuple(
            self._trajectories_by_cabin_id[start.cabin_id] for start in self._starts
        )
        for trajectories in product(*trajectory_groups):
            selection = DddSupportSelection(trajectories=tuple(trajectories))
            if any(cut.excludes(selection) for cut in cuts):
                rejected_count += 1
                continue
            key = (
                active_objective.value(selection),
                selection.support_fingerprint,
            )
            if best_key is None or key < best_key:
                best = selection
                best_key = key

        if best is None or best_key is None:
            return DddSupportMasterResult(
                status=DddSupportMasterStatus.INFEASIBLE,
                selection=None,
                objective_value=None,
                candidate_support_count=support_count,
                cut_rejected_support_count=rejected_count,
            )
        return DddSupportMasterResult(
            status=DddSupportMasterStatus.OPTIMAL,
            selection=best,
            objective_value=best_key[0],
            candidate_support_count=support_count,
            cut_rejected_support_count=rejected_count,
        )
