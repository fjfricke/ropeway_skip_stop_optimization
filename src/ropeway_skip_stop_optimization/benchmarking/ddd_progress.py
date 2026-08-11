from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tqdm.auto import tqdm

from ropeway_skip_stop_optimization.optimization.ddd import (
    DddNetworkTimeRefinementIteration,
    DddNetworkTimeRefinementProgressEvent,
    DddNetworkTimeRefinementProgressStage,
)


def format_ddd_iteration_progress(
    iteration: DddNetworkTimeRefinementIteration,
) -> str:
    lower = _format_bound(iteration.global_lower_bound)
    upper = _format_bound(iteration.global_upper_bound)
    gap = (
        iteration.global_upper_bound - iteration.global_lower_bound
        if iteration.global_lower_bound is not None
        and iteration.global_upper_bound is not None
        else None
    )
    split = (
        "none"
        if iteration.split_state_id is None
        else f"{iteration.split_state_id}@{iteration.split_boundary_seconds:.3f}"
    )
    return " ".join(
        (
            f"round={iteration.round_index}",
            f"LB/UB={lower}/{upper}",
            f"gap={_format_bound(gap)}",
            f"N/A={iteration.node_count}/{iteration.arc_count}",
            f"V/R={iteration.variable_count}/{iteration.constraint_count}",
            (
                "prefix="
                f"{iteration.tracked_prefix_cabin_count}c/"
                f"{iteration.prefix_variable_count}v/"
                f"d{iteration.maximum_prefix_visit_index}"
            ),
            (
                "warm="
                f"{iteration.warm_start_projected_cabin_count}c/"
                f"{iteration.warm_start_complete_cabin_count}f/"
                f"{iteration.warm_start_arc_variable_count + iteration.warm_start_prefix_variable_count}v"
            ),
            (
                "cache="
                f"{iteration.network_transition_cache_hits}h/"
                f"{iteration.network_transition_cache_misses}m/"
                f"{iteration.network_invalidated_state_count}i"
            ),
            (
                "conflicts="
                f"{iteration.conflict_count}/"
                f"+{len(iteration.added_cut_ids)}/"
                f"{iteration.total_conflict_cut_count}"
            ),
            (
                "resource_rows="
                f"{iteration.resource_constraint_count}/"
                f"{iteration.mandatory_resource_constraint_count}m/"
                f"{iteration.additional_resource_constraint_count}a/"
                f"+{len(iteration.added_resource_row_ids)}/"
                f"{iteration.total_universal_resource_row_count}u/"
                f"{iteration.total_interval_resource_row_count}i"
            ),
            (
                "cp="
                f"{iteration.cp_sat_status.value}/"
                f"{iteration.cp_sat_candidate_count}n/"
                f"{iteration.cp_sat_seconds:.2f}s/"
                f"{iteration.cp_sat_conflict_count}c/"
                f"{iteration.cp_sat_branch_count}b/"
                f"complete={int(iteration.cp_sat_search_complete)}"
            ),
            (
                "aggregate="
                f"{iteration.aggregate_support_constraint_count}c/"
                f"{iteration.aggregate_threshold_variable_count}v/"
                f"{iteration.fixed_start_structural_constraint_count}s/"
                f"+{len(iteration.added_aggregate_support_cut_ids)}/"
                f"core={iteration.cp_sat_core_literal_count}"
            ),
            (
                "nearest="
                f"{iteration.cp_sat_nearest_status.value}/"
                f"d={_format_bound(iteration.cp_sat_nearest_distance_primal)}/"
                f"bound={_format_bound(iteration.cp_sat_nearest_distance_lower_bound)}/"
                f"+{len(iteration.added_aggregate_distance_cut_ids)}/"
                f"{iteration.cp_sat_nearest_seconds:.2f}s"
            ),
            (
                "timed_cover="
                f"{iteration.timed_flow_cover_constraint_count}c/"
                f"{iteration.timed_flow_threshold_variable_count}v/"
                f"core={iteration.cp_sat_timed_flow_core_literal_count}/"
                f"+{len(iteration.added_timed_flow_cover_cut_ids)}/"
                "resources="
                + (
                    ",".join(iteration.cp_sat_timed_flow_core_resource_ids)
                    or "-"
                )
            ),
            (
                "master_passenger="
                f"{iteration.master_passenger_variable_count}v/"
                f"{iteration.master_passenger_constraint_count}r/"
                f"served={_format_bound(iteration.master_served_passenger_count)}/"
                f"unserved={_format_bound(iteration.master_unserved_passenger_count)}"
            ),
            (
                "master="
                f"{iteration.master_termination_reason or '-'}/"
                f"build={iteration.master_model_build_seconds:.2f}s/"
                f"solve={iteration.master_optimize_seconds:.2f}s/"
                f"first={_format_bound(iteration.master_time_to_first_incumbent_seconds)}s/"
                f"nodes={iteration.master_explored_node_count:.0f}/"
                f"sol={iteration.master_solution_count}/"
                f"gap={_format_bound(iteration.master_relative_gap)}"
            ),
            (
                "primal="
                f"{iteration.primal_evaluation_status.value}/"
                f"{iteration.primal_evaluation_count}n/"
                f"{iteration.primal_evaluation_seconds:.2f}s/"
                f"obj={_format_bound(iteration.primal_objective_value)}/"
                f"served={iteration.served_passenger_count}/"
                f"unserved={iteration.unserved_passenger_count}"
            ),
            (
                "trajectory_pool="
                f"{iteration.trajectory_pool_status.value if iteration.trajectory_pool_status is not None else 'off'}/"
                f"{iteration.trajectory_pool_option_count}o/"
                f"{iteration.trajectory_pool_ride_variable_count}r/"
                f"{iteration.trajectory_pool_conflict_round_count}c/"
                f"{iteration.trajectory_pool_incompatibility_count}i/"
                f"{iteration.trajectory_pool_seconds:.2f}s"
            ),
            (
                f"splits={iteration.time_split_count}:"
                f"{iteration.trajectory_time_split_count}t/"
                f"{iteration.resource_time_split_count}r:{split}"
            ),
            f"time={iteration.round_seconds:.2f}s",
        )
    )


