from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256

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
    DDD_CP_SAT_CABIN_PATH_CORE_PROVENANCE,
    DddSupportConflictCut,
    DddSupportLiteral,
    DddSupportSelection,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddPartialTimedPath,
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
            cuts = build_ddd_prefix_conflict_cuts(
                selection,
                conflicts,
            )
            return DddExactLiftResult(
                status=DddExactLiftStatus.CONFLICT,
                solution=None,
                conflicts=conflicts,
                cuts=cuts,
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


def build_ddd_prefix_conflict_cuts(
    selection: DddSupportSelection,
    conflicts: tuple[DddReferenceConflict, ...],
) -> tuple[DddSupportConflictCut, ...]:
    return _deduplicate_cuts(
        tuple(
            _prefix_conflict_cut(selection, conflict)
            for conflict in conflicts
        )
    )


def build_ddd_cabin_path_core_cut(
    paths: tuple[DddPartialTimedPath, ...],
    core: tuple[DddSupportLiteral, ...],
) -> DddSupportConflictCut:
    """Lift an exact CP-SAT cabin-path core into a delayed prefix no-good."""

    if not core or tuple(sorted(set(core))) != core:
        raise ValueError("DDD cabin-path core must be sorted and unique")
    paths_by_cabin_id = {path.cabin_id: path for path in paths}
    if len(paths_by_cabin_id) != len(paths):
        raise ValueError("DDD cabin paths must have unique cabin ids")
    unknown = {literal.cabin_id for literal in core} - paths_by_cabin_id.keys()
    if unknown:
        raise ValueError(f"DDD cabin-path core references unknown cabins: {sorted(unknown)}")
    for literal in core:
        path = paths_by_cabin_id[literal.cabin_id]
        if literal.visit_index >= len(path.arcs):
            raise ValueError("DDD cabin-path core visit exceeds the selected path")
        if path.route_option_ids[literal.visit_index] != literal.route_option_id:
            raise ValueError("DDD cabin-path core literal differs from selected path")
    digest = sha256(
        "||".join(
            f"{item.cabin_id}:{item.visit_index}:{item.route_option_id}"
            for item in core
        ).encode("utf-8")
    ).hexdigest()[:20]
    cut = DddSupportConflictCut(
        id=f"cp_sat_cabin_path_core::{digest}",
        literals=core,
        resource_id="cp_sat_joint_cabin_paths",
        # This cut is a logical no-good, not a measured pairwise headway
        # violation.  The legacy field remains positive for schema compatibility.
        violation_seconds=1.0,
        provenance=DDD_CP_SAT_CABIN_PATH_CORE_PROVENANCE,
    )
    cut.validate()
    return cut


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
