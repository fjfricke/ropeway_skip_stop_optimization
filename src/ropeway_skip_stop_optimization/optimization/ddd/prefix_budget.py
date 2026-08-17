from __future__ import annotations

from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddLayeredTimeNetwork,
    estimate_ddd_prefix_formulation_size,
)
from ropeway_skip_stop_optimization.optimization.ddd.support_master import (
    DddSupportConflictCut,
)


def ddd_prefix_depths(
    cuts: tuple[DddSupportConflictCut, ...],
) -> dict[int, int]:
    depths: dict[int, int] = {}
    for cut in cuts:
        for literal in cut.literals:
            depths[literal.cabin_id] = max(
                depths.get(literal.cabin_id, 0),
                literal.visit_index,
            )
    return depths


def ddd_prefix_formulation_within_budget(
    network: DddLayeredTimeNetwork,
    cuts: tuple[DddSupportConflictCut, ...],
    *,
    max_variable_count: int,
    max_cabin_count: int,
    max_visit_index: int,
) -> bool:
    depths = ddd_prefix_depths(cuts)
    if sum(value > 0 for value in depths.values()) > max_cabin_count:
        return False
    if max(depths.values(), default=0) > max_visit_index:
        return False
    size = estimate_ddd_prefix_formulation_size(
        network,
        max_visit_index_by_cabin=depths,
    )
    return size.prefix_variable_count <= max_variable_count


def select_ddd_prefix_cuts_within_budget(
    network: DddLayeredTimeNetwork,
    existing: tuple[DddSupportConflictCut, ...],
    candidates: tuple[DddSupportConflictCut, ...],
    *,
    max_new_cuts: int,
    max_variable_count: int,
    max_cabin_count: int,
    max_visit_index: int,
) -> tuple[tuple[DddSupportConflictCut, ...], bool]:
    selected: list[DddSupportConflictCut] = []
    budget_exhausted = False
    for candidate in candidates:
        if len(selected) >= max_new_cuts:
            break
        trial = (*existing, *selected, candidate)
        if not ddd_prefix_formulation_within_budget(
            network,
            trial,
            max_variable_count=max_variable_count,
            max_cabin_count=max_cabin_count,
            max_visit_index=max_visit_index,
        ):
            budget_exhausted = True
            continue
        selected.append(candidate)
    return tuple(selected), budget_exhausted
