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
            f"splits={iteration.time_split_count}:{split}",
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
