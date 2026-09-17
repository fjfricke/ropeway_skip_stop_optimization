from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.fleet import EanFleetPlan
from ropeway_skip_stop_optimization.optimization.ean.passenger_plan import (
    EanPassengerServicePlan,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import EanMovementPlan
from ropeway_skip_stop_optimization.optimization.ean.validation import (
    validate_ean_initial_boundary_against_artifact,
    validate_ean_movement_plan_against_artifact,
)

from .domain import OipDomain


@dataclass(frozen=True)
class OipCertificateMetrics:
    served: int
    unserved: int
    journey_time_seconds: float
    active_fleet: int


def validate_oip_certificate(
    domain: OipDomain,
    movement: EanMovementPlan,
    fleet: EanFleetPlan,
    passengers: EanPassengerServicePlan,
) -> OipCertificateMetrics:
    validate_oip_movement_certificate(domain, movement, fleet)
    tolerance = 1.1 / domain.grid.ticks_per_second
    build = EanPassengerCandidateBuilder().build(domain.scenario, domain.artifact)
    groups = {group.id: group for group in build.demand_groups}
    candidates = {
        (
            item.demand_group_id,
            item.cabin_id,
            item.board_visit_index,
            item.alight_visit_index,
        )
        for item in build.ride_candidates
    }
    visits = {
        (visit.cabin_id, visit.visit_index): visit
        for trajectory in movement.trajectories
        for visit in trajectory.visits
    }
    served_by_group: dict[str, int] = defaultdict(int)
    onboard: dict[tuple[int, int], int] = defaultdict(int)
    journey = 0.0
    for ride in passengers.served_rides:
        key = (
            ride.demand_group_id,
            ride.cabin_id,
            ride.board_visit_index,
            ride.alight_visit_index,
        )
        if key not in candidates:
            raise ValueError(f"OIP certificate contains unknown ride {key!r}")
        board = visits[ride.cabin_id, ride.board_visit_index]
        alight = visits[ride.cabin_id, ride.alight_visit_index]
        if board.decision.value != "stop" or alight.decision.value != "stop":
            raise ValueError("OIP passenger ride uses a skipped endpoint")
        group = groups[ride.demand_group_id]
        if ride.boarding_time_seconds + tolerance < max(0.0, group.release_time_seconds):
            raise ValueError("OIP passenger ride boards before release")
        if ride.alighting_time_seconds > domain.artifact.config.horizon_seconds + tolerance:
            raise ValueError("OIP passenger ride alights after the service deadline")
        if ride.alighting_time_seconds + tolerance < ride.boarding_time_seconds:
            raise ValueError("OIP passenger ride has negative travel time")
        served_by_group[ride.demand_group_id] += ride.count
        journey += ride.count * (
            ride.alighting_time_seconds - group.release_time_seconds
        )
        for visit_index in range(ride.board_visit_index, ride.alight_visit_index):
            onboard[ride.cabin_id, visit_index] += ride.count
    for key, count in onboard.items():
        if count > domain.artifact.config.cabin_capacity:
            raise ValueError(f"OIP cabin capacity exceeded at {key!r}")
    for group_id, group in groups.items():
        unserved = passengers.unserved_counts_by_demand_group_id.get(group_id)
        if unserved is None or served_by_group[group_id] + unserved != group.count:
            raise ValueError(f"OIP demand balance fails for {group_id!r}")
        journey += unserved * max(
            0.0, domain.artifact.config.horizon_seconds - group.release_time_seconds
        )
    return OipCertificateMetrics(
        served=sum(served_by_group.values()),
        unserved=sum(passengers.unserved_counts_by_demand_group_id.values()),
        journey_time_seconds=journey,
        active_fleet=len(fleet.active_cabin_ids),
    )


def validate_oip_movement_certificate(
    domain: OipDomain, movement: EanMovementPlan, fleet: EanFleetPlan,
) -> None:
    """Validate movement and lifecycle without constructing passenger candidates."""
    tolerance = 1.1 / domain.grid.ticks_per_second
    validate_ean_movement_plan_against_artifact(
        domain.artifact, movement, tolerance_seconds=tolerance
    ).raise_for_errors()
    validate_ean_initial_boundary_against_artifact(
        domain.artifact, movement, fleet, tolerance_seconds=tolerance
    ).raise_for_errors()
    active = set(fleet.active_cabin_ids)
    for trajectory in movement.trajectories:
        if trajectory.cabin_id not in active:
            if trajectory.visits:
                raise ValueError("inactive OIP cabin has movement visits")
            continue
        if not trajectory.visits:
            raise ValueError("active OIP cabin has no movement visits")
        final = trajectory.visits[-1]
        if final.switch_time_seconds > domain.artifact.config.operational_end_seconds + tolerance:
            raise ValueError("OIP active cabin left before the operational end")
        if final.next_switch_time_seconds <= domain.artifact.config.operational_end_seconds:
            raise ValueError("OIP visit supply does not cover the operational end")
