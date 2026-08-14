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
                "resource_window="
                f"{iteration.resource_window_resolve_count}r/"
                f"+{iteration.resource_window_added_count}/"
                f"{iteration.resource_window_entry_row_count}e/"
                f"{iteration.resource_window_energy_row_count}g/"
                f"cand={iteration.resource_window_candidate_count}/"
                f"viol={iteration.resource_window_violated_count}/"
                f"dup={iteration.resource_window_duplicate_count}/"
                f"LB={_format_bound(iteration.resource_window_lower_bound_before)}"
                f"->{_format_bound(iteration.resource_window_lower_bound_after)}/"
                f"{iteration.resource_window_separation_seconds + iteration.resource_window_master_seconds:.2f}s"
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
                "cabin_path="
                f"{iteration.cp_sat_cabin_path_status.value}/"
                f"{iteration.cp_sat_cabin_path_seconds:.2f}s/"
                f"core={len(iteration.cp_sat_cabin_path_core_cabin_ids)}c/"
                f"{iteration.cp_sat_cabin_path_core_literal_count}l"
                f"->{iteration.cp_sat_cabin_path_cut_literal_count}p/"
                f"+{len(iteration.added_cabin_path_core_cut_ids)}"
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
                + (",".join(iteration.cp_sat_timed_flow_core_resource_ids) or "-")
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
                f"{iteration.trajectory_pool_status.value if iteration.trajectory_pool_status is not None else ('pending' if iteration.trajectory_optimizer_mode.value != 'off' else 'off')}/"
                f"{iteration.trajectory_bound_status.value if iteration.trajectory_bound_status is not None else 'none'}/"
                f"{iteration.trajectory_pool_candidate_count}p/"
                f"+{iteration.trajectory_pool_added_option_count}o/"
                f"{iteration.trajectory_pool_option_count}o/"
                f"{iteration.trajectory_pool_ride_variable_count}r/"
                f"{iteration.trajectory_pool_conflict_round_count}c/"
                f"{iteration.trajectory_pool_incompatibility_count}i/"
                f"run={int(iteration.trajectory_pool_solved_this_round)}/"
                f"cache={iteration.trajectory_pool_option_cache_hit_count}h:"
                f"{iteration.trajectory_pool_option_cache_miss_count}m/"
                f"+{iteration.trajectory_pool_added_ride_variable_count}rv/"
                f"model={'new' if iteration.trajectory_pool_master_model_created else 'reuse'}/"
                f"update={iteration.trajectory_pool_master_update_seconds:.2f}s/"
                f"first={_format_bound(iteration.trajectory_pool_time_to_first_incumbent_seconds)}s/"
                f"imp={iteration.trajectory_pool_incumbent_improvement_count}/"
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
    _master_incumbent: float | None = field(init=False, default=None)
    _master_best_bound: float | None = field(init=False, default=None)

    def __enter__(self) -> DddTerminalProgress:
        if self.enabled:
            round_digits = len(str(self.max_iterations))
            self._bar = tqdm(
                total=self.max_iterations,
                desc=self.description,
                unit="round",
                dynamic_ncols=False,
                bar_format=(
                    "{desc} {percentage:5.1f}% "
                    f"{{n:>{round_digits}d}}/{{total:<{round_digits}d}} "
                    "{postfix}"
                ),
            )
        return self

    def __exit__(self, *_: object) -> None:
        if self._bar is not None:
            self._bar.close()

    def update(self, event: DddNetworkTimeRefinementProgressEvent) -> None:
        if self._bar is None:
            return
        if event.stage is DddNetworkTimeRefinementProgressStage.ROUND_STARTED:
            self._master_incumbent = None
            self._master_best_bound = None
        round_finished = (
            event.stage is DddNetworkTimeRefinementProgressStage.ROUND_FINISHED
        )
        if round_finished:
            if event.iteration is None:
                raise ValueError("finished DDD round lacks iteration metrics")
        if event.stage is DddNetworkTimeRefinementProgressStage.MASTER_PROGRESS:
            master = event.master_progress
            if master is None:
                raise ValueError("DDD master progress event lacks diagnostics")
            self._master_incumbent = master.incumbent_objective
            self._master_best_bound = master.best_bound
        stage = event.stage.value
        if event.stage is DddNetworkTimeRefinementProgressStage.MASTER_PROGRESS:
            master = event.master_progress
            if master is None:
                raise ValueError("DDD master progress event lacks diagnostics")
            marker = (
                "final"
                if master.requested_elapsed_seconds is None
                else f"{master.requested_elapsed_seconds:g}s"
            )
            stage = f"master@{marker}"
        self._bar.set_postfix_str(
            _format_fixed_live_progress(
                event=event,
                stage=stage,
                master_incumbent=self._master_incumbent,
                master_best_bound=self._master_best_bound,
            ),
            refresh=False,
        )
        if round_finished:
            self._bar.update(max(0, event.round_index - self._bar.n))
        else:
            self._bar.refresh()


def _format_bound(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.6g}"


def _format_fixed_live_progress(
    *,
    event: DddNetworkTimeRefinementProgressEvent,
    stage: str,
    master_incumbent: float | None,
    master_best_bound: float | None,
) -> str:
    lower_bound = event.global_lower_bound
    if master_best_bound is not None:
        lower_bound = (
            master_best_bound
            if lower_bound is None
            else max(lower_bound, master_best_bound)
        )
    gap = _relative_gap(lower_bound, event.global_upper_bound)
    return " ".join(
        (
            f"S={_short_stage(stage):<4}",
            f"LB={_format_fixed_number(lower_bound)}",
            f"UB={_format_fixed_number(event.global_upper_bound)}",
            f"INC={_format_fixed_number(master_incumbent)}",
            f"GAP={_format_fixed_percent(gap)}",
        )
    )


def _format_fixed_number(value: float | None, *, width: int = 9) -> str:
    if value is None:
        return "-".rjust(width)
    return f"{value:.4g}".rjust(width)


def _format_fixed_percent(value: float | None, *, width: int = 7) -> str:
    if value is None:
        return "-".rjust(width)
    return f"{100.0 * value:.2f}%".rjust(width)


def _short_stage(stage: str) -> str:
    if stage.startswith("master"):
        return "MIP"
    if "primal_oracle" in stage or "bootstrap" in stage:
        return "CP"
    if "evaluation" in stage:
        return "OBJ"
    if "network" in stage:
        return "NET"
    if "decomposition" in stage:
        return "DEC"
    if "recovery" in stage:
        return "REC"
    if "lifting" in stage:
        return "LFT"
    if "resource_window" in stage:
        return "ROW"
    if "trajectory_pool" in stage:
        return "POOL"
    if stage == "round_finished":
        return "DONE"
    return "RND"


def _relative_gap(lower_bound: float | None, upper_bound: float | None) -> float | None:
    if lower_bound is None or upper_bound is None:
        return None
    return max(0.0, upper_bound - lower_bound) / max(1.0, abs(upper_bound))
