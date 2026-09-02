from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

from ropeway_skip_stop_optimization.optimization.ddd.aggregate_support import (
    DddAggregateSupportCut,
    DddAggregateSupportDistanceCut,
)
from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddAnonymousFlowMaster,
    DddAnonymousFlowResult,
    DddAnonymousFlowStatus,
    DddAnonymousFlowWarmStart,
    DddAnonymousMasterProgress,
    DddLayeredTimeNetwork,
)
from ropeway_skip_stop_optimization.optimization.ddd.passenger_master import (
    DddPassengerMasterProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.resource_time import (
    DddAnonymousResourceRow,
    DddAnonymousResourceRowKind,
    DddResourceWindowCutMode,
    separate_ddd_resource_window_rows,
)
from ropeway_skip_stop_optimization.optimization.ddd.support_master import (
    DddSupportConflictCut,
)
from ropeway_skip_stop_optimization.optimization.ddd.timed_flow_cover import (
    DddTimedFlowCoverCut,
)


@dataclass(frozen=True)
class DddNetworkMasterPhaseResult:
    flow: DddAnonymousFlowResult
    active_resource_rows: tuple[DddAnonymousResourceRow, ...]
    added_resource_rows: tuple[DddAnonymousResourceRow, ...]
    solve_seconds: float
    resource_window_resolve_count: int
    resource_window_candidate_count: int
    resource_window_violated_count: int
    resource_window_duplicate_count: int
    resource_window_entry_row_count: int
    resource_window_energy_row_count: int
    resource_window_separation_seconds: float
    resource_window_master_seconds: float
    resource_window_lower_bound_before: float | None
    resource_window_lower_bound_after: float | None


@dataclass(frozen=True)
class DddNetworkMasterPhaseSolver:
    resource_window_cut_mode: DddResourceWindowCutMode
    max_resource_window_rows_per_resolve: int
    max_resource_window_resolves: int

    def __post_init__(self) -> None:
        if not isinstance(self.resource_window_cut_mode, DddResourceWindowCutMode):
            raise ValueError("DDD resource-window cut mode is invalid")
        if self.max_resource_window_rows_per_resolve <= 0:
            raise ValueError("DDD resource-window row limit must be positive")
        if self.max_resource_window_resolves <= 0:
            raise ValueError("DDD resource-window resolve limit must be positive")

    def solve(
        self,
        *,
        master: DddAnonymousFlowMaster,
        network: DddLayeredTimeNetwork,
        cuts: tuple[DddSupportConflictCut, ...],
        aggregate_support_cuts: tuple[DddAggregateSupportCut, ...],
        aggregate_distance_cuts: tuple[DddAggregateSupportDistanceCut, ...],
        timed_flow_cover_cuts: tuple[DddTimedFlowCoverCut, ...],
        resource_rows: tuple[DddAnonymousResourceRow, ...],
        warm_start: DddAnonymousFlowWarmStart | None,
        passenger_problem: DddPassengerMasterProblem | None,
        fixed_start_movement_problem: DddMovementProblem | None,
        on_master_started: Callable[[], None] | None = None,
        on_master_progress: Callable[[DddAnonymousMasterProgress], None] | None = None,
        on_master_finished: Callable[[], None] | None = None,
        on_separation_finished: Callable[[], None] | None = None,
        time_limit_seconds: float | None = None,
    ) -> DddNetworkMasterPhaseResult:
        if time_limit_seconds is not None and time_limit_seconds <= 0:
            raise ValueError("DDD master-phase time limit must be positive")
        phase_started = perf_counter()
        active_resource_rows = list(resource_rows)
        added_resource_rows: list[DddAnonymousResourceRow] = []
        resource_windows = tuple(
            window for arc in network.arcs for window in arc.resource_windows
        )
        resolve_count = 0
        candidate_count = 0
        violated_count = 0
        duplicate_count = 0
        entry_row_count = 0
        energy_row_count = 0
        separation_seconds = 0.0
        resource_window_master_seconds = 0.0
        lower_bound_before: float | None = None
        lower_bound_after: float | None = None
        solve_seconds = 0.0
        current_warm_start = warm_start

        while True:
            if on_master_started is not None:
                on_master_started()
            master_started = perf_counter()
            flow = master.solve(
                network,
                cuts=cuts,
                aggregate_support_cuts=aggregate_support_cuts,
                aggregate_distance_cuts=aggregate_distance_cuts,
                timed_flow_cover_cuts=timed_flow_cover_cuts,
                resource_rows=tuple(active_resource_rows),
                warm_start=current_warm_start,
                passenger_problem=passenger_problem,
                fixed_start_movement_problem=fixed_start_movement_problem,
                progress_callback=on_master_progress,
                time_limit_seconds=(
                    None
                    if time_limit_seconds is None
                    else max(
                        1e-3,
                        time_limit_seconds - (perf_counter() - phase_started),
                    )
                ),
            )
            current_solve_seconds = perf_counter() - master_started
            solve_seconds += current_solve_seconds
            if resolve_count:
                resource_window_master_seconds += current_solve_seconds
            if on_master_finished is not None:
                on_master_finished()
            if flow.status in (
                DddAnonymousFlowStatus.INFEASIBLE,
                DddAnonymousFlowStatus.TIME_LIMIT,
            ):
                break
            if flow.best_bound is None:
                raise RuntimeError("optimal DDD network flow returned no best bound")
            if lower_bound_before is None:
                lower_bound_before = flow.best_bound
            lower_bound_after = flow.best_bound
            if self.resource_window_cut_mode is DddResourceWindowCutMode.OFF:
                break

            separation_started = perf_counter()
            separation = separate_ddd_resource_window_rows(
                resource_windows,
                arc_flow_by_id={item.arc_id: item.value for item in flow.arc_values},
                mode=self.resource_window_cut_mode,
                max_rows=self.max_resource_window_rows_per_resolve,
            )
            separation_seconds += perf_counter() - separation_started
            candidate_count += separation.candidate_window_count
            violated_count += separation.violated_candidate_count
            duplicate_count += separation.duplicate_candidate_count
            active_resource_row_ids = {row.id for row in active_resource_rows}
            new_rows = tuple(
                row
                for row in separation.rows
                if row.id not in active_resource_row_ids
            )
            duplicate_count += len(separation.rows) - len(new_rows)
            if on_separation_finished is not None:
                on_separation_finished()
            if not new_rows or resolve_count >= self.max_resource_window_resolves:
                break

            active_resource_rows.extend(new_rows)
            added_resource_rows.extend(new_rows)
            entry_row_count += sum(
                row.kind is DddAnonymousResourceRowKind.INTERVAL_CAPACITY
                for row in new_rows
            )
            energy_row_count += sum(
                row.kind is DddAnonymousResourceRowKind.INTERVAL_ENERGY
                for row in new_rows
            )
            resolve_count += 1
            current_warm_start = DddAnonymousFlowWarmStart(
                arc_values=flow.arc_values,
                prefix_arc_values=flow.prefix_arc_values,
                projected_cabin_count=len(network.cabin_ids),
                complete_cabin_count=0,
            )

        return DddNetworkMasterPhaseResult(
            flow=flow,
            active_resource_rows=tuple(active_resource_rows),
            added_resource_rows=tuple(added_resource_rows),
            solve_seconds=solve_seconds,
            resource_window_resolve_count=resolve_count,
            resource_window_candidate_count=candidate_count,
            resource_window_violated_count=violated_count,
            resource_window_duplicate_count=duplicate_count,
            resource_window_entry_row_count=entry_row_count,
            resource_window_energy_row_count=energy_row_count,
            resource_window_separation_seconds=separation_seconds,
            resource_window_master_seconds=resource_window_master_seconds,
            resource_window_lower_bound_before=lower_bound_before,
            resource_window_lower_bound_after=lower_bound_after,
        )
