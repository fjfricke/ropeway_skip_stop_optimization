from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ropeway_skip_stop_optimization.optimization.ean.artifact import (
    EanBuildArtifact,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    HeadwayCheckpointKind,
)


VisitKey = tuple[int, int]


@dataclass(frozen=True)
class EanPairwiseFifoBuildMetrics:
    constrained_pair_count: int
    service_fifo_row_count: int
    skip_fifo_row_count: int


@dataclass(frozen=True)
class EanPairwiseFifoConstraintBuilder:
    """Bind pair orders to the physical input order on non-overtaking branches.

    The existing pair expression uses value one for ``first before second``.
    When both events choose Service, or both choose Skip at the direct Exit
    Switch, that output orientation must agree with the chronological station
    entry order. Different Service/Skip choices remain an unconstrained merge.
    """

    def build(
        self,
        *,
        model: Any,
        artifact: EanBuildArtifact,
        headway_pool: Any,
        switch_time: dict[VisitKey, Any],
        stop: dict[VisitKey, Any],
        route_active: dict[VisitKey, Any],
        big_m: float,
    ) -> EanPairwiseFifoBuildMetrics:
        if big_m <= 0:
            raise ValueError("Pairwise FIFO needs a positive Big-M")
        checkpoint_by_id = {
            checkpoint.id: checkpoint for checkpoint in artifact.headway_checkpoints
        }
        candidate_by_id = {
            candidate.id: candidate for candidate in artifact.headway_candidates
        }
        constrained_pairs = 0
        service_rows = 0
        skip_rows = 0
        for pair in artifact.headway_pairs:
            checkpoint = checkpoint_by_id[pair.checkpoint_id]
            if checkpoint.kind not in {
                HeadwayCheckpointKind.ENTRY_SWITCH,
                HeadwayCheckpointKind.PLATFORM_ENTRY,
                HeadwayCheckpointKind.PLATFORM_EXIT,
                HeadwayCheckpointKind.EXIT_SWITCH,
                HeadwayCheckpointKind.SERVICE_MECHANISM,
            }:
                continue
            first = candidate_by_id[pair.first_candidate_id]
            second = candidate_by_id[pair.second_candidate_id]
            first_key = (first.cabin_id, first.visit_index)
            second_key = (second.cabin_id, second.visit_index)
            order = headway_pool.pair_order_expression(pair.id)
            active_relaxation = 2 - route_active[first_key] - route_active[second_key]

            # Both Service: output order must equal input switch-time order.
            service_relaxation = 2 - stop[first_key] - stop[second_key]
            model.addConstr(
                switch_time[first_key] - switch_time[second_key]
                <= big_m * (1 - order + service_relaxation + active_relaxation),
                name=f"fifo_service_forward_{pair.id}",
            )
            model.addConstr(
                switch_time[second_key] - switch_time[first_key]
                <= big_m * (order + service_relaxation + active_relaxation),
                name=f"fifo_service_reverse_{pair.id}",
            )
            service_rows += 2

            # Platform and mechanism candidates are Service-only. At the
            # direct Exit Switch, also preserve the Skip subsequence.
            if checkpoint.kind in {
                HeadwayCheckpointKind.ENTRY_SWITCH,
                HeadwayCheckpointKind.EXIT_SWITCH,
            }:
                skip_relaxation = stop[first_key] + stop[second_key]
                model.addConstr(
                    switch_time[first_key] - switch_time[second_key]
                    <= big_m * (1 - order + skip_relaxation + active_relaxation),
                    name=f"fifo_skip_forward_{pair.id}",
                )
                model.addConstr(
                    switch_time[second_key] - switch_time[first_key]
                    <= big_m * (order + skip_relaxation + active_relaxation),
                    name=f"fifo_skip_reverse_{pair.id}",
                )
                skip_rows += 2
            constrained_pairs += 1
        return EanPairwiseFifoBuildMetrics(
            constrained_pair_count=constrained_pairs,
            service_fifo_row_count=service_rows,
            skip_fifo_row_count=skip_rows,
        )
