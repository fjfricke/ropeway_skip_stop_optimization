"""Solver-independent validation of single-use reservoir plans and checkpoints."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
import json
from pathlib import Path

from .cp_sat_certificate import atomic_json, stable_fingerprint
from .models import DddRouteDecision
from .reservoir_cp_sat_problem import DddReservoirCpSatProblem
from .time_ticks import ddd_seconds_to_tick

SCHEMA = "single_use_reservoir_cp_checkpoint_v1"


@dataclass(frozen=True)
class DddReservoirCpTrip:
    cabin_id: int
    route_option_ids: tuple[str, ...]
    switch_ticks: tuple[int, ...]
    wait_ticks: tuple[int, ...]
    return_tick: int


@dataclass(frozen=True)
class DddReservoirCpPlan:
    trips: tuple[DddReservoirCpTrip, ...]
    ride_counts: dict[str, int]


@dataclass(frozen=True)
class DddReservoirCpMetrics:
    journey_time_tick: int
    served: int
    unserved: int
    used_fleet: int
    peak_active_fleet: int
    unserved_counts: dict[str, int]


def validate_reservoir_cp_plan(
    problem: DddReservoirCpSatProblem, plan: DddReservoirCpPlan
):
    problem.validate()
    core = problem.resolved_core
    options = {o.id: o for o in core.route_options}
    protected, visits = defaultdict(list), {}
    seen, node_times, fleet_events = set(), set(), []
    wait_step = ddd_seconds_to_tick(problem.waiting_policy.step_seconds or 0.000001)
    for trip in plan.trips:
        k = trip.cabin_id
        if (
            type(k) is not int
            or not 0 <= k < problem.available_fleet_count
            or k in seen
        ):
            raise ValueError("invalid or reused reservoir cabin")
        seen.add(k)
        n = len(trip.route_option_ids)
        if (
            not n
            or n >= len(problem.visit_states)
            or len(trip.switch_ticks) != n
            or len(trip.wait_ticks) != n
        ):
            raise ValueError("invalid reservoir trip dimensions")
        if any(
            type(t) is not int or t < 0
            for t in (*trip.switch_ticks, *trip.wait_ticks, trip.return_tick)
        ):
            raise ValueError("invalid reservoir integer times")
        dispatch = trip.switch_ticks[0]
        first, last = map(
            ddd_seconds_to_tick,
            (problem.dispatch_start_seconds, problem.dispatch_end_seconds),
        )
        if not first <= dispatch <= last or (dispatch - first) % ddd_seconds_to_tick(
            problem.dispatch_step_seconds
        ):
            raise ValueError("reservoir dispatch outside its domain")
        state, time = problem.entry_state_id, dispatch
        complete_returns = []
        for i, (oid, t, w) in enumerate(
            zip(trip.route_option_ids, trip.switch_ticks, trip.wait_ticks, strict=True)
        ):
            o = options.get(oid)
            if o is None or o.from_state_id != state or t != time:
                raise ValueError("reservoir route/time discontinuity")
            if (state, t) in node_times:
                raise ValueError("reservoir state-time conflict")
            node_times.add((state, t))
            if (
                w % wait_step
                or w
                > ddd_seconds_to_tick(
                    problem.waiting_policy.maximum_wait_seconds(o.station_id)
                )
                or (w and o.decision is not DddRouteDecision.STOP)
            ):
                raise ValueError("invalid reservoir exit wait")
            if w and t + ddd_seconds_to_tick(
                o.platform_exit_offset_seconds
            ) < ddd_seconds_to_tick(problem.waiting_policy.earliest_wait_time_seconds):
                raise ValueError("reservoir wait starts before allowed phase")
            visits[k, i] = (o, t, w)
            for u in o.resource_usages:
                r = core.resources_by_id[u.resource_id]
                entry = (
                    t
                    + u.follower_enter_offset_tick
                    + u.follower_enter_wait_coefficient * w
                )
                end = (
                    t
                    + u.leader_clear_offset_tick
                    + u.leader_clear_wait_coefficient * w
                    + u.separation_after_tick(r.minimum_headway_tick)
                )
                if end <= entry:
                    raise ValueError("invalid protected reservoir resource interval")
                if entry <= core.operational_end_tick:
                    protected[r.id].append((entry, end))
            state, time = o.to_state_id, t + o.duration_tick + w
            if state == problem.entry_state_id:
                complete_returns.append(time)
        if (
            state != problem.entry_state_id
            or time != trip.return_tick
            or not ddd_seconds_to_tick(problem.return_start_seconds)
            <= time
            <= core.operational_end_tick
        ):
            raise ValueError(
                "reservoir trip must return to its port within the horizon"
            )
        service_end = core.passenger_service_end_tick
        if ddd_seconds_to_tick(problem.return_start_seconds) >= service_end:
            eligible_returns = [value for value in complete_returns if value >= service_end]
            if not eligible_returns or trip.return_tick != eligible_returns[0]:
                raise ValueError(
                    "reservoir trip must use its first complete return at or after service end"
                )
        if (state, time) in node_times:
            raise ValueError("reservoir state-time conflict at return")
        node_times.add((state, time))
        fleet_events.extend([(dispatch, 1), (time, -1)])
    for intervals in protected.values():
        end = -1
        for entry, clear in sorted(intervals):
            if entry < end:
                raise ValueError("reservoir resource/headway conflict")
            end = clear
    from .reservoir_boundary import validate_port_separation

    validate_port_separation(problem, plan)
    groups = {g.id: g for g in problem.demand_groups}
    candidates = {q.id: q for q in problem.passenger_build.ride_candidates}
    served, loads, cost = defaultdict(int), defaultdict(int), 0
    for rid, count in plan.ride_counts.items():
        q = candidates.get(rid)
        if q is None or type(count) is not int or count <= 0:
            raise ValueError("invalid reservoir integer ride count")
        board, alight = (
            visits.get((q.cabin_id, q.board_visit_index)),
            visits.get((q.cabin_id, q.alight_visit_index)),
        )
        if (
            board is None
            or alight is None
            or board[0].decision is not DddRouteDecision.STOP
            or alight[0].decision is not DddRouteDecision.STOP
        ):
            raise ValueError(
                "reservoir ride requires active STOP endpoints; return must be empty"
            )
        g = groups[q.demand_group_id]
        departure = (
            board[1]
            + ddd_seconds_to_tick(board[0].platform_exit_offset_seconds)
            + board[2]
        )
        arrival = alight[1] + ddd_seconds_to_tick(
            alight[0].platform_entry_offset_seconds
        )
        release = ddd_seconds_to_tick(g.release_time_seconds)
        if (
            board[0].station_id != g.origin_station_id
            or alight[0].station_id != g.destination_station_id
            or not release <= departure <= arrival <= core.passenger_service_end_tick
        ):
            raise ValueError("reservoir passenger OD/release/horizon violation")
        served[g.id] += count
        cost += count * (arrival - release)
        for i in range(q.board_visit_index, q.alight_visit_index):
            loads[q.cabin_id, i] += count
    if any(v > problem.cabin_capacity for v in loads.values()):
        raise ValueError("reservoir cabin capacity exceeded")
    unserved = {g.id: g.count - served[g.id] for g in groups.values()}
    if any(v < 0 for v in unserved.values()):
        raise ValueError("reservoir demand exceeded")
    cost += sum(
        unserved[g.id]
        * (
            core.passenger_service_end_tick
            - ddd_seconds_to_tick(g.release_time_seconds)
        )
        for g in groups.values()
    )
    level = peak = 0
    for _, change in sorted(fleet_events):
        level += change
        peak = max(peak, level)
    if level or peak > problem.available_fleet_count:
        raise ValueError("reservoir fleet conservation violated")
    return DddReservoirCpMetrics(
        cost, sum(served.values()), sum(unserved.values()), len(seen), peak, unserved
    )


def write_reservoir_cp_checkpoint(path: Path, problem, plan):
    metrics = validate_reservoir_cp_plan(problem, plan)
    atomic_json(
        path,
        {
            "schema": SCHEMA,
            "problem_fingerprint": problem.fingerprint,
            "domain_manifest": problem.manifest,
            "plan": asdict(plan),
            "metrics": asdict(metrics),
        },
    )


def read_reservoir_cp_checkpoint(path: Path, problem):
    raw = json.loads(path.read_text())
    if (
        raw.get("schema") != SCHEMA
        or raw.get("problem_fingerprint") != problem.fingerprint
        or stable_fingerprint(raw.get("domain_manifest")) != problem.fingerprint
    ):
        raise ValueError("reservoir checkpoint fingerprint mismatch")
    plan = reservoir_cp_plan_from_payload(raw["plan"])
    if asdict(validate_reservoir_cp_plan(problem, plan)) != raw["metrics"]:
        raise ValueError("reservoir checkpoint metrics mismatch")
    return plan


def reservoir_cp_plan_from_payload(payload: dict) -> DddReservoirCpPlan:
    """Decode a plan payload without weakening subsequent domain validation."""
    return DddReservoirCpPlan(
        tuple(
            DddReservoirCpTrip(
                t["cabin_id"],
                tuple(t["route_option_ids"]),
                tuple(t["switch_ticks"]),
                tuple(t["wait_ticks"]),
                t["return_tick"],
            )
            for t in payload["trips"]
        ),
        payload["ride_counts"],
    )


def read_reservoir_cp_checkpoint_for_fleet_resize(path: Path, problem):
    """Read a checkpoint when only the available-fleet cap has changed.

    The stored domain is authenticated by its original fingerprint.  Every
    other manifest field must be byte-for-byte equal, and the unchanged plan
    is independently validated against the target domain.  This permits both
    expansion and contraction, provided all used cabin IDs fit in the target.
    """
    raw = json.loads(path.read_text())
    source_manifest = raw.get("domain_manifest")
    if (
        raw.get("schema") != SCHEMA
        or not isinstance(source_manifest, dict)
        or stable_fingerprint(source_manifest) != raw.get("problem_fingerprint")
    ):
        raise ValueError("invalid reservoir checkpoint source domain")
    target_manifest = problem.manifest
    source_without_cap = dict(source_manifest)
    target_without_cap = dict(target_manifest)
    source_cap = source_without_cap.pop("available_fleet_count", None)
    target_cap = target_without_cap.pop("available_fleet_count", None)
    if (
        type(source_cap) is not int
        or type(target_cap) is not int
        or stable_fingerprint(source_without_cap)
        != stable_fingerprint(target_without_cap)
    ):
        raise ValueError("checkpoint differs by more than the available-fleet cap")
    plan = reservoir_cp_plan_from_payload(raw["plan"])
    metrics = validate_reservoir_cp_plan(problem, plan)
    if asdict(metrics) != raw.get("metrics"):
        raise ValueError("fleet-resized checkpoint metrics mismatch")
    return plan
