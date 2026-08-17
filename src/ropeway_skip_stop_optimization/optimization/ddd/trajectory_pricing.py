from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_primal import (
    DddCpSatPassengerObjectiveEvent,
    DddCpSatPassengerRidePreference,
)
from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.route_topology import (
    deterministic_route_state_ids,
    unique_stop_route_option,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_passenger_lp import (
    DddTrajectoryPassengerLpResult,
    DddTrajectoryPassengerLpStatus,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjective,
    EanPassengerObjectiveEvent,
    ean_passenger_objective_definition,
)


@dataclass(frozen=True)
class DddTrajectoryHeuristicPricingSignal:
    """Dual-guided CP-SAT objective with no certificate semantics."""

    preferences: tuple[DddCpSatPassengerRidePreference, ...]
    master_fingerprint: str
    dual_fingerprint: str
    fingerprint: str


def build_ddd_trajectory_heuristic_pricing_signal(
    *,
    movement_problem: DddMovementProblem,
    artifact: EanBuildArtifact,
    passenger_build: EanPassengerCandidateBuildResult,
    objective: EanPassengerObjective,
    lp_result: DddTrajectoryPassengerLpResult,
) -> DddTrajectoryHeuristicPricingSignal:
    """Translate Passenger RMP duals into a deterministic no-wait CP objective.

    The preferences deliberately ignore shared cabin capacity and therefore
    guide only primal schedule generation.  Exact loading and physical
    validation remain downstream responsibilities.
    """

    movement_problem.validate()
    artifact.validate()
    passenger_build.validate()
    if artifact.scenario_id != movement_problem.scenario_id:
        raise ValueError("trajectory pricing artifact and movement problem differ")
    if lp_result.status is not DddTrajectoryPassengerLpStatus.OPTIMAL:
        raise ValueError("trajectory pricing requires an optimal restricted LP")
    if lp_result.duals is None:
        raise ValueError("trajectory pricing requires restricted-LP duals")
    definition = ean_passenger_objective_definition(objective)
    event = (
        DddCpSatPassengerObjectiveEvent.BOARDING
        if definition.event is EanPassengerObjectiveEvent.BOARDING
        else DddCpSatPassengerObjectiveEvent.ALIGHTING
    )
    group_by_id = {group.id: group for group in passenger_build.demand_groups}
    starts_by_cabin_id = {start.cabin_id: start for start in movement_problem.starts}
    state_ids_by_cabin_id = {
        cabin_id: deterministic_route_state_ids(
            movement_problem,
            start_state_id=start.state_id,
            max_visit_count=start.max_visit_count,
            error_context="trajectory pricing",
        )
        for cabin_id, start in starts_by_cabin_id.items()
    }
    horizon_tick = ddd_seconds_to_tick(artifact.config.horizon_seconds)
    preferences = []
    for candidate in sorted(passenger_build.ride_candidates, key=lambda item: item.id):
        if candidate.cabin_id not in state_ids_by_cabin_id:
            continue
        states = state_ids_by_cabin_id[candidate.cabin_id]
        if candidate.alight_visit_index >= len(states) - 1:
            continue
        board_option = unique_stop_route_option(
            movement_problem,
            states[candidate.board_visit_index],
            error_context="trajectory pricing",
        )
        alight_option = unique_stop_route_option(
            movement_problem,
            states[candidate.alight_visit_index],
            error_context="trajectory pricing",
        )
        if (
            board_option.platform_exit_offset_seconds is None
            or alight_option.platform_entry_offset_seconds is None
        ):
            raise RuntimeError("trajectory pricing STOP option lacks platform offsets")
        group = group_by_id[candidate.demand_group_id]
        raw_dual = lp_result.duals.demand_raw_by_group_id.get(group.id, 0.0)
        preferences.append(
            DddCpSatPassengerRidePreference(
                id=candidate.id,
                cabin_id=candidate.cabin_id,
                board_visit_index=candidate.board_visit_index,
                alight_visit_index=candidate.alight_visit_index,
                release_tick=ddd_seconds_to_tick(group.release_time_seconds),
                board_offset_tick=ddd_seconds_to_tick(
                    board_option.platform_exit_offset_seconds
                ),
                alight_offset_tick=ddd_seconds_to_tick(
                    alight_option.platform_entry_offset_seconds
                ),
                service_horizon_tick=horizon_tick,
                demand_dual_tick=ddd_seconds_to_tick(raw_dual),
                passenger_weight=min(group.count, artifact.config.cabin_capacity),
                objective_event=event,
            )
        )
    payload = {
        "master": lp_result.master_fingerprint,
        "dual": lp_result.duals.fingerprint,
        "preferences": [
            (
                item.id,
                item.cabin_id,
                item.board_visit_index,
                item.alight_visit_index,
                item.release_tick,
                item.board_offset_tick,
                item.alight_offset_tick,
                item.service_horizon_tick,
                item.demand_dual_tick,
                item.passenger_weight,
                item.objective_event.value,
            )
            for item in preferences
        ],
    }
    return DddTrajectoryHeuristicPricingSignal(
        preferences=tuple(preferences),
        master_fingerprint=lp_result.master_fingerprint,
        dual_fingerprint=lp_result.duals.fingerprint,
        fingerprint=sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )
