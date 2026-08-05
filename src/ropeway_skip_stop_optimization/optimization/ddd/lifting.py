from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceConflict,
    DddReferenceSolution,
    find_ddd_reference_conflicts,
    validate_ddd_reference_solution,
)
from ropeway_skip_stop_optimization.optimization.ddd.support_master import (
    DddSupportConflictCut,
    DddSupportLiteral,
    DddSupportSelection,
)


class DddRefinementReason(StrEnum):
    RESOURCE_HEADWAY_CONFLICT = "resource_headway_conflict"


class DddExactLiftStatus(StrEnum):
    FEASIBLE = "feasible"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class DddExactLiftResult:
    status: DddExactLiftStatus
    solution: DddReferenceSolution | None
    conflicts: tuple[DddReferenceConflict, ...]
    cuts: tuple[DddSupportConflictCut, ...]
    refinement_reason: DddRefinementReason | None


@dataclass(frozen=True)
class DddExactSupportLifter:
    tolerance_seconds: float = 1e-9

    def lift(
        self,
        problem: DddMovementProblem,
        selection: DddSupportSelection,
    ) -> DddExactLiftResult:
        problem.validate()
        if self.tolerance_seconds < 0:
            raise ValueError("DDD lift tolerance_seconds must be nonnegative")
        starts_by_cabin_id = {start.cabin_id: start for start in problem.starts}
        selected_cabin_ids = [
            trajectory.cabin_id for trajectory in selection.trajectories
        ]
        if (
            len(selected_cabin_ids) != len(set(selected_cabin_ids))
            or set(selected_cabin_ids) != set(starts_by_cabin_id)
        ):
            raise ValueError("DDD support selection does not match fixed starts")

        # Validate each exact trajectory independently before interpreting any
        # cross-cabin collision as refinement evidence.
        for trajectory in selection.trajectories:
            single_cabin_problem = replace(
                problem,
                starts=(starts_by_cabin_id[trajectory.cabin_id],),
            )
            validate_ddd_reference_solution(
                single_cabin_problem,
                DddReferenceSolution(trajectories=(trajectory,)),
                tolerance_seconds=self.tolerance_seconds,
            )

        occurrences = tuple(
            occurrence
            for trajectory in selection.trajectories
            for occurrence in trajectory.resource_occurrences
        )
        conflicts = find_ddd_reference_conflicts(
            occurrences,
            problem,
            tolerance_seconds=self.tolerance_seconds,
        )
        if conflicts:
            cuts = tuple(
                _prefix_conflict_cut(selection, conflict) for conflict in conflicts
            )
            return DddExactLiftResult(
                status=DddExactLiftStatus.CONFLICT,
                solution=None,
                conflicts=conflicts,
                cuts=_deduplicate_cuts(cuts),
                refinement_reason=DddRefinementReason.RESOURCE_HEADWAY_CONFLICT,
            )

        solution = selection.as_reference_solution()
        validate_ddd_reference_solution(
            problem,
            solution,
            tolerance_seconds=self.tolerance_seconds,
        )
        return DddExactLiftResult(
            status=DddExactLiftStatus.FEASIBLE,
            solution=solution,
            conflicts=(),
            cuts=(),
            refinement_reason=None,
        )


def _prefix_conflict_cut(
    selection: DddSupportSelection,
    conflict: DddReferenceConflict,
) -> DddSupportConflictCut:
    trajectory_by_cabin_id = {
        trajectory.cabin_id: trajectory for trajectory in selection.trajectories
    }
    endpoints = (
        (conflict.first_cabin_id, conflict.first_visit_index),
        (conflict.second_cabin_id, conflict.second_visit_index),
    )
    literals: list[DddSupportLiteral] = []
    for cabin_id, final_visit_index in endpoints:
        trajectory = trajectory_by_cabin_id.get(cabin_id)
        if trajectory is None or final_visit_index >= len(trajectory.visits):
            raise ValueError("DDD conflict references an unknown selected visit")
        literals.extend(
            DddSupportLiteral(
                cabin_id=cabin_id,
                visit_index=visit.visit_index,
                route_option_id=visit.route_option_id,
            )
            for visit in trajectory.visits[: final_visit_index + 1]
        )
    unique_literals = tuple(sorted(set(literals)))
    literal_id = "__".join(
        f"c{literal.cabin_id}_v{literal.visit_index}_{literal.route_option_id}"
        for literal in unique_literals
    )
    cut = DddSupportConflictCut(
        id=f"resource_prefix::{conflict.resource_id}::{literal_id}",
        literals=unique_literals,
        resource_id=conflict.resource_id,
        violation_seconds=conflict.violation_seconds,
    )
    cut.validate()
    return cut


def _deduplicate_cuts(
    cuts: tuple[DddSupportConflictCut, ...],
) -> tuple[DddSupportConflictCut, ...]:
    by_id: dict[str, DddSupportConflictCut] = {}
    for cut in cuts:
        existing = by_id.get(cut.id)
        if existing is None or cut.violation_seconds > existing.violation_seconds:
            by_id[cut.id] = cut
    return tuple(by_id[cut_id] for cut_id in sorted(by_id))
