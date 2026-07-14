from __future__ import annotations

from typing import Any

from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    HORIZON_ACTIVATION_EPSILON_SECONDS,
    EanHorizonFormulation,
    EanTimeBoundFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanCabinStartKind,
    SwitchVisitDefinition,
)
from ropeway_skip_stop_optimization.optimization.ean.time_bounds import (
    EanModelTimeBounds,
    build_ean_model_time_bounds,
)


def add_visit_horizon_activation(
    *,
    model: Any,
    binary_vtype: Any,
    artifact: EanBuildArtifact,
    formulation: EanHorizonFormulation,
    switch_time: dict[tuple[int, int], Any],
    visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]],
    selected_time_bounds: EanModelTimeBounds,
    big_m: float,
) -> dict[tuple[int, int], Any]:
    """Create visit-activation expressions for the selected horizon semantics.

    A visit is active when it receives a route decision. Exact activation uses
    a small numerical separation so an event exactly at the closed horizon is
    active rather than allowing the binary to relax either way. An
    `EARLIEST` cabin start may remain outside the active prefix when its first
    optimized switch entry is after the horizon.
    """

    if formulation is EanHorizonFormulation.LEGACY:
        return {key: 1 for key in switch_time}

    if formulation is EanHorizonFormulation.CONSERVATIVE_FREE_SUFFIX:
        earliest_bounds = build_ean_model_time_bounds(
            artifact,
            EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS,
        )
        horizon = artifact.config.operational_end_seconds
        return {
            key: int(earliest_bounds.by_visit[key].switch_lower <= horizon)
            for key in switch_time
        }

    if formulation is not EanHorizonFormulation.EXACT_TIME_ACTIVATION:
        raise ValueError(f"unsupported EAN horizon formulation: {formulation}")

    horizon = artifact.config.operational_end_seconds
    starts_by_cabin_id = {
        start.cabin_id: start
        for start in artifact.cabin_starts
    }
    active: dict[tuple[int, int], Any] = {}
    for key in switch_time:
        active[key] = model.addVar(
            vtype=binary_vtype,
            name=f"visit_active_{key[0]}_{key[1]}",
        )

    for cabin_id, visits in visits_by_cabin_id.items():
        first_key = (cabin_id, visits[0].visit_index)
        if starts_by_cabin_id[cabin_id].kind is EanCabinStartKind.FIXED:
            model.addConstr(
                active[first_key] == 1,
                name=f"fixed_first_visit_active_{cabin_id}",
            )
        for visit in visits:
            key = (cabin_id, visit.visit_index)
            bounds = selected_time_bounds.by_visit[key]
            local_m = max(
                big_m,
                bounds.switch_upper,
                horizon - bounds.switch_lower,
            )
            model.addConstr(
                switch_time[key] <= horizon + local_m * (1 - active[key]),
                name=f"visit_before_horizon_if_active_{key[0]}_{key[1]}",
            )
            model.addConstr(
                switch_time[key]
                >= horizon
                + HORIZON_ACTIVATION_EPSILON_SECONDS
                - local_m * active[key],
                name=f"visit_after_horizon_if_inactive_{key[0]}_{key[1]}",
            )
        for previous, current in zip(visits, visits[1:]):
            previous_key = (cabin_id, previous.visit_index)
            current_key = (cabin_id, current.visit_index)
            model.addConstr(
                active[current_key] <= active[previous_key],
                name=f"visit_activation_prefix_{cabin_id}_{current.visit_index}",
            )
    return active


def visit_is_active_in_solution(value: Any) -> bool:
    if isinstance(value, int | float):
        return float(value) >= 0.5
    return float(value.X) >= 0.5
