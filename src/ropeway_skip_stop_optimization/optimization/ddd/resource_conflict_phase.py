from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ddd.lifting import (
    build_ddd_prefix_conflict_cuts,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_refinement_model import (
    DddNetworkValidationResult,
    DddTimeSplit,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddLayeredTimeArc,
    DddLayeredTimeArcKind,
    DddLayeredTimeNetwork,
)
from ropeway_skip_stop_optimization.optimization.ddd.prefix_budget import (
    select_ddd_prefix_cuts_within_budget,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceConflict,
)
from ropeway_skip_stop_optimization.optimization.ddd.resource_time import (
    DddAnonymousResourceRow,
    build_ddd_universal_resource_row,
)
from ropeway_skip_stop_optimization.optimization.ddd.support_master import (
    DddSupportConflictCut,
    DddSupportSelection,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddPartialTimedArc,
    DddPartialTimedPath,
    DddTimeDiscretization,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick,
    ddd_tick_to_seconds,
)


@dataclass(frozen=True)
class DddResourceConflictPhaseResult:
    time_splits: tuple[DddTimeSplit, ...]
    refined_discretization: DddTimeDiscretization
    resource_time_split_count: int
    new_resource_rows: tuple[DddAnonymousResourceRow, ...]
    new_prefix_cuts: tuple[DddSupportConflictCut, ...]
    prefix_budget_exhausted: bool
    invalid_missing_support: bool

    @property
    def has_refinement(self) -> bool:
        return bool(self.time_splits or self.new_prefix_cuts or self.new_resource_rows)


@dataclass(frozen=True)
class DddResourceConflictPhaseSolver:
    use_universal_resource_rows: bool
    max_new_constraints_per_type: int
    max_time_splits: int
    max_prefix_variable_count: int
    max_tracked_prefix_cabin_count: int
    max_prefix_visit_index: int
    tolerance_seconds: float

    def __post_init__(self) -> None:
        if self.max_new_constraints_per_type <= 0:
            raise ValueError("DDD resource-conflict constraint limit must be positive")
        if self.max_time_splits <= 0:
            raise ValueError("DDD resource-conflict split limit must be positive")
        if self.max_prefix_variable_count <= 0:
            raise ValueError("DDD resource-conflict prefix budget must be positive")
        if self.max_tracked_prefix_cabin_count <= 0:
            raise ValueError("DDD resource-conflict cabin budget must be positive")
        if self.max_prefix_visit_index <= 0:
            raise ValueError("DDD resource-conflict visit budget must be positive")
        if self.tolerance_seconds < 0:
            raise ValueError("DDD resource-conflict tolerance must be nonnegative")

    def solve(
        self,
        *,
        network: DddLayeredTimeNetwork,
        paths: tuple[DddPartialTimedPath, ...],
        validation: DddNetworkValidationResult,
        initial_time_splits: tuple[DddTimeSplit, ...],
        refined_discretization: DddTimeDiscretization,
        active_resource_rows: tuple[DddAnonymousResourceRow, ...],
        existing_prefix_cuts: tuple[DddSupportConflictCut, ...],
        existing_prefix_cut_ids: frozenset[str],
    ) -> DddResourceConflictPhaseResult:
        selected_arc_by_visit = (
            build_ddd_selected_arc_by_visit(network, paths)
            if validation.conflicts
            and (
                self.use_universal_resource_rows
                or validation.support_selection is not None
            )
            else {}
        )
        resource_row_proofs = (
            build_ddd_universal_resource_rows_for_conflicts(
                network,
                paths,
                validation.conflicts,
                selected_arc_by_visit=selected_arc_by_visit,
            )
            if self.use_universal_resource_rows
            else ()
        )
        active_resource_row_ids = {row.id for row in active_resource_rows}
        selected_resource_row_proofs = tuple(
            proof
            for proof in resource_row_proofs
            if proof[0].id not in active_resource_row_ids
        )[: self.max_new_constraints_per_type]
        new_resource_rows = tuple(
            row for row, _conflict_indices in selected_resource_row_proofs
        )
        covered_conflict_indices = {
            conflict_index
            for _row, conflict_indices in selected_resource_row_proofs
            for conflict_index in conflict_indices
        }
        uncovered_conflicts = tuple(
            conflict
            for conflict_index, conflict in enumerate(validation.conflicts)
            if conflict_index not in covered_conflict_indices
        )

        resource_conflict_splits = build_ddd_resource_conflict_splits(
            network,
            paths,
            uncovered_conflicts,
            validation.support_selection,
            selected_arc_by_visit=selected_arc_by_visit,
        )
        time_splits = initial_time_splits
        resource_time_split_count = 0
        if resource_conflict_splits:
            remaining_split_budget = max(
                0,
                self.max_time_splits - len(time_splits),
            )
            selected_resource_splits = resource_conflict_splits[
                :remaining_split_budget
            ]
            for split in selected_resource_splits:
                refined_discretization = refined_discretization.split(
                    state_id=split.state_id,
                    boundary_seconds=split.boundary_seconds,
                    tolerance_seconds=self.tolerance_seconds,
                )
            time_splits = (*time_splits, *selected_resource_splits)
            resource_time_split_count = len(selected_resource_splits)

        invalid_missing_support = bool(
            uncovered_conflicts
            and not resource_conflict_splits
            and validation.support_selection is None
        )
        if invalid_missing_support:
            return DddResourceConflictPhaseResult(
                time_splits=time_splits,
                refined_discretization=refined_discretization,
                resource_time_split_count=resource_time_split_count,
                new_resource_rows=new_resource_rows,
                new_prefix_cuts=(),
                prefix_budget_exhausted=False,
                invalid_missing_support=True,
            )

        candidate_cuts: tuple[DddSupportConflictCut, ...] = ()
        if uncovered_conflicts and not resource_conflict_splits:
            assert validation.support_selection is not None
            candidate_cuts = (
                validation.cuts
                if len(uncovered_conflicts) == len(validation.conflicts)
                else build_ddd_prefix_conflict_cuts(
                    validation.support_selection,
                    uncovered_conflicts,
                )
            )
        new_prefix_cuts, prefix_budget_exhausted = (
            select_ddd_prefix_cuts_within_budget(
                network,
                existing_prefix_cuts,
                tuple(
                    cut
                    for cut in candidate_cuts
                    if cut.id not in existing_prefix_cut_ids
                ),
                max_new_cuts=self.max_new_constraints_per_type,
                max_variable_count=self.max_prefix_variable_count,
                max_cabin_count=self.max_tracked_prefix_cabin_count,
                max_visit_index=self.max_prefix_visit_index,
            )
        )
        return DddResourceConflictPhaseResult(
            time_splits=time_splits,
            refined_discretization=refined_discretization,
            resource_time_split_count=resource_time_split_count,
            new_resource_rows=new_resource_rows,
            new_prefix_cuts=new_prefix_cuts,
            prefix_budget_exhausted=prefix_budget_exhausted,
            invalid_missing_support=False,
        )


def build_ddd_universal_resource_rows_for_conflicts(
    network: DddLayeredTimeNetwork,
    paths: tuple[DddPartialTimedPath, ...],
    conflicts: tuple[DddReferenceConflict, ...],
    *,
    selected_arc_by_visit: dict[tuple[int, int], DddLayeredTimeArc] | None = None,
) -> tuple[tuple[DddAnonymousResourceRow, tuple[int, ...]], ...]:
    """Classify exact conflicts that are universal in their current cells."""

    if not conflicts:
        return ()
    if selected_arc_by_visit is None:
        selected_arc_by_visit = build_ddd_selected_arc_by_visit(network, paths)

    proof_by_row_id: dict[str, tuple[DddAnonymousResourceRow, set[int]]] = {}
    for conflict_index, conflict in enumerate(conflicts):
        first_arc = selected_arc_by_visit.get(
            (conflict.first_cabin_id, conflict.first_visit_index)
        )
        second_arc = selected_arc_by_visit.get(
            (conflict.second_cabin_id, conflict.second_visit_index)
        )
        if first_arc is None or second_arc is None:
            raise RuntimeError("DDD resource conflict references an unselected visit")
        first_windows = tuple(
            window
            for window in first_arc.resource_windows
            if window.resource_id == conflict.resource_id
        )
        second_windows = tuple(
            window
            for window in second_arc.resource_windows
            if window.resource_id == conflict.resource_id
        )
        for first_window in first_windows:
            for second_window in second_windows:
                row = build_ddd_universal_resource_row(first_window, second_window)
                if row is None:
                    continue
                existing = proof_by_row_id.get(row.id)
                if existing is None:
                    proof_by_row_id[row.id] = (row, {conflict_index})
                else:
                    existing[1].add(conflict_index)

    return tuple(
        (row, tuple(sorted(conflict_indices)))
        for row, conflict_indices in proof_by_row_id.values()
    )


def build_ddd_selected_arc_by_visit(
    network: DddLayeredTimeNetwork,
    paths: tuple[DddPartialTimedPath, ...],
) -> dict[tuple[int, int], DddLayeredTimeArc]:
    arcs_by_partial_key: dict[
        tuple[DddPartialTimedArc, DddLayeredTimeArcKind, int | None],
        list[DddLayeredTimeArc],
    ] = {}
    for arc in network.arcs:
        if arc.partial_arc is None or arc.kind not in (
            DddLayeredTimeArcKind.SOURCE,
            DddLayeredTimeArcKind.MOVEMENT,
        ):
            continue
        key = (
            arc.partial_arc,
            arc.kind,
            arc.cabin_id if arc.kind is DddLayeredTimeArcKind.SOURCE else None,
        )
        arcs_by_partial_key.setdefault(key, []).append(arc)

    selected_arc_by_visit: dict[tuple[int, int], DddLayeredTimeArc] = {}
    for path in paths:
        for partial_arc in path.arcs:
            kind = (
                DddLayeredTimeArcKind.SOURCE
                if partial_arc.visit_index == 0
                else DddLayeredTimeArcKind.MOVEMENT
            )
            candidates = arcs_by_partial_key.get(
                (
                    partial_arc,
                    kind,
                    path.cabin_id if kind is DddLayeredTimeArcKind.SOURCE else None,
                ),
                (),
            )
            if len(candidates) != 1:
                raise RuntimeError(
                    "DDD selected partial visit does not identify one layered arc"
                )
            selected_arc_by_visit[(path.cabin_id, partial_arc.visit_index)] = (
                candidates[0]
            )
    return selected_arc_by_visit


def build_ddd_resource_conflict_splits(
    network: DddLayeredTimeNetwork,
    paths: tuple[DddPartialTimedPath, ...],
    conflicts: tuple[DddReferenceConflict, ...],
    selection: DddSupportSelection | None,
    *,
    selected_arc_by_visit: dict[tuple[int, int], DddLayeredTimeArc] | None = None,
) -> tuple[DddTimeSplit, ...]:
    """Split current source cells at exact headway-order thresholds."""

    if not conflicts or selection is None:
        return ()
    if selected_arc_by_visit is None:
        selected_arc_by_visit = build_ddd_selected_arc_by_visit(network, paths)
    visit_by_key = {
        (trajectory.cabin_id, visit.visit_index): visit
        for trajectory in selection.trajectories
        for visit in trajectory.visits
    }
    splits: set[DddTimeSplit] = set()
    for conflict in conflicts:
        first_arc = selected_arc_by_visit.get(
            (conflict.first_cabin_id, conflict.first_visit_index)
        )
        second_arc = selected_arc_by_visit.get(
            (conflict.second_cabin_id, conflict.second_visit_index)
        )
        if first_arc is None or second_arc is None:
            raise RuntimeError("DDD resource conflict references an unselected visit")
        first_visit = visit_by_key[
            (conflict.first_cabin_id, conflict.first_visit_index)
        ]
        second_visit = visit_by_key[
            (conflict.second_cabin_id, conflict.second_visit_index)
        ]
        first_source_tick = ddd_seconds_to_tick(first_visit.switch_time_seconds)
        second_source_tick = ddd_seconds_to_tick(second_visit.switch_time_seconds)
        first_windows = tuple(
            window
            for window in first_arc.resource_windows
            if window.resource_id == conflict.resource_id
        )
        second_windows = tuple(
            window
            for window in second_arc.resource_windows
            if window.resource_id == conflict.resource_id
        )
        for first_window in first_windows:
            for second_window in second_windows:
                second_boundary_tick = (
                    first_source_tick
                    + first_window.leader_clear_offset_tick
                    + first_window.headway_tick
                    - second_window.follower_enter_offset_tick
                )
                first_boundary_tick = (
                    second_source_tick
                    + second_window.leader_clear_offset_tick
                    + second_window.headway_tick
                    - first_window.follower_enter_offset_tick
                )
                for arc, window, boundary_tick in (
                    (second_arc, second_window, second_boundary_tick),
                    (first_arc, first_window, first_boundary_tick),
                ):
                    if (
                        arc.kind is not DddLayeredTimeArcKind.MOVEMENT
                        or arc.partial_arc is None
                        or not (
                            window.source_interval.lower_tick
                            < boundary_tick
                            < window.source_interval.upper_tick
                        )
                    ):
                        continue
                    splits.add(
                        DddTimeSplit(
                            state_id=arc.partial_arc.from_state_id,
                            boundary_seconds=ddd_tick_to_seconds(boundary_tick),
                        )
                    )
    return tuple(sorted(splits))
