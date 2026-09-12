"""Solver-independent service assignment certificate.

The per-trip timestamps are individual witnesses.  They deliberately do not
claim that different trips are mutually resource-feasible.
"""

from collections import defaultdict
from dataclasses import asdict, dataclass

from ..cp_sat_certificate import stable_fingerprint
from ..reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
)

SCHEMA = "reservoir_service_assignment_v1"


@dataclass(frozen=True)
class ReservoirServiceTrip:
    cabin_id: int
    route_option_ids: tuple[str, ...]
    witness_switch_ticks: tuple[int, ...]
    witness_wait_ticks: tuple[int, ...]
    witness_return_tick: int

    def as_cp_trip(self):
        return DddReservoirCpTrip(
            self.cabin_id,
            self.route_option_ids,
            self.witness_switch_ticks,
            self.witness_wait_ticks,
            self.witness_return_tick,
        )


@dataclass(frozen=True)
class ReservoirServiceAssignment:
    problem_fingerprint: str
    target_served: int
    trips: tuple[ReservoirServiceTrip, ...]
    ride_counts: dict[str, int]
    profile: str

    @property
    def fingerprint(self):
        return stable_fingerprint(assignment_to_payload(self))


def assignment_to_payload(assignment):
    return {"schema": SCHEMA, **asdict(assignment)}


def assignment_from_payload(payload):
    if payload.get("schema") != SCHEMA:
        raise ValueError("invalid reservoir service assignment schema")
    return ReservoirServiceAssignment(
        problem_fingerprint=payload["problem_fingerprint"],
        target_served=payload["target_served"],
        trips=tuple(
            ReservoirServiceTrip(
                cabin_id=t["cabin_id"],
                route_option_ids=tuple(t["route_option_ids"]),
                witness_switch_ticks=tuple(t["witness_switch_ticks"]),
                witness_wait_ticks=tuple(t["witness_wait_ticks"]),
                witness_return_tick=t["witness_return_tick"],
            )
            for t in payload["trips"]
        ),
        ride_counts=dict(payload["ride_counts"]),
        profile=payload["profile"],
    )


def assignment_from_plan(problem, plan, *, profile="reference"):
    """Convert a valid physical plan into the weaker service certificate."""
    metrics = validate_reservoir_cp_plan(problem, plan)
    assignment = ReservoirServiceAssignment(
        problem_fingerprint=problem.fingerprint,
        target_served=metrics.served,
        trips=tuple(
            ReservoirServiceTrip(
                cabin_id=t.cabin_id,
                route_option_ids=t.route_option_ids,
                witness_switch_ticks=t.switch_ticks,
                witness_wait_ticks=t.wait_ticks,
                witness_return_tick=t.return_tick,
            )
            for t in plan.trips
        ),
        ride_counts=dict(plan.ride_counts),
        profile=profile,
    )
    validate_service_assignment(problem, assignment)
    return assignment


def canonicalize_reservoir_plan(problem, plan):
    """Relabel cabins by dispatch time and translate their canonical ride IDs."""
    validate_reservoir_cp_plan(problem, plan)
    ordered = sorted(plan.trips, key=lambda t: (t.switch_ticks[0], t.cabin_id))
    mapping = {trip.cabin_id: new for new, trip in enumerate(ordered)}
    if all(old == new for old, new in mapping.items()):
        return plan, mapping
    candidates = {q.id: q for q in problem.passenger_build.ride_candidates}
    by_key = {
        (q.demand_group_id, q.cabin_id, q.board_visit_index, q.alight_visit_index): q.id
        for q in candidates.values()
    }
    rides = {}
    for rid, count in plan.ride_counts.items():
        q = candidates[rid]
        translated = by_key.get(
            (
                q.demand_group_id,
                mapping[q.cabin_id],
                q.board_visit_index,
                q.alight_visit_index,
            )
        )
        if translated is None:
            raise ValueError("cannot canonicalize reservoir ride ID")
        rides[translated] = count
    canonical = DddReservoirCpPlan(
        tuple(
            DddReservoirCpTrip(
                mapping[t.cabin_id],
                t.route_option_ids,
                t.switch_ticks,
                t.wait_ticks,
                t.return_tick,
            )
            for t in ordered
        ),
        rides,
    )
    validate_reservoir_cp_plan(problem, canonical)
    return canonical, mapping


def validate_service_assignment(problem, assignment):
    problem.validate()
    if assignment.problem_fingerprint != problem.fingerprint:
        raise ValueError("service assignment problem fingerprint mismatch")
    if type(assignment.target_served) is not int or assignment.target_served < 0:
        raise ValueError("invalid service assignment target")
    cabins = tuple(t.cabin_id for t in assignment.trips)
    if cabins != tuple(range(len(cabins))):
        raise ValueError("service assignment cabins must form a canonical prefix")
    candidates = {q.id: q for q in problem.passenger_build.ride_candidates}
    groups = {g.id: g for g in problem.demand_groups}
    served = defaultdict(int)
    by_cabin = defaultdict(dict)
    for rid, count in assignment.ride_counts.items():
        q = candidates.get(rid)
        if q is None or type(count) is not int or count <= 0:
            raise ValueError("invalid service assignment ride count")
        by_cabin[q.cabin_id][rid] = count
        served[q.demand_group_id] += count
    if any(gid not in groups or count > groups[gid].count for gid, count in served.items()):
        raise ValueError("service assignment exceeds demand")
    if sum(served.values()) != assignment.target_served:
        raise ValueError("service assignment does not meet its target")
    known_cabins = set(cabins)
    if set(by_cabin) - known_cabins:
        raise ValueError("service assignment ride uses an absent cabin")
    for service_trip in assignment.trips:
        # The original validator checks every within-trip temporal, route,
        # capacity, release and empty-return condition.  Checking trips one at
        # a time intentionally omits only conflicts between different cabins.
        validate_reservoir_cp_plan(
            problem,
            DddReservoirCpPlan(
                (service_trip.as_cp_trip(),), by_cabin[service_trip.cabin_id]
            ),
        )
    return {
        "served": sum(served.values()),
        "used_fleet": len(assignment.trips),
        "served_by_group": dict(sorted(served.items())),
        "assignment_fingerprint": assignment.fingerprint,
    }