@dataclass
class DddTerminalProgress:
    enabled: bool
    max_iterations: int
    description: str = "DDD refinement"
    _bar: Any | None = field(init=False, default=None)

    def __enter__(self) -> DddTerminalProgress:
        if self.enabled:
            self._bar = tqdm(
                total=self.max_iterations,
                desc=self.description,
                unit="round",
                dynamic_ncols=True,
            )
        return self

    def __exit__(self, *_: object) -> None:
        if self._bar is not None:
            self._bar.close()

    def update(self, event: DddNetworkTimeRefinementProgressEvent) -> None:
        if self._bar is None:
            return
        if event.stage is DddNetworkTimeRefinementProgressStage.ROUND_FINISHED:
            if event.iteration is None:
                raise ValueError("finished DDD round lacks iteration metrics")
            self._bar.update(max(0, event.round_index - self._bar.n))
            self._bar.set_postfix_str(
                format_ddd_iteration_progress(event.iteration),
                refresh=True,
            )
            return
        if event.stage in {
            DddNetworkTimeRefinementProgressStage.PRIMAL_ORACLE_CANDIDATE_FOUND,
            DddNetworkTimeRefinementProgressStage.PRIMAL_EVALUATION_FINISHED,
        }:
            self._bar.set_postfix_str(
                " ".join(
                    (
                        f"round={event.round_index}",
                        f"stage={event.stage.value}",
                        (f"candidate={event.candidate_index}/{event.candidate_limit}"),
                        (
                            f"candidate_time={event.candidate_elapsed_seconds:.1f}s"
                            if event.candidate_elapsed_seconds is not None
                            else "candidate_time=-"
                        ),
                        (f"best={_format_bound(event.primal_best_objective)}"),
                    )
                ),
                refresh=True,
            )
            return
        if event.stage is DddNetworkTimeRefinementProgressStage.MASTER_PROGRESS:
            master = event.master_progress
            if master is None:
                raise ValueError("DDD master progress event lacks diagnostics")
            marker = (
                "final"
                if master.requested_elapsed_seconds is None
                else f"{master.requested_elapsed_seconds:g}s"
            )
            self._bar.set_postfix_str(
                " ".join(
                    (
                        f"round={event.round_index}",
                        f"stage=master@{marker}",
                        f"inc={_format_bound(master.incumbent_objective)}",
                        f"bound={_format_bound(master.best_bound)}",
                        f"gap={_format_bound(master.relative_gap)}",
                        f"nodes={master.explored_node_count:.0f}",
                        f"open={master.open_node_count:.0f}",
                        f"sol={master.solution_count}",
                    )
                ),
                refresh=True,
            )
            return
        self._bar.set_postfix_str(
            " ".join(
                (
                    f"round={event.round_index}",
                    f"stage={event.stage.value}",
                    f"elapsed={event.total_elapsed_seconds:.1f}s",
                )
            ),
            refresh=True,
        )


def _format_bound(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.6g}"
