from __future__ import annotations

from dataclasses import dataclass
import math

from ropeway_skip_stop_optimization.optimization.ddd.network_refinement_model import (
    DddNetworkTimeRefinementStatus,
)


@dataclass(frozen=True)
class DddRoundTerminationDecision:
    status: DddNetworkTimeRefinementStatus | None
    upper_bound: float
    clear_primal_evaluation: bool = False

    @property
    def should_terminate(self) -> bool:
        return self.status is not None


@dataclass(frozen=True)
class DddRoundTerminationPolicy:
    bound_tolerance: float

    def __post_init__(self) -> None:
        if self.bound_tolerance < 0:
            raise ValueError("DDD termination bound tolerance must be nonnegative")

    def decide(
        self,
        *,
        cp_sat_exact_infeasible: bool,
        has_incumbent: bool,
        refinement_stalled: bool,
        time_split_count: int,
        new_prefix_cut_count: int,
        new_resource_row_count: int,
        new_aggregate_support_cut_count: int,
        trajectory_pool_added_option_count: int,
        lower_bound: float,
        upper_bound: float,
    ) -> DddRoundTerminationDecision:
        counts = (
            time_split_count,
            new_prefix_cut_count,
            new_resource_row_count,
            new_aggregate_support_cut_count,
            trajectory_pool_added_option_count,
        )
        if any(count < 0 for count in counts):
            raise ValueError("DDD termination refinement counts must be nonnegative")

        if cp_sat_exact_infeasible:
            return DddRoundTerminationDecision(
                status=(
                    DddNetworkTimeRefinementStatus.INVALID_INTERNAL
                    if has_incumbent
                    else DddNetworkTimeRefinementStatus.EXACT_INFEASIBLE
                ),
                upper_bound=upper_bound if has_incumbent else math.inf,
                clear_primal_evaluation=True,
            )

        has_core_refinement = bool(
            time_split_count
            or new_prefix_cut_count
            or new_resource_row_count
            or new_aggregate_support_cut_count
        )
        if refinement_stalled and not has_core_refinement:
            return DddRoundTerminationDecision(
                status=DddNetworkTimeRefinementStatus.REFINEMENT_STALLED,
                upper_bound=upper_bound,
            )
        if lower_bound > upper_bound + self.bound_tolerance:
            return DddRoundTerminationDecision(
                status=DddNetworkTimeRefinementStatus.INVALID_INTERNAL,
                upper_bound=upper_bound,
            )
        if upper_bound - lower_bound <= self.bound_tolerance:
            return DddRoundTerminationDecision(
                status=DddNetworkTimeRefinementStatus.OPTIMAL,
                upper_bound=upper_bound,
            )
        if not has_core_refinement and trajectory_pool_added_option_count == 0:
            return DddRoundTerminationDecision(
                status=(
                    DddNetworkTimeRefinementStatus.FEASIBLE_WITH_GAP
                    if has_incumbent
                    else DddNetworkTimeRefinementStatus.UNKNOWN_NO_INCUMBENT
                ),
                upper_bound=upper_bound,
            )
        return DddRoundTerminationDecision(status=None, upper_bound=upper_bound)
